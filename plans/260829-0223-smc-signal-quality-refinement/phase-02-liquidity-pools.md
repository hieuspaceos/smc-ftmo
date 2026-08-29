# Phase 02 — EQH / EQL and Liquidity Pools

## Why this phase is optional

This phase should happen only if Regime V2 alone is still not enough.

EQH/EQL adds a real structural concept, but it also introduces another layer of
logic. If Regime V2 already gives a usable `auto` mode, stop before this phase.

## Scope

Add a small pure module that:

- detects equal highs from confirmed swing highs
- detects equal lows from confirmed swing lows
- clusters them into liquidity pools using a fixed ATR-relative tolerance
- marks whether a pool has already been swept

## Intended use

- enrich sweep quality
- improve regime detection
- help manual chart reading

## Constraints

- no raw threshold slider for tolerance in v1
- fixed internal tolerance only
- UI may show pool hits/sweeps, but should not expose many knobs
- do not add another scoring system unless data proves it helps

## Acceptance

- layer is useful for explanation, not just extra drawing
- no regression in current baseline path
- if it adds complexity without improving auto decisions, drop it
