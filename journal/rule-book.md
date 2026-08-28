# RULE BOOK — Manual Trade 8 Tuần

> Trích từ `config.yaml` + `src/smc_engine/`. Đây là luật chơi khi manual trade.
> Không tuân thủ rule dưới = không vào lệnh. Không có ngoại lệ.

---

## 1. Account & Risk (FTMO Challenge)

| Thông số | Giá trị | Nghĩa |
|---|---|---|
| Account size | $100,000 | Challenge phase |
| Profit target | 10% | $10,000 để pass |
| Max daily loss | 5% | $5,000/ngày |
| Max total loss | 10% | $10,000 tổng |
| Risk per trade | 0.55% | $550 mỗi lệnh |
| Max trades/day | 3 | Quá 3 → dừng ngày |
| Daily loss limit | 2R | Mất 2R (~1.1%) → dừng ngày |
| Max open positions | 1 | Không hedge, không grid |
| RR target | 2.5R | TP mục tiêu 2.5× risk |

**Partial TP** (chốt một phần):
- 40% tại 2R → move SL về BE
- 30% tại 3R → giữ SL ở BE
- 30% tại 4R

**Tỷ lệ risk SL**: SL thêm 0.2× ATR buffer dưới OB (không phải tại OB).

---

## 2. Setup BẮT BUỘC (không có = KHÔNG vào lệnh)

### A. Displacement
- Candle range > 1.5× ATR(14)
- Cho biết institutional order đã vào

### B. Bias alignment
- H4 bias phải cùng hướng với M15 entry
- BULLISH H4 + M15 setup → chỉ LONG
- BEARISH H4 + M15 setup → chỉ SHORT

### C. Structure (BOS / CHoCH)
- BOS = Break of Structure (tiếp diễn xu hướng)
- CHoCH = Change of Character (đảo chiều)
- Phải có ít nhất 1 trong 2

### D. Liquidity sweep
- Giá vượt swing high/low ≥ 0.05× ATR
- Sau đó quay đầu (fake breakout)

### E. Order Block (OB)
- OB unmitigated tại vùng displacement
- Entry khi giá quay về test OB

### F. FVG (Fair Value Gap)
- Gap 3-bar imbalance
- Giá fill FVG → entry zone

---

## 3. Confluence Score (tối thiểu 4/5)

| Yếu tố | Trọng số | BẮT BUỘC? |
|---|---|---|
| Displacement | 1 | ✓ Có |
| Bias aligned | 1 | ✓ Có |
| Sweep clean | 1 | Có nếu được |
| Premium/discount | 1 | Có nếu được |
| First test | 1 | Có nếu được |

**Score ≥ 4 mới vào. Không đủ → NO TRADE.**

---

## 4. Session Filter

| Session | Giờ (NY/EST) | Trade được? |
|---|---|---|
| Asia | 19:00 - 02:00 | ✗ |
| London | 02:00 - 05:00 | ✓ |
| New York | 07:00 - 10:00 | ✓ |
| Overlap (LN+NY) | 08:00 - 10:00 | ✓ (volume cao nhất) |

**Ngoài session trên = KHÔNG trade.** Mặc dù config cho phép london/ny/overlap, nhưng tránh 15 phút đầu London open (spread rộng).

---

## 5. Cặp & Khung

**Cặp**: EURUSD (mặc định), XAUUSD, BTCUSD

**Khung**:
- D: bias dài hạn (không trade)
- H4: bias trung hạn (BẮT BUỘC align)
- H1: structure
- M15: entry

**Workflow chart**: D → H4 → H1 → M15 (top-down)

---

## 6. Checklist trước lệnh (in ra, dán cạnh monitor)

```
[ ] Displacement có? (candle > 1.5× ATR)
[ ] H4 bias cùng hướng?
[ ] Có BOS hoặc CHoCH trên H1?
[ ] Có liquidity sweep trên M15?
[ ] Có OB hoặc FVG chưa mitigate?
[ ] Tính confluence score: __/5 (cần ≥4)
[ ] Đang trong session cho phép?
[ ] Không phải 15 phút đầu London open
[ ] SL đặt dưới OB + 0.2× ATR buffer
[ ] Risk 0.55% account = $___
[ ] Chưa hit max 3 trades hôm nay
[ ] Chưa hit 2R daily loss limit

→ Tất cả ✓: VÀO LỆNH
→ Bất kỳ ✗: NO TRADE
```

---

## 7. Position Size

```
Risk ($) = Account × 0.55% = $100,000 × 0.0055 = $550
SL (pips) = tính từ chart
Position size (lots) = $550 / (SL pips × pip value)

EURUSD: 1 lot = $10/pip → 0.5 lots nếu SL 11 pips
```

Tính trước khi vào. Ghi vào journal.

---

## 8. Trade Management

- **TP1** (40%) tại 2R: chốt, move SL → BE
- **TP2** (30%) tại 3R: chốt, SL giữ BE
- **TP3** (30%) tại 4R: chốt hết
- **Nếu structure shift trước TP1**: thoát toàn bộ
- **Nếu hit BE sau TP1**: trailing bằng structure (mỗi BOS mới → move SL dưới swing low gần nhất)

---

## 9. Những lỗi hay mắc (note từ tuần trước)

_Cập nhật sau mỗi tuần review_

- [ ] Để thêm tuần 1
- [ ] Để thêm tuần 2
- [ ] ...

---

## 10. Cam kết

Tôi cam kết:
- Trade theo rule book này, không cảm tính
- Ghi journal trong 30 phút sau khi đóng lệnh
- Review mỗi Chủ nhật
- Không trade nếu checklist chưa đủ ✓

Ký tên: _________________ Ngày: ___________
