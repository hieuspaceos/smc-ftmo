# Phase 6 — Backtester

## Mục tiêu

Loop qua từng bar M15, simulate entry/exit, ra equity curve + metrics + list trades.

## Task

### File: `src/backtester.py`

```python
def run_backtest(df_m15, df_h4, df_d, config):
    """
    Loop qua bar M15:
    1. Tại bar i: detect bias, score, P/D
    2. Nếu có signal và risk OK → mở lệnh
    3. Track lệnh mở: check TP1/2/3, SL, BE
    4. Đóng lệnh khi hit condition
    5. Ghi vào trades list
    """
    trades = []
    open_position = None
    guard = FTMOGuard(
        account_size=config['account_size'],
        max_daily_loss_pct=config['max_daily_loss'],
        max_trades_per_day=config['max_trades_per_day'],
        max_daily_loss_r=config['max_daily_loss_r'],
    )
    equity = config['account_size']
    equity_curve = [(df_m15.index[0], equity)]

    for i in range(config['swing_length'], len(df_m15)):
        bar = df_m15.iloc[i]
        current_date = bar.name.date()

        # Reset daily guard khi sang ngày mới
        if i > 0 and df_m15.index[i].date() != df_m15.index[i-1].date():
            guard.reset_daily()

        # 1. Update bias từ D, H4 đến bar i (cẩn thận look-ahead)
        bias = compute_bias_until(df_d, df_m15.index[i])
        score, pd_state = compute_signals_until(df_m15, df_m15.index[i], config)

        # 2. Update open position
        if open_position:
            actions = open_position['exit_obj'].update(bar['close'])
            if actions:
                for action in actions:
                    if action[0] == 'close_pct':
                        r = action[1] * (current_r - 1)  # partial R
                        equity += r * open_position['risk_amount']
                    elif action[0] == 'close_all':
                        r = current_r * action[1]
                        equity += r * open_position['risk_amount']
                        # Record trade
                        trades.append({...})
                        open_position = None

        # 3. Check entry mới
        if not open_position:
            can, reason = guard.can_trade(equity)
            if can:
                entry = check_entry(df_m15.iloc[:i+1], bias, score, pd_state, config)
                if entry:
                    risk_amount = equity * config['risk_per_trade']
                    lot = calculate_lot(equity, config['risk_per_trade'],
                                        entry['sl_distance'], pip_value)
                    exit_obj = PartialTPExit(...)
                    open_position = {
                        'entry': entry,
                        'lot': lot,
                        'risk_amount': risk_amount,
                        'exit_obj': exit_obj,
                    }

        equity_curve.append((df_m15.index[i], equity))

    return trades, equity_curve
```

### Metrics output

```python
def compute_metrics(trades, equity_curve):
    df_trades = pd.DataFrame(trades)

    return {
        'total_trades': len(df_trades),
        'winrate': (df_trades['r_multiple'] > 0).mean(),
        'profit_factor': df_trades[df_trades['r'] > 0]['r'].sum() / abs(df_trades[df_trades['r'] < 0]['r'].sum()),
        'avg_r': df_trades['r_multiple'].mean(),
        'max_dd': max_drawdown(equity_curve),
        'expectancy': df_trades['r_multiple'].mean(),
        'longest_win_streak': ...,
        'longest_loss_streak': ...,
        'total_r': df_trades['r_multiple'].sum(),
        'final_equity': equity_curve[-1][1],
        'return_pct': (equity_curve[-1][1] / equity_curve[0][1] - 1) * 100,
    }
```

### Acceptance criteria

- [ ] Chạy backtest EURUSD M15 2 năm ra ≥ 50 trades
- [ ] Mỗi trade có đủ field: pair, side, entry, exit, R, pnl, setup_type, score
- [ ] Equity curve vẽ được bằng Plotly
- [ ] Max DD < 4% (để có buffer cho FTMO 5% daily)
- [ ] Winrate nằm trong khoảng 50–60% (realistic cho SMC filtered)
- [ ] Profit factor > 1.5
- [ ] Trade có score < 4 không được mở
- [ ] Sau khi mất 2R trong ngày, không mở lệnh mới
