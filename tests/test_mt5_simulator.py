"""Unit tests for the MT5 fill simulator.

Tests the per-trade penalty model in `src/mt5_simulator.py`. The
simulator doesn't walk OHLCV bars (Python backtester already models
scale-in correctly) — it just applies broker-side spread + slippage
cost on top of `python_r_multiple` from the CSV export.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mt5_simulator import (  # noqa: E402
    FillConfig,
    compute_sim_metrics,
    diff_baseline_vs_sim,
    simulate_trade,
)


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Per-trade penalty model
# ---------------------------------------------------------------------------


class TestSimulateTrade:
    def test_default_config_produces_small_cost(self):
        """0.5 pip spread + 0.2 pip slippage on 100 pip SL ≈ 0.007R cost."""
        result = simulate_trade(
            python_r_multiple=2.0,
            sl_distance_pips=100.0,
            cfg=FillConfig(),
            rng=_rng(),
        )
        # 0.5 (spread) + ~0.2 (mean slippage × 2 fills) = 0.7 pip
        # 0.7 / 100 = 0.007R cost → R ~1.993
        assert abs(result.r_multiple - 1.993) < 0.01

    def test_spread_only_zero_slippage(self):
        cfg = FillConfig(spread_pips=1.0, slippage_mean_pips=0.0,
                          slippage_std_pips=0.0)
        result = simulate_trade(
            python_r_multiple=4.0, sl_distance_pips=50.0,
            cfg=cfg, rng=_rng(),
        )
        assert abs(result.r_multiple - 3.98) < 1e-6
        assert abs(result.spread_cost_r - 0.02) < 1e-6
        assert result.slippage_cost_r == 0.0

    def test_slippage_only_zero_spread(self):
        cfg = FillConfig(spread_pips=0.0, slippage_mean_pips=0.5,
                          slippage_std_pips=0.0)
        result = simulate_trade(
            python_r_multiple=4.0, sl_distance_pips=100.0,
            cfg=cfg, rng=_rng(),
        )
        assert abs(result.r_multiple - 3.99) < 1e-6
        assert result.spread_cost_r == 0.0

    def test_degenerate_sl_distance_no_cost(self):
        result = simulate_trade(
            python_r_multiple=2.0, sl_distance_pips=0.0,
            cfg=FillConfig(), rng=_rng(),
        )
        assert result.r_multiple == 2.0
        assert any("degenerate" in n for n in result.notes)

    def test_high_cost_triggers_note(self):
        cfg = FillConfig(spread_pips=5.0, slippage_mean_pips=0.0,
                          slippage_std_pips=0.0)
        result = simulate_trade(
            python_r_multiple=1.0, sl_distance_pips=5.0,
            cfg=cfg, rng=_rng(),
        )
        assert any("high cost" in n for n in result.notes)

    def test_cost_components_sum_to_total(self):
        cfg = FillConfig()
        result = simulate_trade(
            python_r_multiple=2.0, sl_distance_pips=50.0,
            cfg=cfg, rng=_rng(),
        )
        total_cost_r = result.spread_cost_r + result.slippage_cost_r
        cost_from_r = 2.0 - result.r_multiple
        assert abs(total_cost_r - cost_from_r) < 1e-6

    def test_pnl_usd_uses_risk_amount_formula(self):
        cfg = FillConfig(spread_pips=0.0, slippage_mean_pips=0.0,
                          slippage_std_pips=0.0, account_size=100_000.0,
                          risk_per_trade=0.0055)
        result = simulate_trade(
            python_r_multiple=2.0, sl_distance_pips=50.0,
            cfg=cfg, rng=_rng(),
        )
        assert abs(result.pnl_usd - 1100.0) < 1e-6


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class TestComputeSimMetrics:
    def test_empty_input_returns_zero_metrics(self):
        assert compute_sim_metrics([]) == {
            "trades": 0, "winrate": 0.0, "profit_factor": 0.0,
            "total_pnl_usd": 0.0, "max_dd_pct": 0.0, "avg_r": 0.0,
        }

    def test_basic_aggregates(self):
        rows = [
            {"mt5_sim_pnl_usd": "100.0"},
            {"mt5_sim_pnl_usd": "200.0"},
            {"mt5_sim_pnl_usd": "-50.0"},
            {"mt5_sim_pnl_usd": "-150.0"},
        ]
        m = compute_sim_metrics(rows)
        assert m["trades"] == 4
        assert m["winrate"] == 0.5
        assert abs(m["profit_factor"] - 1.5) < 1e-6
        assert abs(m["total_pnl_usd"] - 100.0) < 1e-6
        assert abs(m["avg_r"] - (25.0 / 550.0)) < 1e-6

    def test_zero_loss_pf_is_inf(self):
        m = compute_sim_metrics([
            {"mt5_sim_pnl_usd": "100.0"},
            {"mt5_sim_pnl_usd": "50.0"},
        ])
        assert m["profit_factor"] == float("inf")


class TestDiffBaselineVsSim:
    def test_diff_computes_deltas(self):
        # 3 wins × +1R + 2 losses × -1R (baseline)
        py = [{"r_multiple": "1.0", "pnl_usd": "550.0"}] * 3 + [
            {"r_multiple": "-1.0", "pnl_usd": "-550.0"}
        ] * 2
        # simulated: smaller wins, larger losses
        sim = [{"mt5_sim_pnl_usd": "500.0"}] * 3 + [
            {"mt5_sim_pnl_usd": "-575.0"}
        ] * 2
        result = diff_baseline_vs_sim(py, sim)
        # baseline total: 3×550 + 2×(-550) = +550
        # simulated total: 3×500 + 2×(-575) = +350
        # delta: 350 - 550 = -200
        assert abs(result["baseline"]["total_pnl_usd"] - 550.0) < 1e-6
        assert abs(result["simulated"]["total_pnl_usd"] - 350.0) < 1e-6
        assert abs(result["delta"]["total_pnl_usd"] - (-200.0)) < 1e-6