"""Backtest with H4-only bias mode (relaxed from strict D+H4).

Run from project root:
    python -m scripts.btest_h4_only
"""
import time
import pandas as pd
from collections import Counter

from src.backtester import run_backtest

# Mirror app/streamlit_app.py line 826-845 run_cfg, ONLY change bias_mode
run_cfg = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10,
        "rr_target": 4.0,
        "displacement_atr_mult": 1.5,
        "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4,
        "require_displacement": True,
        "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        "bias_mode": "h4_only",           # <-- H4-ONLY (vs strict D+H4)
        "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "partial_tp": [
            {"pct": 0.40, "r": 2.0},
            {"pct": 0.50, "r": 3.0},
            {"pct": 1.00, "r": 4.0},
        ],
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
}


def main():
    t0 = time.perf_counter()
    trades, equity = run_backtest(pair='EURUSD', config=run_cfg)
    elapsed = time.perf_counter() - t0
    print(f'Trades: {len(trades)}  time={elapsed:.0f}s')

    if trades:
        years = Counter(pd.Timestamp(t['timestamp_entry']).year for t in trades)
        for y in sorted(years):
            bar = '#' * (years[y] // 2)
            print(f'  {y}: {years[y]:>4d} {bar}')
        n_win = sum(1 for t in trades if float(t.get('r_multiple', 0)) > 0)
        n_loss = len(trades) - n_win
        wr = n_win / len(trades) * 100
        total_r = sum(float(t.get('r_multiple', 0)) for t in trades)
        print(f'\nWinrate: {wr:.1f}%  ({n_win}W / {n_loss}L)')
        print(f'Total R: {total_r:.1f}R')
        if equity:
            eq = pd.DataFrame(equity, columns=['ts', 'eq']).set_index('ts')['eq']
            dd = (eq / eq.cummax() - 1) * 100
            print(f'Max DD: {dd.min():.2f}%')
            print(f'Final: ${eq.iloc[-1]:,.0f}')


if __name__ == "__main__":
    main()