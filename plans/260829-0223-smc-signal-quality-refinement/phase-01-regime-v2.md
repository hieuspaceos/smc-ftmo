# Phase 01 — Regime Detection V2

## Why this phase exists

Current `regime_mode=auto` uses price-path metrics only:

- directional move ratio
- choppiness

That is too weak for SMC because price can trend structurally while still
looking choppy candle-to-candle.

## Intended refinement

Replace pure price-path classification with a structure-aware classifier using:

- BOS density per lookback window
- CHoCH density per lookback window
- sweep density per lookback window
- optional ATR percentile internally

## Required outputs

The regime layer must explain itself in plain language:

- `trending`: many same-direction BOS, low CHoCH
- `ranging`: frequent CHoCH and sweeps, poor directional persistence
- `mixed`: neither clean trend nor clean range

## Constraints

- do not add more than one new **engine** setting unless absolutely necessary
- preserve `regime_mode=off`
- preserve smoke checksum on baseline path
- do not add a second heuristic layer on top of the current heuristic; replace it cleanly
- UI may expose regime result / mode selection, but the core logic must stay narrow

## Acceptance

- `auto` no longer equals `on` on the shipped EURUSD dataset unless the new
  evidence really says so
- `tests/test_smc_regime.py` is extended, not weakened
- docs can explain the classifier in one short table
