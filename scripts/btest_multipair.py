"""Multi-pair backtest runner — ScaleInExit Design A (2R/4R).

Mirrors btest_scale_in.py but parameterizes by pair so we can verify the
strategy generalizes beyond the EURUSD baseline (603 trades, $456K, PF 3.57).

Usage:
    python -m scripts.btest_multipair                   # default: all 3 pairs
    python -m scripts.btest_multipair --pair XAUUSD     # single pair
    python -m scripts.btest_multipair --pair GBPUSD

Outputs (per pair):
- Trade count
- Winrate / Total R / Max DD / Final $
- Per-year distribution histogram
- Exit reason breakdown (scale_in: tp4r / sl / leg2_sl)

Reference (EURUSD 2016-01 → 2026-08, 603 trades):
  - PF 3.57, MaxDD 3.40%, Total $456,400, AvgR +1.075

Other pairs expected (lower edge if available data is shorter):
- XAUUSD: 10.6 năm data (2016-2026) → expected similar edge profile
- GBPUSD: 10.6 năm data (2016-2026) → FX correlation with EURUSD (~0.7);
  may show similar OR slightly lower performance due to cross-pair noise
"""
from __future__ import annotations

import argparse
import time
from collections import Counter

import pandas as pd

from src.backtester import run_backtest

# Mirror app/streamlit_app.py run_cfg exactly, ONLY change exit_mode.
# Same config as btest_scale_in.py — apply identically across pairs to
# isolate pair effect from strategy effect.
DEFAULT_CFG = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10,
        "rr_target": 4.0,
        "displacement_atr_mult": 1.2,
        "sweep_atr_buffer": 0.05,
        "min_confluence_score": 3,
        "require_displacement": True,
        "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        "min_sl_atr": 0.3,
        "max_sl_atr": 5.0,
        "min_sl_pips": {"EURUSD": 17, "XAUUSD": 100},
        "rulebook_entry_proximity_atr": 2.0,
        "htf_daily_enabled": False,
        "htf_h4_enabled": False,
        "bias_mode": "h4_only",
        "regime_mode": "off",
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


def run_one_pair(pair: str, cfg: dict) -> tuple[list, list, float]:
    """Run backtest for a single pair, return (trades, equity, elapsed_sec)."""
    t0 = time.perf_counter()
    trades, equity = run_backtest(pair=pair, config=cfg)
    elapsed = time.perf_counter() - t0
    return trades, equity, elapsed


