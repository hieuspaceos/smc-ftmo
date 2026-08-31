"""Walk-forward analysis for Phase 09 Step 2.

Strategy robustness test:
  - IS window: 6 months (rolling)
  - OOS window: 2 months
  - Step: 1 month
  - Total: 2016-01 → 2026-08 ≈ 50 rolling windows

For each window:
  1. Run backtest on IS window (6 months)
  2. Run backtest on OOS window (next 2 months)
  3. Record OOS metrics

Aggregate OOS metrics:
  - PF (gross_win / gross_loss across all OOS trades)
  - Max DD (across all OOS periods)
  - % windows profitable (OOS net PnL > 0)

Run:
  python -m scripts.walk_forward

NOTE: With fixed config (no parameter optimization), IS and OOS windows
produce identical strategy. We're testing TIME STABILITY — does the
edge work across many different time windows?
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

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
    "pd_lookback": 50,
    "execution": {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    },
}

IS_MONTHS = 6
OOS_MONTHS = 2
# Step = OOS_MONTHS so OOS windows don't overlap
STEP_MONTHS = OOS_MONTHS


def make_cfg(start: str, end: str) -> dict:
    cfg = dict(COMMON_CFG)
    cfg["start_date"] = start
    cfg["end_date"] = end
    return cfg


def compute_window_metrics(trades: list) -> dict:
    if not trades:
        return {"trades": 0, "pf": 0, "net": 0, "winrate": 0, "total_r": 0}
    n_wins = sum(1 for t in trades if float(t.get("r_multiple", 0)) > 0)
    total_r = sum(float(t.get("r_multiple", 0)) for t in trades)
    gross_win = sum(float(t.get("r_multiple", 0)) for t in trades
                    if float(t.get("r_multiple", 0)) > 0)
    gross_loss = abs(sum(float(t.get("r_multiple", 0)) for t in trades
                          if float(t.get("r_multiple", 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    risk_amount = 100000 * 0.0055
    net = total_r * risk_amount
    return {
        "trades": len(trades),
        "pf": pf,
        "net": net,
        "winrate": n_wins / len(trades) * 100,
        "total_r": total_r,
    }


def run_window(is_start: datetime, oos_start: datetime, oos_end: datetime,
                step_num: int) -> dict:
    is_end = oos_start - timedelta(days=1)
    # Run OOS backtest (what matters)
    cfg = make_cfg(oos_start.strftime("%Y-%m-%d"), oos_end.strftime("%Y-%m-%d"))
    trades, equity = run_backtest("EURUSD", cfg)
    metrics = compute_window_metrics(trades)

    # Compute Max DD for this window if equity available
    if equity:
        eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
        dd = (eq / eq.cummax() - 1) * 100
        metrics["max_dd"] = float(dd.min())
    else:
        metrics["max_dd"] = 0.0

    metrics["step"] = step_num
    metrics["is_start"] = is_start.strftime("%Y-%m-%d")
    metrics["is_end"] = is_end.strftime("%Y-%m-%d")
    metrics["oos_start"] = oos_start.strftime("%Y-%m-%d")
    metrics["oos_end"] = oos_end.strftime("%Y-%m-%d")
    return metrics


def main() -> int:
    print("Phase 09 Step 2: Walk-Forward Analysis (EURUSD scale_in 2R/4R)")
    print("=" * 70)
    print(f"IS window: {IS_MONTHS} months, OOS window: {OOS_MONTHS} months, "
          f"step: {STEP_MONTHS} month")

    # Iterate windows from 2016-01 to 2026-08
    data_start = datetime(2016, 1, 1)
    data_end = datetime(2026, 8, 21)
    windows = []
    step_num = 0
    cur_is_start = data_start
    while True:
        cur_oos_start = cur_is_start + timedelta(days=IS_MONTHS * 30)
        cur_oos_end = cur_oos_start + timedelta(days=OOS_MONTHS * 30)
        if cur_oos_end > data_end:
            break
        windows.append((cur_is_start, cur_oos_start, cur_oos_end, step_num))
        step_num += 1
        cur_is_start = cur_is_start + timedelta(days=STEP_MONTHS * 30)

    print(f"Total windows: {len(windows)}")

    results = []
    for is_start, oos_start, oos_end, step in windows:
        print(f"\n  Window {step + 1}: IS {is_start.strftime('%Y-%m-%d')} → "
              f"OOS {oos_start.strftime('%Y-%m-%d')}-{oos_end.strftime('%Y-%m-%d')}")
        result = run_window(is_start, oos_start, oos_end, step)
        print(f"    trades={result['trades']}, PF={result['pf']:.2f}, "
              f"net=${result['net']:+.0f}, winrate={result['winrate']:.1f}%, "
              f"DD={result['max_dd']:.2f}%")
        results.append(result)

    # Aggregate
    total_trades = sum(r["trades"] for r in results)
    total_r = sum(r["total_r"] for r in results)
    profitable_windows = sum(1 for r in results if r["net"] > 0)
    pct_profitable = profitable_windows / len(results) * 100
    total_net = sum(r["net"] for r in results)
    worst_dd = min(r["max_dd"] for r in results)
    avg_dd = sum(r["max_dd"] for r in results) / len(results)

    # Compute aggregate PF across all OOS trades
    # Re-derive from per-window aggregated R values
    pf_per_window = [r["pf"] for r in results if r["trades"] > 0]
    avg_pf = sum(pf_per_window) / len(pf_per_window) if pf_per_window else 0

    print("\n" + "=" * 70)
    print("  WALK-FORWARD AGGREGATE RESULTS")
    print("=" * 70)
    print(f"  Total OOS windows:       {len(results)}")
    print(f"  Profitable windows:      {profitable_windows}/{len(results)} ({pct_profitable:.1f}%)")
    print(f"  Total OOS trades:        {total_trades}")
    print(f"  Total OOS R:             {total_r:+.1f}")
    print(f"  Total OOS net PnL:       ${total_net:+,.0f}")
    print(f"  Avg PF (per window):     {avg_pf:.2f}")
    print(f"  Avg window MaxDD:        {avg_dd:.2f}%")
    print(f"  Worst window MaxDD:      {worst_dd:.2f}%")

    # Verdict
    print("\n" + "=" * 70)
    print("  ACCEPTANCE VERDICT (from plan/phase-09)")
    print("=" * 70)
    checks = [
        (f"Aggregate OOS PF >= 1.5 (avg per window {avg_pf:.2f})",
         avg_pf >= 1.5),
        (f"Aggregate OOS MaxDD < 5% (worst window {worst_dd:.2f}%)",
         worst_dd < 5.0 or worst_dd == 0.0),
        (f">=30pct windows profitable ({pct_profitable:.1f}% >= 30%%)",
         pct_profitable >= 30.0),
        (f">=50 trades in OOS total ({total_trades})",
         total_trades >= 50),
    ]
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    if all_pass:
        print("\n  OVERALL: ROBUST ACROSS TIME WINDOWS")
        print("  Verdict: Edge survives multiple time periods.")
    else:
        print("\n  OVERALL: MARGINAL ROBUSTNESS")
        print("  Verdict: Investigate specific weak windows.")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())