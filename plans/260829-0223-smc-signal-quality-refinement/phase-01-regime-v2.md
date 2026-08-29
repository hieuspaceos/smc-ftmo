# Phase 01 — Regime Detection V2

**Status:** completed

## Why this phase exists

Current `regime_mode=auto` used price-path metrics only:

- directional move ratio
- choppiness

That was too weak for SMC because price can trend structurally while still
looking choppy candle-to-candle. On shipped EURUSD M15, auto mis-classified as
`ranging` and behaved like forced `on`.

## Implemented refinement

Replaced pure price-path classification with a structure-aware classifier in
`src/smc_engine/regime.py` using:

- BOS density per lookback window (up to 600 bars)
- CHoCH density per lookback window
- sweep density per lookback window
- continuation vs ranging-pressure blend → `trending` / `ranging` / `mixed`
- sparse-structure fallback to the older price-path heuristic (still conservative)

## Required outputs (delivered)

| Label | Structural read | Weights |
|---|---|---|
| `trending` | many same-direction BOS, low CHoCH/range pressure | OB 1.0 / breaker 0.0 |
| `ranging` | frequent CHoCH and sweeps, weak directional persistence | OB 0.0 / breaker 1.0 |
| `mixed` | neither clean trend nor clean range | OB 1.0 / breaker 0.0 |

`RegimeState` also exposes `bos_density`, `choch_density`, `sweep_density`,
`dominant_direction`, and a plain-language `explanation`.

## Constraints held

- no new engine settings beyond existing `regime_mode`
- `regime_mode=off` preserved
- smoke checksum on baseline path preserved
- replaced the old auto heuristic cleanly rather than stacking a second layer
- UI still only selects off/on/auto

## Acceptance — met

- `auto` no longer equals `on` on shipped EURUSD M15
  - `detect_regime` → `mixed`, `breaker_weight=0`
  - auto = **32 trades** (matches off)
  - forced on = **21 trades**, PF **2.7475**
- `tests/test_smc_regime.py` extended; full suite **209 passed**
- docs explain the classifier in a short table (`docs/smc-engine-extensions.md`)

## Verification anchors

- full suite: 209 passed
- smoke checksum:
  `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`
- Phase 02 later added EQH/EQL density on top without changing these baseline results
