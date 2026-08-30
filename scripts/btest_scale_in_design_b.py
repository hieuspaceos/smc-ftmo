"""Backtest with ScaleInExit Design B — optional leg2 TP1 at 3R.

Design B extends Design A with an intermediate profit-take on leg2:
  - Hit 2R  → open leg2 (SL=entry BE)
  - Hit 3R  → close 50% leg2 at +0.25R locked, move remaining leg2 SL → 3R
  - Hit 4R  → close leg1 rem + leg2 rem (capped at TP, no overshoot)
  - Cascade → leg2 closes at locked SL if TP1 was hit, else at entry

Design A vs B tradeoff on EURUSD 2016-2026 (603 vs 595 trades):
  - Design A: PF 3.57, AvgR +1.075, MaxDD 3.40%, PnL $456,400
  - Design B: PF 3.40, AvgR +1.050, MaxDD 3.43%, PnL $443,750

Design B trades PnL for risk reduction (-2.8% PnL vs Design A, but
winrate +6.6pp). Kept as opt-in feature flag.

Run from project root:
    python -m scripts.btest_scale_in_design_b
"""
import time
import pandas as pd
from collections import Counter

from src.backtester import run_backtest

# Mirror app/streamlit_app.py run_cfg exactly, ONLY toggle exit_mode=scale_in
# AND leg2_tp1_r=3.0 to enable Design B. Streamlit 'Enable Design B' checkbox
# produces the same run_cfg.
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
        "bias_mode": "strict",
        "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": 3.0,             # Design B: leg2 50% close at 3R
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
        # Design B keeps the same exit_reason taxonomy as Design A
        # (tp4r / sl / leg2_sl). The TP1 lock is invisible in exit_reason —
        # it shows up as reduced PnL on tp4r trades and reduced loss on
        # leg2_sl cascade trades.
        reasons = Counter(t.get('exit_reason', '?') for t in trades)
        print(f'\nExit reasons: {dict(reasons)}')


if __name__ == "__main__":
    main()