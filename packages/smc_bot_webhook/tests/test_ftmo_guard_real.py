"""Tests for Phase 02 — Real FTMO guard implementation.

Closes audit finding C1 (FTMO guard stub) + H2 (FTMO config mismatch).

The old ``build_guard_state_from_db`` always returned zeros, so the guard
never blocked any trade. The new implementation reads ``execution_log``
via BotDB aggregation methods. ``FtmoGuard.from_config`` derives the
daily loss threshold from ``config.risk.per_trade_pct`` and
``daily_loss_limit_r`` instead of hardcoded -0.011.
"""
from __future__ import annotations

import gc
import shutil
import tempfile
from pathlib import Path

import pytest

from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.mt5_bridge.ftmo_guard import (
    FtmoGuard,
    GuardState,
    build_guard_state_from_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_dir() -> Path:
    """Create a unique tmp dir for one DB. Caller is responsible for cleanup.

    On Windows, ``tempfile.TemporaryDirectory`` + ``with``-context does not
    work because the SQLite connection inside BotDB keeps the file handle
    open after the context manager exits, causing PermissionError on
    cleanup. Manual ``shutil.rmtree(ignore_errors=True)`` in the test
    fixture is the workaround.
    """
    return Path(tempfile.mkdtemp(prefix="test_phase02_"))


def _cleanup(db: BotDB | None, td: Path) -> None:
    """Best-effort cleanup: close BotDB, force GC, remove tmp dir."""
    del db  # drop reference so SQLite connection can close
    gc.collect()
    shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# BotDB aggregation methods
# ---------------------------------------------------------------------------


class TestBotDBAggregations:
    def test_get_daily_pnl_sums_filled_and_closed(self) -> None:
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            db.upsert_execution("sig001", "file", "filled", pnl=-0.005)
            db.upsert_execution("sig002", "file", "closed", pnl=0.003)
            db.upsert_execution("sig003", "file", "queued")
            pnl = db.get_daily_pnl("1970-01-01T00:00:00+00:00")
            assert pnl == pytest.approx(-0.005 + 0.003)
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_get_daily_pnl_skips_queued(self) -> None:
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            db.upsert_execution("sig001", "file", "filled", pnl=-0.005)
            db.upsert_execution("sig002", "file", "closed", pnl=0.003)
            db.upsert_execution("sig003", "file", "queued")  # no pnl
            pnl = db.get_daily_pnl("1970-01-01T00:00:00+00:00")
            # only filled + closed contribute
            assert pnl == pytest.approx(-0.002)
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_get_daily_pnl_empty_db_returns_zero(self) -> None:
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            assert db.get_daily_pnl("1970-01-01T00:00:00+00:00") == 0.0
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_get_trades_today_counts_active(self) -> None:
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            db.upsert_execution("sig001", "file", "filled", pnl=-0.005)
            db.upsert_execution("sig002", "file", "closed", pnl=0.003)
            db.upsert_execution("sig003", "file", "queued")
            assert db.get_trades_today("1970-01-01T00:00:00+00:00") == 3
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_get_trades_today_empty_db_returns_zero(self) -> None:
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            assert db.get_trades_today("1970-01-01T00:00:00+00:00") == 0
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_upsert_execution_preserves_existing_pnl(self) -> None:
        """Passing pnl=None on update must keep the previous value."""
        td = _make_db_dir()
        try:
            path = td / "bot.db"
            db = BotDB(path)
            db.upsert_execution("sig", "file", "filled", pnl=-0.01)
            db.upsert_execution("sig", "file", "closed", error="ok")  # no pnl
            rows = db.list_executions()
            assert len(rows) == 1
            assert rows[0]["pnl"] == pytest.approx(-0.01)
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise


# ---------------------------------------------------------------------------
# build_guard_state_from_db
# ---------------------------------------------------------------------------


class TestBuildGuardStateFromDb:
    def test_returns_zero_state_for_empty_db(self) -> None:
        td = _make_db_dir()
        try:
            db = BotDB(td / "bot.db")
            state = build_guard_state_from_db(
                db, "EURUSD", today_start="1970-01-01T00:00:00+00:00"
            )
            assert state.daily_pnl == 0.0
            assert state.trades_today == 0
            assert state.open_positions == {}
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_aggregates_daily_pnl_and_trade_count(self) -> None:
        td = _make_db_dir()
        try:
            db = BotDB(td / "bot.db")
            db.upsert_execution("sig_filled", "file", "filled", pnl=-0.005)
            db.upsert_execution("sig_queued", "file", "queued")
            state = build_guard_state_from_db(
                db, "EURUSD", today_start="1970-01-01T00:00:00+00:00"
            )
            assert state.daily_pnl == pytest.approx(-0.005)
            assert state.trades_today == 2  # filled + queued
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_raises_when_db_missing_method(self) -> None:
        class FakeDB:
            pass
        with pytest.raises(RuntimeError, match="missing aggregation method"):
            build_guard_state_from_db(
                FakeDB(), "EURUSD", today_start="1970-01-01T00:00:00+00:00"
            )


# ---------------------------------------------------------------------------
# FtmoGuard.from_config
# ---------------------------------------------------------------------------


class TestFtmoGuardFromConfig:
    def test_derives_daily_loss_from_risk_config(self) -> None:
        config = {
            "risk": {
                "per_trade_pct": 0.0055,
                "daily_loss_limit_r": 2.0,
                "max_trades_per_day": 3,
                "max_open_positions": 1,
            },
        }
        g = FtmoGuard.from_config(config)
        # -0.0055 × 2 = -0.011
        assert g._max_daily_pnl == pytest.approx(-0.011)
        assert g._max_trades == 3
        assert g._max_open == 1
        assert g.enabled is True

    def test_uses_floats(self) -> None:
        g = FtmoGuard.from_config({
            "risk": {"per_trade_pct": 0.01, "daily_loss_limit_r": 1.5},
        })
        assert g._max_daily_pnl == pytest.approx(-0.015)

    def test_none_config_returns_disabled_guard(self) -> None:
        g = FtmoGuard.from_config(None)
        assert g.enabled is False

    def test_empty_config_returns_disabled_guard(self) -> None:
        g = FtmoGuard.from_config({})
        # No risk section → fall back to defaults AND disable (no
        # configured risk means the trader hasn't set the bot up for
        # live trading yet).
        assert g.enabled is False

    def test_missing_risk_section_returns_disabled_guard(self) -> None:
        g = FtmoGuard.from_config({"ftmo": {}})
        assert g.enabled is False

    def test_blocks_when_daily_loss_exceeds_limit(self) -> None:
        config = {
            "risk": {
                "per_trade_pct": 0.0055,
                "daily_loss_limit_r": 2.0,
            },
        }
        g = FtmoGuard.from_config(config)
        state = GuardState(daily_pnl=-0.012, trades_today=0, open_positions={})
        result = g.check(state, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "daily_loss"
        assert result.threshold == pytest.approx(-0.011)

    def test_blocks_at_3rd_trade(self) -> None:
        config = {"risk": {"per_trade_pct": 0.0055, "daily_loss_limit_r": 2.0, "max_trades_per_day": 3}}
        g = FtmoGuard.from_config(config)
        state = GuardState(daily_pnl=0.0, trades_today=3, open_positions={})
        result = g.check(state, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "trades_today"

    def test_blocks_second_eurusd_position(self) -> None:
        config = {"risk": {"per_trade_pct": 0.0055, "daily_loss_limit_r": 2.0, "max_open_positions": 1}}
        g = FtmoGuard.from_config(config)
        state = GuardState(daily_pnl=0.0, trades_today=1, open_positions={"EURUSD": 1})
        result = g.check(state, "EURUSD")
        assert result.allowed is False
        assert result.limit_name == "open_position"


# ---------------------------------------------------------------------------
# End-to-end: build_guard_state_from_db → FtmoGuard.check
# ---------------------------------------------------------------------------


class TestEndToEndGuardFlow:
    def test_db_with_loss_exceeding_limit_blocks(self) -> None:
        td = _make_db_dir()
        try:
            db = BotDB(td / "bot.db")
            # 2 closed trades, each -0.006 → total -0.012 > -0.011 limit
            db.upsert_execution("s1", "file", "closed", pnl=-0.006)
            db.upsert_execution("s2", "file", "closed", pnl=-0.006)
            guard = FtmoGuard.from_config({
                "risk": {"per_trade_pct": 0.0055, "daily_loss_limit_r": 2.0}
            })
            state = build_guard_state_from_db(
                db, "EURUSD", today_start="1970-01-01T00:00:00+00:00"
            )
            result = guard.check(state, "EURUSD")
            assert result.allowed is False
            assert result.limit_name == "daily_loss"
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise

    def test_db_at_trade_limit_blocks(self) -> None:
        td = _make_db_dir()
        try:
            db = BotDB(td / "bot.db")
            for i in range(3):
                db.upsert_execution(f"s{i}", "file", "queued")
            guard = FtmoGuard.from_config({
                "risk": {"per_trade_pct": 0.0055, "daily_loss_limit_r": 2.0, "max_trades_per_day": 3}
            })
            state = build_guard_state_from_db(
                db, "EURUSD", today_start="1970-01-01T00:00:00+00:00"
            )
            result = guard.check(state, "EURUSD")
            assert result.allowed is False
            assert result.limit_name == "trades_today"
            _cleanup(db, td)
        except Exception:
            _cleanup(None, td)
            raise
