# Phase 5 — Strategy + Risk manager

## Mục tiêu

Code đầy đủ entry/exit rules với partial TP 40/30/30, BE khi hit 2R, daily stop -2R.

## Task

### File: `src/risk_manager.py`

```python
def calculate_lot(account_equity, risk_pct, sl_distance, pip_value):
    """Tính lot size từ risk amount và SL distance"""
    risk_amount = account_equity * risk_pct
    lot = risk_amount / (sl_distance * pip_value)
    return max(round(lot, 2), 0.01)  # min 0.01 lot

class FTMOGuard:
    def __init__(self, account_size, max_daily_loss_pct, max_trades_per_day, max_daily_loss_r):
        self.account_size = account_size
        self.max_daily_loss = account_size * max_daily_loss_pct
        self.max_trades = max_trades_per_day
        self.max_daily_loss_r = max_daily_loss_r

        self.today_trades = []
        self.today_r = 0.0

    def reset_daily(self):
        self.today_trades = []
        self.today_r = 0.0

    def can_trade(self, current_equity):
        # Quy tắc 9: mất 2R trong ngày → dừng
        if self.today_r <= -self.max_daily_loss_r:
            return False, "Đã mất 2R hôm nay"
        # Max trades/day
        if len(self.today_trades) >= self.max_trades:
            return False, f"Đã trade {self.max_trades} lệnh hôm nay"
        # Daily loss guard
        daily_pnl = current_equity - self.account_size
        if daily_pnl <= -self.max_daily_loss:
            return False, "Equity chạm daily loss limit"
        return True, "OK"

    def record_trade(self, r_multiple):
        self.today_r += r_multiple
        self.today_trades.append(r_multiple)
```

### File: `src/strategy.py`

```python
class PartialTPExtit:
    """
    40% tại 2R, 30% tại 3R, 30% tại 4R.
    Move SL về entry (BE) sau khi hit 2R.
    """
    def __init__(self, entry, sl, side, atr_buffer):
        self.entry = entry
        self.sl = sl
        self.side = side  # 'long' or 'short'
        self.sl_distance = abs(entry - sl)
        self.remaining_pct = 1.0
        self.be_moved = False
        self.closed = False

    def update(self, current_price):
        if self.closed:
            return None

        actions = []

        # Long
        if self.side == 'long':
            r1 = (current_price - self.entry) / self.sl_distance  # R-multiple hiện tại

            # Hit 2R → close 40% + move SL to BE
            if r1 >= 2.0 and self.remaining_pct == 1.0:
                actions.append(('close_pct', 0.40))
                self.remaining_pct = 0.60
                self.sl = self.entry  # BE
                self.be_moved = True

            # Hit 3R → close 30% (còn 30%)
            if r1 >= 3.0 and self.remaining_pct == 0.60:
                actions.append(('close_pct', 0.50))  # 30% / 60% còn lại
                self.remaining_pct = 0.30

            # Hit 4R → close nốt 30%
            if r1 >= 4.0 and self.remaining_pct == 0.30:
                actions.append(('close_pct', 1.0))
                self.closed = True

            # SL hit
            if current_price <= self.sl:
                actions.append(('close_all', self.remaining_pct))
                self.closed = True

        # Short tương tự, đảo chiều
        # ...

        return actions
```

### Entry rules

```python
def check_entry(df_m15, bias_state, score_state, pd_state):
    """
    Entry long khi:
    - bias_d == 'bull' AND bias_h4 == 'bull'
    - Có BOS↑ trong N bar gần nhất
    - Có OB bullish chưa mitigate
    - Score >= 4 (đã tính ở Phase 4)
    - Giá hiện tại trong vùng Discount
    """
    if not (bias_state['aligned_long']):
        return None

    if score_state['entry_allowed'] is False:
        return None

    # Có OB bullish gần giá hiện tại?
    last_ob = find_nearest_unmitigated_ob(df_m15, side='bull')
    if last_ob is None:
        return None

    # Giá đang trong vùng Discount?
    if pd_state['zone'] != 'discount':
        return None

    return {
        'side': 'long',
        'entry': last_ob['bottom'],
        'sl': last_ob['bottom'] - atr * 0.2,
        'tp': last_ob['bottom'] + (last_ob['bottom'] - last_ob['bottom'] + atr * 0.2) * 2.5,
        'ob_top': last_ob['top'],
        'ob_bottom': last_ob['bottom'],
    }
```

## Acceptance criteria

- [ ] `calculate_lot(100000, 0.0055, 50, 10)` → trả về lot hợp lý
- [ ] `FTMOGuard.can_trade()` trả False khi `today_r <= -2`
- [ ] `FTMOGuard.can_trade()` trả False khi `len(today_trades) >= 3`
- [ ] `PartialTPExit` long: hit 2R → close 40% + move BE
- [ ] `PartialTPExit` long: hit 3R → close tiếp 30%
- [ ] `PartialTPExit` long: hit 4R → close nốt 30%
- [ ] `PartialTPExit` long: hit SL trước khi 2R → close 100% ở -1R
- [ ] Short logic đối xứng long
