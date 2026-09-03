"""Per-pair, 4 exit modes: ladder / scale_in / scale_in_middle / scale_in_middle_1r.

Writes incremental reports per (mode, pair) so you can see live progress.
"""
from __future__ import annotations
import os, sys, time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _build_cfg(mode):
    cfg = {
        "ftmo": {"account_size": 100000, "phase": "challenge",
                 "profit_target": 0.10, "max_daily_loss": 0.05,
                 "max_total_loss": 0.10, "max_open_positions": 1,
                 "daily_loss_limit_r": 2.0},
        "execution": {
            "spread_pips": {
                "EURUSD": 0.5, "GBPUSD": 0.7, "USDCHF": 0.8,
                "XAUUSD": 2.0, "BTCUSD": 5.0,
            },
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3},
        },
        "risk": {"per_trade_pct": 0.0055, "max_trades_per_day": 3,
                 "daily_loss_limit_r": 2.0, "max_open_positions": 1},
        "strategy": {
            "swing_length": 10, "rr_target": 4.0,
            "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
            "min_confluence_score": 4, "require_displacement": True,
            "require_bias_aligned": True, "sl_atr_buffer": 0.2,
            "bias_mode": "strict", "regime_mode": "off",
            "promotion_lookback_bars": 50,
            "partial_tp": [
                {"pct": 0.40, "r": 2.0},
                {"pct": 0.30, "r": 3.0},
                {"pct": 0.30, "r": 4.0},
            ],
            "exit_mode": mode, "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                   "sweep_clean": 1, "premium_discount": 1,
                                   "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01", "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50, "pairs": ["EURUSD"],
    }
    if mode != "ladder":
        cfg["strategy"].pop("partial_tp", None)
    return cfg


def _stats(trades, eq):
    if not trades:
        return {}
    n = len(trades)
    wins = [t for t in trades if float(t.get("r_multiple", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("r_multiple", 0) or 0) <= 0]
    be = sum(1 for t in trades if abs(float(t.get("r_multiple", 0) or 0)) < 1e-9)
    total_r = sum(float(t.get("r_multiple", 0) or 0) for t in trades)
    total_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in trades)
    win_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in wins)
    loss_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in losses)
    avg_win_r = sum(float(t["r_multiple"]) for t in wins) / len(wins) if wins else 0
    avg_loss_r = sum(float(t["r_multiple"]) for t in losses) / len(losses) if losses else 0
    eq_df = pd.DataFrame(eq, columns=["ts", "val"]).set_index("ts")["val"] if eq else None
    dd_pct = ((eq_df / eq_df.cummax() - 1).min() * 100) if eq_df is not None and not eq_df.empty else 0.0
    final_eq = float(eq_df.iloc[-1]) if eq_df is not None and not eq_df.empty else 0.0
    roi_pct = (final_eq / 100000.0 - 1) * 100
    exits = Counter(t.get("exit_reason", "?") for t in trades)
    years = sorted(set(pd.Timestamp(t["timestamp_entry"]).year for t in trades))
    pos_r = sum(float(t["r_multiple"]) for t in wins)
    neg_r = sum(float(t["r_multiple"]) for t in losses)
    pf = abs(pos_r / neg_r) if neg_r else float('inf')
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "wr_pct": round(len(wins) / n * 100, 1),
        "be_count": be,
        "total_r": round(total_r, 1),
        "total_pnl": round(total_pnl, 0),
        "win_pnl": round(win_pnl, 0),
        "loss_pnl": round(loss_pnl, 0),
        "avg_win_R": round(avg_win_r, 2),
        "avg_loss_R": round(avg_loss_r, 2),
        "dd_pct": round(dd_pct, 2),
        "final_eq": round(final_eq, 0),
        "roi_pct": round(roi_pct, 1),
        "pf": round(pf, 3) if pf != float('inf') else "inf",
        "exits": dict(exits),
        "year_range": f"{min(years)}-{max(years)}" if years else "-",
    }


def main():
    from src.backtester import run_backtest

    pairs = ["EURUSD", "GBPUSD", "USDCHF", "XAUUSD", "BTCUSD"]
    out_dir = ROOT / "output" / "multipair-4modes"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_file = out_dir / "summary.csv"
    summary_rows = []
    detail_file = out_dir / "exit_reasons.csv"
    detail_rows = []

    print(f"Started at {time.strftime('%H:%M:%S')}")
    print(f"20 runs total = {len(pairs)} pairs × 4 modes")
    print()

    for mode in ["ladder", "scale_in", "scale_in_middle", "scale_in_middle_1r"]:
        print(f"\n========== Mode: {mode} ==========")
        for i, pair in enumerate(pairs, 1):
            print(f"\n--- [{i}/{len(pairs)}] {pair} ---", flush=True)
            cfg = _build_cfg(mode)
            cfg["pairs"] = [pair]
            t0 = time.perf_counter()
            try:
                trades, eq = run_backtest(pair, cfg)
            except Exception as e:
                print(f"  ERROR: {e}")
                continue
            elapsed = time.perf_counter() - t0
            s = _stats(trades, eq)
            if not s:
                print(f"  no trades in window ({elapsed:.0f}s)")
                continue
            print(f"  n={s['n']:>4d}  WR={s['wr_pct']:>4.1f}%  "
                  f"Total_R={s['total_r']:>+6.1f}R  "
                  f"PnL=${s['total_pnl']:>+10,.0f}  "
                  f"DD={s['dd_pct']:>5.2f}%  "
                  f"PF={s['pf']}  "
                  f"({elapsed:.0f}s)")
            print(f"    Avgs: Win_R=+{s['avg_win_R']}R  Loss_R={s['avg_loss_R']}R  "
                  f"  Final_$={s['final_eq']:,.0f}", flush=True)
            summary_rows.append({
                "mode": mode, "pair": pair, **s, "elapsed_s": round(elapsed, 1),
            })
            # Flush after each pair so we can read partial output
            pd.DataFrame(summary_rows).to_csv(summary_file, index=False)
            for er, cnt in s["exits"].items():
                detail_rows.append({
                    "mode": mode, "pair": pair, "exit_reason": er,
                    "count": cnt,
                })
            pd.DataFrame(detail_rows).to_csv(detail_file, index=False)

    print(f"\n=== DONE ===")
    print(f"Summary CSV: {summary_file}")
    print(f"Detail CSV:  {detail_file}")
    print()
    df = pd.DataFrame(summary_rows)
    # Pretty pivot table: pair across, mode down
    pivot = df.pivot(index="mode", columns="pair",
                     values=["n", "total_pnl", "total_r", "dd_pct",
                             "wr_pct", "final_eq", "pf"])
    print(pivot)


if __name__ == "__main__":
    main()
