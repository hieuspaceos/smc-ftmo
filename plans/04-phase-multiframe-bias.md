# Phase 3 — Đa khung + Bias detector

## Mục tiêu

Nhìn 1 lần thấy bias Daily, H4, H1, M15 cùng lúc. Trade chỉ khi D và H4 aligned.

## Task

### File: `src/bias_detector.py`

```python
def detect_bias(df, swing_length=20):
    """Trả về 'bull' | 'bear' | None dựa trên BOS/CHoCH gần nhất"""
    swings = smc.swing_highs_lows(df, swing_length=swing_length)
    structure = smc.bos_choch(df, swings)

    last_bos = structure['BOS'].iloc[-swing_length:].sum()
    last_choch = structure['CHOCH'].iloc[-swing_length:].sum()

    if last_choch > 0:
        # Có CHoCH gần đây → đã đổi trend
        return "bull" if structure['CHOCH'].iloc[-swing_length:].iloc[-1] == 1 else "bear"
    elif last_bos > 0:
        return "bull" if structure['BOS'].iloc[-swing_length:].iloc[-1] == 1 else "bear"
    else:
        return None  # sideway
```

### File: `src/data_loader.py` thêm

- `load_multi_tf(pair, timeframes)` → dict {tf: df}

### File: `app.py` (version 3)

Layout mới:

```
┌────────────────────────────────────────────────┐
│ Top: 4 mini chart xếp dọc (D / H4 / H1 / M15) │
│      Mỗi chart có 1 indicator BOS marker      │
├────────────────────────────────────────────────┤
│ Bias Panel (4 ô):                              │
│   Daily: ✅ Bull                               │
│   H4:     ✅ Bull                              │
│   H1:     ➖ Bear (info)                       │
│   M15:    ➖ Bull (info)                       │
│   Trade Direction: LONG ONLY (D+H4 aligned)   │
├────────────────────────────────────────────────┤
│ Main chart M15 (như Phase 2)                  │
└────────────────────────────────────────────────┘
```

## Logic hiển thị bias

```python
bias_d   = detect_bias(df_d, swing_length)
bias_h4  = detect_bias(df_h4, swing_length)
bias_h1  = detect_bias(df_h1, swing_length)  # info only
bias_m15 = detect_bias(df_m15, swing_length)  # info only

# Quy tắc 1 của bạn: chỉ trade khi D và H4 aligned
can_trade = bias_d is not None and bias_d == bias_h4
trade_direction = "long" if bias_d == "bull" else "short" if bias_d == "bear" else None
```

## Acceptance criteria

- [ ] 4 mini chart hiển thị đúng dữ liệu từng khung
- [ ] Bias panel hiển thị đúng bull/bear/None cho từng khung
- [ ] Khi D và H4 cùng hướng → "Trade Direction: LONG/SHORT ONLY"
- [ ] Khi D và H4 khác hướng hoặc 1 trong 2 None → "ĐỨNG NGOÀI"
- [ ] Đổi pair → bias recalc đúng
- [ ] Đổi swing_length → bias recalc đúng
