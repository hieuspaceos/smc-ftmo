# Phase 2 — Chart cơ bản + SMC signals

## Mục tiêu

Mở app.py thấy chart nến EURUSD M15 với đầy đủ OB, FVG, BOS/CHoCH, sweep, displacement vẽ tự động.

## Task

### File: `src/data_loader.py`

- `load_pair(pair, timeframe)` → đọc parquet
- `prepare_ohlc(df)` → lowercase columns, DatetimeIndex, dropna

### File: `src/smc_signals.py`

Dùng `smartmoneyconcepts`:

```python
from smartmoneyconcepts import smc

def detect_swings(df, swing_length):
    return smc.swing_highs_lows(df, swing_length=swing_length)

def detect_bos_choch(df, swings, close_break=True):
    return smc.bos_choch(df, swings, close_break=close_break)

def detect_fvg(df, join_consecutive=False):
    return smc.fvg(df, join_consecutive=join_consecutive)

def detect_ob(df, swings, close_mitigation=False):
    return smc.ob(df, swings, close_mitigation=close_mitigation)

def detect_sweep(df, swings, atr_buffer=0.05):
    """Custom: giá vượt swing high/low +0.05 ATR rồi close ngược lại"""
    ...

def detect_displacement(df, atr_period=14, threshold=1.5):
    """Custom: candle range > 1.5× ATR"""
    ...
```

### Patch look-ahead bias

`smartmoneyconcepts.swing_highs_lows()` có issue #101 — swing được biết sau khi bar `[swingLen]` xuất hiện. Phải shift signal 1 bar trước khi dùng cho backtest:

```python
# Đúng: chỉ dùng swing sau khi bar thứ swingLen đã đóng
swings = smc.swing_highs_lows(df, swing_length=swingLen)
# Shift right để signal chỉ active từ bar swingLen trở đi
swings_shifted = swings.shift(swingLen)
```

### File: `app.py` (version 2)

- Dropdown chọn pair (EURUSD / XAUUSD / BTCUSD)
- Dropdown chọn TF (M15)
- Slider swing_length (5–50, default 20)
- Checkbox: show OB / FVG / BOS / sweep
- Chart Plotly: nến + OB (box xanh) + FVG (box vàng) + BOS/CHoCH (annotation mũi tên) + sweep (marker đỏ) + displacement (highlight)

## Acceptance criteria

- [ ] Mở app, chọn EURUSD M15 → thấy chart nến
- [ ] Tick show OB → thấy box màu tại các OB
- [ ] Tick show FVG → thấy box FVG
- [ ] Tick show BOS → thấy mũi tên tại các điểm BOS/CHoCH
- [ ] Tick show sweep → thấy marker tại các swing sweep
- [ ] Slider swing_length → chart re-render, OB/BOS thay đổi theo
- [ ] Không có error trên console khi đổi param
- [ ] Spot check: trên chart EURUSD M15, vài OB khớp với SMC textbook
