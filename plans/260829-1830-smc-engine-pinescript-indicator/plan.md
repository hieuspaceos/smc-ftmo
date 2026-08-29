---
title: "SMC Engine Pine Script Indicator"
description: "Build one private Pine v6 indicator with a shared causal core and two profiles: Rulebook 8W and Engine Audit."
status: done
branch: "master"
tags: [smc, tradingview, pine-script, causality, parity, rulebook]
blockedBy: []
blocks: []
created: "2026-08-29T18:30:00+07:00"
createdBy: "codex"
source: direct-request
---

# SMC Engine Pine Script Indicator

## Overview

Build one private Pine Script v6 indicator with one shared causal core and two profiles:

- `Rulebook 8W` as the default user-facing decision assistant
- `Engine Audit` as the parity and debug profile

This is a single indicator, not two independent indicators. If a one-script profile later fails profiler limits, the fallback is a private Pine library plus two thin frontends, not a second autonomous indicator.

The target is event parity on the frozen OHLC feed and timeframe, not visual similarity to public SMC scripts.

The indicator must remain readable by default:

- show compact structure state, the selected fresh OB, and manual-gate state
- keep raw swings, displacement, FVGs, sweeps, and liquidity pools behind preset-controlled visibility
- offer a `Recent` display mode that prunes old drawings explicitly

## Product Decisions

1. Use Pine Script v6.
2. Keep one shared causal core for both profiles.
3. Default to `Rulebook 8W`; expose `Engine Audit` as a secondary profile.
4. Do not plan a second independent indicator.
5. Fallback after profiler failure is a private Pine library plus two thin frontends.
6. Never call a state fully actionable when manual account or trade-state gates are unknown; use `chart-qualified`, `watch`, or `blocked`.

## Research Outcome

The port is feasible. Pine v6 supports the state, arrays, user-defined types, boxes, lines, labels, and confirmed higher-timeframe requests needed by the core engine. Exact parity is practical for chart-timeframe events. Python API contracts, unlimited historical lifecycle storage, backtester behavior, and arbitrary full-history queries cannot be copied literally into one Pine script.

See [market comparison and feasibility](./research/smc-market-comparison-and-pine-feasibility.md).

## Locked Decisions

1. Port behavior from this repo only; do not derive rules from third-party scripts.
2. The actual engine has 12 substantive modules: one events contract, seven baseline modules (`swings`, `displacement`, `structure`, `sweeps`, `order_blocks`, `fvg`, `context`), and four extensions (`liquidity_pools`, `breaker_blocks`, `ob_body_mode`, `regime`). `SMCSignals` and the app/backtester adapters are not engine components.
3. Desired parity target is the actual current app/config profile, not the `SMCSignals` constructor default:
   - `config.yaml` sets `swing_length: 10`
   - the app passes that value through
   - effective left/right swing window is `5 / 5`
   - ATR is `SMA(True Range, 14)`
   - displacement is strict `> 1.5`
   - structure buffer is `0`
   - sweep overlay buffer is `0.05`
   - OB lookback is `20`
   - OB expiry is `200`
   - OB cap is `128`
   - OB geometry is full wick
   - FVG expiry is `200`
   - FVG cap is `128`
4. Gate A is baseline parity for the seven baseline modules.
5. Gate B is liquidity-pool parity for the extension layer.
6. Breaker, body mode, and regime exist in Python but are deferred from Pine `Rulebook 8W` v1.
7. Rulebook default is locked to EURUSD M15 only, strict completed D+H4 structure bias, H4 premium/discount, full-wick base OB, no breaker, and no claim of green actionable status when account or trade-state gates are unknown.
8. Rulebook manual gates remain risk `0.55%`, max `3` trades/day, daily loss limit `-2R`, one open position, and spread/news/judgment filters.
9. The indicator does not execute or track an FTMO account reliably; unknown manual gates block a green actionable claim.
10. The selected candidate pipeline must be deterministic:
    linked BOS provenance -> direction matches strict bias -> active and first-test eligible -> no later CHoCH -> proximity -> SL width -> HTF wall -> score -> choose most recent qualifying activation, then nearest edge, then OB id.
11. Do not inherit current Python bugs: displacement-as-sweep, any-direction sweep, M15 P/D, entry-bar displacement, or blindly choosing the last OB.
12. V1 parity target feed is a frozen `FXPRO:EURUSD` M15 sample with metadata and checksum. Do not label local HistData as FXPRO.
13. Current verified test state: full suite `209 passed`; focused SMC suite `191 passed`. Earlier research counts are obsolete.
14. UI has not run yet: no `.pine` file exists now, so current Streamlit screenshots do not validate Pine UI quality. UI quality remains an acceptance target, not a present fact.

