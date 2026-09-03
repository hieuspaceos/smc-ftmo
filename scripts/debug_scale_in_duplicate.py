"""Trace what happens at 2016-04-04 10:15 to find why scale_in entry fires there."""
import os, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Patch backtester.run_backtest to dump state around 2016-04-04 10:15
import src.backtester as bt_mod
orig = bt_mod.run_backtest

CFG = {
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
        "partial_tp": [{"pct": 0.40, "r": 2.0}, {"pct": 0.30, "r": 3.0},
                       {"pct": 0.30, "r": 4.0}],
        "exit_mode": "scale_in", "leg2_tp1_r": None,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                               "sweep_clean": 1, "premium_discount": 1,
                               "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01", "end_date": "2016-04-08",
    "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
    "pd_lookback": 50, "pairs": ["EURUSD"],
}

# Run scale_in with limited date
trades, _ = bt_mod.run_backtest("EURUSD", CFG)
for t in trades:
    print(t["timestamp_entry"], t["timestamp_exit"], t["exit_reason"])
