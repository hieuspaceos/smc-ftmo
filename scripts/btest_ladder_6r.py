"""BTC backtest test: compare scale_in 2R/4R vs ladder 2R/4R/6R.

Compares two TP schemes on BTCUSD 2017-08 to 2026-08:
  1. Scale-in 2R/4R (current baseline, 816 trades, PF 3.17)
  2. Ladder 2R/4R/6R with cumulative 33%/33%/34% partial TP

Risk per trade unchanged: 0.55% = $550. Single SL still original.
"""
import time
from collections import Counter

import pandas as pd

from src.backtester import run_backtest


SCALE_IN_CFG = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 6.0,
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
    "start_date": "2017-08-17",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
}


# Ladder 2R/4R/6R with cumulative 33%/33%/34% partial close.
# pct = fraction of REMAINING (not original). To get cumulative X% of original:
#   Stage 1: close (X1/100) of remaining = X1/100
#   Stage 2: close (X2/(100-X1)) of remaining = X2/(100-X1)
#   Stage 3: close (X3/(100-X1-X2)) of remaining = 1.0 (must be 1.0 to fully close)
# For cumulative 33/33/34%:
#   Stage 1: 0.33 of 1.0 = 0.33 (close 33% of remaining)
#   Stage 2: 0.33 of 0.67 = 0.50 (close 50% of remaining → cumulative 66%)
#   Stage 3: 0.34 of 0.34 = 1.00 (close 100% of remaining → cumulative 100%)
LADDER_6R_CFG = dict(SCALE_IN_CFG)
LADDER_6R_CFG["strategy"] = dict(SCALE_IN_CFG["strategy"])
LADDER_6R_CFG["strategy"]["exit_mode"] = "ladder"
LADDER_6R_CFG["strategy"]["partial_tp"] = [
    {"pct": 0.33, "r": 2.0},
    {"pct": 0.50, "r": 4.0},
    {"pct": 1.00, "r": 6.0},
]


def report(label: str, trades: list, equity: list) -> dict:
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    metrics: dict = {"label": label, "trades": len(trades)}
    if not trades:
        return metrics

    n_win = sum(1 for t in trades if float(t.get("r_multiple", 0)) > 0)
    n_loss = len(trades) - n_win
    wr = n_win / len(trades) * 100
    total_r = sum(float(t.get("r_multiple", 0)) for t in trades)
    avg_r = total_r / len(trades)
    metrics.update({"wins": n_win, "losses": n_loss, "winrate": wr,
                     "total_r": total_r, "avg_r": avg_r})
    print(f"  Trades: {len(trades)}, WR: {wr:.1f}% ({n_win}W / {n_loss}L)")
    print(f"  Total R: {total_r:+.1f}R, AvgR: {avg_r:+.3f}")

    if equity:
        eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
        dd_pct = (eq / eq.cummax() - 1) * 100
        max_dd_pct = dd_pct.min()
        final = float(eq.iloc[-1])
        net_pnl = final - 100000
        roi = net_pnl / 100000 * 100
        metrics.update({"max_dd_pct": max_dd_pct, "final": final,
                         "net_pnl": net_pnl, "roi": roi})
        print(f"  Max DD: {max_dd_pct:.2f}%  Final: ${final:,.0f}  Net: ${net_pnl:+,.0f}")

    gross_win = sum(float(t.get("r_multiple", 0)) for t in trades
                    if float(t.get("r_multiple", 0)) > 0)
    gross_loss = abs(sum(float(t.get("r_multiple", 0)) for t in trades
                          if float(t.get("r_multiple", 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    metrics["profit_factor"] = pf
    print(f"  Profit Factor: {pf:.2f}")

    reasons = Counter(t.get("exit_reason", "?") for t in trades)
    print(f"  Exit reasons: {dict(reasons)}")
    return metrics


def main() -> int:
    pair = "BTCUSD"
    scale_trades, scale_eq = run_backtest(pair=pair, config=SCALE_IN_CFG)
    scale_t = 0.0  # time tracking not available without monkey-patching
    print(f"  [scale_in 2R/4R] Trades: {len(scale_trades)}")
    scale_metrics = report(f"{pair} — Scale-In 2R/4R (baseline)", scale_trades, scale_eq)

    ladder_trades, ladder_eq = run_backtest(pair=pair, config=LADDER_6R_CFG)
    ladder_t = 0.0
    print(f"  [ladder 2R/4R/6R] Trades: {len(ladder_trades)}")
    ladder_metrics = report(f"{pair} — Ladder 2R/4R/6R (test)", ladder_trades, ladder_eq)
    print(f"\n{'=' * 70}")
    print("  SIDE-BY-SIDE COMPARISON (BTCUSD)")
    print(f"{'=' * 70}\n")
    print(f"  {'Metric':18s}  {'Scale-In 2R/4R':>16s}  {'Ladder 2R/4R/6R':>16s}  {'Diff':>10s}")
    print(f"  {'-'*18}  {'-'*16}  {'-'*16}  {'-'*10}")

    rows = [
        ("trades", "{:>16d}", "Trades"),
        ("winrate", "{:>15.1f}%", "Winrate"),
        ("avg_r", "{:>+15.3f}", "AvgR"),
        ("total_r", "{:>+15.1f}", "TotalR"),
        ("max_dd_pct", "{:>14.2f}%", "MaxDD"),
        ("net_pnl", "{:>+15,.0f}", "NetPnL"),
        ("roi", "{:>+14.1f}%", "ROI"),
        ("profit_factor", "{:>15.2f}", "PF"),
    ]
    for key, fmt, label in rows:
        s = scale_metrics.get(key, 0)
        l = ladder_metrics.get(key, 0)
        diff = l - s
        diff_str = f"{diff:+,.2f}" if not isinstance(diff, int) else f"{diff:+d}"
        print(f"  {label:18s}  {fmt.format(s)}  {fmt.format(l)}  {diff_str:>10s}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())