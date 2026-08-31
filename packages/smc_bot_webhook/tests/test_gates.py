"""Unit + integration tests for Phase 03 11-gate validator + Telegram ack flow."""

from __future__ import annotations

import time
import os
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
    evaluate_chart_gates,
    missing_manual_gates,
)
from smc_bot_webhook.notify.discord import DiscordMirror, FakeDiscordTransport
from smc_bot_webhook.notify.formatting import build_ack_keyboard
from smc_bot_webhook.notify.telegram import FakeTelegramTransport, TelegramDispatcher
from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.payload import AlertPayload, parse_payload
from smc_bot_webhook.security import SecurityConfig
from smc_bot_webhook.server import AppSettings, create_app

VALID_PIPE = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


def _cleanup(p: Path) -> None:
    """Best-effort delete of db file + parent dir. Windows holds SQLite
    file lock after TestClient closes; ignore PermissionError on this
    platform. The mkdtemp parent directory is removed in a second pass."""
    import shutil
    try:
        p.unlink()
    except (FileNotFoundError, PermissionError):
        pass
    try:
        if p.parent.exists() and p.parent.name.startswith("test_accept_"):
            shutil.rmtree(p.parent, ignore_errors=True)
    except (FileNotFoundError, PermissionError):
        pass


def _make_db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_gates_{int(time.time() * 1000000)}.db")
    init_db(p)
    return BotDB(p), p


def _make_payload(**overrides: object) -> AlertPayload:
    """Build an AlertPayload directly so chart-gate tests can probe specific
    field values without the parser's pre-validations rejecting them first.

    Uses ``model_construct`` to skip Pydantic validators — the gate functions
    being tested here ARE the validators; we don't want to pre-filter inputs.
    """
    base = parse_payload(VALID_PIPE)
    return AlertPayload.model_construct(
        prefix=base.prefix,
        version=base.version,
        event=str(overrides.get("event", base.event)),
        symbol=str(overrides.get("symbol", base.symbol)),
        tf=str(overrides.get("tf", base.tf)),
        dir=str(overrides.get("dir", base.dir)),
        level=float(overrides.get("level", base.level)),
        bar_time=int(overrides.get("bar_time", base.bar_time)),
        ob_id=int(overrides.get("ob_id", base.ob_id)),
        bos_id=int(overrides.get("bos_id", base.bos_id)),
        state=str(overrides.get("state", base.state)),
        reason=str(overrides.get("reason", base.reason)),
        received_at=overrides.get("received_at") or datetime.now(timezone.utc),
        raw_payload="",
        signal_id=str(overrides.get("signal_id", base.signal_id)),
    )


# ---------------------------------------------------------------------------
# Chart gates (pure)
# ---------------------------------------------------------------------------


class TestChartGates:
    def test_valid_payload_passes_all_5(self) -> None:
        results = evaluate_chart_gates(parse_payload(VALID_PIPE))
        assert len(results) == 5
        assert all(r.passed for r in results)
        assert {r.name for r in results} == set(CHART_GATE_NAMES)

    def test_wrong_symbol_fails(self) -> None:
        p = _make_payload(symbol="GBPUSD")
        results = evaluate_chart_gates(p)
        sym = next(r for r in results if r.name == "symbol_eurusd")
        assert sym.passed is False
        assert "GBPUSD" in sym.reason

    def test_wrong_tf_fails(self) -> None:
        p = _make_payload(tf="M5")
        results = evaluate_chart_gates(p)
        assert next(r for r in results if r.name == "tf_m15").passed is False

    def test_blocked_state_fails(self) -> None:
        p = _make_payload(state="blocked")
        results = evaluate_chart_gates(p)
        assert next(r for r in results if r.name == "pine_state_ok").passed is False

    def test_no_signal_state_fails(self) -> None:
        p = _make_payload(state="no-signal")
        results = evaluate_chart_gates(p)
        assert next(r for r in results if r.name == "pine_state_ok").passed is False

    def test_watch_state_passes(self) -> None:
        p = _make_payload(state="watch")
        results = evaluate_chart_gates(p)
        assert all(r.passed for r in results)

    def test_direction_none_fails(self) -> None:
        p = _make_payload(dir="none")
        results = evaluate_chart_gates(p)
        assert next(r for r in results if r.name == "direction_exists").passed is False

    def test_trade_event_without_ob_fails(self) -> None:
        p = _make_payload(event="chart_qualified", ob_id=-1, bos_id=-1)
        results = evaluate_chart_gates(p)
        ob = next(r for r in results if r.name == "ob_bos_provenance")
        assert ob.passed is False
        assert "ob_id" in ob.reason

    def test_watch_event_without_ob_passes(self) -> None:
        p = _make_payload(event="watch", ob_id=-1, bos_id=-1)
        results = evaluate_chart_gates(p)
        assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# Manual gate state
