---
date: 2026-08-29
session: manual-trade-playbook
plan: none
---

# Journal Rule Book: Trade Tay SMC

## Mục đích

Đây là bộ rule ngắn để trade tay với engine hiện tại.
Nó phải khớp với:

- [Checklist Trade Tay SMC](../smc-manual-trade-checklist.md)
- [SMC Engine Giải Thích Bằng Tiếng Việt](../smc-engine-vietnamese-guide.md)

## Rule book ngắn

1. Luôn đọc D, H4, H1 trước khi nhìn M15.
2. Nếu D và H4 trái nhau mạnh, đứng ngoài.
3. Bias là hướng ưu tiên, không phải lệnh vào ngay.
4. OB chỉ dùng sau BOS hoặc CHoCH hợp lệ.
5. OB đã invalidated thì không trade nữa.
6. Sweep là dấu hiệu quét liquidity, không phải entry một mình.
7. FVG là lớp xác nhận thêm, không phải trigger độc lập.
8. EQH / EQL là bối cảnh liquidity, không phải lý do vào lệnh.
9. Breaker chỉ là lớp nghiên cứu khi OB cũ đã chết rồi CHoCH mới xác nhận.
10. `regime_mode=off` là setup học mặc định.
11. `regime_mode=on/auto` chỉ dùng khi muốn nghiên cứu breaker.
12. Mỗi lệnh phải ghi journal.

## Cách ra quyết định trên chart

### Bước 1

Xác định bias:

- D bull + H4 bull -> ưu tiên long
- D bear + H4 bear -> ưu tiên short
- D/H4 lệch nhau mạnh -> đứng ngoài

### Bước 2

Tìm structure trên M15:

- tìm swing gần nhất
- chờ BOS hoặc CHoCH
- chỉ lấy OB được sinh ra sau cú break đó

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
- BOS hay CHoCH nào là trigger
- OB / sweep / FVG / EQH / EQL / breaker nào đã dùng
- lý do vào lệnh
- lý do đặt stop
- lý do đặt TP
- kết quả trade

## Điều không được làm

- không vào chỉ vì thấy OB
- không vào chỉ vì thấy sweep
- không vào chỉ vì thấy EQH / EQL
- không coi breaker là tốt hơn OB mặc định
- không đổi nhiều slider cùng lúc rồi kết luận
- không dùng `auto` như nút thần kỳ

## Câu nhớ nhanh

Bias trước, structure sau, OB rồi mới nhìn sweep, liquidity chỉ là bối cảnh, không phải lệnh.

