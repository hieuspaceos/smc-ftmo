# SMC Signal Quality Refinement — Outcome

**Plan:** `plans/260829-0223-smc-signal-quality-refinement/`  
**Date:** 2026-08-29  
**Status:** completed (Phases 01 + 02)

## Outcome

Regime Detection V2 shipped, then EQH/EQL liquidity pools shipped as a narrow
Phase 02 extension.

The refinement fixed the real gap: `regime_mode=auto` no longer mirrors forced
breakers on the shipped EURUSD path, while baseline `off` and smoke invariants
stay identical.

## What shipped

- `src/smc_engine/regime.py` structure-aware classifier
  - BOS / CHoCH / sweep densities over a recent window
  - labels: `trending` | `ranging` | `mixed`
  - conservative weights: only clean `ranging` sets `breaker_weight=1`
  - plain-language `RegimeState.explanation`
- `src/smc_engine/liquidity_pools.py` pure EQH/EQL layer
  - fixed internal `0.15 × ATR` tolerance
  - confirmation at the second matching swing
  - reclaim-only sweep semantics
  - causal extension: later matching swings cannot rewrite earlier sweeps
- existing `regime_mode` off/on/auto surface reused (no new knobs)
- docs updated: architecture, extensions, verification, plan artifacts

## Verification

| Check | Result |
|---|---|
| Full suite | **209 passed** |
| Smoke checksum | `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a` (unchanged) |
| `regime_mode=off` | 32 trades (baseline preserved) |
| `regime_mode=auto` | 32 trades — `detect_regime` → `mixed`, `breaker_weight=0` |
| `regime_mode=on` | 21 trades, PF **2.7475** |
| EQH/EQL pools | 495 detected on shipped EURUSD M15 |

## Phase 02 outcome

Delivered as a pure structural enrichment layer. It now feeds regime
explanation and ranging pressure, but does not widen the user config surface
and does not destabilize the shipped auto path.

## Docs touched

- `docs/system-architecture.md`
- `docs/smc-engine-extensions.md`
- `docs/smc-engine-module-reference.md`
- `docs/smc-engine-verification.md`
- plan + phase notes under this directory
