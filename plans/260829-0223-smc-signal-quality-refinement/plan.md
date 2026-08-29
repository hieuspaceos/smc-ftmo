---
title: "SMC Signal Quality Refinement"
description: "Tighten the SMC engine only where current evidence shows real decision-quality gaps, while explicitly rejecting feature growth that would mostly add parameters or UI complexity."
status: completed
priority: P1
branch: "master"
tags: [smc, regime, liquidity, simplification]
blockedBy: []
blocks: []
created: "2026-08-29T02:23:00Z"
createdBy: "codex"
source: direct-request
---

# SMC Signal Quality Refinement

## Goal

Improve **real decision quality** of the current SMC engine without turning it
into a larger, harder-to-tune parameter surface.

The user constraint is explicit:

- the engine should become **better**
- the result should be **usable immediately**
- the system should **not get more complicated just for feature count**
- avoid changes that mostly become “just more parameters” without proven edge

## Current State

The current engine already covers the main causal SMC stack:

- swings
- displacement / ATR
- BOS / CHoCH
- sweeps
- BOS-activated order blocks
- FVGs
- structure-derived bias and premium/discount
- non-invasive breaker/body/regime extensions

Verified baseline from docs + tests (post Regime V2 + liquidity pools):

- base engine path remains deterministic
- **209 tests pass**
- `smoke-phase12.py` checksum is stable:
  `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`
- shipped EURUSD M15 2026 characterization:
  - `bias_mode=strict`, `regime_mode=off` → 32 trades (baseline)
  - `regime_mode=auto` → `detect_regime` = `mixed`, `breaker_weight=0` → **32 trades** (matches off)
  - `regime_mode=on` → **21 trades**, PF **2.7475**
  - EQH/EQL pool count on the dataset: **495**

Resolved weak spots:

- Regime V2 replaced price-path-only auto switching with structure densities
- Phase 02 added causal EQH/EQL density without widening the config surface
- `auto` still avoids becoming a noisy alias for `on` on the shipped dataset
## Core Assessment

### What is actually missing?

Not more signal families.

The engine already detects the important SMC objects.
The main issue is **selection quality** — choosing when to trust which object.

That means the next useful upgrade is **decision logic**, not “more indicators”.

### What would likely make the engine worse?

Adding more UI knobs and more configurable thresholds without evidence.

Examples of risky additions right now:

- too many mitigation toggles
- more ATR multipliers everywhere
- multiple swing engines exposed in UI
- several new confluence checkboxes
- adding internal-structure complexity before the current regime logic is fixed

These changes would mostly increase:

- tuning burden
- overfitting risk
- explanation cost in docs/UI
- maintenance cost

while not clearly improving signal quality.

## Decision (executed)

1. **Regime Detection V2** — completed and verified
2. **EQH / EQL + liquidity-pool clustering** — completed and verified

Phase 01 fixed the decision-quality gate (`auto` distinct from `on`,
baseline-safe, explainable). Phase 02 then added equal-level liquidity context
as a pure extension layer, while preserving the shipped auto path and baseline
checksum.

### Still deferred (out of plan scope)

Do **not** implement these in this plan:

- more mitigation models in the main UI
- extra imbalance families (IFVG, VI, OG)
- internal vs swing dual-structure engine
- volumetric OB metrics
- adaptive swing lengths in UI
- scanner / alerts / market-wide tooling

Those may be valid later, but they do not match the user goal of “better and
usable now, without extra complication”.

## Why this plan is stable

### Reason 1 — it builds on current strong parts

The current engine already has robust structural detection. Testing showed that
on the shipped EURUSD dataset, changing:

- `swing_length`
- `displacement_atr_mult`
- `sweep_atr_buffer`
- `pd_lookback`

hardly changed the trade set.

Interpretation: the weak point is not raw event detection. The weak point is
**context selection**.

### Reason 2 — it minimizes new engine surface area

Regime V2 and EQH/EQL improve decisions using **derived structural metrics**,
not new engine branches or lots of extra thresholds.

### Reason 3 — UI can grow a little without making the engine messy

The user explicitly wants UI controls so the refinement can be tested quickly.

That is acceptable **as long as**:

- the new controls mostly expose already-computed engine decisions
- thresholds remain internal where possible
- the engine does not become a bag of parameters

In short:

- **engine stays simple**
- **UI may become a little richer**

### Reason 4 — it keeps the current baseline safe

Any refinement must preserve:

- baseline `regime_mode=off`
- current smoke checksum on the default path
- current test coverage
- current docs + UI readability

