# REPLAY SAMPLES — 16 Setup từ Bot Backtest

> Chạy backtest để lấy trade samples.
> Chọn 16 setup đại diện (2/tuần × 8 tuần):
> - 4 thắng lớn (R ≥ 3)
> - 4 thắng nhỏ (1 ≤ R < 2)
> - 4 thua (R < 0)
> - 4 breakeven (R ≈ 0)
>
> Điền vào đây trước khi bắt đầu tuần 1.
> Luật đọc chart: `journal/rule-book.md`. 8 tuần: EURUSD only.
> Sweep tay ≥ 0.25× ATR + reclaim mới cộng điểm. SL > 1.2× ATR hoặc 2R đụng HTF → NO TRADE.

---

## Cách chọn setup

```bash
cd smc-ftmo
PYTHONPATH=src python -m src.backtester
```

Xem output (`output/trades.db` hoặc journal app). Chọn 16 trade đại diện theo 4 nhóm trên.

Prediction **ghi trước khi reveal**. Bot exit chỉ có `tp1 / tp2 / tp3 / sl`. Không bịa “structure shift” thành exit của bot.

---

## Setup #1 — Tuần 1, Replay A

```
Trade ID từ bot:        _______________
Cặp / TF:               EURUSD M15
Ngày giờ (entry):       _______________
Bot decision:           LONG / SHORT / NO TRADE
Bot R multiple:         _______________
Bot exit reason:        tp1 / tp2 / tp3 / sl / (khác: ___)

Bias:
- D:                    bull / bear / neutral
- H4:                   bull / bear / neutral
- Aligned strict?:      YES / NO

Structure M15:
- Trigger:              BOS / CHoCH / NONE
- Close-break?:         YES / NO
- Displacement >1.5 ATR: YES / NO

OB:
- Zone [bottom, top]:   _______ / _______
- Active tại entry?:    YES / NO
- Invalidated (OB break) trước entry?: YES / NO
- First-test?:          YES / NO

Xác nhận / bối cảnh:
- Sweep reclaim:        YES (level: ___, pierce ATR: ___ / ≥0.25?) / NO
- FVG nearby:           YES / NO
- P/D zone:             premium / discount / neutral
- EQH / EQL:            EQH / EQL / NONE
- Breaker?:             NO (default) / YES

Confluence score:       ___/5  (sweep chỉ +1 nếu pierce ≥0.25)
SL / ATR:               _______  (>1.2 = tay sẽ NO TRADE dù bot vào)
2R vs HTF liquidity:    CLEAR / BLOCKED
Session:                london / ny / overlap
```

**My prediction tại entry bar** (ghi TRƯỚC reveal): ________________

**Lý do** (1 câu: bias → BOS → OB còn sống): ________________

**Reveal (sau khi tua hết replay)**:
```
Actual R multiple:     _______________
Bot exit reason:       tp1 / tp2 / tp3 / sl
Price path đáng chú ý: _______________________________________________
OB còn sống hay bị break sau entry?:  survived / invalidated lúc ___
```

**So sánh với bot**:
- Trùng ở: _____________________________________________
- Lệch ở (bias / BOS vs CHoCH / OB break / sweep / P/D / first-test): ___
- Có đọc FVG/EQH/breaker như trigger không?  YES / NO

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
- Bias D+H4:                    ___ lần
- BOS vs CHoCH:                 ___ lần
- OB còn sống / OB break:       ___ lần
- First-test:                   ___ lần
- Sweep reclaim:                ___ lần
- P/D:                          ___ lần
- Nhầm FVG/EQH/breaker thành entry: ___ lần

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
- Bot không exit vì structure shift / trail BOS. Đừng lấy đó làm đáp án replay
