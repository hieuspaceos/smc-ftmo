---
status: active
title: "Checklist Trade Tay SMC"
created: "2026-08-29"
updated: "2026-08-29"
---

# Checklist Trade Tay SMC

Đây là bản ngắn để mở chart và làm theo ngay.

## Setup mặc định nên dùng khi học

- `bias_mode = strict (D+H4)`
- `regime_mode = off`
- `promotion_lookback_bars = 50`
- `TP profile = Conservative`
- giữ `Displacement ATR`, `Sweep ATR buffer`, `P/D lookback` ở mặc định

## Cách đọc nhanh trước khi vào M15

1. Chọn 1 pair, 1 phiên, 1 khung chính.
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

OB = vùng nến cuối cùng ngược chiều trước cú phá cấu trúc.

Làm theo thứ tự:

1. Tìm swing gần nhất.
2. Chờ bar sau xác nhận có BOS hoặc CHoCH.
3. Nhìn cây nến cuối cùng ngược chiều trước cú break đó.
4. Vùng nến đó là OB.
5. Chỉ dùng OB khi nó còn active.
6. OB đã bị invalidated thì không vào nữa.

Nhớ:

- OB không phải cứ thấy là vào
- OB tốt là OB nằm đúng với bias và đúng thời điểm

## Cách nhận ra Sweep

Sweep = quét thanh khoản rồi đóng cửa quay lại.

Nhìn như sau:

1. Giá chọc qua đỉnh cũ hoặc đáy cũ.
2. Sau đó nến đóng cửa quay ngược lại.
3. Nếu quét lên rồi đóng xuống -> bearish sweep.
4. Nếu quét xuống rồi đóng lên -> bullish sweep.

Sweep dùng để:

- xác nhận thị trường vừa lấy liquidity
- tăng độ tin cậy cho setup

Sweep không nên dùng một mình để vào lệnh.

## Trên M15 thì làm gì

1. Xác định bias từ D/H4/H1.
2. Tìm swing gần nhất trên M15.
3. Chờ BOS hoặc CHoCH.
4. Chỉ lấy OB sinh ra sau cú break đó.
5. Xem giá đang ở premium hay discount.
6. Nếu có sweep hoặc FVG, coi đó là xác nhận thêm.
7. Chỉ vào khi zone còn active và chưa invalidated.

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

1. Bias D/H4 có ủng hộ hướng trade không?
2. M15 có BOS hoặc CHoCH rõ không?
3. OB có được tạo từ cú break hợp lệ không?
4. OB còn active không?
5. Giá đang ở premium hay discount?
6. Có sweep hoặc FVG xác nhận thêm không?
7. EQH / EQL có giúp hiểu liquidity không?
8. Stop có đặt ngoài OB kèm buffer chưa?
9. TP có theo profile đang chọn chưa?
10. Nếu không giải thích được setup trong 1 câu, bỏ qua.

## Điều nên tránh

- vào chỉ vì thấy OB
- vào chỉ vì thấy sweep
- vào chỉ vì thấy EQH / EQL
- dùng `auto` như nút thần kỳ
- đổi nhiều slider cùng lúc rồi kết luận

## Ghi journal

Mỗi lệnh nên ghi:

- pair, timeframe, session
- bias D / H4 / H1 / M15
- BOS hay CHoCH nào là trigger
- OB / sweep / FVG / EQH / EQL / breaker nào đã dùng
- lý do vào, lý do đặt stop, lý do đặt TP
- trade đúng hay sai theo checklist

## Câu nhớ nhanh

Bias trước, structure sau, OB rồi mới nhìn sweep, liquidity chỉ là bối cảnh, không phải lệnh.

