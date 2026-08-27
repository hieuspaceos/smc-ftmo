# Phase 4 — Premium/Discount + Confluence score

## Mục tiêu

Mỗi setup trên chart có score 1–5 theo 5 tiêu chí, chỉ setup score ≥ 4 mới được vào lệnh (trong đó bắt buộc có Displacement + Bias aligned).

## Task

### File: `src/premium_discount.py`

```python
def detect_premium_discount(df, lookback=50):
    """
    Tính vùng Premium/Discount dựa trên swing high/low gần nhất.
    Range = high - low
    Equilibrium = 50% của range
    Premium = nửa trên (giá > equilibrium)
    Discount = nửa dưới (giá < equilibrium)
    """
    recent = df.iloc[-lookback:]
    range_high = recent['high'].max()
    range_low = recent['low'].min()
    eq = (range_high + range_low) / 2

    current_price = df['close'].iloc[-1]

    if current_price > eq:
        return "premium", eq, range_high, range_low
    elif current_price < eq:
        return "discount", eq, range_high, range_low
    else:
        return "neutral", eq, range_high, range_low
```

### File: `src/confluence.py`

```python
def score_setup(setup):
    """
    Trả về (score, reasons_list, entry_allowed)
    Quy tắc 8: 4/5 tiêu chí, bắt buộc có Displacement + Bias aligned.
    """
    score = 0
    reasons = []

    # BẮT BUỘC
    if setup['displacement']:
        score += 1
        reasons.append("Displacement mạnh")
    if setup['bias_aligned']:
        score += 1
        reasons.append("Thuận Bias H4/Daily")

    # CỘNG THÊM
    if setup['sweep_clean'] or setup.get('is_breaker_with_choch', False):
        score += 1
        if setup['sweep_clean']:
            reasons.append("Sweep sạch")
        else:
            reasons.append("CHoCH kèm Breaker")
    if setup['in_pd_zone']:
        score += 1
        reasons.append(f"Đúng {setup['pd_zone']}")
    if setup['first_test']:
        score += 1
        reasons.append("Test lần đầu, ít mitigate")

    # Entry condition: score >= 4 VÀ 2 điều kiện bắt buộc
    has_required = setup['displacement'] and setup['bias_aligned']
    entry_allowed = (score >= 4) and has_required

    return score, reasons, entry_allowed
```

### Hiển thị trên chart

- Mỗi setup có marker riêng:
  - Score 2–3: marker xám, không vào lệnh
  - Score 4–5: marker xanh/lime, có thể vào lệnh
- Hover vào marker → tooltip hiện score + reasons

### Hiển thị Premium/Discount

- Vẽ 2 đường ngang: range high (đỏ), range low (xanh), equilibrium (vàng)
- Tô nền nhạt: nửa premium đỏ nhạt, nửa discount xanh nhạt

## Acceptance criteria

- [ ] Trên chart, mỗi OB/BOS marker có score hiển thị
- [ ] Setup score ≥ 4 có marker nổi bật hơn
- [ ] Hover vào marker thấy tooltip "Score: 5 — Displacement, Bias, Sweep, Discount, First test"
- [ ] Setup score < 4 không có marker "Entry" (chỉ marker info)
- [ ] Đổi slider `min_confluence_score` → marker Entry biến mất/xuất hiện đúng
- [ ] Vùng P/D hiển thị rõ trên chart
