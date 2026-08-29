# MANUAL TRADE JOURNAL — 8 Tuần Practice

> Dùng song song với TV Premium (Bar Replay + VPVR + Alert).
> Bot `smc-ftmo` là reference. Luật vào lệnh: `journal/rule-book.md`.
> Setup học: `bias_mode=strict`, `regime_mode=off`, OB `full`, **EURUSD only**.
> Freeze: sweep ≥ 0.25× ATR + reclaim mới cộng điểm. SL > 1.2× ATR hoặc 2R đụng HTF → bỏ.

---

## TUẦN 0 — Setup (ngày mua Premium)

### Ngày ____/____/2026

**Setup ban đầu**:
- [ ] Đọc xong `rule-book.md`, in checklist mục 16 dán cạnh monitor
- [ ] Chạy backtest lấy 16 setup mẫu → điền `replay_samples_2026.md`
- [ ] Mở TV EURUSD, cài VPVR + bar replay + alert
- [ ] Test 1 lệnh demo (không tính vào 8 tuần)

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
Setup type:        OB retest (default) / breaker-research / OTHER: ___
Cặp:               EURUSD (bắt buộc 8 tuần)
Session:           _______________ (london / ny / overlap)
Timeframe:         D bias: ___  |  H4 bias: ___  |  H1: ___  |  M15: ___

Structure:
- BOS / CHoCH nào là trigger:   BOS / CHoCH / NONE
- Close-break (không phải wick): YES / NO
- Displacement ( >1.5× ATR ):    YES / NO

OB:
- Origin (nến ngược trước BOS):  _______________
- Zone full [low, high]:         _______ / _______
- Còn active tại entry:          YES / NO
- Đã invalidated (OB break):     YES / NO   close xuyên lúc: _______
- First-test:                    YES / NO

Xác nhận / bối cảnh (không phải trigger):
- Sweep reclaim:     YES (level: ___, pierce ATR: ___ ; ≥0.25 mới cộng điểm) / NO
- FVG:               YES (zone: ___) / NO
- P/D zone:          premium / discount / neutral
- EQH / EQL gần:     EQH / EQL / NONE   (chỉ bối cảnh)
- Breaker dùng?:     NO (học mặc định) / YES — vì sao: ___

Confluence score:  ___/5
  [ ] displacement  [ ] D+H4 bias  [ ] sweep  [ ] P/D  [ ] first-test

Entry:
- Giá:         _______   (long=OB top / short=OB bottom)
- SL:          _______   (ngoài OB + 0.2× ATR; SL_ATR = ___ ; >1.2 = NO TRADE)
- 2R vs tường HTF: CLEAR / BLOCKED → _______
- TP1 (40%):   _______   (2R)
- TP2 (30%):   _______   (3R)
- TP3 (30%):   _______   (4R)
- Position:    _______ lots
- Risk:        $_______ (0.55% account)
- Overlay tay thêm (không phải bot):  NONE / structure-exit / trail-BOS / OTHER: ___

Reasoning (1 câu + chi tiết):
_________________________________________________
_________________________________________________

Emotion tại entry:  _______________ (confident / FOMO / sợ / etc.)

Kết quả:
- Close tại:   _______
- R multiple:  _______ (TP1 / TP2 / TP3 / SL / BE)
- P&L:         $_______
- Exit reason: TP1 / TP2 / TP3 / SL / BE / overlay-tay: ___

What actually happened (so với expectation):
_________________________________________________

Tại sao thắng/thua:
_________________________________________________

Lesson:
_________________________________________________

Bot signal match:  YES / NO / PARTIAL  →  Chi tiết: _______________
Đúng checklist rule-book?:  YES / NO  → Lệch ở: _______________
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

**Cập nhật `rule-book.md` mục 20** với mistake mới.

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
- Khối A mục 16 thiếu, hoặc score < 4 (thiếu cả sweep lẫn P/D)
- Đã hit 3 trades hôm nay
- Đã hit 2R daily loss
- Ngoài session london / ny / overlap
- Trong 15 phút đầu London open
- D và H4 lệch
- OB đã break (invalidated) hoặc hết first-test
- SL > 1.2× ATR(M15) hoặc 2R đụng tường HTF
- Setup chỉ là FVG / sweep / EQH-EQL / breaker / CHoCH một mình
- Không phải EURUSD

**Kỷ luật**:
- Journal ghi trong 30 phút sau lệnh (không để cuối ngày)
- Weekly review không skip
- Không revenge trade sau thua
- Không FOMO vào setup thiếu confluence

**Tinh thần**:
- Practice 8 tuần này KHÔNG phải để kiếm tiền
- Mục tiêu: đọc đúng structure engine, quyết định sạch hơn
- Trade xấu cũng là data — ghi đầy đủ, học từ đó