# ---------------------------------------------------------------------------


class TestManualGates:
    def test_default_snapshot_all_unacked(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            snap = store.snapshot()
            for name in MANUAL_GATE_NAMES:
                status = snap.statuses[name]
                assert status.value is None
                assert status.expired is True
        finally:
            _cleanup(path)

    def test_upsert_then_snapshot_fresh(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            store.upsert("risk_ok", True, acknowledged_by="u1")
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].value is True
            assert snap.statuses["risk_ok"].fresh is True
            assert snap.statuses["risk_ok"].expired is False
        finally:
            _cleanup(path)

    def test_upsert_unknown_gate_raises(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            with pytest.raises(ValueError, match="unknown"):
                store.upsert("not_a_gate", True, acknowledged_by="u1")
        finally:
            _cleanup(path)

    def test_expired_snapshot_stale(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            store.upsert("risk_ok", True, acknowledged_by="u1", window_minutes=0)
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].expired is True
        finally:
            _cleanup(path)

    def test_missing_manual_gates_lists_unacked(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            store.upsert("risk_ok", True, acknowledged_by="u1")
            snap = store.snapshot()
            missing = missing_manual_gates(snap)
            assert "risk_ok" not in missing
            assert "trades_left" in missing
            assert "daily_loss_ok" in missing
            assert "no_position" in missing
            assert "spread_news_clean" in missing
            assert "judgment_clear" in missing
            assert len(missing) == 5
        finally:
            _cleanup(path)

    def test_clear_signal_specific_deletes_only_three(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            for name in MANUAL_GATE_NAMES:
                store.upsert(name, True, acknowledged_by="u1")
            store.clear_signal_specific()
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].value is True
            assert snap.statuses["trades_left"].value is True
            assert snap.statuses["daily_loss_ok"].value is True
            assert snap.statuses["no_position"].value is None
            assert snap.statuses["spread_news_clean"].value is None
            assert snap.statuses["judgment_clear"].value is None
        finally:
            _cleanup(path)

    def test_window_minutes_default_5_hours(self) -> None:
        """Default ack window covers a full NY session."""
        assert GATE_ACK_WINDOW_MINUTES == 5 * 60


# ---------------------------------------------------------------------------
# NY session date
# ---------------------------------------------------------------------------


class TestNYSessionDate:
    def test_during_session(self) -> None:
        ny = datetime(2026, 8, 30, 18, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-08-30"

    def test_before_session_open(self) -> None:
        ny = datetime(2026, 8, 30, 10, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-08-29"

    def test_dst_spring_forward_pre_open(self) -> None:
        # 03:00 NY is BEFORE the 17:00 session open → previous session date
        ny = datetime(2026, 3, 8, 3, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-03-07"

    def test_dst_spring_forward_during_session(self) -> None:
        ny = datetime(2026, 3, 8, 18, 0, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-03-08"

    def test_dst_fall_back_pre_open(self) -> None:
        ny = datetime(2026, 11, 1, 1, 30, tzinfo=NY_TZ)
        assert ny_session_date(ny) == "2026-10-31"


# ---------------------------------------------------------------------------
# Validator orchestration
# ---------------------------------------------------------------------------


class TestValidatorOrchestration:
    def _setup(self) -> tuple[BotDB, GateStateStore, Validator, Path]:
        db, path = _make_db()
        store = GateStateStore(db)
        validator = Validator(store)
        return db, store, validator, path

    def test_chart_only_blocked(self) -> None:
        db, store, v, path = self._setup()
        try:
            p = _make_payload(symbol="GBPUSD")
            outcome = v.validate(p)
            assert outcome.decision is Decision.BLOCKED
        finally:
            _cleanup(path)

    def test_chart_ok_no_manual_needs_ack(self) -> None:
        db, store, v, path = self._setup()
        try:
            p = parse_payload(VALID_PIPE)
            outcome = v.validate(p)
            assert outcome.decision is Decision.NEEDS_MANUAL_ACK
            assert len(outcome.missing_manual) == 6
        finally:
            _cleanup(path)

    def test_all_manual_acked_accepted_ready(self) -> None:
        db, store, v, path = self._setup()
        try:
            for name in MANUAL_GATE_NAMES:
                store.upsert(name, True, acknowledged_by="u1")
            p = parse_payload(VALID_PIPE)
            outcome = v.validate(p)
            assert outcome.decision is Decision.ACCEPTED_READY
            assert outcome.all_passed is True
        finally:
            _cleanup(path)

    def test_admin_override_skips_manual(self) -> None:
        db, path = _make_db()
        try:
            store = GateStateStore(db)
            v = Validator(store, admin_override=True)
            p = parse_payload(VALID_PIPE)
            outcome = v.validate(p)
            assert outcome.decision is Decision.ACCEPTED_READY
        finally:
            _cleanup(path)

    def test_manual_ack_false_yields_notify_only(self) -> None:
        """If all 6 manual gates acked but one is False, decision = NOTIFY_ONLY."""
        db, store, v, path = self._setup()
        try:
            for name in MANUAL_GATE_NAMES:
                store.upsert(name, name != "judgment_clear", acknowledged_by="u1")
            p = parse_payload(VALID_PIPE)
            outcome = v.validate(p)
            assert outcome.decision is Decision.NOTIFY_ONLY
            assert outcome.missing_manual == ()
        finally:
            _cleanup(path)

    def test_blocking_reasons_human_readable(self) -> None:
        db, store, v, path = self._setup()
        try:
            p = _make_payload(symbol="GBPUSD", state="blocked")
            outcome = v.validate(p)
            reasons = outcome.blocking_reasons()
            assert any("symbol_eurusd" in r for r in reasons)
            assert any("pine_state_ok" in r for r in reasons)
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Telegram ack keyboard + parse_ack_callback
# ---------------------------------------------------------------------------


class TestAckKeyboard:
    def test_keyboard_layout_three_gates(self) -> None:
        kb = build_ack_keyboard(
            "abc1234567890abc", ["risk_ok", "trades_left", "daily_loss_ok"]
        )
        rows = kb["inline_keyboard"]
        assert len(rows) == 3
        assert rows[0][0]["callback_data"] == "ack:risk_ok:abc1234567890abc"
        assert rows[0][1]["callback_data"] == "ack:trades_left:abc1234567890abc"
        assert len(rows[1]) == 1
        assert rows[1][0]["callback_data"] == "ack:daily_loss_ok:abc1234567890abc"
        assert rows[2][0]["callback_data"] == "accept:abc1234567890abc:nonce"
        assert rows[2][1]["callback_data"] == "reject:abc1234567890abc:nonce"

    def test_no_missing_gives_only_accept_reject(self) -> None:
        kb = build_ack_keyboard("sig1", [])
        rows = kb["inline_keyboard"]
        assert len(rows) == 1
        assert rows[0][0]["text"] == "✅ Accept"

    def test_two_gates_one_row(self) -> None:
        kb = build_ack_keyboard("sig1", ["risk_ok", "trades_left"])
        rows = kb["inline_keyboard"]
        assert len(rows) == 2
        assert len(rows[0]) == 2


class TestParseAckCallback:
    def test_valid_ack(self) -> None:
        result = TelegramDispatcher.parse_ack_callback("ack:risk_ok:abc1234567890abc")
        assert result == ("risk_ok", "abc1234567890abc")

    def test_uppercase_normalized(self) -> None:
        result = TelegramDispatcher.parse_ack_callback("ack:risk_ok:ABC1234567890ABC")
        assert result == ("risk_ok", "abc1234567890abc")

    def test_unknown_gate_rejected(self) -> None:
        assert TelegramDispatcher.parse_ack_callback("ack:not_a_gate:sig") is None

    def test_missing_prefix_rejected(self) -> None:
        assert TelegramDispatcher.parse_ack_callback("accept:abc:nonce") is None

    def test_malformed_rejected(self) -> None:
        assert TelegramDispatcher.parse_ack_callback("ack:only_gate") is None


# ---------------------------------------------------------------------------
# Accept revalidation end-to-end via /telegram/callback
# ---------------------------------------------------------------------------


class TestAcceptRevalidation:
    def _setup_app(self) -> tuple[TestClient, BotDB, FakeTelegramTransport, Path]:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="test_accept_"))
        db_path = tmp_dir / "bot.db"
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

    def _capture_accept_cb(self, tg: FakeTelegramTransport) -> str:
        sent_msg = tg.sent[-1]
        kb = sent_msg["reply_markup"]["inline_keyboard"]
        return next(
            b["callback_data"]
            for row in kb for b in row if b["text"].startswith("✅")
        )

    def test_accept_refused_when_manual_gates_missing(self) -> None:
        client, db, tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            accept_cb = self._capture_accept_cb(tg)
            resp = client.post(
                "/telegram/callback?token=test-secret-do-not-use-in-prod",
                json={"callback_data": accept_cb, "from_user_id": 456},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 409
            body = resp.json()
            assert body["decision"] == "refused"
            assert "risk_ok" in body["reason"]
            signal_id = parse_payload(VALID_PIPE).signal_id
            events = [e for e in db.list_recent_events() if e["signal_id"] == signal_id]
            assert any(e["event_type"] == "reject" for e in events)
        finally:
            _cleanup(db_path)

    def test_accept_succeeds_when_all_acked(self) -> None:
        client, db, tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            for name in MANUAL_GATE_NAMES:
                client.post(
                    "/telegram/command?token=test-secret-do-not-use-in-prod",
                    json={"text": f"/ack {name}", "from_user_id": "456"},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
                )
            accept_cb = self._capture_accept_cb(tg)
            resp = client.post(
                "/telegram/callback?token=test-secret-do-not-use-in-prod",
                json={"callback_data": accept_cb, "from_user_id": 456},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 200
            assert resp.json()["decision"] == "accepted"
            signal_id = parse_payload(VALID_PIPE).signal_id
            events = [e for e in db.list_recent_events() if e["signal_id"] == signal_id]
            assert any(e["event_type"] == "accept" for e in events)
        finally:
            _cleanup(db_path)

    def test_unauthorized_user_accept_refused(self) -> None:
        client, _db, tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            accept_cb = self._capture_accept_cb(tg)
            resp = client.post(
                "/telegram/callback?token=test-secret-do-not-use-in-prod",
                json={"callback_data": accept_cb, "from_user_id": 999},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 403
        finally:
            _cleanup(db_path)

    def test_reject_clears_signal_specific_gates(self) -> None:
        client, db, tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            from smc_bot_webhook.gates.state import GateStateStore
            store = GateStateStore(db)
            for name in ("no_position", "spread_news_clean", "judgment_clear", "risk_ok", "trades_left", "daily_loss_ok"):
                store.upsert(name, True, acknowledged_by="u")
            reject_cb = next(
                b["callback_data"]
                for row in tg.sent[-1]["reply_markup"]["inline_keyboard"]
                for b in row
                if b["text"].startswith("❌")
            )
            resp = client.post(
                "/telegram/callback?token=test-secret-do-not-use-in-prod",
                json={"callback_data": reject_cb, "from_user_id": 456},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 200
            snap = store.snapshot()
            assert snap.statuses["no_position"].value is None
            assert snap.statuses["spread_news_clean"].value is None
            assert snap.statuses["judgment_clear"].value is None
            assert snap.statuses["risk_ok"].value is True
            signal_id = parse_payload(VALID_PIPE).signal_id
            events = [e for e in db.list_recent_events() if e["signal_id"] == signal_id]
            assert any(e["event_type"] == "reject" for e in events)
        finally:
            _cleanup(db_path)

    def test_telegram_command_rejects_unauthorized_user(self) -> None:
        client, _db, _tg, db_path = self._setup_app()
        try:
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            resp = client.post(
                "/telegram/command?token=test-secret-do-not-use-in-prod",
                json={"text": "/ack risk_ok", "from_user_id": 999},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 403
            assert resp.json()["reason"] == "user not allowed"
        finally:
            _cleanup(db_path)

    def test_telegram_command_accepts_authorized_user(self) -> None:
        client, db, _tg, db_path = self._setup_app()
        try:
            from smc_bot_webhook.gates.state import GateStateStore
            store = GateStateStore(db)
            url = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"
            client.post(url, content=VALID_PIPE, headers={
                "content-type": "text/plain", "x-forwarded-for": "52.89.214.238",
            })
            resp = client.post(
                "/telegram/command?token=test-secret-do-not-use-in-prod",
                json={"text": "/ack risk_ok", "from_user_id": 456},
                headers={
                    "x-forwarded-for": "52.89.214.238",
                    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-callback-secret",
                }
            )
            assert resp.status_code == 200
            assert resp.json()["handled"] is True
            assert resp.json()["gate"] == "risk_ok"
            snap = store.snapshot()
            assert snap.statuses["risk_ok"].value is True
        finally:
            _cleanup(db_path)