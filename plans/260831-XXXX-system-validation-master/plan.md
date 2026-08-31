# Master Plan — System Validation (Track B)

> **Track status:**
> - ✅ **Track A DONE** — `260831-1036-bot-audit-fixes` shipped 2026-08-31.
>   7/7 phases merged to master, 308 webhook tests pass, tag `v0.4.0-audit-fixed`.
>   Audit findings C1-C4 + H1-H6 closed (24/24 operational safety items).
> - 🔄 **Track B (this plan)** — validation layer, 0/5 phases done.
> - 📋 **Track C** — live validation, plan TBD after Track B.

> **Critical context:** Track A made the bot **operationally safe** (auth,
> guard, outbox, markdown, payload, smoke) and Track B must prove the **logic
> itself is valid** (realistic execution + statistical edge + parity +
> multi-pair + broker execution). Without Track B, deploying to FTMO live
> means: "safe bot executing unverified logic."
>
> **Update 2026-08-31**: Phase 11 (multi-pair) partially complete —
> EURUSD + XAUUSD + GBPUSD baseline done (commit `acb6dc6`). All 3 pairs
> profitable (PF 3.27-3.70, ROI 308-376%). BTCUSD excluded (only 1000 bars
> sample). Correlation matrix computed — EURUSD/GBPUSD ~0.70 (no
> auto-block, UI warning only per user decision 2026-08-31).
## Mục tiêu tổng thể

Nâng hệ thống từ **"safe bot + profitable backtest"** lên **"validated
trading system đủ tin cậy để nộp FTMO challenge"**:

1. **Track A done:** Bot production-ready. Manual smoke runbook committed
   (`docs/smoke-test-bot.md`).
2. **Track B (this plan):** Backtest realistic (spread/commission/session) +
   statistically validated (WF/OOS/MC/sensitivity) + Pine↔Python parity clean
   + multi-pair smoke + MT5 execution matches Python.
3. **Track C (plan sau):** Live validation — FTMO demo 2-4 tuần + adherence
   metric + go/no-go gate.

## Nguyên tắc

1. **Trust backtest trước khi trust live.** Track A productionized bot;
   Track B validates logic; Track C validates trader. Không nhảy tầng.
2. **Mỗi phase có 1 acceptance test cụ thể** — pass mới move on. Fail = block.
3. **Real data, real execution.** Không mock, không synthetic-only, không
   "backtest overfit để pass test".
4. **Backward compat.** Track B không được break Track A tests (308 webhook
   tests must stay green).

## Dependency graph

```
Track A (DONE — v0.4.0-audit-fixed)
    │
    │  Bot hardened: auth, guard, outbox, markdown, payload, smoke
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Track B — System Validation (this plan)                       │
│                                                              │
│  Phase 08 (Trust Backtest)                                    │
│    ├─ 8.1 verify calculate_lot unit-conversion (30 min)       │
│    ├─ 8.2 add spread + commission to core backtester         │
│    ├─ 8.3 move entry to next-bar-open                        │
│    └─ 8.4 tag trades by real session                         │
│         │                                                     │
│         ▼                                                     │
│  Phase 09 (Statistical Validation)                            │
│    ├─ 9.1 OOS split (2014-2022 IS / 2023-2024 OOS)            │
│    ├─ 9.2 walk-forward analysis                               │
│    ├─ 9.3 Monte Carlo (max DD, ruin%)                         │
│    ├─ 9.4 parameter sensitivity                               │
│    └─ 9.5 t-test + bootstrap CI on Sharpe                     │
│         │                                                     │
│         ▼                                                     │
│  Phase 10 (Pine Parity — REAL capture)                        │
│    └─ execute plans/260831-0430 end-to-end                    │
│         │                                                     │
│         ▼                                                     │
│  Phase 11 (Multi-pair + Regime)                               │
│    ├─ 11.1 verify/extend XAUUSD + BTCUSD data                │
│    ├─ 11.2 multi-pair backtest sweep                          │
│    ├─ 11.3 regime tagging in trade dict                      │
│    ├─ 11.4 regime-tagged metrics                             │
│    └─ 11.5 cross-pair correlation check                      │
│         │                                                     │
│         ▼                                                     │
│  Phase 12 (MT5 Strategy Tester — REAL run)                    │
│    └─ execute plans/260831-0437 Phase 1+ end-to-end          │
└─────────────────────────────────────────────────────────────┘
    │
    │  Track B done: backtest validated, parity clean, MT5 matches
    ▼
Track C — Live Validation (plan riêng)
    ├─ Phase 13: FTMO demo 2-4 tuần
    ├─ Phase 14: adherence metric + journal scoring
    └─ Phase 15: go/no-go gate cho FTMO challenge thật
```

## Danh sách phase

