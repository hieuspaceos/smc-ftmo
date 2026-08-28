# REPLAY SAMPLES — 16 Setup từ Bot Backtest

> Chạy `python -m src.backtester --backtest` để lấy trade samples.
> Chọn 16 setup đại diện (2/tuần × 8 tuần):
> - 4 thắng lớn (R ≥ 3)
> - 4 thắng nhỏ (1 ≤ R < 2)
> - 4 thua (R < 0)
> - 4 breakeven (R ≈ 0)
>
> Điền vào đây trước khi bắt đầu tuần 1.

---

## Cách chọn setup

```bash
# Chạy backtest
cd smc-ftmo
python -m src.backtester --backtest --symbol EURUSD --tf M15
```

Xem file output (thường là `output/backtest_trades.csv` hoặc journal), chọn 16 trade đại diện theo 4 nhóm trên.

---

## Setup #1 — Tuần 1, Replay A

```
Trade ID từ bot:        _______________
Cặp / TF:               EURUSD M15
Ngày giờ (entry):       _______________
Bot decision:           LONG / SHORT / NO TRADE
Bot R multiple:         _______________

Setup components:
- Displacement (candle > 1.5× ATR): YES / NO
- H4 bias:              BULLISH / BEARISH / RANGING
- H1 structure:         BOS / CHoCH / NONE
- M15 sweep:            YES (level: ___) / NO
- OB / FVG:             OB at ___ / FVG at ___ / BOTH / NONE
- Confluence score:     ___/5

Session:                london / ny / overlap
```

**My prediction tại entry bar**: ________________

**Lý do prediction**: _______________________________________________

**Reveal (sau khi tua hết replay)**:
```
Actual R multiple:     _______________
Bot exit reason:       _______________ (TP1 / TP2 / TP3 / SL / structure shift)
Price path đáng chú ý: _______________________________________________
```

**So sánh với bot**:
- Trùng/khách ở chỗ nào: _____________________________________________
- Tại sao lệch (nếu có): _____________________________________________

**Lesson**: ____________________________________________________________

---

## Setup #2 — Tuần 1, Replay B

_(copy template trên)_

---

## Setup #3-#16 — Tuần 2-8

_(copy template cho mỗi setup)_

---

## Thống kê sau 16 replay

```
Tổng prediction đúng hướng:    ___/16  (___%)
Tổng prediction trùng bot:     ___/16  (___%)

Lệch nhiều nhất ở:
- Confluence score đánh giá:    ___ lần
- Bias reading:                 ___ lần
- Structure nhận diện:          ___ lần
- Sweep detection:              ___ lần

Lesson tổng hợp sau 16 replay:
1. _________________________________________________
2. _________________________________________________
3. _________________________________________________
```

---

## Ghi chú

- Prediction PHẢI ghi trước khi reveal — không sửa sau
- Mỗi replay session ~30 phút, không cần làm hơn
- Nếu prediction sai 12/16 → xem lại cách đọc chart, không phải lỗi bot
