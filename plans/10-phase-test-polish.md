# Phase 9 — Test + Polish

## Mục tiêu

Verify toàn bộ app hoạt động đúng, fix bug, đảm bảo kết quả backtest realistic.

## Task

### Test EURUSD M15

1. Chạy backtest 2 năm với default config
2. Verify:
   - Số trade ≥ 50
   - Winrate 45–60%
   - Profit factor > 1.3
   - Max DD < 4%
   - Không có exception

### Test XAUUSD M15

- Spread/slippage XAU cao hơn → winrate có thể thấp hơn EUR
- Verify vẫn profitable hoặc flat

### Test BTCUSD M15

- Volatility cao, SL phải rộng
- Funding fee cần add nếu trade perpetual (skip cho spot/backtest)
- Verify winrate hợp lý

### Walk-forward mini test

- Train: 2023-01 → 2023-12
- Test: 2024-01 → 2024-06
- So sánh metrics train vs test
- Nếu test << train → overfit warning

### Bug thường gặp

| Bug | Fix |
|---|---|
| Look-ahead bias: dùng signal bar i cho entry bar i | Shift signal 1 bar trước khi dùng |
| Số trade = 0 | Check signal threshold quá cao, giảm min_score xuống 3 |
| Equity curve phẳng | Check pip_value đúng cho từng pair |
| DD âm | Check SL > 0 và đúng hướng |
| Partial TP không đóng | Check logic close_pct cộng dồn |
| Daily guard không reset | Check reset_daily() đúng ngày |

### Polish

- Thêm tooltip giải thích từng slider
- Thêm warning khi winrate < 40% (có thể overfit hoặc chưa đủ filter)
- Thêm export button cho CSV
- Thêm so sánh equity curve giữa các lần backtest

## Acceptance criteria

- [ ] 3 pairs đều backtest ra kết quả hợp lý
- [ ] Walk-forward test không bị suy giảm > 30% so với in-sample
- [ ] Không có bug nghiêm trọng
- [ ] Đủ documentation trong code
- [ ] README có hướng dẫn sử dụng từng tính năng