| 11 | Multi-pair + Regime | XAUUSD + BTCUSD + regime metrics | Each pair PF ≥ 1.5; regime split shows which regime produces edge | 1 tuần | 🟡 (partial: 3-pair baseline done, regime tagging pending) |
|---|---|---|---|---|---|
| 08 | Trust Backtest | Backtest realistic (spread, commission, session) | New backtest numbers within ±20% of old; entry at next-bar-open; trades tagged by session | 1 tuần | ⏳ |
| 09 | Statistical Validation | WF + OOS + MC + sensitivity | Walk-forward OOS PF ≥ 2.0; MC ruin% < 5%; sensitivity ±20% parameter survives | 2 tuần | ⏳ |
| 10 | Pine Parity (real capture) | TradingView Bar Replay diff clean | `matches=True` OR all mismatches documented in NOTES.md | 1 tuần | ⏳ |
| 11 | Multi-pair + Regime | XAUUSD + BTCUSD + regime metrics | Each pair PF ≥ 1.5; regime split shows which regime produces edge | 1 tuần | ⏳ |
| 12 | MT5 Strategy Tester (real run) | Broker-side execution matches Python | All 5 metrics within tolerance (PF ±10%, PnL ±15%, DD +1pp, trade count ±5%, 0 rejections) | 1-2 tuần | ⏳ |

**Tổng Track B: ~5-6 tuần.**

## Acceptance criteria cho Track B done

1. `python -m scripts.btest_10y` chạy với config mới:
   - Spread modeled (per-pair, default 0.5 pip EURUSD)
   - Commission modeled (default $3.5/lot/side FTMO)
   - Entry at next-bar-open (không same-bar-close)
   - Session filter từ `config.yaml:active_sessions`
   - Trades tagged với real session + day-of-week
2. `python -m scripts.walk_forward --window-months 6 --step-months 1` ra kết quả
   với OOS PF ≥ 2.0.
3. `python -m scripts.monte_carlo --shuffles 1000` ra max-DD distribution với
   ruin probability < 5%.
4. `python -m scripts.sensitivity --param swing_length --pct 20` ra matrix
   cho thấy PnL không sụp quá 30% khi perturb.
5. `tests/fixtures/pine-parity/<run-id>/NOTES.md` tồn tại, hoặc `matches=True`
   hoặc mọi mismatch có rationale.
6. `output/mt5_strategy_tester_validation_<date>/NOTES.md` tồn tại, tất cả 5
   metrics trong tolerance.
7. XAUUSD + BTCUSD backtests (data tùy khả dụng) đều có PF ≥ 1.5 nếu data
   ≥ 3 năm.
8. **Toàn bộ pytest suite green** (308 webhook tests + backtest tests +
   new validation tests).
9. **Track A tests không regress** — đây là acceptance cứng.

## Risks

- **calculate_lot bug (Phase 08 step 1) confirmed**: nếu fix xong, toàn bộ
  backtest dollar figures trước đó vô nghĩa (PnL scaled 100× off). Cần
  re-run all previous backtest numbers để baseline lại. Estimated 4-6 giờ
- **Multi-pair data** — EURUSD + XAUUSD + GBPUSD có 10 năm M1 data trong
  repo (processed). BTCUSD chỉ 1000 bars sample — excluded from Phase 11.
- **MT5 Strategy Tester modeling**: "Every tick based on real ticks" cần broker
  có 10 năm tick history (không phải broker nào có). Fallback `Every tick`
  widening tolerance.
- **Multi-pair data thiếu** — XAUUSD + BTCUSD chỉ có 2024+ trong repo, không
  đủ 10 năm. Có thể download thêm hoặc accept shorter window.
- **Track A regression risk**: Phase 08-12 touch core backtest + strategy
  code, có thể break Track A's webhook flow nếu coupling không clean.

## Out of scope (Track C)

- FTMO demo run (live)
- Manual trade journaling + adherence scoring
- Trader psychology tracking
- Go/no-go gate logic cho live FTMO challenge

## Status (updated 2026-08-31 after Track A done)
- [ ] Phase 10 — Pine Parity (real capture)
- [x] Phase 11 — Multi-pair + Regime (partial: 3-pair baseline + correlation warning)
- [ ] Phase 12 — MT5 Strategy Tester (real run)

## Next step

1. ✅ **Phase 08 Step 1** — DONE (commit `9e66381`). Bug fix verified.
2. ✅ **Phase 08 Step 1.5** (re-baseline) — DONE. 5 scripts + 3 pairs verified.
3. ✅ **Phase 11 partial** — DONE (commit `acb6dc6`). Multi-pair baseline +
   correlation warning spec in plan.
4. **Next**: Phase 08 Step 2 — spread + commission + slippage to core
   backtester (~2-3 ngày). Will reduce PnL ~25-35% from execution costs.
5. Phase 09 (statistical validation) — sequential after Step 2.
6. Phase 10 (Pine parity real capture) + Phase 12 (MT5 Strategy Tester) —
   can overlap with Track C (manual broker / TradingView work).
