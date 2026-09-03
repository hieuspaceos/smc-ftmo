"""Sweep SL buffer values 0.2-1.5 to find sweet spot."""
import sys, time
from pathlib import Path

ROOT = Path("/Users/hieuspace/Desktop/CODE/smc-ftmo")
sys.path.insert(0, str(ROOT))
for pkg in ("smc_engine", "smc_bot_core", "smc_bot_webhook", "smc_bot_backtest", "smc_bot_dashboard"):
    src = ROOT / "packages" / pkg / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

import pandas as pd
from collections import Counter

from src.backtester import run_backtest

base = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0, "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 4.0,
        "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4, "require_displacement": True,
        "require_bias_aligned": True, "bias_mode": "strict",
        "regime_mode": "off", "promotion_lookback_bars": 50,
        "exit_mode": "scale_in", "leg2_tp1_r": None,
        "min_sl_atr": 0.0, "max_sl_atr": 99.0,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01", "end_date": "2026-09-02",
    "pd_lookback": 50, "pairs": ["EURUSD"],
}

print("EURUSD 10y - SL buffer sweep (ScaleIn Design A)")
print("=" * 90)
print(f'{"sl_buf":>8} {"trades":>7} {"WR%":>6} {"avgR":>7} {"totalR":>8} {"PF":>6} {"MaxDD%":>7}')

results = []
for sl_buf in [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.5]:
    cfg = dict(base)
    cfg["strategy"] = dict(base["strategy"], sl_atr_buffer=sl_buf)
    t0 = time.perf_counter()
    trades, equity = run_backtest("EURUSD", cfg)
    elapsed = time.perf_counter() - t0
    if not trades:
        print(f'{sl_buf:>8.2f} {"0":>7}')
        continue
    n = len(trades)
    wins = [t for t in trades if float(t.get("r_multiple", 0)) > 0]
    losses = [t for t in trades if float(t.get("r_multiple", 0)) <= 0]
    wr = len(wins) / n * 100
    avg_r = sum(float(t["r_multiple"]) for t in trades) / n
    total_r = sum(float(t["r_multiple"]) for t in trades)
    gross_win = sum(float(t["r_multiple"]) for t in wins)
    gross_loss = abs(sum(float(t["r_multiple"]) for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
    dd = (eq / eq.cummax() - 1) * 100
    print(f'{sl_buf:>8.2f} {n:>7d} {wr:>5.1f}% {avg_r:>+6.2f} {total_r:>+7.0f} {pf:>5.2f} {dd.min():>6.2f}%')
    results.append((sl_buf, n, wr, avg_r, total_r, pf, dd.min()))

print()
print("Best by avg R:", max(results, key=lambda r: r[3]))
print("Best by PF:    ", max(results, key=lambda r: r[5]))
print("Best by totalR:", max(results, key=lambda r: r[4]))
