"""Multi-pair scale_in (and ladder) backtest — EURUSD, GBPUSD, USDCHF, XAUUSD, BTCUSD.

Counts: ladder 40/30/30 vs scale_in Design A 2R/4R.
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
    if mode == "scale_in":
        cfg["strategy"].pop("partial_tp", None)
    return cfg


def _summary(trades, equity):
    if not trades:
        return {"n": 0}
    n = len(trades)
    n_win = sum(1 for t in trades if float(t.get("r_multiple", 0) or 0) > 0)
    total_r = sum(float(t.get("r_multiple", 0) or 0) for t in trades)
    eq_df = pd.DataFrame(equity, columns=["ts", "val"]).set_index("ts")["val"] if equity else None
    dd = ((eq_df / eq_df.cummax() - 1).min() * 100) if eq_df is not None and not eq_df.empty else 0.0
    years = sorted(set(pd.Timestamp(t["timestamp_entry"]).year for t in trades))
    return {
        "n": n, "wins": n_win, "wr": n_win / n * 100,
        "total_r": round(total_r, 1),
        "dd": round(dd, 2),
        "year_range": f"{min(years)}-{max(years)}" if years else "-",
    }


def main():
    from src.backtester import run_backtest

    pairs = ["EURUSD", "GBPUSD", "USDCHF", "XAUUSD", "BTCUSD"]
    print(f"{'PAIR':<8} {'MODE':<10} {'N':>5} {'WR%':>6} {'TOTAL_R':>9} "
          f"{'DD%':>7} {'YEARS':<10}")
    print("-" * 60)

    for mode in ["ladder", "scale_in"]:
        for pair in pairs:
            cfg = _build_cfg(mode)
            cfg["pairs"] = [pair]
            t0 = time.perf_counter()
            try:
                trades, eq = run_backtest(pair, cfg)
            except Exception as e:
                print(f"{pair:<8} {mode:<10} ERROR  {e}")
                continue
            elapsed = time.perf_counter() - t0
            s = _summary(trades, eq)
            if s.get("n") == 0:
                print(f"{pair:<8} {mode:<10} {0:>5d} (no data / no trades)")
                continue
            print(f"{pair:<8} {mode:<10} {s['n']:>5d} {s['wr']:>5.1f}% "
                  f"{s['total_r']:>8.1f}R {s['dd']:>6.2f}% {s['year_range']:<10}")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