def print_pair_report(pair: str, trades: list, equity: list, elapsed: float) -> dict:
    """Print summary for one pair, return dict of metrics for tabulation."""
    print(f"\n{'=' * 70}")
    print(f"  PAIR: {pair}")
    print(f"{'=' * 70}")
    print(f"  Trades: {len(trades)}  time={elapsed:.0f}s")

    metrics: dict = {"pair": pair, "trades": len(trades), "elapsed": elapsed}

    if not trades:
        print("  (no trades)")
        return metrics

    # Per-year histogram
    years = Counter(pd.Timestamp(t['timestamp_entry']).year for t in trades)
    print(f"\n  Per-year distribution:")
    for y in sorted(years):
        bar = '#' * (years[y] // 2)
        print(f"    {y}: {years[y]:>4d} {bar}")

    # Winrate / Total R
    n_win = sum(1 for t in trades if float(t.get('r_multiple', 0)) > 0)
    n_loss = len(trades) - n_win
    wr = n_win / len(trades) * 100
    total_r = sum(float(t.get('r_multiple', 0)) for t in trades)
    avg_r = total_r / len(trades)
    metrics.update({"wins": n_win, "losses": n_loss, "winrate": wr,
                     "total_r": total_r, "avg_r": avg_r})

    print(f"\n  Winrate: {wr:.1f}%  ({n_win}W / {n_loss}L)")
    print(f"  Total R: {total_r:+.1f}R  (AvgR {avg_r:+.3f})")

    # Exit reasons — always (not conditional on equity)
    reasons = Counter(t.get('exit_reason', '?') for t in trades)
    metrics["exit_reasons"] = dict(reasons)
    print(f"\n  Exit reasons: {dict(reasons)}")

    # Max DD + final equity
    if equity:
        eq = pd.DataFrame(equity, columns=['ts', 'eq']).set_index('ts')['eq']
        dd_pct = (eq / eq.cummax() - 1) * 100
        dd_dollar = eq - eq.cummax()
        max_dd_pct = dd_pct.min()
        max_dd_dollar = dd_dollar.min()
        final = float(eq.iloc[-1])
        net_pnl = final - 100000
        roi = net_pnl / 100000 * 100
        metrics.update({"max_dd_pct": max_dd_pct, "max_dd_dollar": max_dd_dollar,
                         "final": final, "net_pnl": net_pnl, "roi": roi})
        print(f"  Max DD:  {max_dd_pct:.2f}% (${max_dd_dollar:,.0f})")
    # Profit factor (gross win $ / gross loss $) — best-effort, only if R data present
    gross_win = sum(float(t.get('r_multiple', 0)) for t in trades if float(t.get('r_multiple', 0)) > 0)
    gross_loss = abs(sum(float(t.get('r_multiple', 0)) for t in trades if float(t.get('r_multiple', 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    metrics["profit_factor"] = pf
    print(f"  Profit Factor: {pf:.2f}  (gross {gross_win:.0f}R win / {gross_loss:.0f}R loss)")

    return metrics


def print_summary_table(all_metrics: list[dict]) -> None:
    """Print cross-pair comparison table at the end."""
    print(f"\n{'=' * 70}")
    print("  CROSS-PAIR SUMMARY (ScaleInExit Design A)")
    print(f"{'=' * 70}\n")

    if not all_metrics:
        print("  No pairs ran successfully.")
        return

    header = (f"  {'Pair':8s}  {'Trades':>7s}  {'WR%':>5s}  "
              f"{'AvgR':>7s}  {'TotalR':>8s}  {'MaxDD':>7s}  "
              f"{'NetPnL':>10s}  {'ROI':>6s}  {'PF':>5s}")
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for m in all_metrics:
        if "winrate" not in m:
            # Pair had no trades; print minimal row
            print(f"  {m['pair']:8s}  {m.get('trades', 0):>7d}  (no trades)")
            continue
        print(f"  {m['pair']:8s}  {m['trades']:>7d}  "
              f"{m['winrate']:>5.1f}  {m['avg_r']:>+7.3f}  "
              f"{m['total_r']:>+8.1f}  {m['max_dd_pct']:>6.2f}%  "
              f"${m['net_pnl']:>+9,.0f}  {m['roi']:>+5.1f}%  "
              f"{m['profit_factor']:>5.2f}")

    # Comparison to baseline (btest_scale_in.py: EURUSD 603 / $456K / PF 3.57)
    print(f"\n  Reference (EURUSD baseline): 603 trades, +$356,400 net, PF 3.57, MaxDD 3.40%")


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-pair backtest runner")
    parser.add_argument(
        "--pair", choices=["EURUSD", "XAUUSD", "GBPUSD", "USDCHF", "BTCUSD", "ALL"],
        default="ALL",
        help="Pair to backtest (default: ALL — runs EURUSD, XAUUSD, GBPUSD, USDCHF, BTCUSD)",
    )
    args = parser.parse_args()

    pairs = ["EURUSD", "XAUUSD", "GBPUSD", "USDCHF", "BTCUSD"] if args.pair == "ALL" else [args.pair]

    print(f"Running backtest for: {', '.join(pairs)}")
    print(f"Window: {DEFAULT_CFG['start_date']} → {DEFAULT_CFG['end_date']}")
    print(f"Strategy: ScaleInExit Design A (leg2_tp1_r=None)")
    print(f"Risk per trade: 0.55% = $550")

    all_metrics: list[dict] = []
    for pair in pairs:
        try:
            trades, equity, elapsed = run_one_pair(pair, DEFAULT_CFG)
            metrics = print_pair_report(pair, trades, equity, elapsed)
            all_metrics.append(metrics)
        except Exception as e:
            print(f"\n  PAIR: {pair} FAILED: {e}")
            import traceback
            traceback.print_exc()
            all_metrics.append({"pair": pair, "trades": 0, "error": str(e)})

    print_summary_table(all_metrics)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())