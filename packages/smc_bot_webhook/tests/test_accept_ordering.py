"""Tests for Phase 03 — Accept ordering + idempotency.

Closes audit finding C3 (gate clear before executor) + M7 (edit failure
not retried). Verifies:

- ``clear_signal_specific`` runs AFTER successful executor handoff, not
  before. A failed executor leaves the gates intact so the trader can
  retry without re-acking.
- Per-signal_id asyncio.Lock is shared across calls.
- ``_edit_with_retry`` retries once on transient failure (unit-level).
"""
from __future__ import annotations

import asyncio
import gc
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smc_bot_core.db import BotDB
from smc_bot_webhook.gates.state import GateStateStore, MANUAL_GATE_NAMES
from smc_bot_webhook.notify.telegram import (
    FakeTelegramTransport,
    TelegramDispatcher,
)
from smc_bot_webhook.payload import parse_payload
from smc_bot_webhook.security import SecurityConfig
from smc_bot_webhook.server import (
    _edit_with_retry,
    _signal_lock_for,
    AppSettings,
    create_app,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_db() -> Path:
    return Path(tempfile.mkdtemp(prefix="test_p3_"))


def _cleanup(td: Path) -> None:
    gc.collect()
    shutil.rmtree(td, ignore_errors=True)


def _setup_app(
    db_path: Path,
    tg: FakeTelegramTransport,
) -> tuple[TestClient, BotDB, GateStateStore]:
    settings = AppSettings(
        url_secret="test-webhook-secret-not-for-prod",
        db_path=db_path,
        security=SecurityConfig(
            url_secret="test-webhook-secret-not-for-prod",
            rate_limit_per_min=1000,
        ),
        trusted_proxy=True,
        telegram_callback_secret="test-telegram-callback-secret",
    )
    db = BotDB(db_path)
    dispatcher = TelegramDispatcher(
        tg, chat_id=12345, allowed_user_ids={456},
        max_retries=1, backoff_base_seconds=0.001,
    )
    from smc_bot_webhook.mt5_bridge.executor import DisabledExecutor
    executor = DisabledExecutor()
    gate_store = GateStateStore(db)
    from smc_bot_webhook.gates.validator import Validator
    validator = Validator(gate_store, admin_override=False)
    app = create_app(
        settings=settings, db=db, dispatcher=dispatcher,
        gate_store=gate_store, validator=validator, executor=executor,
    )
    return TestClient(app), db, gate_store


def _accept_all_gates(gate_store: GateStateStore) -> None:
    for name in MANUAL_GATE_NAMES:
        gate_store.upsert(name, True, acknowledged_by="tester")


def _post_webhook(client: TestClient) -> str:
    body = (
        "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
        "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
        "|state=chart-qualified|reason=ok"
    )
    r = client.post(
        "/webhooks/tradingview?token=test-webhook-secret-not-for-prod",
        content=body,
        headers={
            "content-type": "text/plain",
            "x-forwarded-for": "52.89.214.238",
        },
    )
    assert r.status_code in (200, 202)
    payload = parse_payload(body)
    return payload.signal_id

def _post_accept(
    client: TestClient,
    signal_id: str,
    from_user_id: int = 456,
) -> Any:
    accept_cb = f"accept:{signal_id}:test_nonce"
    return client.post(
        "/telegram/callback?token=test-webhook-secret-not-for-prod",
        json={"callback_data": accept_cb, "from_user_id": from_user_id},
        headers={
            "x-forwarded-for": "52.89.214.238",
            "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
        },
    )


# ---------------------------------------------------------------------------
# Lock helper
# ---------------------------------------------------------------------------


class TestSignalLock:
    def test_returns_same_lock_for_same_id(self) -> None:
        a = _signal_lock_for("sig1")
        b = _signal_lock_for("sig1")
        assert a is b

    def test_different_ids_get_different_locks(self) -> None:
        a = _signal_lock_for("sig-a")
        b = _signal_lock_for("sig-b")
        assert a is not b

    def test_lock_is_asyncio_lock(self) -> None:
        lock = _signal_lock_for("sig-asyncio")
        assert isinstance(lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# Edit-with-retry (unit-level — no full app needed)
# ---------------------------------------------------------------------------


class TestEditWithRetry:
    def test_returns_true_on_first_success(self) -> None:
        async def runner() -> None:
            class FakeDispatcher:
                def __init__(self) -> None:
                    self.calls = 0
                async def edit_signal(self, message_id, payload, **kw):
                    self.calls += 1
                    return True
            d = FakeDispatcher()
            ok = await _edit_with_retry(
                d, 1, type("P", (), {"signal_id": "s"})(),
                decision="accept", actor="t",
            )
            assert ok is True
            assert d.calls == 1
        asyncio.run(runner())

    def test_retries_once_on_failure_then_succeeds(self) -> None:
        async def runner() -> None:
            class FakeDispatcher:
                def __init__(self) -> None:
                    self.calls = 0
                async def edit_signal(self, message_id, payload, **kw):
                    self.calls += 1
                    if self.calls == 1:
                        return False
                    return True
            d = FakeDispatcher()
            ok = await _edit_with_retry(
                d, 1, type("P", (), {"signal_id": "s"})(),
                decision="accept", actor="t",
                backoff_seconds=0.001,
            )
            assert ok is True
            assert d.calls == 2
        asyncio.run(runner())

    def test_returns_false_when_all_retries_fail(self) -> None:
        async def runner() -> None:
            class FakeDispatcher:
                def __init__(self) -> None:
                    self.calls = 0
                async def edit_signal(self, message_id, payload, **kw):
                    self.calls += 1
                    return False
            d = FakeDispatcher()
            ok = await _edit_with_retry(
                d, 1, type("P", (), {"signal_id": "s"})(),
                decision="accept", actor="t",
                backoff_seconds=0.001,
            )
            assert ok is False
            assert d.calls == 2  # max_retries=1 → 2 attempts
        asyncio.run(runner())


# ---------------------------------------------------------------------------
# Accept ordering — gate clear happens AFTER executor success
# ---------------------------------------------------------------------------


class TestAcceptOrdering:
    def test_gates_cleared_on_accepted_executor(self) -> None:
        """Disabled executor returns state=queued → gates should clear."""
        td = _tmp_db()
        try:
            tg = FakeTelegramTransport()
            client, _db, gate_store = _setup_app(td / "bot.db", tg)
            signal_id = _post_webhook(client)
            _accept_all_gates(gate_store)
            r = _post_accept(client, signal_id)
            assert r.status_code == 200
            body = r.json()
            assert body["decision"] == "accepted"
            assert body["execution"]["state"] == "queued"
            snap = gate_store.snapshot()
            for name in ("no_position", "spread_news_clean", "judgment_clear"):
                assert snap.statuses[name].value is None, (
                    f"{name} should be cleared after successful accept"
                )
            for name in ("risk_ok", "trades_left", "daily_loss_ok"):
                assert snap.statuses[name].value is True
        finally:
            _cleanup(td)

    def test_second_accept_after_first_succeeds_is_refused(self) -> None:
        """Two sequential Accepts on the same signal_id: the first
        clears the gates; the second is refused because the gates are
        no longer satisfied."""
        td = _tmp_db()
        try:
            tg = FakeTelegramTransport()
            client, _db, gate_store = _setup_app(td / "bot.db", tg)
            signal_id = _post_webhook(client)
            _accept_all_gates(gate_store)
            r1 = _post_accept(client, signal_id)
            r2 = _post_accept(client, signal_id)
            assert r1.status_code == 200
            assert r1.json()["decision"] == "accepted"
            assert r2.status_code == 409
            assert r2.json()["decision"] == "refused"
        finally:
            _cleanup(td)

    def test_signal_specific_gates_cleared_AFTER_executor_not_before(
        self,
    ) -> None:
        """If we peek at gates after Accept but before the executor
        callback completes, the gates must still be set. This is
        hard to test deterministically in a sync test client — the
        real check is in the source: ``clear_signal_specific`` is
        called inside the same async function as
        ``_execute_via_executor`` but AFTER it. This test verifies
        the order in source via inspection: the function body
        ``_accept_signal`` contains the literal call
        ``gate_store.clear_signal_specific()`` positioned AFTER the
        ``await _execute_via_executor(...)`` line. If a future
        refactor moves the clear before the executor, this test
        fails (it parses the file)."""
        import inspect
        from smc_bot_webhook import server as _srv
        src = inspect.getsource(_srv._accept_signal)
        exec_idx = src.find("await _execute_via_executor")
        clear_idx = src.find("gate_store.clear_signal_specific()")
        assert exec_idx > 0, "_execute_via_executor call not found"
        assert clear_idx > 0, "clear_signal_specific call not found"
        assert clear_idx > exec_idx, (
            "clear_signal_specific must run AFTER _execute_via_executor"
        )
