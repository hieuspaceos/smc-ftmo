# Phase 02 — EQH / EQL and Liquidity Pools

**Status:** completed

## Why this phase exists

Regime V2 already fixed the shipped auto-path bug, but EQH/EQL still adds a
real structural concept for:

- richer range-quality explanation
- future sweep-quality research
- cleaner equal-level liquidity context

## Implemented scope

Built `src/smc_engine/liquidity_pools.py` as a small pure module that:

- detects equal highs from confirmed swing highs
- detects equal lows from confirmed swing lows
- clusters them into liquidity pools with a fixed internal `0.15 × ATR` tolerance
- confirms a pool at the **second** matching swing
- marks a pool swept only when price takes the level **and closes back through it**
- keeps sweep causality stable when later matching swings extend the pool

## Integration

- `src/smc_engine/regime.py` now includes EQH/EQL pool density in ranging pressure
- `RegimeState.explanation` reports `EQH/EQL pools ... /100`
- no new user-facing knobs were added

## Acceptance — met

- layer is useful for explanation, not just extra drawing
- baseline path did not regress
- shipped EURUSD path stayed `mixed` / `breaker_weight=0`, so Phase 02 enriched context without destabilizing auto

## Verification anchors

- `tests/test_smc_liquidity_pools.py` added
- focused pool/regime/backtester tests pass
- full suite: **209 passed**
- smoke checksum unchanged:
  `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`
