"""Tests for Phase 06 MT5 file-bridge modules.

Coverage:
  - SignalRecord construction (defaults, override, ISO timestamps)
  - OutboxWriter atomic write (.tmp never visible, fsync, rename)
  - OutboxWriter idempotency (pending/processing duplicate detection)
  - OutboxWriter reads (sorted pending list)
  - write_signal() expiry check (raises SignalExpiredError)
  - FtmoGuard: all 3 limits, edge cases (exactly at threshold)
  - Executor dispatcher: disabled / file / metaapi / unknown
  - FileBridgeExecutor: writes JSON to outbox
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from smc_bot_webhook.mt5_bridge.executor import (
    DisabledExecutor,
    FileBridgeExecutor,
    build_executor,
)
from smc_bot_webhook.mt5_bridge.ftmo_guard import (
    FTMO_DEFAULT_MAX_DAILY_PNL,
    FTMO_DEFAULT_MAX_OPEN_POSITIONS,
    FTMO_DEFAULT_MAX_TRADES_PER_DAY,
    FtmoGuard,
    FtmoGuardResult,
    GuardState,
)
from smc_bot_webhook.mt5_bridge.signal_writer import (
    EXECUTION_SCHEMA_VERSION,
    OutboxWriter,
    SignalAlreadyWrittenError,
    SignalExpiredError,
    SignalRecord,
    write_signal,
)


def _tmp_outbox() -> Path:
    p = Path(f"output/test_mt5_{int(time.time() * 1e6)}_{id(Path())}")
    return p


def _cleanup(p: Path) -> None:
    import shutil
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def _make_record(**overrides: object) -> SignalRecord:
    base = dict(
        signal_id="abc1234567890ab",
        symbol="EURUSD",
        side="long",
        entry=1.1000,
        sl=1.0950,
        tp=(1.1100, 1.1150, 1.1200),
        risk_pct=0.0055,
        bar_time="2026-08-30T12:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
        ob_id=1,
        bos_id=2,
        approved_by="tester",
        guard_snapshot={"trades_today": 0},
    )
    base.update(overrides)
    return SignalRecord(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SignalRecord
# ---------------------------------------------------------------------------


class TestSignalRecord:
    def test_construction_with_overrides(self) -> None:
        rec = _make_record(entry=1.2000, side="short")
        assert rec.entry == 1.2000
        assert rec.side == "short"

    def test_to_dict_includes_schema_version(self) -> None:
        rec = _make_record()
        d = rec.to_dict()
        assert d["schema"] == EXECUTION_SCHEMA_VERSION
        assert d["signal_id"] == rec.signal_id
        assert d["tp"] == list(rec.tp)  # tuple -> list for JSON

    def test_from_alert_payload_defaults(self) -> None:
        from pytest import approx
        rec = SignalRecord.from_alert_payload(
            signal_id="abc1234567890ab",
            symbol="EURUSD",
            side="long",
            level=1.1000,
            bar_time=datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
            ob_id=1,
            bos_id=2,
            approved_by="tester",
        )
        assert rec.signal_id == "abc1234567890ab"
        assert rec.symbol == "EURUSD"
        assert rec.side == "long"
        # Use approx due to floating-point: 1.1 + 0.0050*2 != exactly 1.11
        assert rec.tp[0] == approx(1.11, abs=1e-9)
        assert rec.tp[1] == approx(1.115, abs=1e-9)
        assert rec.tp[2] == approx(1.12, abs=1e-9)
        assert rec.ob_id == 1
        assert rec.bos_id == 2
        assert rec.approved_by == "tester"
        # ISO timestamps with Z suffix (MQL5 friendly)
        assert rec.bar_time.endswith("Z")
        assert rec.expires_at.endswith("Z")

    def test_from_alert_payload_short_side_uses_lower_tp(self) -> None:
        rec = SignalRecord.from_alert_payload(
            signal_id="x", symbol="EURUSD", side="short", level=1.1000,
            bar_time=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            ob_id=1, bos_id=2, approved_by="t",
        )
        # Short: SL above entry, TP below.
        assert rec.sl > rec.entry
        assert all(tp < rec.entry for tp in rec.tp)

    def test_from_alert_payload_explicit_overrides(self) -> None:
        rec = SignalRecord.from_alert_payload(
            signal_id="x", symbol="EURUSD", side="long", level=1.1,
            bar_time=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            ob_id=1, bos_id=2, approved_by="t",
            sl=1.05, tp_levels=(1.15, 1.20, 1.25), risk_pct=0.01,
            ttl_seconds=600,
        )
        assert rec.sl == 1.05
        assert rec.tp == (1.15, 1.20, 1.25)
        assert rec.risk_pct == 0.01
        # ttl_seconds=600 -> expires 10 min after bar_time
        delta = (
            datetime.fromisoformat(rec.expires_at.replace("Z", "+00:00"))
            - datetime.fromisoformat(rec.bar_time.replace("Z", "+00:00"))
        )
        assert delta.total_seconds() == 600


# ---------------------------------------------------------------------------
# OutboxWriter
# ---------------------------------------------------------------------------


class TestOutboxWriter:
    def test_create_outbox_creates_subdirs(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        for sub in ("pending", "processing", "done", "failed"):
            assert (tmp_path / sub).is_dir()
        assert ob.pending == tmp_path / "pending"

    def test_atomic_write_creates_json_file(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        rec = _make_record()
        path = ob.write_atomic("sig001", rec)
        assert path.exists()
        assert path.suffix == ".json"
        assert path.parent.name == "pending"
        # No .tmp leftover.
        assert list(ob.pending.glob("*.tmp")) == []

    def test_atomic_write_json_is_parseable(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        rec = _make_record()
        path = ob.write_atomic("sig002", rec)
        data = json.loads(path.read_text())
        assert data["schema"] == EXECUTION_SCHEMA_VERSION
        assert data["signal_id"] == rec.signal_id
        assert data["symbol"] == "EURUSD"

    def test_is_pending_true_after_write(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        ob.write_atomic("sig003", _make_record())
        assert ob.is_pending("sig003") is True
        assert ob.is_pending("nonexistent") is False

    def test_is_done_returns_false_until_moved(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        ob.write_atomic("sig004", _make_record())
        assert ob.is_done("sig004") is False

    def test_idempotency_blocks_duplicate_pending(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        ob.write_atomic("sig005", _make_record())
        with pytest.raises(SignalAlreadyWrittenError):
            ob.write_atomic("sig005", _make_record())

    def test_idempotency_blocks_duplicate_against_processing(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        ob.write_atomic("sig006", _make_record())
        # Simulate EA moving file to processing/
        (tmp_path / "pending" / "sig006.json").rename(tmp_path / "processing" / "sig006.json")
        with pytest.raises(SignalAlreadyWrittenError):
            ob.write_atomic("sig006", _make_record())

    def test_read_pending_sorted_alphabetically(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        for sid in ("z_last", "a_first", "m_middle"):
            ob.write_atomic(sid, _make_record(signal_id=sid))
        files = [p.name for p in ob.read_pending()]
        assert files == sorted(files)
        # alphabetical (and "z" > "m" > "a")
        assert files[0].startswith("a_")
        assert files[-1].startswith("z_")

    def test_existing_file_does_not_overwrite(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        ob.write_atomic("sig007", _make_record(signal_id="sig007", entry=1.10))
        with pytest.raises(SignalAlreadyWrittenError):
            ob.write_atomic("sig007", _make_record(signal_id="sig007", entry=1.99))


class TestWriteSignal:
    def test_expired_signal_raises(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        # expires_at in 1970 (way past)
        rec = _make_record(expires_at="1970-01-01T00:00:00Z")
        with pytest.raises(SignalExpiredError):
            write_signal(ob, rec)

    def test_future_expiry_writes(self, tmp_path: Path) -> None:
        ob = OutboxWriter(tmp_path)
        rec = _make_record(expires_at="2099-01-01T00:00:00Z")
        path = write_signal(ob, rec)
        assert path.exists()


# ---------------------------------------------------------------------------
# FTMO Guard
# ---------------------------------------------------------------------------


class TestFtmoGuard:
    def test_all_passed(self) -> None:
        g = FtmoGuard()
        st = GuardState(daily_pnl=0.005, trades_today=0, open_positions={})
        result = g.check(st, "EURUSD")
        assert result.allowed is True

    def test_daily_loss_blocks(self) -> None:
        g = FtmoGuard()
        # FTMO 10k default = -1.1% threshold.
        st = GuardState(daily_pnl=FTMO_DEFAULT_MAX_DAILY_PNL - 0.001, trades_today=0)
        result = g.check(st, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "daily_loss"

    def test_daily_loss_exactly_at_threshold_blocks(self) -> None:
        """Boundary test: at exactly the threshold, still blocked (>= semantics)."""
        g = FtmoGuard()
        st = GuardState(daily_pnl=FTMO_DEFAULT_MAX_DAILY_PNL, trades_today=0)
        result = g.check(st, "EURUSD")
        assert result.allowed is False

    def test_trades_today_blocks(self) -> None:
        g = FtmoGuard()
        st = GuardState(daily_pnl=0.0, trades_today=FTMO_DEFAULT_MAX_TRADES_PER_DAY)
        result = g.check(st, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "trades_today"

    def test_open_position_per_symbol_blocks(self) -> None:
        g = FtmoGuard()
        st = GuardState(daily_pnl=0.0, trades_today=0, open_positions={"EURUSD": 1})
        result = g.check(st, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "open_position"

    def test_open_position_only_blocks_for_that_symbol(self) -> None:
        g = FtmoGuard()
        st = GuardState(open_positions={"GBPUSD": 1})
        # Asking about EURUSD while GBPUSD is open should pass.
        assert g.check(st, "EURUSD").allowed is True

    def test_custom_limits(self) -> None:
        g = FtmoGuard(
            max_daily_pnl=-0.05,           # 5% loss limit
            max_trades_per_day=10,
            max_open_positions=3,
        )
        st = GuardState(daily_pnl=-0.03, trades_today=5, open_positions={"X": 1})
        assert g.check(st, "X").allowed is True

    def test_invalid_limits_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="max_daily_pnl"):
            FtmoGuard(max_daily_pnl=0.01)  # positive
        with pytest.raises(ValueError, match="max_trades"):
            FtmoGuard(max_trades_per_day=0)
        with pytest.raises(ValueError, match="max_open"):
            FtmoGuard(max_open_positions=0)


# ---------------------------------------------------------------------------
# Executor dispatcher
# ---------------------------------------------------------------------------


class TestExecutorDispatcher:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EXECUTOR_TRANSPORT", raising=False)
        e = build_executor()
        assert e.name == "disabled"
        assert e.enabled is False

    def test_disabled_returns_true_with_message(self) -> None:
        e = DisabledExecutor()
        rec = _make_record()
        ok, msg = e.execute(rec)
        assert ok is True
        assert "disabled" in msg

    def test_file_executor_enabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("EXECUTOR_TRANSPORT", "file")
        monkeypatch.setenv("MT5_OUTBOX_DIR", str(tmp_path))
        e = build_executor(outbox_dir=tmp_path)
        assert e.name == "file"
        assert e.enabled is True
        rec = _make_record()
        ok, msg = e.execute(rec)
        assert ok is True
        # File should be at <outbox>/pending/<sid>.json
        assert (tmp_path / "pending").is_dir()

    def test_metaapi_not_implemented(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXECUTOR_TRANSPORT", "metaapi")
        with pytest.raises(NotImplementedError, match="Phase 06.5"):
            build_executor()

    def test_unknown_transport_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXECUTOR_TRANSPORT", "weird")
        with pytest.raises(ValueError, match="unknown EXECUTOR_TRANSPORT"):
            build_executor()

    def test_file_executor_idempotency(self, tmp_path: Path) -> None:
        """Same signal_id twice -> second call returns False (duplicate)."""
        e = FileBridgeExecutor(OutboxWriter(tmp_path))
        rec = _make_record(signal_id="dup001")
        ok1, _ = e.execute(rec)
        assert ok1 is True
        ok2, msg2 = e.execute(rec)
        assert ok2 is False
        assert "duplicate" in msg2.lower()

    def test_file_executor_creates_pending_dir(self, tmp_path: Path) -> None:
        e = FileBridgeExecutor(OutboxWriter(tmp_path))
        rec = _make_record(signal_id="new001")
        ok, _ = e.execute(rec)
        assert ok is True
        # File should exist in pending/.
        assert (tmp_path / "pending" / "new001.json").exists()


# ---------------------------------------------------------------------------
# Webhook integration: Accept fires executor
# ---------------------------------------------------------------------------


class TestWebhookAcceptExecutesSignal:
    """End-to-end: webhook receives Telegram Accept -> executor fires -> execution_log
    has a row. Uses FastAPI TestClient."""

    def test_accept_disabled_executor_records_queued(self, tmp_path: Path) -> None:
        """EXECUTOR_TRANSPORT=disabled (default) records execution_log row as queued."""
        import os
        from smc_bot_webhook.notify.telegram import FakeTelegramTransport, TelegramDispatcher
        from smc_bot_webhook.security import SecurityConfig
        from smc_bot_webhook.server import AppSettings, create_app
        from smc_bot_webhook.gates.state import GateStateStore
        from smc_bot_webhook.gates.validator import Validator

        os.environ["SMC_BOT_DB_PATH"] = str(tmp_path / "bot.db")
        os.environ["MT5_OUTBOX_DIR"] = str(tmp_path / "outbox")
        os.environ["EXECUTOR_TRANSPORT"] = "disabled"

        from smc_bot_core.db import BotDB, init_db
        init_db(tmp_path / "bot.db")
        db = BotDB(tmp_path / "bot.db")

        # Insert a fresh alert + ack all 6 gates so validator passes.
        from smc_bot_webhook.payload import parse_payload
        body = (
            "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
            "|state=chart-qualified|reason=ok"
        )
        payload = parse_payload(body)
        db.insert_alert(payload, url_token_ok=True)
        store = GateStateStore(db)
        for name in ("risk_ok","trades_left","daily_loss_ok","no_position","spread_news_clean","judgment_clear"):
            store.upsert(name, True, acknowledged_by="tester")

        tg = FakeTelegramTransport()
        dispatcher = TelegramDispatcher(
            tg, chat_id=12345, allowed_user_ids={99},
            max_retries=2, backoff_base_seconds=0.001,
        )
        settings = AppSettings(
            url_secret="smoke-test-secret-not-for-prod",
            db_path=tmp_path / "bot.db",
            security=SecurityConfig(
                url_secret="smoke-test-secret-not-for-prod", rate_limit_per_min=1000,
            ),
            trusted_proxy=True,
        )
        app = create_app(settings=settings, db=db, dispatcher=dispatcher)
        from fastapi.testclient import TestClient
        client = TestClient(app)

        # Skip webhook POST (bg dispatch fires only on lifespan exit, not after
        # client.post). Craft callback_data from known signal_id.
        accept_cb = f"accept:{payload.signal_id}:test_nonce"
        r = client.post(
            "/telegram/callback?token=smoke-test-secret-not-for-prod",
            json={"callback_data": accept_cb, "from_user_id": 99},
            headers={"x-forwarded-for": "52.89.214.238"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["decision"] == "accepted"
        # Disabled executor records queued row.
        assert body["execution"]["state"] == "queued"
        assert body["execution"]["transport"] == "disabled"

        rows = db.list_executions()
        assert len(rows) == 1
        assert rows[0]["signal_id"] == payload.signal_id
        assert rows[0]["transport"] == "disabled"
        assert rows[0]["state"] == "queued"

    def test_accept_file_executor_writes_outbox(self, tmp_path: Path) -> None:
        """EXECUTOR_TRANSPORT=file writes JSON to outbox/pending/."""
        import os
        from smc_bot_webhook.notify.telegram import FakeTelegramTransport, TelegramDispatcher
        from smc_bot_webhook.security import SecurityConfig
        from smc_bot_webhook.server import AppSettings, create_app
        from smc_bot_webhook.gates.state import GateStateStore

        os.environ["SMC_BOT_DB_PATH"] = str(tmp_path / "bot.db")
        os.environ["EXECUTOR_TRANSPORT"] = "file"
        os.environ["MT5_OUTBOX_DIR"] = str(tmp_path / "outbox")

        from smc_bot_core.db import BotDB, init_db
        init_db(tmp_path / "bot.db")
        db = BotDB(tmp_path / "bot.db")

        from smc_bot_webhook.payload import parse_payload
        body = (
            "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
            "|state=chart-qualified|reason=ok"
        )
        payload = parse_payload(body)
        db.insert_alert(payload, url_token_ok=True)
        store = GateStateStore(db)
        for name in ("risk_ok","trades_left","daily_loss_ok","no_position","spread_news_clean","judgment_clear"):
            store.upsert(name, True, acknowledged_by="tester")

        tg = FakeTelegramTransport()
        dispatcher = TelegramDispatcher(
            tg, chat_id=12345, allowed_user_ids={99},
            max_retries=2, backoff_base_seconds=0.001,
        )
        settings = AppSettings(
            url_secret="smoke-test-secret-not-for-prod",
            db_path=tmp_path / "bot.db",
            security=SecurityConfig(
                url_secret="smoke-test-secret-not-for-prod", rate_limit_per_min=1000,
            ),
            trusted_proxy=True,
        )
        app = create_app(settings=settings, db=db, dispatcher=dispatcher)
        from fastapi.testclient import TestClient
        client = TestClient(app)

        accept_cb = f"accept:{payload.signal_id}:test_nonce"
        r = client.post(
            "/telegram/callback?token=smoke-test-secret-not-for-prod",
            json={"callback_data": accept_cb, "from_user_id": 99},
            headers={"x-forwarded-for": "52.89.214.238"},
        )
        assert r.status_code == 200
        assert r.json()["execution"]["state"] == "queued"
        assert r.json()["execution"]["transport"] == "file"
        # Outbox file exists
        outbox_dir = Path(os.environ["MT5_OUTBOX_DIR"])
        assert (outbox_dir / "pending" / f"{payload.signal_id}.json").exists()
        rows = db.list_executions()
        assert len(rows) == 1
        assert rows[0]["transport"] == "file"
        assert rows[0]["state"] == "queued"