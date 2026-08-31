"""Out-of-Sample (OOS) split validation for Phase 09.

Splits the 10-year EURUSD dataset into:
  - In-Sample (IS): 2016-01-01 → 2022-12-31 (7 năm)
  - Out-of-Sample (OOS): 2023-01-01 → 2026-08-21 (3.7 năm)

Runs scale_in 2R/4R backtest on each window. Compares IS vs OOS metrics.

Acceptance (from plan/phase-09):
  - OOS PF >= 0.7 * IS PF (allow 30% degradation)
  - OOS Winrate >= 0.7 * IS Winrate
  - OOS MaxDD < 5% (FTMO limit)

Note: This script does NOT re-optimize params on IS — repo uses
fixed config from config.yaml. We just verify the fixed config
generalizes from IS to OOS period.

Run:
  python -m scripts.oos_split
"""
from __future__ import annotations

import sys
from collections import Counter
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
    # Execution costs (Phase 08 Step 2 realistic baseline)
    "execution": {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    },
}

# OOS split: IS = 2016-01 → 2022-12 (7 năm), OOS = 2023-01 → 2026-08 (3.7 năm)
IS_END = "2022-12-31"
OOS_START = "2023-01-01"


def run_window(label: str, start: str, end: str) -> dict:
    cfg = dict(COMMON_CFG)
    cfg["start_date"] = start
    cfg["end_date"] = end
    print(f"\n--- {label} ({start} → {end}) ---")
    trades, equity = run_backtest("EURUSD", cfg)
    if not trades:
        print(f"  (no trades)")
        return {"label": label, "trades": 0}

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

    print(f"  Trades: {len(trades)}, WR: {wr:.1f}%, AvgR: {avg_r:+.3f}, "
          f"TotalR: {total_r:+.1f}")
    print(f"  MaxDD: {max_dd:.2f}%, Final: ${final:,.0f}, "
          f"Net: ${net:+,.0f} ({roi:+.1f}%)")
    print(f"  PF: {pf:.2f}")
    return {
        "label": label, "trades": len(trades), "winrate": wr,
        "avg_r": avg_r, "total_r": total_r, "max_dd": max_dd,
        "final": final, "net": net, "roi": roi, "pf": pf,
    }


def main() -> int:
    print("Phase 09 Step 1: Out-of-Sample Split (EURUSD scale_in 2R/4R)")
    print("=" * 70)

    is_metrics = run_window("IN-SAMPLE (IS)", "2016-01-01", IS_END)
    oos_metrics = run_window("OUT-OF-SAMPLE (OOS)", OOS_START, "2026-08-21")

    # Comparison + verdict
    print("\n" + "=" * 70)
    print("  SIDE-BY-SIDE COMPARISON")
    print("=" * 70)
    print(f"  {'Metric':12s}  {'IS (7y)':>12s}  {'OOS (3.7y)':>12s}  {'OOS/IS':>10s}")
    print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*10}")
    for key in ["trades", "winrate", "avg_r", "total_r", "max_dd", "net", "roi", "pf"]:
        if not is_metrics.get(key) or not oos_metrics.get(key):
            continue
        fmt = {"trades": "{:>12d}", "winrate": "{:>11.1f}%", "avg_r": "{:>+11.3f}",
               "total_r": "{:>+11.1f}", "max_dd": "{:>10.2f}%", "net": "{:>+11,.0f}",
               "roi": "{:>+10.1f}%", "pf": "{:>11.2f}"}[key]
        s = is_metrics[key]
        l = oos_metrics[key]
        ratio = l / s if s not in (0, None) and not (isinstance(s, float) and s != s) else float("nan")
        if key in ("max_dd",):
            # Lower is better for DD
            ratio_str = f"{ratio:.2f}x" if isinstance(ratio, float) else "N/A"
        else:
            ratio_str = f"{ratio:.2f}x" if isinstance(ratio, float) else "N/A"
        print(f"  {key:12s}  {fmt.format(s)}  {fmt.format(l)}  {ratio_str:>10s}")

    # Acceptance verdict
    print("\n" + "=" * 70)
    print("  ACCEPTANCE VERDICT (from plan/phase-09)")
    print("=" * 70)
    is_pf = is_metrics.get("pf", 0)
    oos_pf = oos_metrics.get("pf", 0)
    is_wr = is_metrics.get("winrate", 0)
    oos_wr = oos_metrics.get("winrate", 0)
    oos_dd = abs(oos_metrics.get("max_dd", 0))

    pf_ratio = oos_pf / is_pf if is_pf > 0 else 0
    wr_ratio = oos_wr / is_wr if is_wr > 0 else 0

    checks = [
        ("OOS PF >= 0.7 * IS PF", pf_ratio >= 0.7),
        ("OOS Winrate >= 0.7 * IS Winrate", wr_ratio >= 0.7),
        ("OOS MaxDD < 5% (FTMO limit)", oos_dd < 5.0),
        ("OOS PF > 1.5 (profitable)", oos_pf > 1.5),
    ]
    all_pass = True
    for name, ok in checks:
        status = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    print(f"\n  OVERALL: {'✅ EDGE GENERALIZES' if all_pass else '❌ CURVE-FIT SUSPECTED'}")
    print(f"  Verdict: {'Move to Phase 09 Step 2' if all_pass else 'BLOCK — investigate before moving on'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())