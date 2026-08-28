# MANUAL TRADE JOURNAL — 8 Tuần Practice

> Dùng song song với TV Premium (Bar Replay + VPVR + Alert).
> Bot `smc-ftmo` là reference, không phải authority.

---

## TUẦN 0 — Setup (ngày mua Premium)

### Ngày ____/____/2026

**Setup ban đầu**:
- [ ] Đọc xong `rule-book.md`, in checklist dán cạnh monitor
- [ ] Chạy `python -m src.backtester --backtest` lấy 16 setup mẫu → điền vào `replay_samples_2026.md`
- [ ] Mở TV EURUSD, cài VPVR + bar replay + alert
- [ ] Test thử 1 manual trade trên demo account (không tính vào 8 tuần)

**Setup tập trung tuần này**:
1. _______________________________________________
2. _______________________________________________

**3 Manual trade mục tiêu**:
1. Trade 1: ____________
2. Trade 2: ____________
3. Trade 3: ____________

**2 Replay session mục tiêu (Thứ 7)**:
1. Setup A: ____________
2. Setup B: ____________

---

## TUẦN 1 — Ngày ____/____ → ____/____

### Manual trade trong tuần

#### Trade #1 — Ngày ____/____
```
Setup type:        _______________ (OB / FVG / Sweep / Confluence)
Cặp:               _______________ (EURUSD mặc định)
Timeframe:         H4 bias: ___  |  H1 structure: ___  |  M15 entry: ___
Confluence score:  ___/5
Session:           _______________ (london / ny / overlap)

Entry:
- Giá:         _______
- SL:          _______ (dưới OB + 0.2× ATR)
- TP1 (40%):   _______ (2R)
- TP2 (30%):   _______ (3R)
- TP3 (30%):   _______ (4R)
- Position:    _______ lots
- Risk:        $_______ (0.55% account)

Reasoning (tại sao vào?):
_________________________________________________
_________________________________________________

Emotion tại entry:  _______________ (confident / FOMO / sợ / etc.)

Kết quả:
- Close tại:   _______
- R multiple:  _______ (TP1 / TP2 / TP3 / SL / BE / structure exit)
- P&L:         $_______

What actually happened (so với expectation):
_________________________________________________
_________________________________________________

Tại sao thắng/thua:
_________________________________________________
_________________________________________________

Lesson học được:
_________________________________________________
_________________________________________________

Bot signal match:  YES / NO / PARTIAL  →  Chi tiết: _______________
```

#### Trade #2 — Ngày ____/____
_(copy template trên)_

#### Trade #3 — Ngày ____/____
_(copy template trên)_

---

### Replay session (Thứ 7)

#### Replay A
```
Setup từ bot backtest:    _______________________________________________
Bot decision:             LONG / SHORT / NO TRADE

Replay trên TV:
- Tua từ bar: _______
- Tại entry bar: _______________ → My prediction: _______________
- Lý do prediction:        _______________________________________________
- Reveal:                  _______________________________________________
- Bot đúng / Sai / Tại sao lệch: _______________________________________________
- Lesson:                  _______________________________________________
```

#### Replay B
_(copy template trên)_

---

### Weekly Review (Chủ nhật)

```
Số manual trade:    ___
Winrate:            ___% (chia cho tổng R dương / tổng R âm)
Avg R multiple:     ___
Total P&L:          $___

3 mistake lặp lại nhiều nhất:
1. _________________________________________________
2. _________________________________________________
3. _________________________________________________

1 rule cần điều chỉnh:
_________________________________________________

Có nên tiếp tục plan không?  YES / NO
Nếu NO, vì sao:             _____________________________________________
```

**Cập nhật rule-book.md** với mistake mới phát hiện.

---

## TUẦN 2 — Ngày ____/____ → ____/____

_(copy toàn bộ structure tuần 1)_

---

## TUẦN 3-8

_(copy structure tuần 2, mỗi tuần 1 section)_

---

## SAU 8 TUẦN — Tổng kết

### Thống kê tổng

```
Tổng manual trade:       ___
Tổng replay prediction:  ___
Tổng P&L:                $___

Winrate trung bình:      ___%
Avg R multiple:          ___
Max consecutive loss:    ___
Max consecutive win:     ___

Best trade:  _____________  R multiple: ___  Lesson: _____________
Worst trade: _____________  R multiple: ___  Lesson: _____________
```

### Skill tăng ở đâu

1. _________________________________________________
2. _________________________________________________
3. _________________________________________________

### Skill vẫn kẹt

1. _________________________________________________
2. _________________________________________________

### Rule book cần sửa gì

1. _________________________________________________
2. _________________________________________________

### Quyết định

- [ ] Bot `smc-ftmo` đủ tốt → tin tưởng auto-execute
- [ ] Bot cần điều chỉnh rule → list cụ thể bên dưới
- [ ] Manual trade vẫn cần thiết → tiếp tục 8 tuần nữa
- [ ] Cần build tool mới → cụ thể: _________________________________

---

## GHI CHÚ QUAN TRỌNG

**Không trade khi**:
- Checklist chưa đủ ✓ (xem rule-book.md mục 6)
- Đã hit 3 trades hôm nay
- Đã hit 2R daily loss
- Ngoài session london/ny/overlap
- Trong 15 phút đầu London open

**Kỷ luật**:
- Journal ghi trong 30 phút sau lệnh (không để cuối ngày)
- Weekly review không skip
- Không revenge trade sau thua
- Không FOMO vào setup thiếu confluence

**Tinh thần**:
- Practice 8 tuần này KHÔNG phải để kiếm tiền
- Mục tiêu: hiểu rõ hơn, đưa ra quyết định tốt hơn
- Trade xấu cũng là data — ghi đầy đủ, học từ đó
