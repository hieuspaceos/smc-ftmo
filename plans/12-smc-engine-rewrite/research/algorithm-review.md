---
title: "SMC Algorithm and Plan Review"
status: reviewed
created: "2026-08-27"
---

# SMC Algorithm and Plan Review

## Summary
DIY implementation remains the recommended approach. No maintained Python package provides the required causal, timestamp-aligned contracts for swings, BOS/CHoCH, sweeps, OB, FVG, context, and MTF bias.

## Library Findings
| Option | State | Decision |
|---|---|---|
| `smartmoneyconcepts==0.0.27` | Current dependency; index/NaN/API issues observed locally | Remove after gated cutover |
| rafalsza fork | Useful reference implementation; stale/version skew | Source reference only |
| jaydai81 fork | External/unverified ZigZag dependency; stale | Reject as runtime dependency |
| pandas-ta / TA-Lib | Indicators/pivots only; no complete ICT engine | Optional primitives, unnecessary |

## Locked MVP Algorithms
| Concept | Baseline |
|---|---|
| Swings | Williams/fractal left/right pivot, activation at `pivot+right` |
| ATR | True range rolling mean, causal NaN warmup |
| Range expansion | `(high-low) > multiplier×ATR` |
| BOS | Close breaks latest unconsumed activated swing in current/neutral trend |
| CHoCH | Close breaks opposite swing relative to prior trend |
| Sweep | Wick crosses activated swing and close reclaims/rejects; one-shot per level |
| OB | Last opposing candle before BOS; activation at BOS close; touch/invalidation timestamps |
| FVG | Three-candle strict gap; activation at third candle close; later touch/full-fill lifecycle |
| Bias | Structure trend: `bull`/`bear`/`neutral` |
| Premium/Discount | Latest valid activated structure dealing range; neutral when unavailable |

## Critical Review Corrections
1. Encode origin and activation timestamps in every event.
2. Query zone state as-of historical timestamp; never use terminal mitigation boolean for entries.
3. Use latest completed HTF bar at or before M15 timestamp.
4. Preserve exact `SMCSignals` signature, generic `Signal` fields, six keys, and `get_smc_overlays()`.
5. Replace real-market count/PF gates with synthetic/golden/property causal oracles.
6. Keep breakers, body/volume filters, ZigZag variants, and tuning outside MVP.
7. Use staged gates; do not remove dependency before UI behavior passes.

## Rejected Review Claims
- `equity_curve` is not duplicated on normal bars: one append exists for NaN early-continue and one for normal completion, not two for the same execution path.
- `df.iloc[:searchsorted(day_end, side="left")]` does not include the next day's first bar. The real causality issue is assigning a same-day completed D/H4 state to earlier M15 bars; Phase 8 fixes this with completed-bar as-of alignment.

## Sources
- https://github.com/rafalsza/smartmoneyconcepts/blob/master/smartmoneyconcepts/smc.py
- https://github.com/jaydai81/smartmoneyconcepts/blob/master/smartmoneyconcepts/SMC.py
- In-repo contracts: `src/smc_signals.py`, `src/bias_detector.py`, `src/backtester.py`, `src/premium_discount.py`, `app.py`.

## Unresolved Questions
None for MVP. Optional upgrades require separate approval after cutover metrics are available.
