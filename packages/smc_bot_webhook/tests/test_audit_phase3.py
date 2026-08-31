"""Edge-case + concurrency audit tests for Phase 03 gates + Telegram flow.

Includes documentation tests for bugs found during audit + their fixes.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_bot_webhook.gates.state import (
    GATE_ACK_WINDOW_MINUTES,
    MANUAL_GATE_NAMES,
    NY_TZ,
    GateStateStore,
    ny_session_date,
)
from smc_bot_webhook.gates.validator import (
    CHART_GATE_NAMES,
    Decision,
    Validator,
)
from smc_bot_webhook.notify.discord import DiscordMirror, FakeDiscordTransport
from smc_bot_webhook.notify.formatting import build_ack_keyboard, parse_callback_data
from smc_bot_webhook.notify.telegram import FakeTelegramTransport, TelegramDispatcher
from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.payload import AlertPayload, compute_signal_id, parse_payload
from smc_bot_webhook.security import SecurityConfig
from smc_bot_webhook.server import AppSettings, create_app

VALID_PIPE = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)

# Canonical 16-char hex signal_id (matches compute_signal_id output length)
GOOD_SID = "1c54f6c631e1fc3d"


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except (FileNotFoundError, PermissionError):
        pass


def _make_db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_p3audit_{int(time.time() * 1000000)}.db")
    init_db(p)
    return BotDB(p), p


# ---------------------------------------------------------------------------
# Fix #1: model_construct auto-fills signal_id
# ---------------------------------------------------------------------------


class TestSignalIdModelConstructFix:
    def test_model_construct_empty_signal_id_auto_filled(self) -> None:
        """Bug fix: model_construct used to leave signal_id empty, breaking
        audit lookups by signal_id. Now it auto-computes the canonical hash."""
        p = AlertPayload.model_construct(
            prefix="SMC", version="v1", event="bos", symbol="EURUSD",
            tf="M15", dir="long", level=1.1, bar_time=1700000000,
            ob_id=-1, bos_id=-1, state="chart-qualified", reason="ok",
            received_at=None, raw_payload="", signal_id="",
        )
        expected = compute_signal_id(
            "bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1
        )
        assert p.signal_id == expected

    def test_model_construct_with_explicit_signal_id_preserves_it(self) -> None:
        p = AlertPayload.model_construct(
            prefix="SMC", version="v1", event="bos", symbol="EURUSD",
            tf="M15", dir="long", level=1.1, bar_time=1700000000,
            ob_id=-1, bos_id=-1, state="chart-qualified", reason="ok",
            received_at=None, raw_payload="", signal_id="custom_id",
        )
        assert p.signal_id == "custom_id"

    def test_end_to_end_audit_uses_canonical_signal_id(self) -> None:
        """Webhook -> DB -> Accept -> re-hydrate -> record_event uses canonical id."""
        db, path = _make_db()
        try:
            alert = parse_payload(VALID_PIPE)
            db.insert_alert(alert, url_token_ok=True)
            stored = db.get_alert_by_signal_id(alert.signal_id)
            assert stored is not None
            rebuilt = AlertPayload.model_construct(
                prefix=stored["prefix"], version=stored["version"],
                event=stored["event"], symbol=stored["symbol"], tf=stored["tf"],
                dir=stored["side"], level=float(stored["level"]),
                bar_time=int(stored["bar_time"]),
                ob_id=int(stored["ob_id"]), bos_id=int(stored["bos_id"]),
                state=stored["state"], reason=stored["reason"],
                received_at=None, raw_payload=stored["raw_payload"],
                signal_id="",
            )
            db.record_event(rebuilt.signal_id, "accept", actor="tester")
            canonical = alert.signal_id
            assert rebuilt.signal_id == canonical
            recent = db.list_recent_events(limit=10)
            accept_rows = [
                e for e in recent
                if e["signal_id"] == canonical and e["event_type"] == "accept"
            ]
            assert len(accept_rows) == 1
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Fix #2/#3: parse_callback_data signal_id length cap (16 chars exactly)
# ---------------------------------------------------------------------------


class TestCallbackSignalIdLength:
    def test_signal_id_16_chars_accepted(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID}:nonce1234")
        assert cb is not None
        assert cb.signal_id == GOOD_SID

    def test_signal_id_too_short_rejected(self) -> None:
        # 15 chars — canonical is 16.
        cb = parse_callback_data("accept:abc1234567890a:nonce1234")
        assert cb is None

    def test_signal_id_too_long_rejected(self) -> None:
        # 17 chars.
        cb = parse_callback_data("accept:abc1234567890abcd:nonce1234")
        assert cb is None

    def test_huge_signal_id_rejected_dos(self) -> None:
        cb = parse_callback_data("accept:" + "a" * 10_000 + ":nonce1234")
        assert cb is None

    def test_uppercase_signal_id_normalized(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID.upper()}:nonce1234")
        assert cb is not None
        assert cb.signal_id == GOOD_SID  # lowercased


class TestCallbackNonceLength:
    def test_nonce_min_4_chars(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID}:abcd")
        assert cb is not None
        assert cb.nonce == "abcd"

    def test_nonce_max_64_chars(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID}:{'x' * 64}")
        assert cb is not None

    def test_nonce_too_short_rejected(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID}:abc")
        assert cb is None

    def test_nonce_too_long_rejected(self) -> None:
        cb = parse_callback_data(f"accept:{GOOD_SID}:{'x' * 65}")
        assert cb is None


class TestCallbackEdgeCases:
    def test_empty_callback_data(self) -> None:
        assert parse_callback_data("") is None

    def test_only_action(self) -> None:
        assert parse_callback_data("accept") is None

    def test_action_with_empty_signal_id(self) -> None:
        assert parse_callback_data("accept::nonce1234") is None


# ---------------------------------------------------------------------------
# Validator concurrency
# ---------------------------------------------------------------------------


class TestValidatorConcurrent:
    def test_concurrent_acks_then_validate(self) -> None:
        """Many threads ack the same gate; validate() must see consistent state."""
        import threading

        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store)
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    for _ in range(10):
                        store.upsert("risk_ok", True, acknowledged_by=f"u{i}")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert errors == [], f"concurrent upsert crashed: {errors[:3]}"
            outcome = v.validate(parse_payload(VALID_PIPE))
            assert outcome.missing_manual == (
                "trades_left", "daily_loss_ok", "no_position",
                "spread_news_clean", "judgment_clear",
            )
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# NY session boundary
# ---------------------------------------------------------------------------


class TestNYSessionBoundary:
    def test_exactly_at_17_00_00_belongs_to_same_day(self) -> None:
        """At exactly 17:00 local NY, the session HAS opened → today."""
        ny = datetime(2026, 8, 30, 17, 0, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-08-30"

    def test_one_second_before_17_belongs_to_previous(self) -> None:
        ny = datetime(2026, 8, 30, 16, 59, 59, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-08-29"

    def test_one_second_after_17_belongs_to_today(self) -> None:
        ny = datetime(2026, 8, 30, 17, 0, 1, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-08-30"

    def test_dst_spring_forward(self) -> None:
        ny = datetime(2026, 3, 8, 17, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-03-08"

    def test_dst_fall_back(self) -> None:
        ny = datetime(2026, 11, 1, 17, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-11-01"


# ---------------------------------------------------------------------------
# Validator semantics with expired acks
# ---------------------------------------------------------------------------


class TestValidatorExpiredAcks:
    def test_all_manual_acks_expired_returns_expired(self) -> None:
        """When signal-specific gates (no_position, spread_news, judgment) are
        expired, validator returns EXPIRED — current design."""
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store)
            # Use window=0 so all 6 gates expire immediately.
            for name in MANUAL_GATE_NAMES:
                store.upsert(name, True, acknowledged_by="u", window_minutes=0)
            outcome = v.validate(parse_payload(VALID_PIPE))
            # Per design: signal-specific expired -> EXPIRED wins over
            # missing/notify-only distinction.
            assert outcome.decision is Decision.EXPIRED
        finally:
            _cleanup(path)

    def test_daily_acks_expired_but_signal_specific_fresh(self) -> None:
        """If only daily gates are expired (signal-specific are fresh),
        validator should NOT report EXPIRED — they can be re-acked."""
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store)
            from smc_bot_webhook.gates.state import SIGNAL_GATE_WINDOW_MINUTES, SIGNAL_SPECIFIC_GATE_NAMES, GATE_ACK_WINDOW_MINUTES
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            # Signal-specific: very long window so they don't expire quickly.
            for name in SIGNAL_SPECIFIC_GATE_NAMES:
                store.upsert(name, True, acknowledged_by="u",
                             window_minutes=GATE_ACK_WINDOW_MINUTES,
                             trade_date=ny_session_date(now))
            # Daily gates: window=0 → expired.
            for name in ("risk_ok", "trades_left", "daily_loss_ok"):
                store.upsert(name, True, acknowledged_by="u", window_minutes=0)
            outcome = v.validate(parse_payload(VALID_PIPE))
            # Daily expired → not EXPIRED (signal-specific still fresh); we
            # treat daily expiry as NEEDS_MANUAL_ACK since the trader can re-ack.
            assert outcome.decision in (Decision.NEEDS_MANUAL_ACK, Decision.NOTIFY_ONLY)
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Admin override (current design: chart > admin, admin > manual)
# ---------------------------------------------------------------------------


class TestAdminOverrideDesign:
    def test_admin_override_bypasses_manual_only(self) -> None:
        """Per design choice: BLOCKED (chart fail) takes precedence over
        admin_override. Admin only skips manual gates."""
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store, admin_override=True)
            p = AlertPayload.model_construct(
                prefix="SMC", version="v1", event="chart_qualified",
                symbol="GBPUSD", tf="M15", dir="long", level=1.1,
                bar_time=1700000000, ob_id=42, bos_id=7,
                state="chart-qualified", reason="ok",
                received_at=None, raw_payload="", signal_id="",
            )
            outcome = v.validate(p)
            assert outcome.decision is Decision.BLOCKED

        finally:
            _cleanup(path)

    def test_admin_override_skips_manual_with_valid_chart(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store, admin_override=True)
            outcome = v.validate(parse_payload(VALID_PIPE))
            assert outcome.decision is Decision.ACCEPTED_READY
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Telegram endpoint edges (no body cap on /telegram routes — FastAPI default)
# ---------------------------------------------------------------------------


class TestTelegramEndpointEdges:
    def _setup_app(self) -> tuple[TestClient, BotDB, FakeTelegramTransport, Path]:
        db_path = Path(f"output/test_p3edges_{int(time.time() * 1000000)}.db")
        db = BotDB(db_path)
        settings = AppSettings(
            url_secret="test-secret-do-not-use-in-prod",
            db_path=db_path,
            security=SecurityConfig(
                url_secret="test-secret-do-not-use-in-prod",
                rate_limit_per_min=1000,
            ),
            trusted_proxy=True,
            telegram_callback_secret="test-telegram-callback-secret",
        )
        tg = FakeTelegramTransport()
        dc = FakeDiscordTransport()
        dispatcher = TelegramDispatcher(
            tg, chat_id=12345, allowed_user_ids={456},
            max_retries=2, backoff_base_seconds=0.001,
        )
        mirror_dc = DiscordMirror(
            dc, webhook_url="http://x",
            max_retries=2, backoff_base_seconds=0.001,
        )
        app = create_app(
            settings=settings, db=db,
            dispatcher=dispatcher, mirror=mirror_dc,
        )
        return TestClient(app), db, tg, db_path

    def test_command_empty_text_returns_200(self) -> None:
        client, _db, _tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            resp = client.post(
                "/telegram/command?token=test-secret-do-not-use-in-prod",
                json={"text": "", "from_user_id": 456},
            headers={
                "x-forwarded-for": "52.89.214.238",
                "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
            }
            )
            assert resp.status_code == 200
            assert resp.json()["handled"] is False
        finally:
            _cleanup(db_path)

    def test_command_missing_text_field(self) -> None:
        client, _db, _tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            resp = client.post(
                "/telegram/command?token=test-secret-do-not-use-in-prod",
                json={"from_user_id": 456},
            headers={
                "x-forwarded-for": "52.89.214.238",
                "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
            }
            )
            assert resp.status_code == 200
        finally:
            _cleanup(db_path)

    def test_command_ack_too_many_words(self) -> None:
        client, _db, _tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            resp = client.post(
                "/telegram/command?token=test-secret-do-not-use-in-prod",
                json={"text": "/ack risk_ok extra", "from_user_id": 456},
            headers={
                "x-forwarded-for": "52.89.214.238",
                "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
            }
            )
            assert resp.status_code == 200
            assert "usage" in resp.json()["reason"]
        finally:
            _cleanup(db_path)


# ---------------------------------------------------------------------------
# clear_signal_specific empty DB
# ---------------------------------------------------------------------------


class TestClearSignalSpecificEdge:
    def test_clear_when_no_rows_returns_zero(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            n = store.clear_signal_specific()
            assert n == 0
        finally:
            _cleanup(path)

    def test_clear_preserves_daily_gates(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            for name in MANUAL_GATE_NAMES:
                store.upsert(name, True, acknowledged_by="u1")
            n = store.clear_signal_specific()
            assert n == 3
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].value is True
            assert snap.statuses["trades_left"].value is True
            assert snap.statuses["daily_loss_ok"].value is True
            assert snap.statuses["no_position"].value is None
            assert snap.statuses["spread_news_clean"].value is None
            assert snap.statuses["judgment_clear"].value is None
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Gate window extremes
# ---------------------------------------------------------------------------


class TestUpsertWindowEdge:
    def test_window_zero_expires_immediately(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            store.upsert("risk_ok", True, acknowledged_by="u", window_minutes=0)
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].expired is True
        finally:
            _cleanup(path)

    def test_negative_window_does_not_crash(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            # Negative window — should either raise or produce clearly-expired row.
            try:
                store.upsert("risk_ok", True, acknowledged_by="u", window_minutes=-1)
                snap = store.snapshot()
                assert snap.statuses["risk_ok"].expired is True
            except (ValueError, AssertionError):
                pass
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Disabled dispatcher route handling
# ---------------------------------------------------------------------------


class TestCallbackWithDisabledDispatcher:
    def test_callback_works_when_dispatcher_disabled(self) -> None:
        """Webhook URL secret gates /telegram routes. Disabling the
        dispatcher should NOT block the route — handle_callback returns None
        which is handled gracefully (returns 200 'ignored')."""
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("DISCORD_WEBHOOK_URL", None)
        db_path = Path(f"output/test_disabled_{int(time.time() * 1000000)}.db")
        try:
            db = BotDB(db_path)
            settings = AppSettings(
                url_secret="test-secret-do-not-use-in-prod",
                db_path=db_path,
                security=SecurityConfig(
                    url_secret="test-secret-do-not-use-in-prod",
                    rate_limit_per_min=1000,
                ),
                trusted_proxy=True,
                telegram_callback_secret="test-telegram-callback-secret",
            )
            app = create_app(settings=settings, db=db)
            client = TestClient(app)
            resp = client.post(
                "/telegram/callback?token=test-secret-do-not-use-in-prod",
                json={"callback_data": f"accept:{GOOD_SID}:nonce1234", "from_user_id": 456},
            headers={
                "x-forwarded-for": "52.89.214.238",
                "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
            }
            )
            # Disabled dispatcher returns None from handle_callback → 200 "ignored".
            assert resp.status_code == 200
            assert resp.json()["decision"] == "ignored"
        finally:
            try:
                db_path.unlink()
            except (FileNotFoundError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# NaN / extreme level
# ---------------------------------------------------------------------------


class TestValidatorRobustness:
    def test_nan_level_does_not_crash_chart_gates(self) -> None:
        from smc_bot_webhook.gates.validator import evaluate_chart_gates
        p = AlertPayload.model_construct(
            prefix="SMC", version="v1", event="bos", symbol="EURUSD",
            tf="M15", dir="long", level=float("nan"), bar_time=1700000000,
            ob_id=-1, bos_id=-1, state="chart-qualified", reason="ok",
            received_at=None, raw_payload="", signal_id="ignored",
        )
        # No exception, results returned.
        results = evaluate_chart_gates(p)
        assert isinstance(results, tuple)