---
status: active
title: "SMC Engine Giải Thích Bằng Tiếng Việt"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Giải Thích Bằng Tiếng Việt

## Mục tiêu của file này

File này không thay thế docs kỹ thuật.

Nó tồn tại để trả lời 3 câu hỏi dễ bị nghẽn nhất:

1. **Engine này đang làm gì thật ra?**
2. **Các thuật ngữ như BOS, CHoCH, OB, Breaker, FVG nghĩa là gì trong code này?**
3. **Tại sao lại có công thức / rule đó?**

Nếu đọc docs tiếng Anh thấy nặng, hãy đọc file này trước, rồi quay lại:

- [SMC Engine Overview](./smc-engine-overview.md)
- [SMC Engine Event Pipeline](./smc-engine-event-pipeline.md)
- [SMC Engine Verification](./smc-engine-verification.md)

## Cách hiểu ngắn nhất

Engine này không phải bot đoán tương lai.

Nó là **máy đọc cấu trúc giá**.

Nó làm theo flow:

1. tìm swing high / swing low
2. xem giá có phá swing đó thật không
3. nếu phá thật thì gắn BOS hoặc CHoCH
4. từ đó sinh ra OB, FVG, sweep, bias, premium/discount
5. backtester mới dùng các tín hiệu đó để vào lệnh

Nói ngắn gọn:

> Engine = bộ máy biến nến OHLC thành event có nghĩa theo SMC.

## Giải thích các thuật ngữ chính

### Swing

**Swing high / low** = đỉnh / đáy đủ rõ để coi là mốc cấu trúc.

Trong code này:

- swing high tại bar `i` khi high của bar đó lớn hơn cụm bar bên trái và không yếu hơn cụm bar bên phải
- swing low tương tự theo hướng ngược lại

Tại sao phải làm vậy?

Vì nếu không có swing thì không biết giá đang phá cái gì.
SMC luôn cần một mốc trước khi nói BOS hay CHoCH.

### BOS

**BOS = Break of Structure**

Có nghĩa là giá phá mốc swing **cùng chiều với trend đang có**.

Ví dụ:

- thị trường đang bullish
- giá phá lên trên swing high gần nhất
- đó là BOS bullish

Tại sao phải có BOS?

Vì OB trong engine này chỉ sinh ra sau một cú phá cấu trúc có ý nghĩa.
Nếu không có BOS thì rất nhiều “OB” chỉ là vùng giá ngẫu nhiên.

### CHoCH

**CHoCH = Change of Character**

Là dấu hiệu đảo chiều cấu trúc.

Ví dụ:

- trước đó trend bullish
- giờ giá phá xuống swing low quan trọng
- engine coi đó là CHoCH bearish

Tại sao phải tách BOS và CHoCH?

Vì 2 cái này khác nhau về ý nghĩa:

- BOS = tiếp diễn
- CHoCH = đảo chiều

Nếu trộn chúng vào một loại signal, logic trade sẽ rất bẩn.

### OB — Order Block

Trong engine này, OB được hiểu là:

- cây nến ngược chiều cuối cùng trước cú BOS
- vùng giá của cây nến đó là zone để chờ retest

Tại sao cần rule này?

Vì SMC giả định ở đó có lệnh lớn chưa được fill hết.
Khi giá quay lại vùng đó, có khả năng phản ứng.

### Breaker Block

Breaker không phải OB mới.

Breaker là **OB cũ đã bị phá**, sau đó được **CHoCH xác nhận đổi vai**.

Ví dụ dễ hiểu:

- có bullish OB
- giá phá thủng bullish OB đó => OB này chết
- sau đó thị trường có CHoCH bearish
- vùng OB cũ giờ có thể trở thành breaker bearish

Tại sao phải cần CHoCH mới cho promote breaker?

Vì chỉ việc phá OB thôi chưa đủ chứng minh đổi trend.
CHoCH là bước xác nhận rằng vai trò vùng đó đã thật sự lật.

### FVG — Fair Value Gap

FVG là khoảng trống giá giữa 3 nến.

Hiểu đơn giản:

- giá đi quá nhanh
- để lại khoảng mất cân bằng
- thị trường hay có xu hướng quay lại lấp vùng đó

Trong engine này, FVG là layer hỗ trợ, không phải trung tâm của cấu trúc.

### Sweep

Sweep = quét thanh khoản.

Ví dụ:

- giá chọc lên qua đỉnh cũ
- sau đó đóng cửa quay ngược xuống
- đó là bearish sweep

