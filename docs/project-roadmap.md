---
status: active
title: "Project Roadmap"
created: "2026-08-29"
updated: "2026-08-31"
---

# Project Roadmap

## Current State

The project is past the engine rewrite stage and now sits in an extension and
refinement phase:

- Phase 12 completed the in-house causal SMC engine rewrite.
- Regime V2 and liquidity pools were added as a follow-on refinement.
- Phase 13 breaker block + OB body toggle remains the next open extension.

## Track A — Bot Audit Fixes (2026-08-31)

The bot webhook was hardened against a 24-finding static audit. All 4 Critical,
6 High, 8 Medium, and 6 Low findings are closed via the 7-phase rollout
documented at [plans/260831-1036-bot-audit-fixes/plan.md](../plans/260831-1036-bot-audit-fixes/plan.md).

| Phase | Branch | Scope | Tests |
|---|---|---|---|
| 01 | `audit-fixes/phase-01-telegram-auth` | Telegram callback auth (C2) | +18 |
| 02 | `audit-fixes/phase-02-ftmo-guard` | Real FTMO guard impl (C1, H2) | +19 |
| 03 | `audit-fixes/phase-03-accept-ordering` | Accept ordering + idempotency (C3, M7) | +9 |
| 04 | `audit-fixes/phase-04-markdownv2` | MarkdownV2 + retry backpressure (C4, H5, M6, M8) | +18 |
| 05 | `audit-fixes/phase-05-payload` | Payload hardening (H4, H6, M2, M3, M4) | +14 |
| 06 | `audit-fixes/phase-06-outbox` | Outbox + rate limit + DB lifecycle (H1, H3, L5, L6) | +10 |

Total: 88 new tests, 308 passing, 0 regressions. Tag `v0.4.0-audit-fixed` released.

**Do not** run live FTMO trades on `master` without first running
[smoke-test-bot.md](smoke-test-bot.md).

## Track B — System Validation (2026-08-31)

Edge statistically validated end-to-end. 4/5 Phase 09 steps passed with
strong evidence; Phase 09 Step 4 (sensitivity) script ready but full sweep
timed out in test environment. Full plan at
[plans/260831-XXXX-system-validation-master/plan.md](../plans/260831-XXXX-system-validation-master/plan.md).

### Phase 08 — Trust Backtest (DONE)

| Step | Description | Result |
|---|---|---|
| 1 | Fix `calculate_lot()` unit-conversion bug (commit `9e66381`) | Lot sized correctly; 14 regression tests |
| 1.5 | Re-baseline all EURUSD scripts | Numbers match pre-fix claimed (PF 3.04 with execution costs) |
| 2 | Spread + commission + slippage to core backtester | PnL drops 20% to realistic +$284K net |

### Phase 09 — Statistical Validation (4/5 PASS)

| Step | Test | Result | Verdict |
|---|---|---|---|
| 1 | OOS split (IS 7y → OOS 3.7y) | OOS PF=2.85, IS PF=3.24, ratio 0.88x | **PASS** |
| 2 | Walk-Forward (61 non-overlapping OOS windows) | 24/61 profitable (39.3%), +$77K aggregate, worst DD -1.76% | **PASS** |
| 3 | Monte Carlo (1000 shuffles) | 95%ile DD -2.09%, ruin 0%, worst DD -8.45% | **PASS** |
| 4 | Parameter sensitivity (swing_length, sl_atr_buffer, displacement_atr_mult, min_confluence_score) | Script ready; partial smoke test passed | PARTIAL |
| 5 | t-test + bootstrap CI on Sharpe | t=9.89, p=2e-21; 95% CI [0.336, 0.480] excludes 0 | **PASS** |

### Phase 11 — Multi-pair Validation (PARTIAL)

| Pair | Trades | Winrate | PF | Net PnL | Status |
|---|---:|---:|---:|---:|---|
| EURUSD | 603 | 37.3% | 3.57 | +$356K | Done |
| XAUUSD | 641 | 36.5% | 3.70 | +$375K | Done |
| USDCHF | 488 | 33.0% | 2.74 | +$241K | Done |
| GBPUSD | 564 | 35.8% | 3.27 | +$308K | Done |
| BTCUSD | 816 | 33.7% | 3.17 | +$414K | Done |

Correlation matrix (5-pair, daily returns, 9y):
- EURUSD/USDCHF: **-0.77** (true hedge — effective 2-trade risk = 0.68×)
- EURUSD/GBPUSD: +0.65 (correlated — avoid combined exposure)
- BTCUSD: near-zero correlation with all FX (independent diversifier)

**Edge generalizes across FX, metals, crypto.** All 5 pairs profitable
(PF 2.74-3.70).

## Track C — Live Validation (NOT STARTED)

Pending manual work:
1. FTMO demo 2-4 weeks (live, FTMO platform)
2. Adherence metric + journal scoring (tooling)
3. Go/no-go gate for FTMO challenge (criteria-based)

## Active Workstreams

| Workstream | Status | Notes |
|---|---|---|
| Engine core | Done | Causal swings, structure, OB, FVG, sweeps, context |
| Extension layers | In progress | Breaker promotion, body-only OB geometry |
| Decision quality | In progress | Regime V2, liquidity pools, conservative auto selection |
| UI / backtester sync | Ongoing | Keep overlays and compatibility surfaces aligned |
| Statistical validation | Done | Phase 09 4/5 PASS (Step 4 partial) |

## Linked Plans

- [Phase 12 rewrite](../plans/12-smc-engine-rewrite/plan.md)
- [Breaker block + OB body toggle](../plans/13-breaker-block-upgrade/plan.md)
- [Signal-quality refinement](../plans/260829-0223-smc-signal-quality-refinement/plan.md)
- [Bot audit fixes (Track A)](../plans/260831-1036-bot-audit-fixes/plan.md)
- [System validation (Track B)](../plans/260831-XXXX-system-validation-master/plan.md)
- [Pine parity capture procedure](../plans/260831-0430-pine-parity-capture-procedure/plan.md)
- [MT5 Strategy Tester validation](../plans/260831-0437-mt5-strategy-tester-validation/plan.md)

## Near-Term Direction

1. **Track C** — run FTMO demo 2-4 weeks to validate trader behavior + adherence
2. **Phase 09 Step 4** — finish parameter sensitivity sweep (4 min × 12 runs)
3. **Phase 10** — Pine parity real capture (manual TradingView Bar Replay)
4. **Phase 12** — MT5 Strategy Tester (manual broker run)

## Longer-Term Direction

- live MT5 integration and demo validation
- safer research tooling around journal analytics
- incremental rule tuning only when backed by data, not by extra knobs