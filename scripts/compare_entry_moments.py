"""Compare entry moments between ladder and scale_in runs.

If both configs generate identical entry signals, the trades list entries
should have identical timestamps. Only exit outcomes should differ.

This diagnostic finds the discrepancy.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.backtester import run_backtest

BASE = {
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
        "partial_tp": [
            {"pct": 0.40, "r": 2.0},
            {"pct": 0.30, "r": 3.0},
            {"pct": 0.30, "r": 4.0},
        ],
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01", "end_date": "2026-08-21",
    "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
    "pd_lookback": 50, "pairs": ["EURUSD"],
}


def main():
    runs = {}
    for em in ["ladder", "scale_in"]:
        cfg = dict(BASE)
        cfg["strategy"] = dict(BASE["strategy"])
        cfg["strategy"]["exit_mode"] = em
        cfg["strategy"]["leg2_tp1_r"] = None
        if em == "scale_in":
            cfg["strategy"].pop("partial_tp", None)
        trades, _ = run_backtest("EURUSD", cfg)
        ts = [t.get("timestamp_entry") for t in trades]
        runs[em] = ts
        print(f"{em}: {len(trades)} trades, "
              f"first={ts[0] if ts else None}, "
              f"last={ts[-1] if ts else None}")

    ts_l = set(runs["ladder"])
    ts_s = set(runs["scale_in"])
    common = ts_l & ts_s
    only_l = ts_l - ts_s
    only_s = ts_s - ts_l
    print()
    print(f"common entries:    {len(common)}")
    print(f"only in ladder:    {len(only_l)}")
    print(f"only in scale_in:  {len(only_s)}")
    if only_s:
        print(f"\nFirst 5 only_in_scale_in:")
        for x in sorted(only_s)[:5]:
            print(f"  {x}")
    if only_l:
        print(f"\nFirst 5 only_in_ladder:")
        for x in sorted(only_l)[:5]:
            print(f"  {x}")


if __name__ == "__main__":
    main()
