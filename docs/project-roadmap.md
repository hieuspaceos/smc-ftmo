---
status: active
title: "Project Roadmap"
created: "2026-08-29"
updated: "2026-08-29"
---

# Project Roadmap

## Current State

The project is past the engine rewrite stage and now sits in an extension and
refinement phase:

- Phase 12 completed the in-house causal SMC engine rewrite.
- Regime V2 and liquidity pools were added as a follow-on refinement.
- Phase 13 breaker block + OB body toggle remains the next open extension.

## Audit Fixes (2026-08-31)

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

Total: 88 new tests, 303 passing, 0 regressions.

**Do not** run live FTMO trades on `master` without first running
[smoke-test-bot.md](smoke-test-bot.md).

## Active Workstreams

| Workstream | Status | Notes |
|---|---|---|
| Engine core | Done | Causal swings, structure, OB, FVG, sweeps, context |
| Extension layers | In progress | Breaker promotion, body-only OB geometry |
| Decision quality | In progress | Regime V2, liquidity pools, conservative auto selection |
| UI / backtester sync | Ongoing | Keep overlays and compatibility surfaces aligned |

## Linked Plans

- [Phase 12 rewrite](../plans/12-smc-engine-rewrite/plan.md)
- [Breaker block + OB body toggle](../plans/13-breaker-block-upgrade/plan.md)
- [Signal-quality refinement](../plans/260829-0223-smc-signal-quality-refinement/plan.md)

## Near-Term Direction

1. Finish the breaker/body upgrade without breaking the base OB lifecycle.
2. Keep docs synchronized with actual smoke output and test counts.
3. Preserve baseline `regime_mode=off` behavior while refining `auto`.

## Longer-Term Direction

- live MT5 integration and demo validation
- safer research tooling around journal analytics
- incremental rule tuning only when backed by data, not by extra knobs

