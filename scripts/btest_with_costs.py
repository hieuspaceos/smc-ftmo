"""Compare backtest with vs without execution costs.

Runs EURUSD scale_in 2R/4R with:
  1. No costs (current default)
  2. FTMO realistic costs: spread + commission + slippage

Expected: PnL drop ~25-35% with costs.
"""
import sys
import os

sys.path.insert(0, "src")
sys.path.insert(0, "packages/smc_engine/src")

from src.backtester import run_backtest
import pandas as pd
from collections import Counter

BASE_CFG = {
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
}

# Add FTMO-realistic execution costs
WITH_COSTS_CFG = dict(BASE_CFG)
WITH_COSTS_CFG["execution"] = {
    "spread_pips": {"EURUSD": 0.5},
    "commission_per_lot_per_side": 2.50,
    "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
}


def report(label, trades, equity):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    if not trades:
        print("  (no trades)")
        return {}

    n_win = sum(1 for t in trades if float(t.get("r_multiple", 0)) > 0)
    wr = n_win / len(trades) * 100
    total_r = sum(float(t.get("r_multiple", 0)) for t in trades)
    avg_r = total_r / len(trades)

    eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
    dd = (eq / eq.cummax() - 1) * 100
    max_dd = dd.min()
    final = float(eq.iloc[-1])
    net = final - 100000
    roi = net / 100000 * 100

    gross_win = sum(float(t.get("r_multiple", 0)) for t in trades
                    if float(t.get("r_multiple", 0)) > 0)
    gross_loss = abs(sum(float(t.get("r_multiple", 0)) for t in trades
                          if float(t.get("r_multiple", 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    print(f"  Trades: {len(trades)}, WR: {wr:.1f}%, AvgR: {avg_r:+.3f}")
    print(f"  TotalR: {total_r:+.1f}, MaxDD: {max_dd:.2f}%")
    print(f"  Final: ${final:,.0f}  Net: ${net:+,.0f}  ROI: {roi:+.1f}%")
    print(f"  PF: {pf:.2f}")

    return {
        "trades": len(trades), "winrate": wr, "avg_r": avg_r,
        "total_r": total_r, "max_dd": max_dd, "net": net,
        "roi": roi, "pf": pf,
    }


# Run both
print("Running EURUSD scale_in 2R/4R — no costs (baseline)...")
t1, e1 = run_backtest("EURUSD", BASE_CFG)
m1 = report("NO COSTS (baseline)", t1, e1)

print("\nRunning EURUSD scale_in 2R/4R — WITH FTMO costs...")
t2, e2 = run_backtest("EURUSD", WITH_COSTS_CFG)
m2 = report("WITH COSTS (spread + commission + slippage)", t2, e2)

# Side-by-side
print(f"\n{'=' * 60}")
print("  SIDE-BY-SIDE COMPARISON (EURUSD scale_in 2R/4R)")
print(f"{'=' * 60}\n")
print(f"  {'Metric':12s}  {'No Costs':>12s}  {'With Costs':>12s}  {'Diff':>10s}")
print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*10}")
for key in ["trades", "winrate", "avg_r", "total_r", "max_dd", "net", "roi", "pf"]:
    fmt = {"trades": "{:>12d}", "winrate": "{:>11.1f}%", "avg_r": "{:>+11.3f}",
           "total_r": "{:>+11.1f}", "max_dd": "{:>10.2f}%", "net": "{:>+11,.0f}",
           "roi": "{:>+10.1f}%", "pf": "{:>11.2f}"}[key]
    s = m1.get(key, 0)
    l = m2.get(key, 0)
    diff = l - s
    print(f"  {key:12s}  {fmt.format(s)}  {fmt.format(l)}  {diff:>+10.2f}")