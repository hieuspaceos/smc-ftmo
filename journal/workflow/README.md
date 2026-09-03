# Workflow Trade — SMC FTMO

Workflow trade tay cho EURUSD và XAUUSD trên FTMO $25k.
Trade live bắt đầu: Thứ 2 sau khi mua tài khoản. Trade 100% manual;
chỉ dùng Pine indicator trên TradingView làm nguồn tín hiệu.

## Múi giờ

- Local: Asia/Ho_Chi_Minh (UTC+7)
- Giờ session bên dưới ghi UTC, giờ VN trong ngoặc.

## Lịch hàng ngày

### Sáng (06:30-08:30 VN, 15 phút)
- Mở file `daily/YYYY-MM-DD.md`, điền block buổi sáng.
- Xem bias D1 + H4 trên EURUSD M15 và XAUUSD M15.
- Check tin quan trọng hôm nay trên forexfactory.com.
- Sau đó đi làm.

### Trưa (12:00-13:00 VN, 5 phút, tuỳ chọn)
- Lướt chart nhanh nếu có Pine alert trong giờ làm.
- Không vào lệnh trưa (giữa London và NY, volatility thấp).

### Session chính (18:30-21:30 VN = 11:30-14:30 UTC)
- Setup chart TradingView M15 EUR + XAU.
- Chạy Pine indicator, chờ setup first-touch OB.
- Mỗi setup → copy `pre-entry-checklist.md`, điền, quyết định.
- Log mọi trade (vào lệnh hoặc skip) trong file daily.

### Cuối ngày (21:30 VN)
- Cập nhật file daily: P/L, vị thế mở, ghi chú kỷ luật.
- Set SL/TP cho vị thế giữ qua đêm trước khi rời chart.

### Tối Chủ nhật (22:00 VN)
- Copy `weekly-review.md` vào `weekly/YYYY-Www.md` (ISO week).
- Log tổng trade, win rate, P/L, bài học.

## Quy tắc quản lý vốn

- Risk mỗi trade: 0.55% tài khoản = $137.50 trên $25k.
- Max loss trong ngày: -2R ($275).
- Max vị thế mở: 2 (1 EUR, 1 XAU).
- Không trade trong 30 phút trước/sau tin quan trọng.
- Không trade thứ 2 đầu tuần (gap cuối tuần).
- Chiều thứ 6: đóng hết vị thế trước 20:00 UTC tránh gap cuối tuần.

## Ghi chú từng cặp

### EURUSD
- Min SL: 17 pip ($170/lot).
- Pip value: $10/lot.
- Session tốt nhất: London + NY overlap (07:00-10:00 UTC).
- Spread mục tiêu: <1 pip.

### XAUUSD
- Min SL: 400 pip ($400/lot = $4/oz trên 1 lot).
- Pip value: $1/lot.
- Session tốt nhất: NY open + NY morning (07:00-12:00 UTC).
- Spread mục tiêu: <5 pip.

## Cấu trúc file

```
journal/workflow/
+- README.md                     # file này
+- pre-entry-checklist.md        # checklist copy cho mỗi setup
+- daily/                        # một file cho mỗi ngày trade
|  +- YYYY-MM-DD.md              # tạo từ daily-template.md
+- weekly/                       # một file cho mỗi tuần ISO
   +- YYYY-Www.md                # tạo từ weekly-review.md
+- daily-template.md             # template cho file daily
+- weekly-review.md              # template cho file weekly
```

## Cài Pine indicator

- File: `tradingview/smc-engine-main.pine`
- Profile: "Rulebook 8W" (mặc định)
- obZoneMode: Body 50% (chuẩn SMC)
- Hiện: BOS/CHoCH + Order Blocks + Context table
- Tắt: Swings, Displacement, Sweeps, FVGs, Pools (bớt nhiễu)

## Luồng quyết định

```
Có tín hiệu (OB first-touch)
  |
  v
Copy pre-entry-checklist.md vào file daily
  |
  v
Điền đủ 8 gate
  |
  +-- gate nào fail --> skip, log lý do, đi tiếp
  |
  v
Tính lot size theo SL
  |
  v
Vào lệnh qua cTrader
  |
  v
Sau trade: log entry, SL, TP, lý do thoát
```
