# RULE BOOK — Manual Trade 8 Tuần

> Luật chơi khi trade tay. Lớp tín hiệu khớp `config.yaml` + `src/smc_engine/`.
> 3 dòng đóng băng 8 tuần **siết hơn bot** — không đổi slider engine.
> Thiếu khối A hoặc score < 4 = không vào lệnh. Không ngoại lệ.
>
> **Milestone 2026-08-30**: Backtest parity giữa Python engine và Pine v6 indicator
> hoàn thành (v1.2). Rule book mapping đầy đủ ở `docs/rulebook-pine-mapping.md`.
> Pine script chạy ổn trên TradingView Premium với 4 display presets.
**Câu nhớ:** Bias trước, structure sau, OB rồi mới nhìn sweep. Liquidity là bối cảnh, không phải lệnh.

Setup học mặc định (khớp app, **đóng băng 8 tuần**):

- `bias_mode = strict` (D + H4) — không `h4_only` / `any`
- `regime_mode = off` — không breaker, không `auto`
- OB zone = `full` (high–low)
- Displacement `1.5× ATR`, SL buffer `0.2× ATR`
- Cặp sample: **EURUSD only**
- Không thêm slider, không thêm khái niệm giữa chừng

**3 dòng freeze (overlay tay, bot không có):**

1. Sweep chỉ cộng điểm khi wick pierce **≥ 0.25× ATR** và close reclaim. Engine overlay vẫn vẽ từ `0.05× ATR` — râu sát tick **không** tính sweep sạch.
2. NO TRADE nếu SL (kèm buffer) **> 1.2× ATR(M15)**, hoặc mức 2R đụng tường thanh khoản HTF gần nhất (EQH/EQL / swing D hoặc H4) cùng hướng lệnh.
3. 8 tuần chỉ EURUSD. XAU để sau. BTC không tính sample.

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
| Kỳ vọng R | ~2.9R nếu chạy hết ladder 40/30/30 tại 2R/3R/4R. 2.5R chỉ là mốc nghĩ trước khi vào. |

**Partial TP** (engine):

- 40% tại 2R → move SL về BE
- 30% tại 3R → giữ SL ở BE
- 30% tại 4R

### Exit mode: scale-in (alternative, milestone 2026-08-31)

Config opt-in: `strategy.exit_mode = "scale_in"` (default `ladder`). Scale-in
chỉ dùng cho bot và backtest khi nghiên cứu. Khi trade tay 8 tuần này vẫn
giữ ladder 40/30/30 — không áp scale-in lên chart.

**State machine (long, mirror cho short):**

1. Entry: leg1 = 1.0 lot @ OB top, SL = ob_bottom - 0.2× ATR (1R)
2. Hit 2R: đóng 0.5 lot leg1 → lock +1R; mở leg2 = 0.5 lot @ 2R; move SL leg1
   rem → entry (BE)
3. Hit 4R: đóng leg1 rem @ 4R (+2R) + đóng leg2 @ 4R (+1R) = +4R tổng
4. Cascade về entry: leg1 rem = 0 (BE) + leg2 = -1R → 0R tổng
5. SL trước 2R: -1R (leg2 chưa mở)

**Risk profile scale-in (backtest EURUSD 2016-2026, 1326 lệnh):**

| Metric | Ladder | Scale-in |
|---|---|---|
| Avg R | +0.684R | **+0.824R** |
| Profit factor | 1.88 | **2.74** |
| Max DD | 5.69% | **3.21%** |
| Winrate | 52.1% | 32.4% |
| Total PnL | $488,908 | **$601,150** |

Scale-in tăng +23% PnL, giảm -44% DD so với ladder, nhưng giảm winrate vì
trade hit 4R (đếm win) ít hơn trade cascade BE (không tính win/loss). Triết
lý scale-in: **R/R và payoff quan trọng hơn winrate**.

**Overshoot-safe:** PnL luôn cap tại đúng exit price, không tính theo bar
close. SL gap-through không over-debit; TP overshoot không over-credit. Đã
regress 11 unit test.

**Design B (optional, không dùng production):** leg2 chốt 50% tại 3R (TP1
intermediate), move SL leg2 rem → 3R để lock profit. Backtest Design B cho
winrate cao hơn (38% vs 32%) nhưng PnL thấp hơn (-3.2%) do giảm max profit
ở hit-4R. Giữ làm feature flag (`leg2_tp1_r: null` = Design A).

**SL:** ngoài cạnh OB + `0.2× ATR` buffer. Không đặt SL sát mép zone.

---

## 2. Thứ tự đọc chart (bắt buộc)

