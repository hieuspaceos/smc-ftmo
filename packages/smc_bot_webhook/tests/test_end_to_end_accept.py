"""End-to-end smoke tests for the bot webhook.

These tests cover the full alert-accept-execute pipeline that
phase 01-06 hardening was designed to protect. They run against
the FastAPI app via TestClient (no real Telegram, no real MT5).
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
from smc_bot_webhook.gates.state import (
    GATE_ACK_WINDOW_MINUTES,
    MANUAL_GATE_NAMES,
    GateStateStore,
)
from smc_bot_webhook.gates.validator import Validator
from smc_bot_webhook.notify.telegram import (
    FakeTelegramTransport,
    TelegramDispatcher,
)
from smc_bot_webhook.payload import parse_payload
from smc_bot_webhook.security import SecurityConfig
from smc_bot_webhook.server import AppSettings, create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="test_e2e_"))


def _cleanup(p: Path) -> None:
    gc.collect()
    shutil.rmtree(p, ignore_errors=True)


def _build_app(
    db_path: Path,
    tg: FakeTelegramTransport,
    executor: Any = None,
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
    gate_store = GateStateStore(db)
    validator = Validator(gate_store, admin_override=False)
    app = create_app(
        settings=settings, db=db, dispatcher=dispatcher,
        gate_store=gate_store, validator=validator, executor=executor,
    )
    return TestClient(app), db, gate_store


def _post_webhook(client: TestClient) -> str:
    body = (
        "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
        "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
        "|state=chart-qualified|reason=ok"
    )
    r = client.post(
        "/webhooks/tradingview?token=test-webhook-secret-not-for-prod",
        content=body,
        headers={"content-type": "text/plain", "x-forwarded-for": "52.89.214.238"},
    )
    assert r.status_code in (200, 202)
    return parse_payload(body).signal_id


def _accept_all_gates(gate_store: GateStateStore) -> None:
    for name in MANUAL_GATE_NAMES:
        gate_store.upsert(name, True, acknowledged_by="tester")


def _post_accept(client: TestClient, signal_id: str) -> Any:
    accept_cb = f"accept:{signal_id}:test_nonce"
    return client.post(
        "/telegram/callback?token=test-webhook-secret-not-for-prod",
        json={"callback_data": accept_cb, "from_user_id": 456},
        headers={
            "x-forwarded-for": "52.89.214.238",
            "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
        },
    )


# ---------------------------------------------------------------------------
# Happy path: Pine alert → accept → executor
# ---------------------------------------------------------------------------


class TestEndToEndAccept:
    def test_happy_path_disabled_executor(self) -> None:
        td = _tmp_dir()
        try:
            tg = FakeTelegramTransport()
            from smc_bot_webhook.mt5_bridge.executor import DisabledExecutor
            client, db, gate_store = _build_app(
                td / "bot.db", tg, executor=DisabledExecutor(),
            )
            sid = _post_webhook(client)
            _accept_all_gates(gate_store)
            r = _post_accept(client, sid)
            assert r.status_code == 200
            body = r.json()
            assert body["decision"] == "accepted"
            assert body["execution"]["state"] == "queued"
            # execution_log row persisted.
            rows = db.list_executions()
            assert len(rows) == 1
            assert rows[0]["signal_id"] == sid
        finally:
            _cleanup(td)

    def test_failure_path_keeps_gates_intact(self) -> None:
        """When the executor fails, the trader can retry without
        re-acking gates. Phase 03 (C3) regression guard."""
        td = _tmp_dir()
        try:
            tg = FakeTelegramTransport()

            class FailingExecutor:
                name = "failing"
                enabled = True
                def execute(self, record):  # noqa: ARG002
                    return (False, "simulated failure")

            client, db, gate_store = _build_app(
                td / "bot.db", tg, executor=FailingExecutor(),
            )
            sid = _post_webhook(client)
            _accept_all_gates(gate_store)
            r = _post_accept(client, sid)
            assert r.status_code == 200
            assert r.json()["execution"]["state"] == "failed"
            # Gates must NOT be cleared (phase 03 fix).
            snap = gate_store.snapshot()
            for name in ("no_position", "spread_news_clean", "judgment_clear"):
                assert snap.statuses[name].value is True
        finally:
            _cleanup(td)

    def test_second_accept_after_first_succeeds_is_refused(self) -> None:
        """Replaying Accept on an already-accepted signal must be
        refused (gates already cleared from first accept)."""
        td = _tmp_dir()
        try:
            tg = FakeTelegramTransport()
            from smc_bot_webhook.mt5_bridge.executor import DisabledExecutor
            client, _db, gate_store = _build_app(
                td / "bot.db", tg, executor=DisabledExecutor(),
            )
            sid = _post_webhook(client)
            _accept_all_gates(gate_store)
            r1 = _post_accept(client, sid)
            assert r1.status_code == 200
            r2 = _post_accept(client, sid)
            assert r2.status_code == 409
        finally:
            _cleanup(td)

    def test_refusal_when_gates_missing(self) -> None:
        """No gates acked → Accept is refused with 409."""
        td = _tmp_dir()
        try:
            tg = FakeTelegramTransport()
            from smc_bot_webhook.mt5_bridge.executor import DisabledExecutor
            client, _db, gate_store = _build_app(
                td / "bot.db", tg, executor=DisabledExecutor(),
            )
            sid = _post_webhook(client)
            # Don't ack any gate.
            r = _post_accept(client, sid)
            assert r.status_code == 409
            body = r.json()
            assert body["decision"] == "refused"
            assert "risk_ok" in body["reason"]
        finally:
            _cleanup(td)

    def test_telegram_callback_requires_secret_header(self) -> None:
        """Phase 01 (C2) regression: missing secret header → 401."""
        td = _tmp_dir()
        try:
            tg = FakeTelegramTransport()
            from smc_bot_webhook.mt5_bridge.executor import DisabledExecutor
            client, _db, _ = _build_app(
                td / "bot.db", tg, executor=DisabledExecutor(),
            )
            r = client.post(
                "/telegram/callback?token=test-webhook-secret-not-for-prod",
                json={
                    "callback_data": "accept:sig1:nonce",
                    "from_user_id": 456,
                },
                headers={"x-forwarded-for": "52.89.214.238"},
                # No X-Telegram-Bot-Api-Secret-Token header.
            )
            assert r.status_code == 401
        finally:
            _cleanup(td)
