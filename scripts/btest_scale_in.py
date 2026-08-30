"""Backtest with ScaleInExit Design A (2R/4R) — default 50/50 leg split.

Compares to ladder 40/30/30 baseline:
  - Scale-in: +1.075R avg, PF 3.57, MaxDD 3.40%, total $456,400
  (EURUSD 2016-08 → 2026-08, 603 trades)

Use this script to verify the scale_in exit mode produces the documented
numbers when run from CLI. For interactive comparison use
app/streamlit_app.py and select 'scale_in' from the Exit mode dropdown.

Run from project root:
    python -m scripts.btest_scale_in
"""
import time
import pandas as pd
from collections import Counter

from src.backtester import run_backtest

# Mirror app/streamlit_app.py run_cfg exactly, ONLY change exit_mode + drop
# partial_tp (scale-in ignores the ladder config — uses ScaleInExit 2R/4R).
run_cfg = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10,
        "rr_target": 4.0,                  # echoed for backtester; not used by scale_in
        "displacement_atr_mult": 1.5,
        "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4,
        "require_displacement": True,
        "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        "bias_mode": "strict",
        "regime_mode": "off",
        "promotion_lookback_bars": 50,
        # Exit mode toggle — Design A (leg2_tp1_r=None) by default.
        # ScaleInExit partial_tp ladder is computed internally (50% @ 2R,
        # 50% leg2 runs to 4R). partial_tp below is ignored when exit_mode=scale_in.
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
        # Exit reason breakdown for scale-in (valid: tp4r / sl / leg2_sl)
        reasons = Counter(t.get('exit_reason', '?') for t in trades)
        print(f'\nExit reasons: {dict(reasons)}')


if __name__ == "__main__":
    main()