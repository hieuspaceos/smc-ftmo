---
date: 2026-08-29
session: smc-signal-quality-regime-v2
plan: plans/260829-0223-smc-signal-quality-refinement
---

# Journal: 2026-08-29 — SMC signal quality regime V2 + liquidity pools

## Context

Refine SMC decision quality without growing the parameter surface. Weak spot:
`regime_mode=auto` used price-path metrics only (move ratio + choppiness) and
did not improve selection vs baseline on the shipped EURUSD M15 set.

## What Happened

- Replaced price-path-only regime auto with structure-aware BOS / CHoCH / sweep
  density classification (`trending` / `ranging` / `mixed`).
- Removed hash-sampled breaker inclusion; auto is now regime-gated and
  conservative. `regime_mode=off` baseline path preserved.
- Added `src/smc_engine/liquidity_pools.py` for causal EQH/EQL clustering:
  fixed internal tolerance, second-member confirmation, reclaim-only sweep.
- Fed EQH/EQL pool density into regime explanation and ranging pressure without
  adding any new UI knobs.
- Verification: **209 tests** passed; smoke checksum **unchanged**; shipped
  EURUSD M15: `auto` = `off` = **32** trades, `on` = **21** trades; pool layer
  detects **495** confirmed pools and the app explanation surfaces pool density.

## Reflection

Structure-aware densities were the right minimal cut — decision context, not
more signal families. Hash-sampled breakers were noise dressed as coverage.
The EQH/EQL layer was worth adding only once it stayed pure, causal, and
non-configurable from the UI.

## Decisions Made

| Decision | Rationale | Impact |
| --- | --- | --- |
| Ship structure-aware regime V2 | Price-path auto misclassified; BOS/CHoCH/sweep match SMC | Auto is conservative and explainable |
| Drop hash-sampled breaker inclusion | Sampling ≠ evidence; auto must be regime-gated | Fewer false breaker paths under auto |
| Add causal EQH/EQL pool layer | Equal-level liquidity is real structure, not a random knob | Richer ranging context with no new UI surface |
| Expose pool density only through explanation | User can compare modes immediately without tolerance tuning | Maintains narrow decision contract |

## Next Steps

- Measure whether EQH/EQL density helps on other pairs / years.
- Keep deferred items deferred unless they improve decisions without adding knob-sprawl.