1. D rồi H4 — lấy bias.
2. H1 — nhịp trung gian, không phải cổng vào lệnh.
3. M15 — structure, OB, entry.
4. Sweep / FVG — xác nhận thêm.
5. EQH / EQL — bối cảnh liquidity.
6. Breaker — chỉ khi đang nghiên cứu (`regime_mode=on`).

D và H4 trái nhau mạnh → đứng ngoài. Không ép M15.

---

## 3. Setup — cái nào bắt buộc, cái nào không

### Bắt buộc (thiếu 1 cái = NO TRADE)

| Lớp | Rule engine |
|---|---|
| Bias | D + H4 cùng hướng với lệnh |
| Displacement | Nến `(high-low) > 1.5× ATR(14)` tại/near cú BOS |
| BOS | Close phá swing cùng chiều trend. Wick không tính |
| OB active | Zone còn sống, chưa invalidated, còn first-test |
| Score | ≥ 4/5. Qua cổng trên đã có disp + bias + first-test = 3. Điểm 4 lấy từ sweep **hoặc** P/D |

### Điểm cộng (không bắt buộc từng cái; thiếu cả hai → 3/5 → NO TRADE)

- Sweep sạch (pierce ≥ 0.25× ATR + close reclaim)
- Premium / discount đúng phía

### Bối cảnh (không được vào lệnh vì chúng)

- FVG
- EQH / EQL liquidity pool
- Breaker
- CHoCH một mình

---

## 4. Bias

Default `strict`:

- D bull + H4 bull → chỉ LONG
- D bear + H4 bear → chỉ SHORT
- lệch nhau, hoặc 1 bên neutral → NO TRADE

D/H4 bull-bear **theo BOS gần nhất của engine**, không theo cảm giác nến.

Bias là hướng ưu tiên, không phải lệnh. Không dùng M15 để “sửa” H4.

`h4_only` / `any` tồn tại trong app — không dùng khi học 8 tuần này.

---

## 5. Structure: BOS vs CHoCH

Engine phá structure bằng **close**, không bằng wick.

| Event | Nghĩa | Hệ quả trade |
|---|---|---|
| **BOS** | Phá swing **cùng chiều** trend | Tạo OB. Đây là trigger zone |
| **CHoCH** | Phá swing **ngược** trend | Đảo character. **Không tạo OB** |

Không gộp BOS và CHoCH thành 1 tín hiệu.

Sau CHoCH: đứng ngoài OB cũ. Chỉ vào lại khi có BOS mới cùng chiều bias.

Đây là lựa chọn học: muộn một nhịp, ít vẽ zone trên cú đảo nhiễu. **Không** biến thành “CHoCH không bao giờ đáng trade” — breaker/CHoCH là `regime_mode`, đóng trong 8 tuần này.

---

## 6. Order Block + OB break

OB = nến ngược chiều **cuối cùng trước BOS**, zone mặc định = `[low, high]` nến đó.

Engine chỉ sinh OB từ **BOS** + displacement tại bar BOS hoặc bar ngay trước. CHoCH không đẻ OB.

### Lifecycle

```
BOS + displacement
  → OB active từ bar BOS (test/invalidate từ bar sau)
  → First touch: wick vào zone
  → OB break (invalidation): close xuyên cạnh kia
  → Zone chết, không vào nữa
  → (nghiên cứu) CHoCH đến sau → breaker chiều ngược
```

**OB break / invalidation:**

- Bullish OB chết khi `close < bottom`
- Bearish OB chết khi `close > top`
- Wick xuyên chưa đủ để giết zone; close xuyên mới chết
- OB chết = không trade. Không “hy vọng nó còn giữ”

**First-test:**

- Chỉ lấy lần chạm đầu
- Sau first-touch, backtester bỏ zone đó dù chưa invalidate
- First-test = 1 điểm confluence, không phải lý do vào một mình

**Entry / SL:**

- LONG: entry = `ob_top`, SL = `ob_bottom - 0.2×ATR`
- SHORT: entry = `ob_bottom`, SL = `ob_top + 0.2×ATR`
- Giá phải gần mép OB (trong `1.5× ATR`). Không chase xa zone
- Freeze: `SL_distance > 1.2× ATR(M15)` → NO TRADE (zone béo, 2R quá xa)
- Freeze: mức 2R nằm trong/qua tường thanh khoản HTF gần nhất cùng hướng → NO TRADE

**OB body mode:** `full` = cả râu (học mặc định). `body` = chỉ thân nến, zone hẹp hơn. Không đổi origin / BOS / invalidation.

---

## 7. Displacement

- `(high - low) > 1.5 × ATR(14)`
- Bắt buộc cho score và cho việc BOS được quyền sinh OB
- Không đủ để vào lệnh một mình

---

## 8. Sweep (xác nhận, không bắt buộc)

