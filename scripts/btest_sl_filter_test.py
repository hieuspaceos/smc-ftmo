"""Test 3 SL filter configs on EURUSD M15 - last 6 months.

Compares Pine v1.2, Pine v1.3, and Python current.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

ROOT = Path("/Users/hieuspace/Desktop/CODE/smc-ftmo")
sys.path.insert(0, str(ROOT))
for pkg in ("smc_engine", "smc_bot_core", "smc_bot_webhook", "smc_bot_backtest", "smc_bot_dashboard"):
    src = ROOT / "packages" / pkg / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

from src.backtester import run_backtest, compute_metrics

BASE = {
    "swing_length": 10, "rr_target": 4.0, "displacement_atr_mult": 1.5,
    "sweep_atr_buffer": 0.05, "min_confluence_score": 4,
    "require_displacement": True, "require_bias_aligned": True,
    "sl_atr_buffer": 0.2, "bias_mode": "strict", "regime_mode": "off",
    "promotion_lookback_bars": 50, "exit_mode": "scale_in", "leg2_tp1_r": None,
}

CONFIGS = {
    "BASELINE (no SL filter)":   {},
    "Pine v1.2 (max_sl_atr=1.2)": {"max_sl_atr": 1.2},
    "Pine v1.3 (min=2.5 max=1.2)": {"min_sl_atr": 2.5, "max_sl_atr": 1.2},
    "Pine strict (min=0.0 max=1.2)": {"min_sl_atr": 0.0, "max_sl_atr": 1.2},
}

CFG_TEMPLATE = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05, "max_total_loss": 0.10,
             "timezone": "Europe/Paris"},
    "execution": {"spread_pips": {"EURUSD": 0.5, "GBPUSD": 0.7, "USDCHF": 0.8,
                                   "XAUUSD": 2.0, "BTCUSD": 5.0},
                  "commission_per_lot_per_side": 2.50,
                  "slippage_pips": {"mean": 0.1, "std": 0.3}},
    "risk": {"per_trade_pct": 0.0055, "max_trades_per_day": 3,
             "daily_loss_limit_r": 2.0, "max_open_positions": 1},
    "data": {"start_date": "2026-03-01", "end_date": "2026-09-02"},
    "pairs": ["EURUSD"],
}

def report(label, trades, equity, elapsed):
    if not trades:
        return f"{label:35s}  N=  0  (elapsed={elapsed:.0f}s)"
    n = len(trades)
    wr = sum(1 for t in trades if t["r_multiple"] > 0) / n * 100
    avg_r = sum(t["r_multiple"] for t in trades) / n
    total_r = sum(t["r_multiple"] for t in trades)
    return (f"{label:35s}  N={n:3d}  WR={wr:5.1f}%  "
            f"avgR={avg_r:+5.2f}  totalR={total_r:+7.1f}  ({elapsed:.0f}s)")


print("EURUSD M15 — 2026-03-01 to 2026-09-02 (6 months)")
print("=" * 100)

results = {}
for label, overrides in CONFIGS.items():
    strat = dict(BASE, **overrides)
    cfg = dict(CFG_TEMPLATE, strategy=strat)
    t0 = time.perf_counter()
    trades, eq = run_backtest("EURUSD", cfg)
    elapsed = time.perf_counter() - t0
    print(report(label, trades, eq, elapsed))
    results[label] = (trades, eq)

print()
print("=" * 100)
print("Compare to Pine on chart (visual):")
print(" Pine v1.2  → likely matches BASELINE (no min filter)")
print(" Pine v1.3  → IMPOSSIBLE config (min=2.5 max=1.2 → 0 trades)")
print(" Pine v1.3 strict fix → matches Pine strict (min=0 max=1.2)")
