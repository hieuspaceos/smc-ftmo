---
date: 2026-08-29
session: manual-trade-playbook
plan: none
---

# Journal Rule Book: Trade Tay SMC

## Mục đích

Đây là bộ rule ngắn để trade tay với engine hiện tại.
Nó phải khớp với:

- [journal/rule-book.md](../../journal/rule-book.md)
- [Checklist Trade Tay SMC](../smc-manual-trade-checklist.md)
- [SMC Engine Giải Thích Bằng Tiếng Việt](../smc-engine-vietnamese-guide.md)

## Rule book ngắn

1. Luôn đọc D, H4, H1 trước khi nhìn M15.
2. Nếu D và H4 trái nhau mạnh, đứng ngoài.
3. Bias là hướng ưu tiên, không phải lệnh vào ngay.
4. OB chỉ dùng sau **BOS** hợp lệ + displacement. CHoCH không tạo OB.
5. OB đã invalidated (close xuyên cạnh kia) thì không trade nữa.
6. Sweep là dấu hiệu quét liquidity rồi reclaim, không phải entry một mình.
7. FVG là lớp xác nhận thêm, không phải trigger độc lập.
8. EQH / EQL là bối cảnh liquidity, không phải lý do vào lệnh.
9. Breaker chỉ là lớp nghiên cứu khi OB cũ đã chết rồi CHoCH mới xác nhận.
10. `regime_mode=off` là setup học mặc định. Không `h4_only`, không `auto`.
11. 8 tuần: EURUSD only. Sweep cộng điểm chỉ khi pierce ≥ 0.25× ATR + reclaim. SL > 1.2× ATR(M15) hoặc 2R đụng tường HTF → NO TRADE.
12. Mỗi lệnh phải ghi journal. Score ≥ 4 = (disp + bias + first-test) rồi thêm sweep hoặc P/D. Đóng băng — không thêm dòng đến Chủ nhật tuần 8.

## Cách ra quyết định trên chart

### Bước 1

Xác định bias:

- D bull + H4 bull -> ưu tiên long
- D bear + H4 bear -> ưu tiên short
- D/H4 lệch nhau mạnh -> đứng ngoài

### Bước 2

Tìm structure trên M15:

- tìm swing gần nhất
- chờ BOS cùng chiều bias (close-break, không phải wick)
- chỉ lấy OB được sinh ra từ BOS đó
- CHoCH = đảo chiều: bỏ OB cũ, không đẻ OB mới

### Bước 3

Kiểm tra zone:

- OB còn active chưa
- giá đang ở premium hay discount
- có sweep hoặc FVG xác nhận thêm không
- có EQH / EQL gần đó không

### Bước 4

Nếu setup còn sạch:

- mới cân nhắc entry
- stop phải nằm ngoài OB và có buffer
- TP nên theo profile đang chọn

## Cách ghi journal cho mỗi lệnh

Mỗi trade nên có:

- pair
- timeframe
- session
- bias D / H4 / H1 / M15
- BOS nào tạo OB; CHoCH nào chỉ là đảo chiều / breaker-research
- OB còn sống hay đã break; first-test hay không
- sweep / FVG / EQH / EQL / breaker nào đã dùng
- lý do vào lệnh
- lý do đặt stop
- lý do đặt TP
- kết quả trade

## Điều không được làm

- không vào chỉ vì thấy OB, sweep, FVG, EQH / EQL, hoặc breaker
- không trade OB đã invalidated
- không coi CHoCH = BOS
- không coi breaker là tốt hơn OB mặc định
- không đổi nhiều slider cùng lúc rồi kết luận
- không dùng `auto` như nút thần kỳ

## Câu nhớ nhanh

Bias trước, structure sau, OB rồi mới nhìn sweep, liquidity chỉ là bối cảnh, không phải lệnh.

