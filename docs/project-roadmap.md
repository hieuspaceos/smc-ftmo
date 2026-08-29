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

