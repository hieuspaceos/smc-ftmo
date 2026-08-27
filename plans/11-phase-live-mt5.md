# Phase 10 — Live trade với MT5 (sau Phase 9)

## Mục tiêu

Kết nối MT5 demo FTMO, auto-detect signal realtime, auto-execute lệnh, track equity intraday.

## Task

### File: `src/mt5_connector.py`

```python
import MetaTrader5 as mt5

class MT5Connector:
    def __init__(self, login, password, server):
        self.login = login
        self.password = password
        self.server = server
        self.connected = False

    def connect(self):
        if not mt5.initialize(login=self.login, password=self.password, server=self.server):
            raise ConnectionError(f"MT5 init failed: {mt5.last_error()}")
        self.connected = True

    def get_ohlcv(self, symbol, timeframe, count=500):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        return df

    def get_account_info(self):
        return mt5.account_info()

    def get_symbol_info(self, symbol):
        return mt5.symbol_info(symbol)

    def send_order(self, symbol, order_type, lot, sl, tp):
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "sl": sl,
            "tp": tp,
            "magic": 234000,
            "comment": "SMC FTMO",
        }
        return mt5.order_send(request)

    def get_positions(self):
        return mt5.positions_get()

    def close_position(self, ticket):
        pos = mt5.positions_get(ticket=ticket)
        if pos:
            return mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos[0].symbol,
                "volume": pos[0].volume,
                "type": mt5.ORDER_TYPE_SELL if pos[0].type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "magic": 234000,
            })

    def disconnect(self):
        mt5.shutdown()
```

### Realtime pipeline

```python
def live_loop(symbol, timeframe_m15, connector, config):
    while True:
        # 1. Pull latest OHLCV
        df = connector.get_ohlcv(symbol, timeframe_m15, count=1000)

        # 2. Compute signals (same as backtest)
        signals = detect_all_signals(df, ...)

        # 3. Check entry
        entry = check_entry(df, bias_state, score_state, pd_state, config)
        if entry and connector.can_trade():
            # 4. Send order
            order = connector.send_order(
                symbol=symbol,
                order_type=mt5.ORDER_TYPE_BUY if entry['side'] == 'long' else mt5.ORDER_TYPE_SELL,
                lot=entry['lot'],
                sl=entry['sl'],
                tp=entry['tp'],
            )
            # 5. Log to journal
            journal.insert_trade({...})

        # 6. Check open positions
        for pos in connector.get_positions():
            # Track partial TP, BE move
            ...

        # 7. Sleep
        time.sleep(60)
```

### Streamlit live tab

```python
tab1, tab2 = st.tabs(["Backtest", "Live Trade"])

with tab2:
    st.subheader("Live Trading")
    if not connector.connected:
        if st.button("Connect MT5"):
            login = st.secrets["mt5_login"]
            connector = MT5Connector(login, ...)
            connector.connect()
    else:
        st.success(f"Connected: {connector.get_account_info().name}")
        st.metric("Equity", connector.get_account_info().equity)
        st.metric("Daily P/L", ...)
        # Show positions
        # Show signal stream
```

### FTMO guard realtime

```python
def check_ftmo_breach(connector, account_start):
    info = connector.get_account_info()
    daily_pnl = info.equity - info.balance + info.credit
    total_pnl = info.equity - account_start

    if daily_pnl <= -account_start * 0.05:
        # Đóng tất cả lệnh
        for pos in connector.get_positions():
            connector.close_position(pos.ticket)
        alert("FTMO: Daily loss limit hit, all positions closed")

    if total_pnl <= -account_start * 0.10:
        alert("FTMO: Total loss limit hit, STOP trading")
        return False
    return True
```

## Acceptance criteria

- [ ] Connect được MT5 demo FTMO
- [ ] Pull OHLCV realtime
- [ ] Detect signal realtime (giống backtest)
- [ ] Auto-send order khi có signal
- [ ] Track partial TP, move SL BE
- [ ] Daily guard hoạt động (đóng lệnh khi chạm limit)
- [ ] Forward test 30 ngày winrate ±5% so với backtest
- [ ] Không có order gửi nhầm khi signal thay đổi

## Risk

- Test kỹ trên demo trước khi live
- Dry-run mode: chỉ detect signal, không gửi order thật
- Có nút Kill Switch manual trong UI
- Log tất cả action ra file để debug

## Phase này KHÔNG làm nếu chưa stable

Nếu Phase 9 (backtest) chưa cho kết quả ổn định → KHÔNG chuyển sang Phase 10. Tiếp tục tinh chỉnh rule, filter, hoặc đứng ngoài quan sát.
