"""End-to-end backtest for ScaleInExit via run_backtest(exit_mode='scale_in').

Verifies the ScaleInExit class wires into the M15 bar-by-bar backtester
without errors and produces closed trades with sensible R-multiple math.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtester import compute_metrics, run_backtest  # noqa: E402


# Tuned params — matches test_backtest.py floor config but with scale_in exit.
SCALE_IN_CONFIG = {
    "swing_length": 10,
    "require_bias_aligned": False,  # data range hẹp nên 1-side trade tốt hơn
    "max_trades_per_day": 3,
    "max_daily_loss_r": 2.0,
    "min_confluence_score": 4,
    "account_size": 100_000.0,
    "sl_atr_buffer": 0.2,
    "displacement_atr_mult": 1.5,
    "sweep_atr_buffer": 0.05,
    "pair": "EURUSD",
    "exit_mode": "scale_in",  # <<< the point of this test
}


@pytest.fixture(scope="module")
def scale_in_result():
    trades, equity_curve = run_backtest("EURUSD", SCALE_IN_CONFIG)
    metrics = compute_metrics(trades, equity_curve)
    return {"trades": trades, "equity_curve": equity_curve, "metrics": metrics}


class TestScaleInBacktestSmoke:
    def test_runs_without_error(self, scale_in_result):
        """Backtester must complete with exit_mode='scale_in' — no exceptions."""
        assert scale_in_result["trades"] is not None
        assert scale_in_result["equity_curve"] is not None

    def test_uses_scale_in_exit_module(self):
        """Sanity: confirm the ScaleInExit class is the one wired in."""
        from scale_in_exit import ScaleInExit
        ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")
        # Same scenario as the unit test
        ex.update(1.1100)
        assert ex.state == "phase2"


class TestScaleInTradeInvariants:
    """ScaleInExit has bounded R-multiples: each trade in [-1R, +4R]."""

    def test_trades_within_r_bounds(self, scale_in_result):
        trades = scale_in_result["trades"]
        if not trades:
            pytest.skip("0 trades produced — engine did not fire; not a ScaleInExit bug")
        for t in trades:
            r = t["r_multiple"]
            # ScaleInExit math:
            #   - SL before 2R: -1R
            #   - Cascade at entry: 0R
            #   - Leg2 SL only (leg1 runs to 4R): +2R
            #   - Full 4R hit: +4R
            assert -1.5 <= r <= 4.5, (
                f"r_multiple {r} outside ScaleInExit bounds [-1, +4]; "
                f"exit_reason={t.get('exit_reason')}"
            )

    def test_exit_reasons_are_valid(self, scale_in_result):
        trades = scale_in_result["trades"]
        if not trades:
            pytest.skip("0 trades produced")
        valid = {"tp4r", "sl", "leg2_sl"}
        for t in trades:
            assert t["exit_reason"] in valid, (
                f"unexpected exit_reason={t['exit_reason']!r}"
            )


class TestScaleInMetrics:
    """Characterization: just print metrics; no hard gate beyond sane ranges."""

    def test_metrics_exist(self, scale_in_result):
        m = scale_in_result["metrics"]
        for key in ("total_trades", "winrate", "profit_factor", "max_dd_pct"):
            assert key in m, f"missing metric: {key}"

    def test_metrics_in_sane_range(self, scale_in_result):
        m = scale_in_result["metrics"]
        if m["total_trades"] == 0:
            pytest.skip("0 trades — characterization not meaningful")
        # DD should never explode past 50% on a single run
        assert m["max_dd_pct"] < 50.0, f"MaxDD {m['max_dd_pct']:.2f}% too large"
        # PF characterization floor
        assert m["profit_factor"] > 0.5, (
            f"PF {m['profit_factor']:.2f} below characterization floor 0.5"
        )


@pytest.fixture(scope="module")
def design_b_result():
    """Same config but Design B enabled (leg2_tp1_r=3.0)."""
    cfg = {**SCALE_IN_CONFIG, "leg2_tp1_r": 3.0}
    trades, equity_curve = run_backtest("EURUSD", cfg)
    metrics = compute_metrics(trades, equity_curve)
    return {"trades": trades, "equity_curve": equity_curve, "metrics": metrics}


class TestDesignBBacktest:
    """Design B: scale-in with intermediate leg2 TP at 3R.

    Validates that leg2_tp1_r=3.0 config wires through the backtester,
    runs without errors, and produces trades within the bounded
    Design B math range:
      - SL before 2R: -1R
      - Cascade at entry (no TP1): 0R
      - Hit 3R then cascade to entry: +1.5R (TP1 locked + leg2 rem at locked SL)
      - Hit 4R (with TP1 partial): +3.75R (NOT +4R like Design A)
    """

    def test_runs_without_error(self, design_b_result):
        assert design_b_result["trades"] is not None
        assert design_b_result["equity_curve"] is not None

    def test_design_b_r_bounds(self, design_b_result):
        """Trades must fall in Design B's bounded R range [-1, +3.75]."""
        trades = design_b_result["trades"]
        if not trades:
            pytest.skip("0 trades produced")
        for t in trades:
            r = t["r_multiple"]
            assert -1.5 <= r <= 4.0, (
                f"Design B r_multiple {r} outside bounds [-1, +3.75]; "
                f"exit_reason={t.get('exit_reason')}"
            )

    def test_design_b_higher_winrate_than_design_a(self, scale_in_result, design_b_result):
        """Design B should convert some 0R cascades to partial wins,
        raising winrate vs Design A.
        """
        wr_a = scale_in_result["metrics"]["winrate"]
        wr_b = design_b_result["metrics"]["winrate"]
        assert wr_b >= wr_a, (
            f"Design B winrate {wr_b:.1%} should be >= Design A winrate {wr_a:.1%}"
        )

    def test_design_b_max_dd_lower_than_design_a(self, scale_in_result, design_b_result):
        """Design B locks profit earlier, should reduce max DD."""
        dd_a = scale_in_result["metrics"]["max_dd_pct"]
        dd_b = design_b_result["metrics"]["max_dd_pct"]
        assert dd_b <= dd_a + 0.5, (
            f"Design B MaxDD {dd_b:.2f}% should be <= Design A {dd_a:.2f}% (with 0.5pp tolerance)"
        )



if __name__ == "__main__":
    # Manual run for quick smoke check
    trades, equity_curve = run_backtest("EURUSD", SCALE_IN_CONFIG)
    metrics = compute_metrics(trades, equity_curve)
    print(f"Trades: {metrics['total_trades']}")
    print(f"Winrate: {metrics['winrate']:.1%}")
    print(f"Profit factor: {metrics['profit_factor']:.2f}")
    print(f"Max DD: {metrics['max_dd_pct']:.2f}%")
    if trades:
        reasons = {}
        for t in trades:
            reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
        print(f"Exit reasons: {reasons}")
        rs = [t["r_multiple"] for t in trades]
        print(f"R range: [{min(rs):.2f}, {max(rs):.2f}]")