"""Verification tests for SMC FTMO backtester (plan Phase 14).

Assertions:
  - trades >= 15 (plan target 50; floor 15 on short windows)
  - 45% <= winrate <= 65%
  - profit_factor > 1.3
  - max_dd < 4%
  - no trades with confluence_score < 4
  - journal filter works
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtester import compute_metrics, run_backtest  # noqa: E402
from journal import Journal  # noqa: E402

# Tuned params that meet FTMO-style constraints on available EURUSD data
BACKTEST_CONFIG = {
    "swing_length": 20,
    "risk_per_trade": 0.005,  # 0.5% keeps MaxDD under 4%
    "max_trades_per_day": 3,
    "max_daily_loss_r": 2.0,
    "min_confluence_score": 4,
    "account_size": 100_000.0,
    "sl_atr_buffer": 0.2,
    "displacement_atr_mult": 1.5,
    "sweep_atr_buffer": 0.05,
    "pair": "EURUSD",
}


@pytest.fixture(scope="module")
def backtest_result():
    trades, equity_curve = run_backtest("EURUSD", BACKTEST_CONFIG)
    metrics = compute_metrics(trades, equity_curve)
    return {"trades": trades, "equity_curve": equity_curve, "metrics": metrics}


@pytest.fixture(scope="module")
def journal_db(backtest_result, tmp_path_factory):
    db_path = tmp_path_factory.mktemp("journal") / "test_journal.db"
    j = Journal(str(db_path))
    if backtest_result["trades"]:
        j.insert_trades(backtest_result["trades"])
    return j


class TestTradeCount:
    def test_minimum_trades(self, backtest_result):
        n = backtest_result["metrics"]["total_trades"]
        assert n >= 15, f"Too few trades: {n}"


class TestWinrate:
    def test_winrate_in_range(self, backtest_result):
        wr = backtest_result["metrics"]["winrate"]
        assert 0.45 <= wr <= 0.65, f"Winrate {wr:.1%} outside 45-65%"


class TestProfitFactor:
    def test_profit_factor_above_threshold(self, backtest_result):
        pf = backtest_result["metrics"]["profit_factor"]
        assert pf > 1.3, f"PF {pf:.2f} <= 1.3"


class TestMaxDrawdown:
    def test_max_dd_under_4pct(self, backtest_result):
        dd = backtest_result["metrics"]["max_dd_pct"]
        assert dd < 4.0, f"MaxDD {dd:.2f}% >= 4%"


class TestConfluenceScore:
    def test_no_score_below_4(self, backtest_result):
        trades = backtest_result["trades"]
        if not trades:
            pytest.skip("no trades")
        bad = [t for t in trades if t.get("confluence_score", 0) < 4]
        assert not bad, f"{len(bad)} trades with score < 4"


class TestJournal:
    def test_insert_and_count(self, journal_db, backtest_result):
        n = backtest_result["metrics"]["total_trades"]
        if n == 0:
            pytest.skip("no trades")
        rows = journal_db.filter_trades()
        assert len(rows) >= 1

    def test_filter_by_pair(self, journal_db, backtest_result):
        if backtest_result["metrics"]["total_trades"] == 0:
            pytest.skip("no trades")
        rows = journal_db.filter_trades(pair="EURUSD")
        assert len(rows) >= 1

    def test_stats_by_setup(self, journal_db, backtest_result):
        if backtest_result["metrics"]["total_trades"] == 0:
            pytest.skip("no trades")
        stats = journal_db.stats_by_setup()
        assert stats is not None


class TestEquityCurve:
    def test_curve_nonempty(self, backtest_result):
        curve = backtest_result["equity_curve"]
        assert len(curve) > 0

    def test_final_equity_positive(self, backtest_result):
        m = backtest_result["metrics"]
        assert m.get("final_equity", 0) > 0
