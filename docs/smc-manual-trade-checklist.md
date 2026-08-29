---
status: active
title: "Checklist Trade Tay SMC"
created: "2026-08-29"
updated: "2026-08-29"
---

# Checklist Trade Tay SMC

Đây là bản ngắn để mở chart và làm theo ngay.

Luật đầy đủ (in ra khi trade): [journal/rule-book.md](../journal/rule-book.md).

**Câu nhớ:** Bias trước, structure sau, OB rồi mới nhìn sweep. Liquidity là bối cảnh, không phải lệnh.

## Setup mặc định nên dùng khi học

- `bias_mode = strict (D+H4)` — đóng băng, không `h4_only`
- `regime_mode = off`
- `promotion_lookback_bars = 50`
- `TP profile = Conservative`
- giữ slider engine mặc định (sweep bot vẫn `0.05× ATR`)
- 8 tuần: **EURUSD only**
- Overlay tay: sweep cộng điểm chỉ khi pierce **≥ 0.25× ATR** + reclaim
- Overlay tay: SL **> 1.2× ATR(M15)** hoặc 2R đụng tường HTF → NO TRADE

## Cách đọc nhanh trước khi vào M15

1. Chọn EURUSD, 1 phiên, khung D→H4→H1→M15.
2. Nhìn D trước.
3. Nhìn H4 sau.
4. Nhìn H1 để lấy nhịp trung gian.
5. Kết luận bias tổng là `bull`, `bear`, hay `neutral`.
6. Nếu D và H4 trái nhau mạnh, đứng ngoài.

## Cách nhận ra Bias

Bias là hướng ưu tiên của thị trường.

- `bull`: khung lớn đang nghiêng lên
- `bear`: khung lớn đang nghiêng xuống
- `neutral`: chưa có hướng rõ

Khi nhìn chart:

- D và H4 cùng bull -> ưu tiên long
- D và H4 cùng bear -> ưu tiên short
- D và H4 lệch nhau -> đừng ép lệnh

## Cách nhận ra OB

OB = nến ngược chiều cuối cùng **trước BOS**. Engine chỉ sinh OB từ BOS, không từ CHoCH.

Làm theo thứ tự:

1. Tìm swing gần nhất.
2. Chờ close phá swing đó: BOS = tiếp diễn, CHoCH = đảo chiều. Wick không tính.
3. Chỉ lấy OB sau **BOS** + displacement. CHoCH không đẻ OB.
4. Vùng nến ngược chiều cuối trước BOS là OB (`full` = high–low).
5. Chỉ dùng OB khi còn active và còn first-test.
6. OB break / invalidated (`close` xuyên cạnh kia) thì không vào nữa.

Nhớ:

- OB không phải cứ thấy là vào
- OB tốt là OB đúng bias, đúng BOS, còn sống
- Sau CHoCH: bỏ OB cũ. Chờ BOS mới cùng chiều, hoặc (nghiên cứu) breaker

## Cách nhận ra Sweep

Sweep = quét thanh khoản rồi **close reclaim** về đúng phía level.

Nhìn như sau:

1. Giá chọc qua đỉnh cũ hoặc đáy cũ.
2. Nến đóng cửa **quay lại xuyên level** (reclaim).
3. Quét lên rồi close dưới level -> bearish sweep.
4. Quét xuống rồi close trên level -> bullish sweep.
5. Wick vượt mà close không reclaim = không phải sweep.
6. Overlay bot vẽ từ `0.05× ATR` (thường < 1 pip). 8 tuần tay: chỉ cộng điểm nếu pierce **≥ 0.25× ATR**.

Sweep dùng để:

- xác nhận thị trường vừa lấy liquidity
- tăng độ tin cậy cho setup

Sweep không nên dùng một mình để vào lệnh.

## Trên M15 thì làm gì

1. Xác định bias từ D/H4 (strict). H1 chỉ là nhịp trung gian.
2. Tìm swing gần nhất trên M15.
3. Chờ **BOS** cùng chiều bias (close-break).
4. Chỉ lấy OB sinh ra từ BOS đó. Không lấy “OB” sau CHoCH.
5. Xem giá đang ở premium hay discount.
6. Sweep reclaim hoặc FVG chỉ là xác nhận thêm, không phải entry.
7. EQH / EQL chỉ đọc bối cảnh liquidity.
8. Chỉ vào khi zone còn active, chưa invalidated, còn first-test.

## EQH / EQL dùng thế nào

EQH / EQL là vùng thanh khoản.

- dùng để biết nơi giá có thể quét
- dùng để đọc regime và bối cảnh
- không phải trigger vào lệnh độc lập

## Breaker dùng thế nào

Breaker là OB cũ đã chết, sau đó được CHoCH xác nhận đổi vai.

Làm đúng thứ tự:

1. OB bị invalidated.
2. Sau đó mới có CHoCH.
3. Lúc đó breaker mới hợp lệ.

Khi học tay:

- học OB classic trước
- breaker chỉ xem là lớp nghiên cứu
- đừng mặc định breaker tốt hơn OB

## Checklist vào lệnh

Hai khối. Không áp “bất kỳ ✗ = cấm” lên sweep / P/D.

**Khối A — cấm nếu thiếu**

1. Bias D/H4 theo BOS engine (`strict`), không cảm giác nến.
2. M15 BOS cùng chiều, close-break, displacement gắn BOS.
3. OB từ BOS đó, còn sống, còn first-test, giá gần mép ≤ 1.5× ATR.
4. SL ≤ 1.2× ATR(M15), 2R không đụng tường HTF.
5. EURUSD, session hợp lệ, risk 0.55%, chưa 3 lệnh, chưa 2R ngày.
6. Không breaker / `h4_only` / `auto`. Giải thích được 1 câu.

**Khối B — chấm điểm (cần ≥ 4)**

Qua A đã có disp + bias + first-test = 3. Điểm 4 lấy từ sweep **hoặc** P/D.

- Sweep ≥ 0.25× ATR + reclaim → +1 (overlay 0.05 không đủ)
- P/D đúng phía, range H4 → +1
- Thiếu sweep được nếu P/D có (hoặc ngược lại). Thiếu cả hai → NO TRADE

## Điều nên tránh

- vào chỉ vì thấy OB, sweep, FVG, EQH / EQL, hoặc breaker
- trade OB đã invalidated (OB break)
- coi CHoCH = BOS, coi FVG = entry zone
- dùng `auto` / `h4_only` / breaker giữa 8 tuần
- đổi slider hoặc nới 0.25 / 1.2 ATR vì ít lệnh
- trade XAU / BTC trong sample 8 tuần
- đổi nhiều slider cùng lúc rồi kết luận

## Ghi journal

Mỗi lệnh nên ghi:

- pair, timeframe, session
- bias D / H4 / H1 / M15
- BOS nào tạo OB; CHoCH nào (nếu có) chỉ là đảo chiều / breaker-research
- OB còn sống hay đã break; first-test hay không
- sweep / FVG / EQH / EQL / breaker nào đã dùng (và cái nào không phải trigger)
- lý do vào, lý do đặt stop, lý do đặt TP
- trade đúng hay sai theo checklist

## Câu nhớ nhanh

Bias trước, structure sau, OB rồi mới nhìn sweep, liquidity chỉ là bối cảnh, không phải lệnh.

