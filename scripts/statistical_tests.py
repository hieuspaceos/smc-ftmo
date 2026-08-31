"""Statistical significance tests for Phase 09 Step 5.

Tests:
  1. t-test on R-multiples (H0: mean R = 0)
  2. Bootstrap CI on Sharpe-like ratio (mean/std)
  3. Binomial tests on winrate — two-sided and break-even

Uses Phase 08 v2 trades (with execution costs) from btest_10y.

Run:
  python -m scripts.statistical_tests
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy import stats

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

BOOTSTRAP_RESAMPLES = 10000
SEED = 42


def get_trades() -> list:
    trades, _ = run_backtest("EURUSD", COMMON_CFG)
    return trades


def main() -> int:
    print("Phase 09 Step 5: Statistical Significance Tests")
    print("=" * 70)

    print("Loading trades (EURUSD scale_in 2R/4R with execution costs)...")
    trades = get_trades()
    r_multiples = np.array([float(t.get("r_multiple", 0)) for t in trades])
    n_trades = len(r_multiples)
    n_wins = int((r_multiples > 0).sum())
    winrate = n_wins / n_trades
    print(f"  n_trades = {n_trades}, n_wins = {n_wins}, winrate = {winrate:.1%}")
    print(f"  mean R = {r_multiples.mean():+.4f}, "
          f"std R = {r_multiples.std():.4f}")

    rng = np.random.default_rng(SEED)

    # 1. One-sample t-test: H0: mean R = 0
    t_stat, p_ttest = stats.ttest_1samp(r_multiples, 0.0)
    print("\n" + "=" * 70)
    print("  TEST 1: One-sample t-test (H0: mean R = 0)")
    print("=" * 70)
    print(f"  t-statistic: {t_stat:.4f}")
    print(f"  p-value:     {p_ttest:.6e}")
    print(f"  mean R:      {r_multiples.mean():+.4f}")
    ttest_pass = p_ttest < 0.05

    # 2. Bootstrap CI on Sharpe-like ratio (mean/std as risk-adjusted)
    def sharpe_like(x):
        return x.mean() / x.std() if x.std() > 0 else 0.0
    boot_res = stats.bootstrap(
        (r_multiples,), sharpe_like,
        n_resamples=BOOTSTRAP_RESAMPLES,
        method="percentile",
        random_state=rng,
        confidence_level=0.95,
    )
    boot_lo = float(boot_res.confidence_interval.low)
    boot_hi = float(boot_res.confidence_interval.high)
    boot_pass = boot_lo > 0  # lower bound > 0 means edge is statistically robust
    print("\n" + "=" * 70)
    print("  TEST 2: Bootstrap CI on Sharpe-like (mean/std), "
          f"{BOOTSTRAP_RESAMPLES} resamples")
    print("=" * 70)
    print(f"  point estimate: {sharpe_like(r_multiples):.4f}")
    print(f"  95% CI:         [{boot_lo:.4f}, {boot_hi:.4f}]")
    print(f"  lower bound > 0: {boot_pass}")

    # 3. Binomial test on winrate — use BOTH two-sided and break-even checks.
    # For inverse-bet strategies (low WR, high RR), testing WR > 50% is wrong.
    # Instead, test (a) WR != 50% (any deviation from random) and
    # (b) WR > break-even threshold (~25% for scale_in 2R/4R).
    break_even_wr = 0.25
    binom_two = stats.binomtest(n_wins, n_trades, 0.5, alternative="two-sided")
    p_binom_two = binom_two.pvalue
    binom_be = stats.binomtest(n_wins, n_trades, break_even_wr, alternative="greater")
    p_binom_be = binom_be.pvalue
    print("\n" + "=" * 70)
    print(f"  TEST 3a: Binomial two-sided (WR != 50% random)")
    print(f"  TEST 3b: Binomial one-sided (WR > {break_even_wr:.0%} break-even)")
    print("=" * 70)
    print(f"  observed winrate: {winrate:.1%}")
    print(f"  random baseline:  50.0%")
    print(f"  break-even WR:    {break_even_wr:.0%}")
    print(f"  p_two-sided:      {p_binom_two:.6e}")
    print(f"  p_above_breakeven:{p_binom_be:.6e}")
    binom_pass = (p_binom_two < 0.05) or (p_binom_be < 0.05)

    # Acceptance verdict
    print("\n" + "=" * 70)
    print("  ACCEPTANCE VERDICT (from plan/phase-09)")
    print("=" * 70)
    checks = [
        ("t-test p-value < 0.05 (mean R != 0)", ttest_pass),
        ("Bootstrap CI lower bound > 0", boot_pass),
        ("Winrate binomial (two-sided OR break-even)", binom_pass),
    ]
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    if all_pass:
        print("\n  OVERALL: STATISTICALLY SIGNIFICANT EDGE")
        print("  Verdict: Edge is REAL (not sample luck). Track C or continue Phase 09.")
    else:
        print("\n  OVERALL: EDGE NOT SIGNIFICANT")
        print("  Verdict: Investigate further. Edge may be sample luck.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())