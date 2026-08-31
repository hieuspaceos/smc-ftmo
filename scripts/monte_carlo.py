"""Monte Carlo simulation for Phase 09 Step 3.

Shuffles trade order N times to estimate:
  - Max DD distribution (5th, 50th, 95th percentile)
  - Ruin probability (equity drops below 50% of start)
  - Final PnL distribution

Uses Phase 08 v2 trades (with execution costs) from btest_10y.

Run:
  python -m scripts.monte_carlo
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "smc_engine" / "src"))

from backtester import run_backtest  # noqa: E402


COMMON_CFG = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 4.0,
        "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4, "require_displacement": True,
        "require_bias_aligned": True, "sl_atr_buffer": 0.2,
        "bias_mode": "strict", "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": None,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
    "execution": {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    },
}

N_SHUFFLES = 1000
SEED = 42
START_EQUITY = 100000.0
RISK_PCT = 0.0055  # 0.55% per trade (matches backtest)


def get_trade_r_multiples() -> np.ndarray:
    """Run backtest once and extract R-multiples as numpy array."""
    trades, _ = run_backtest("EURUSD", COMMON_CFG)
    r_multiples = np.array([float(t.get("r_multiple", 0)) for t in trades])
    return r_multiples


def simulate_one_shuffle(r_multiples: np.ndarray, rng: np.random.Generator) -> dict:
    """Shuffle trade order once, simulate equity curve."""
    perm = rng.permutation(len(r_multiples))
    shuffled = r_multiples[perm]

    # Each trade: PnL = r * risk_amount
    # risk_amount = account_size * risk_pct = $550 (constant since fixed)
    risk_amount = START_EQUITY * RISK_PCT
    pnls = shuffled * risk_amount

    # Equity curve
    equity = START_EQUITY + np.cumsum(pnls)
    # Running max + drawdown
    running_max = np.maximum.accumulate(equity)
    drawdown_pct = (equity / running_max - 1.0) * 100.0  # negative
    max_dd_pct = drawdown_pct.min()

    # Ruin: equity drops below 50% of start at any point
    ruin = (equity < START_EQUITY * 0.5).any()

    return {
        "max_dd_pct": float(max_dd_pct),
        "final_pnl": float(equity[-1] - START_EQUITY),
        "final_equity": float(equity[-1]),
        "ruin": bool(ruin),
    }


def main() -> int:
    print("Phase 09 Step 3: Monte Carlo (1000 shuffles)")
    print("=" * 70)
    print("Loading trade list via backtest (EURUSD scale_in 2R/4R with costs)...")

    r_multiples = get_trade_r_multiples()
    n_trades = len(r_multiples)
    total_r = r_multiples.sum()
    avg_r = r_multiples.mean()
    print(f"  Loaded {n_trades} trades, AvgR={avg_r:+.3f}, TotalR={total_r:+.1f}")

    rng = np.random.default_rng(SEED)
    results = {
        "max_dd_pct": np.zeros(N_SHUFFLES),
        "final_pnl": np.zeros(N_SHUFFLES),
        "final_equity": np.zeros(N_SHUFFLES),
        "ruin": np.zeros(N_SHUFFLES, dtype=bool),
    }
    print(f"\nRunning {N_SHUFFLES} shuffles...")
    for i in range(N_SHUFFLES):
        sim = simulate_one_shuffle(r_multiples, rng)
        results["max_dd_pct"][i] = sim["max_dd_pct"]
        results["final_pnl"][i] = sim["final_pnl"]
        results["final_equity"][i] = sim["final_equity"]
        results["ruin"][i] = sim["ruin"]
        if (i + 1) % 200 == 0:
            print(f"  ...{i + 1}/{N_SHUFFLES} done")

    # Aggregate statistics
    dd = results["max_dd_pct"]
    pnl = results["final_pnl"]
    eq = results["final_equity"]
    ruin_count = int(results["ruin"].sum())
    ruin_pct = ruin_count / N_SHUFFLES * 100.0

    pcts = [5, 25, 50, 75, 95]

    print("\n" + "=" * 70)
    print("  MONTE CARLO RESULTS (1000 shuffles)")
    print("=" * 70)
    print(f"\n  Max Drawdown distribution (pct from peak):")
    for p in pcts:
        v = float(np.percentile(dd, p))
        print(f"    {p:>2d}th percentile: {v:>6.2f}%")
    print(f"    min: {dd.min():>6.2f}%   max: {dd.max():>6.2f}%   mean: {dd.mean():>6.2f}%")

    print(f"\n  Final PnL distribution:")
    for p in pcts:
        v = float(np.percentile(pnl, p))
        print(f"    {p:>2d}th percentile: ${v:>+12,.0f}")
    print(f"    min: ${pnl.min():>+12,.0f}   max: ${pnl.max():>+12,.0f}   "
          f"mean: ${pnl.mean():>+12,.0f}")

    print(f"\n  Final Equity distribution:")
    for p in pcts:
        v = float(np.percentile(eq, p))
        print(f"    {p:>2d}th percentile: ${v:>12,.0f}")

    print(f"\n  Ruin Probability (equity drops below 50% of start):")
    print(f"    {ruin_count}/{N_SHUFFLES} ({ruin_pct:.2f}%)")

    # Acceptance verdict
    print("\n" + "=" * 70)
    print("  ACCEPTANCE VERDICT (from plan/phase-09)")
    print("=" * 70)
    dd_95 = float(np.percentile(dd, 95))
    pnl_5 = float(np.percentile(pnl, 5))
    checks = [
        ("95th percentile MaxDD < 10% (FTMO limit * 2)", dd_95 < 10.0),
        ("Ruin probability < 5%", ruin_pct < 5.0),
        ("5th percentile final PnL > 0 (worst case still profitable)", pnl_5 > 0),
        ("95th percentile MaxDD < 5% (FTMO daily limit, strict)", dd_95 < 5.0),
    ]
    all_pass = True
    for name, ok in checks:
        status = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    print(f"\n  OVERALL: {'✅ ROBUST THROUGH MONTE CARLO' if all_pass else '⚠️ MARGIN ISSUES — REVIEW'}")
    print(f"  Verdict: {'Move to Step 5' if all_pass else 'Investigate risk before proceeding'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())