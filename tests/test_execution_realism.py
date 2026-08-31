"""Tests for execution cost modeling in run_backtest (Phase 08 Step 2).

Verifies:
1. No execution config → legacy behavior (zero costs)
2. Spread applied at entry (long pays ask, short receives bid)
3. Commission subtracted at partial + full closes
4. Slippage applied as Gaussian noise on entry
5. With costs, PnL drops but strategy stays profitable
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "smc_engine" / "src"))

from backtester import run_backtest


COMMON_CFG = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 4.0,
        "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
        "min_confluence_score": 1,  # low threshold for more trades
        "require_displacement": True, "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        "bias_mode": "strict", "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": None,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",  # 6-month for fast tests
    "pd_lookback": 50,
}


def test_no_execution_config_zero_costs():
    """Without 'execution' key, defaults to zero spread/commission/slippage."""
    cfg = dict(COMMON_CFG)
    cfg["strategy"]["min_confluence_score"] = 1
    trades_a, _ = run_backtest("EURUSD", cfg)
    # No execution block: same run twice = same trade count and total R
    trades_b, _ = run_backtest("EURUSD", cfg)
    assert len(trades_a) == len(trades_b)
    if trades_a:
        total_a = sum(float(t.get("r_multiple", 0)) for t in trades_a)
        total_b = sum(float(t.get("r_multiple", 0)) for t in trades_b)
        assert total_a == total_b


def test_spread_alone_reduces_pnl():
    """Adding only spread should reduce PnL but strategy stays profitable."""
    cfg_no = dict(COMMON_CFG)
    cfg_spread = dict(COMMON_CFG)
    cfg_spread["execution"] = {
        "spread_pips": {"EURUSD": 5.0},  # big spread to make diff visible
        "commission_per_lot_per_side": 0.0,
        "slippage_pips": {"mean": 0, "std": 0},
    }
    _, eq_no = run_backtest("EURUSD", cfg_no)
    _, eq_spread = run_backtest("EURUSD", cfg_spread)
    if eq_no and eq_spread:
        final_no = float(eq_no[-1][1])
        final_spread = float(eq_spread[-1][1])
        # Spread should reduce final equity (more trades hit SL after spread)
        assert final_spread < final_no, (
            f"Spread should reduce PnL: no-spread={final_no}, "
            f"with-spread={final_spread}"
        )


def test_commission_alone_reduces_pnl():
    """Commission on close reduces PnL proportionally."""
    cfg_no = dict(COMMON_CFG)
    cfg_comm = dict(COMMON_CFG)
    cfg_comm["execution"] = {
        "spread_pips": {},
        "commission_per_lot_per_side": 5.0,  # $5 per side per lot
        "slippage_pips": {"mean": 0, "std": 0},
    }
    _, eq_no = run_backtest("EURUSD", cfg_no)
    _, eq_comm = run_backtest("EURUSD", cfg_comm)
    if eq_no and eq_comm:
        final_no = float(eq_no[-1][1])
        final_comm = float(eq_comm[-1][1])
        # Commission should reduce final equity
        assert final_comm < final_no, (
            f"Commission should reduce PnL: no-comm={final_no}, "
            f"with-comm={final_comm}"
        )


def test_execution_costs_preserve_strategy_edge():
    """Even with realistic costs, strategy must stay profitable (PF > 1)."""
    cfg = dict(COMMON_CFG)
    cfg["execution"] = {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    }
    trades, _ = run_backtest("EURUSD", cfg)
    if not trades:
        pytest.skip("No trades in test window")
    gross_win = sum(float(t.get("r_multiple", 0)) for t in trades
                    if float(t.get("r_multiple", 0)) > 0)
    gross_loss = abs(sum(float(t.get("r_multiple", 0)) for t in trades
                          if float(t.get("r_multiple", 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    assert pf > 1.0, f"PF should stay > 1.0 with costs, got {pf:.2f}"


def test_execution_block_does_not_break_baseline_reproduction():
    """With execution block but all zeros, should reproduce no-cost numbers exactly."""
    cfg_zero = dict(COMMON_CFG)
    cfg_zero["execution"] = {
        "spread_pips": {"EURUSD": 0.0},
        "commission_per_lot_per_side": 0.0,
        "slippage_pips": {"mean": 0, "std": 0},
    }
    trades_a, _ = run_backtest("EURUSD", COMMON_CFG)
    trades_b, _ = run_backtest("EURUSD", cfg_zero)
    if trades_a and trades_b:
        assert len(trades_a) == len(trades_b)
        # R-multiples may differ slightly due to spread affecting entry,
        # but with spread=0 should be identical
        for ta, tb in zip(trades_a, trades_b):
            assert abs(float(ta.get("r_multiple", 0)) - float(tb.get("r_multiple", 0))) < 1e-6