Sweep = quét liquidity **rồi close reclaim**. Reclaim là điều kiện đúng. Biên độ mới là chỗ siết.

**Engine overlay** (bot, không đổi slider): wick ≥ `0.05× ATR` + reclaim. Ngưỡng này trên EURUSD M15 thường < 1 pip — gần như mọi râu ló qua swing đều bị vẽ. Đừng tưởng bot đang đòi cú săn thanh khoản khung lớn.

**8 tuần tay — chỉ cộng 1 điểm sweep khi đủ cả 2:**

- Bullish: wick dưới swing low **≥ 0.25× ATR**, close **trên** level
- Bearish: wick trên swing high **≥ 0.25× ATR**, close **dưới** level
- Wick sát tick / chỉ ≥ 0.05× ATR = **không** cộng điểm, dù overlay bot có vẽ
- Close không reclaim = không phải sweep
- Bar quét cả 2 phía = bỏ
- Mỗi swing chỉ tính 1 sweep

Thiếu sweep vẫn vào được nếu score ≥ 4 (P/D + first-test). Không hạ ngưỡng 0.25 giữa chừng.

---

## 9. FVG — không phải entry zone

- Gap 3 nến: bullish `high[i-2] < low[i]`, bearish ngược lại
- Overlay xác nhận imbalance
- Giá fill FVG **không** mở lệnh
- Không thay OB. Checklist cũ “OB hoặc FVG” là sai

---

## 10. Premium / Discount

- Long ưu tiên discount (rẻ hơn equilibrium)
- Short ưu tiên premium (đắt hơn)
- P/D theo **range H4 đang dùng để bias**. Không đổi công thức giữa tuần
- 1 điểm confluence, không phải trigger. Thiếu P/D vẫn vào nếu đã có sweep ≥ 0.25; thiếu cả P/D lẫn sweep → NO TRADE

---

## 11. Liquidity pools (EQH / EQL)

Engine gom swing gần nhau (`~0.15×ATR`), confirm khi có **2 member**.

- EQH = cụm đỉnh bằng nhau (thanh khoản phía trên)
- EQL = cụm đáy bằng nhau (thanh khoản phía dưới)
- Sweep pool cũng cần reclaim close; breakout xuyên close qua level **không** gọi là sweep

Dùng để:

- biết chỗ giá có thể quét
- đọc ranging vs trending

Không dùng để:

- vào lệnh vì “có EQH/EQL”
- thay BOS / OB

---

## 12. Breaker — lớp nghiên cứu, không phải setup học

Breaker = OB **đã chết**, rồi **CHoCH đến sau** mới đổi vai.

Thứ tự bắt buộc:

1. OB invalidated (close xuyên)
2. CHoCH activation **sau** invalidation (không cùng lúc, không trước)
3. Origin OB không quá cũ (`promotion_lookback_bars = 50`)
4. 1 OB chỉ flip 1 lần

Khi học 8 tuần:

- `regime_mode = off`
- không vào breaker
- không coi breaker tốt hơn OB
- không bật `on` / `auto` “cho vui”

`auto` không phải nút thần kỳ. Đóng băng. Sau 8 tuần mới được mở nghiên cứu.

---

## 13. Confluence Score (tối thiểu 4/5)

| Yếu tố | Điểm | Bắt buộc? |
|---|---|---|
| Displacement | 1 | Có |
| Bias aligned (D+H4) | 1 | Có |
| First test | 1 | Có (cổng OB active 8 tuần) |
| Sweep clean (≥ 0.25× ATR + reclaim) | 1 | Không |
| Premium/discount đúng phía | 1 | Không |

**Score ≥ 4.** Qua cổng bắt buộc luôn có disp + bias + first-test = 3. Điểm 4 = sweep **hoặc** P/D. Thiếu cả hai → 3/5 → NO TRADE.

Thiếu displacement hoặc bias → cấm vào, kể cả khi điểm kia đủ.

Breaker + CHoCH có thể thế điểm sweep trong code confluence, nhưng path học (`regime_mode=off`) **không dùng**. Đừng tự cộng điểm breaker.

---

## 14. Session Filter

| Session | Giờ (NY/EST) | Trade? |
|---|---|---|
| Asia | 19:00 - 02:00 | ✗ |
| London | 02:00 - 05:00 | ✓ |
| New York | 07:00 - 10:00 | ✓ |
| Overlap (LN+NY) | 08:00 - 10:00 | ✓ |

Ngoài session trên = không trade tay. Tránh 15 phút đầu London open (spread).

London 02:00–05:00 EST là **cửa hẹp** (cắt nửa phiên London thật). Cố ý: ít lệnh, sạch hơn. Đừng kỳ vọng tần suất full London.

Bot backtester hiện **không lọc session** — đây là kỷ luật tay, vẫn bắt buộc.