## Scope Outcome

## Phase 1 — Regime Detection V2 — **DONE**

`src/smc_engine/regime.py` now uses structure-aware signals:

- BOS density (same-direction continuation frequency)
- CHoCH density (reversal frequency)
- sweep density (liquidity-take frequency)
- plain-language `explanation` + density fields on `RegimeState`

### Delivered behavior

- many same-direction BOS, low CHoCH => `trending` (`breaker_weight=0`)
- frequent CHoCH + frequent sweeps => `ranging` (`breaker_weight=1`)
- mixed signal => `mixed` (`breaker_weight=0`, conservative)
- sparse structure falls back to price-path metrics, still conservative

### Guardrail held

No new engine parameters exposed. UI still uses `regime_mode` only.

## Phase 2 — Liquidity Pool Layer (EQH / EQL) — **DONE**

Built `src/smc_engine/liquidity_pools.py`:

- equal highs / equal lows from confirmed swings
- fixed internal `0.15 × ATR` clustering tolerance
- confirmation at the second matching swing
- sweep requires wick-through plus reclaim close
- later matching swings cannot rewrite prior sweep outcomes

### Integration notes

- regime now includes EQH/EQL pool density in ranging pressure
- `RegimeState.explanation` reports `EQH/EQL pools ... /100`
- no new user-facing controls were added
### Backtester integration

- EQH/EQL proximity used as a counter-side liquidity filter for entry selection:
  longs require a nearby low-side pool, shorts require a nearby high-side pool
- Falls back to permissive when no pools are nearby, so the shipped baseline count stays identical

## Phase 3 — Minimal integration + usable UI — **DONE**

- App: EQH/EQL overlays on the main chart (rectangles + diamond markers for swept pools)
- App: regime explanation surfaces pool density and dominant direction
## File Plan

### Modified during execution

- `src/smc_engine/regime.py` (Regime V2 + pool-density integration)
- `src/smc_engine/liquidity_pools.py` (new pure EQH/EQL layer)
- `src/backtester.py` (auto consumes structure-aware weights, EQH/EQL proximity filter)
- `app.py` (EQH/EQL chart overlays, regime explanation panel)
- `tests/test_smc_regime.py`
- `tests/test_smc_liquidity_pools.py`
- `tests/test_backtest_breakers.py`
- docs listed in the outcome report

## Success Criteria — status

- [x] baseline `regime_mode=off` stays unchanged
- [x] full test suite passes (**209**)
- [x] smoke checksum unchanged on the baseline path
- [x] `auto` no longer blindly mirrors `on` on shipped EURUSD
- [x] auto decisions explainable (`mixed` + densities / weights)
- [x] UI reuses existing mode selector (no new control surface)
- [x] no more than two or three new user-facing controls (zero added)
- [x] docs updated without a glossary rewrite
- [x] Phase 02 EQH/EQL delivered without widening the parameter surface
- [x] EQH/EQL clusters surfaced as chart overlays (no separate UI control)

## Go / No-Go Gates

### Gate 1 — Complexity gate

Before implementation starts, ask:

- does this add a new structural signal, or just a tunable threshold?
- does it reduce decisions to clearer categories, or create more knobs?

If the answer is “mostly more knobs”, stop.

### Gate 2 — Baseline safety gate

- `pytest tests/ -q` stays green
- `smoke-phase12.py` checksum unchanged on baseline path

### Gate 3 — Decision-quality gate

- `regime_mode=auto` must stop being a noisy alias for `on`
- output should be explainable as:
  - trending
  - ranging
  - mixed
  with concrete structural reasons

### Gate 4 — Anti-parameter gate

No rollout if the implementation requires exposing many new thresholds.
Small mode selectors in UI are allowed; a broad tuning surface is not.

## Final Outcome

**Ship Regime V2 + causal EQH/EQL liquidity pools.**

Evidence:

- suite green at **209 passed**
- smoke checksum unchanged:
  `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`
- shipped EURUSD: `auto` = mixed / breaker_weight 0 / 32 trades
- forced `on` still 21 trades, PF 2.7475
- 495 EQH/EQL liquidity pools detected on the shipped dataset
- app explanation surfaces `EQH/EQL pools ... /100`
- main chart overlays EQH/EQL rectangles + swept-pool diamonds
- backtester uses EQH/EQL proximity as counter-side liquidity filter, no trade-count drift

That is the narrow Phase 02 implementation that keeps complexity controlled.