## Scope

### In scope

- shared causal core for both profiles
- baseline parity for swings, displacement, structure, sweeps, OB, FVG, and context
- liquidity-pool parity after baseline is stable
- deterministic Rulebook selector and readable chart policy
- MTF/session/alert behavior with confirmed-bar semantics
- frozen-feed parity artifacts and comparator tooling

### Deferred

- strategy execution
- journal and database integration
- breaker, body-mode, and regime behavior in the Pine v1 Rulebook profile
- lower-timeframe reconstruction from intrabars
- public TradingView publication

## Phases
| 1 | [Contract + fixtures](./phase-01-parity-specification-and-fixtures.md) | Done | None |
| 2 | [Causal baseline parity + pools](./phase-02-causal-structure-core.md) | Done | Phase 1 |
| 3 | [Rulebook selector + visual policy](./phase-03-zones-liquidity-and-clean-visuals.md) | Done | Phase 2 |
| 4 | [HTF, alerts, and verification](./phase-04-mtf-alerts-and-parity-verification.md) | Done | Phase 3 |


- Baseline target is exact `7/7` parity for the seven baseline behavior modules.
- Liquidity pools are tracked as `1/4` extension parity after baseline parity is locked.
- Total current module scope for Pine v1 is `8/11` behavior modules excluding the events contract, or `72.7%` of the behavior-module surface.
- Rulebook semantics are a separate gating layer; they are not counted as a new engine module.
- Do not claim profitability.

## Deliverables

- parity fixture exporter
- synthetic and frozen-feed fixture sets
- comparator and mismatch report
- Pine indicator source
- user guide and verification notes
- evidence bundle for screenshots, replay, and profiler output

Required parity artifacts include frozen OHLC plus metadata/checksum, Python
reference output, Pine-captured output, comparator output, and the final evidence
report. Local HistData must never be relabeled as the FXPRO fixture.

No Python engine behavior should change for this port. If parity exposes an engine ambiguity, resolve it in tests or specification before changing either implementation.

## Dependencies

- TradingView Pine Editor with Pine Script v6
- exact symbol, broker feed, timeframe, timezone, and date window recorded for parity runs
- v1 reference symbol/feed: frozen `FXPRO:EURUSD` M15
- project `.venv` for fixture export and Python reference tests
- editable private TradingView script for profiler and Bar Replay checks
- a reproducible method for storing the frozen OHLC sample

## Acceptance Criteria

- [ ] Pine compiles with no errors that affect behavior.
- [ ] Synthetic fixtures match swing, displacement, BOS, CHoCH, OB, sweep, FVG, and pool events exactly.
- [ ] Frozen-feed comparison records event count and timestamp/price mismatches per event type.
- [ ] All Gate A and Gate B outputs have zero algorithm mismatches on identical frozen OHLC.
- [ ] Signals only finalize on confirmed chart bars.
- [ ] Confirmed HTF values use completed-bar semantics and do not repaint after reload.
- [ ] Default Decision view remains readable without raw-event spam.
- [ ] TradingView Profiler shows no execution-limit failures on the agreed EURUSD M15 window.
- [ ] Existing Python engine tests remain green.

## Verification Gates

1. **Specification gate:** fixture schema captures OHLC, per-bar state, events and lifecycles, and diagnostics/rejections.
2. **Core gate:** exact synthetic parity for swings, ATR/displacement, and structure.
3. **Lifecycle gate:** exact synthetic parity for OB, FVG, sweep, and pool ordering.
4. **Market-data gate:** compare frozen `FXPRO:EURUSD` M15 only after feed, timezone, and session are identical.
5. **Realtime gate:** Bar Replay and reload do not move finalized events.
6. **Rulebook gate:** policy fixtures prove every selector gate, tie-break, state transition, and rejection reason.
7. **Usability gate:** the frozen 500-bar window passes the numeric object budgets, screenshot matrix, accessibility check, and first-load comprehension tasks.

## Risks

- Broker-feed differences can create legitimate event differences; do not label them algorithm bugs.
- Pine drawing garbage collection requires explicit pruning and recent/history modes.
- MTF requests can repaint unless confirmed values are offset correctly.
- A single all-feature script can exceed runtime or object limits; preserve module-like sections and bounded arrays.
- Public-script descriptions do not prove implementation details; comparisons remain feature and semantics comparisons unless source is audited.
- Current Streamlit screenshots do not validate Pine UI quality because the Pine file does not exist yet.

## Rollback

The Pine indicator is additive and must not replace the Python engine. If parity fails, keep the last phase that passed and disable later modules by input toggle. No backtester or engine rollback should be required.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