Tại sao sweep quan trọng?

Vì nhiều cú sweep báo rằng market vừa lấy liquidity xong và có thể đổi hướng.

### Premium / Discount

Đây là cách engine nói:

- long ở vùng rẻ hơn (discount)
- short ở vùng đắt hơn (premium)

Hiểu đơn giản như chia đoạn giá hiện tại thành 2 nửa quanh một mức cân bằng.

## Tại sao lại có các công thức đó?

## 1. Tại sao displacement dùng `(high - low) > multiplier * ATR`?

Vì engine cần một cách đo khách quan xem cây nến đó có “mạnh” hay chỉ là dao động bình thường.

- `high - low` = biên độ thật của cây nến
- `average true range` = độ rung trung bình gần đây
- so sánh 2 cái giúp biết cây nến hiện tại có mạnh hơn mức bình thường hay không

Hiểu dân dã:

> Nếu cây nến hiện tại không lớn hơn mặt bằng gần đây, thì chưa chắc đó là displacement thật.

### 2. Tại sao swing phải chờ `right` bars mới confirm?

Nếu không chờ, engine sẽ repaint.

Ví dụ:

- tại bar hiện tại tưởng là đỉnh
- nhưng 2 bar sau lại còn cao hơn
- vậy “đỉnh” cũ hóa ra không phải đỉnh

Nên engine chấp nhận trễ một chút để đổi lấy **không nhìn tương lai**.

### 3. Tại sao OB chỉ được touch / invalidate từ bar sau activation?

Nếu cho cùng bar:

- bar BOS vừa sinh OB
- rồi chính nó lại chạm / invalidate luôn OB đó

thì logic rất bẩn, vì một bar vừa tạo zone vừa phá zone.

Nên engine khóa rule:

> bar tạo OB không được phép tự test chính nó

### 4. Tại sao breaker cần `invalidation_timestamp < choch_activation_timestamp`?

Đây là rule chống lookahead.

Nếu breaker được promote trước hoặc cùng lúc chưa rõ ràng với invalidation,
engine sẽ vô tình dùng tương lai để hợp thức hóa vùng cũ.

Nên phải là:

1. OB chết trước
2. CHoCH đến sau
3. lúc đó mới cho breaker sống

## Tại sao có thêm `ob_body_mode`?

Vì có 2 cách hiểu vùng OB:

- **full**: lấy cả râu nến
- **body**: chỉ lấy thân nến

Hiểu đơn giản:

- full = vùng rộng hơn, dễ fill hơn, nhưng đôi khi nhiễu
- body = vùng chặt hơn, đẹp hơn, nhưng có thể miss trade

Đây là chỉnh **hình học zone**, không phải thay đổi logic cấu trúc.

## Tại sao có `regime_mode`?

Vì thị trường không phải lúc nào cũng cùng 1 kiểu.

- lúc trend mạnh: OB classic thường tốt hơn
- lúc sideway/choppy: breaker có thể hữu ích hơn

Nên thêm:

- `off` = không dùng breaker
- `on` = luôn dùng breaker
- `auto` = engine tự đo regime rồi quyết định

Nhưng hiện tại `auto` vẫn là heuristic, chưa nên tin tuyệt đối.

## Tôi nên đọc bộ docs theo thứ tự nào?

Nếu muốn dễ nuốt:

1. file này
2. [SMC Engine Overview](./smc-engine-overview.md)
3. [SMC Engine Event Pipeline](./smc-engine-event-pipeline.md)
4. [SMC Engine Extensions](./smc-engine-extensions.md)
5. [SMC Engine Verification](./smc-engine-verification.md)

## Nên tin cái gì, không nên tin cái gì?

### Nên tin

- engine detect structure theo logic nhất quán
- events là causal, không lookahead
- baseline smoke checksum ổn định
- OB / FVG lifecycle query theo thời gian là đúng kiểu kỹ thuật

### Không nên tin tuyệt đối

- winrate đẹp trên 1 giai đoạn dữ liệu
- `auto` regime hiện tại
- breaker sẽ luôn tốt hơn OB classic
- đổi vài slider rồi nghĩ chiến lược đã tối ưu

## Kết luận

Nếu phải nói 1 câu dễ nhớ:

> SMC engine này là máy đọc cấu trúc giá một cách causal và deterministic; nó không tiên tri, nó chỉ biến giá thành event có nghĩa để bạn quyết định tốt hơn.