---

## 15. Cặp & Khung

**Cặp 8 tuần:** EURUSD only. XAU để sau 8 tuần. BTC **ngoài sample** (session/ATR/sweep không hợp bộ luật này).

Config app vẫn liệt XAU/BTC — không trade chúng trong journal 8 tuần.

**Khung:**

- D: bias dài hạn (không trade)
- H4: bias trung hạn (bắt buộc align với D)
- H1: nhịp trung gian
- M15: BOS / OB / entry

Workflow: D → H4 → H1 → M15.

---

## 16. Checklist trước lệnh (in ra, dán cạnh monitor)

Hai khối. **Không** áp “bất kỳ ✗ = cấm” lên điểm cộng.

```
KHỐI A — CẤM NẾU THIẾU (bất kỳ ✗ = NO TRADE)
[ ] D và H4 cùng hướng? (strict, theo BOS engine, không cảm giác nến)
[ ] Displacement gắn BOS? (candle > 1.5× ATR)
[ ] M15 BOS cùng chiều, close-break (không phải wick)?
[ ] OB từ BOS đó, không từ CHoCH?
[ ] OB còn sống, chưa close xuyên?
[ ] Còn first-test?
[ ] Giá gần mép OB ≤ 1.5× ATR, không chase?
[ ] SL ngoài OB + 0.2× ATR và SL ≤ 1.2× ATR(M15)?
[ ] 2R không đụng tường HTF gần nhất cùng hướng?
[ ] Cặp = EURUSD?
[ ] Session london / ny / overlap, không phải 15 phút đầu London?
[ ] Risk 0.55% = $___
[ ] Chưa hit 3 trades hôm nay
[ ] Chưa hit 2R daily loss
[ ] Không breaker / h4_only / auto?
[ ] Giải thích setup được 1 câu?

KHỐI B — CHẤM ĐIỂM (cần ≥ 4; qua A đã có disp + bias + first-test = 3)
[ ] Sweep ≥ 0.25× ATR + reclaim  (+1)   overlay 0.05 không đủ
[ ] P/D đúng phía (range H4)     (+1)
[ ] First-test                    (+1, luôn có nếu qua A)

Score: __/5
Thiếu sweep được nếu P/D có (hoặc ngược lại).
Thiếu cả hai → 3/5 → NO TRADE.

→ A đủ ✓ và score ≥ 4: VÀO LỆNH
→ A có ✗, hoặc score < 4: NO TRADE
```

---

## 17. Position Size

```
Risk ($) = Account × 0.55% = $100,000 × 0.0055 = $550
SL (pips) = |entry - SL| trên chart
Position size (lots) = $550 / (SL pips × pip value)

EURUSD: 1 lot = $10/pip → 0.5 lots nếu SL 11 pips
```

Tính trước khi vào. Ghi journal.

---

## 18. Trade Management

**Engine (phải theo để khớp bot):**

- TP1 40% tại 2R: chốt, SL → BE
- TP2 30% tại 3R: chốt, SL giữ BE
- TP3 30% tại 4R: chốt hết
- SL hit: đóng phần còn lại

**Không có trong engine** — đừng ghi vào replay như “bot exit”:

- thoát hết vì CHoCH / structure shift trước TP1
- trail SL theo BOS mới sau TP1

Nếu tự thêm 2 rule trên khi trade tay, ghi rõ là **overlay tay**, không phải luật bot.

---

## 19. Cấm

- Vào vì thấy OB, sweep, FVG, EQH/EQL, hoặc breaker một mình
- Trade OB đã invalidated
- Coi CHoCH = BOS, coi FVG = entry zone
- Coi breaker tốt hơn OB
- Dùng `auto` / `h4_only` / breaker giữa 8 tuần
- Đổi slider hoặc nới 0.25 / 1.2 ATR vì chán ít lệnh
- Trade XAU / BTC trong sample 8 tuần
- Revenge / FOMO / ngoài session / thiếu score

---

## 20. Những lỗi hay mắc (cập nhật mỗi tuần review)

_Cập nhật sau mỗi Chủ nhật_

- [ ] Để thêm tuần 1
- [ ] Để thêm tuần 2
- [ ] ...

---

## 21. Cam kết

Tôi cam kết:

- Trade theo rule book này, không cảm tính
- Giữ 3 dòng freeze 8 tuần; không nới ngưỡng, không bật h4_only/breaker
- Ghi journal trong 30 phút sau khi đóng lệnh
- Review mỗi Chủ nhật
- Không trade nếu khối A thiếu hoặc score < 4
- Từ ngày ký đến Chủ nhật tuần 8: **không thêm dòng** vào rule book này

Ký tên: _________________ Ngày: ___________
