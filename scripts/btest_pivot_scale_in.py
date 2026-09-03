"""ScaleInExit backtest with Pine chart params (untitled.md).

Compares:
  - A: scale_in + config.yaml baseline (swing=10, mult=1.5)  ← btest_scale_in reference
  - B: scale_in + Pine pivot params (swing=5, mult=2.5)

Includes ladder baseline for context.

Run:
    python -m scripts.btest_pivot_scale_in
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

from src.backtester import run_backtest


def _summary(trades, eq):
    if not trades:
        return {"n": 0}
    n = len(trades)
    n_w = sum(1 for t in trades if float(t.get("r_multiple", 0) or 0) > 0)
    n_l = n - n_w
    wr = n_w / n * 100
    total_r = sum(float(t.get("r_multiple", 0) or 0) for t in trades)
    eq_df = pd.DataFrame(eq, columns=["ts", "val"]).set_index("ts")["val"] if eq else None
    dd = ((eq_df / eq_df.cummax() - 1).min() * 100) if eq_df is not None and not eq_df.empty else 0.0
    reasons = Counter(t.get("exit_reason", "?") for t in trades)
    return {
        "n": n, "w": n_w, "l": n_l,
        "wr": round(wr, 1), "total_r": round(total_r, 2),
        "dd": round(dd, 2), "reasons": dict(reasons),
        "years": {str(y): c for y, c in sorted(
            Counter(pd.Timestamp(t["timestamp_entry"]).year for t in trades).items())},
    }


CONFIGS = {
    # Reference: scale_in + config.yaml baseline (swing=10, mult=1.5)
    "A_scale_in_baseline": {
        "ftmo": {"account_size": 100000, "phase": "challenge",
                 "profit_target": 0.10, "max_daily_loss": 0.05,
                 "max_total_loss": 0.10, "max_open_positions": 1,
                 "daily_loss_limit_r": 2.0},
        "execution": {
            "spread_pips": {"EURUSD": 0.5},
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
            "exit_mode": "scale_in", "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                   "sweep_clean": 1, "premium_discount": 1,
                                   "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01", "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50, "pairs": ["EURUSD"],
    },

    # Pivot: scale_in + Pine chart params
    "B_scale_in_pine_pivot": {
        "ftmo": {"account_size": 100000, "phase": "challenge",
                 "profit_target": 0.10, "max_daily_loss": 0.05,
                 "max_total_loss": 0.10, "max_open_positions": 1,
                 "daily_loss_limit_r": 2.0},
        "execution": {
            "spread_pips": {"EURUSD": 0.5},
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3},
        },
        "risk": {"per_trade_pct": 0.0055, "max_trades_per_day": 3,
                 "daily_loss_limit_r": 2.0, "max_open_positions": 1},
        "strategy": {
            "swing_length": 5, "rr_target": 4.0,
            "displacement_atr_mult": 2.5, "sweep_atr_buffer": 0.05,
            "min_confluence_score": 4, "require_displacement": True,
            "require_bias_aligned": True, "sl_atr_buffer": 0.2,
            "bias_mode": "strict", "regime_mode": "off",
            "promotion_lookback_bars": 50,
            "exit_mode": "scale_in", "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                   "sweep_clean": 1, "premium_discount": 1,
                                   "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01", "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50, "pairs": ["EURUSD"],
    },
}


def main():
    results = {}
    raw = {}
    for label, cfg in CONFIGS.items():
        t0 = time.perf_counter()
        pairs = cfg.get("pairs") or ["EURUSD"]
        all_trades, all_eq = [], []
        for pair in pairs:
            trades, eq = run_backtest(pair, cfg)
            all_trades.extend(trades)
            all_eq.extend(eq)
        elapsed = time.perf_counter() - t0
        s = _summary(all_trades, all_eq)
        s["elapsed_s"] = elapsed
        results[label] = s
        raw[label] = all_trades
        print(f"\n=== {label} ===")
        print(f"  trades={s['n']}  WR={s.get('wr', 0):.1f}%  "
              f"total_R={s.get('total_r', 0):.1f}  DD={s.get('dd', 0):.2f}%  "
              f"reasons={s.get('reasons', {})}")
        if s.get("years"):
            for y, c in s["years"].items():
                print(f"    {y}: {c}")
    return results


if __name__ == "__main__":
    main()
