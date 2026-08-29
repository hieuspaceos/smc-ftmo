---
title: "SMC Signal Quality Refinement"
description: "Tighten the SMC engine only where current evidence shows real decision-quality gaps, while explicitly rejecting feature growth that would mostly add parameters or UI complexity."
status: proposed
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

Verified baseline from docs + tests:

- base engine path remains deterministic
- 197 tests pass
- `smoke-phase12.py` checksum is stable
- current baseline on shipped EURUSD M15 2026 dataset:
  - `bias_mode=strict`, `regime_mode=off`
  - 32 trades
  - 81.2% WR
  - 8.29 PF

Known weak spot:

- `regime_mode=auto` exists but does **not** improve decisions yet
- price-path-only regime logic misclassifies the shipped dataset as ranging
- enabling breakers (`regime_mode=on/auto`) reduces edge on the shipped dataset

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

## Decision

### Do now

Only pursue **one primary upgrade track**:

1. **Regime Detection V2**

And allow **one secondary track only if the first one remains simple and
measurably useful**:

2. **EQH / EQL + liquidity-pool clustering**

### Explicitly defer

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

Regime V2 can improve decisions using mostly **derived metrics**, not new
engine branches or lots of extra thresholds.

EQH/EQL can also be introduced as a structural enrichment layer without
exploding the engine API.

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

## Proposed Scope

## Phase 1 — Regime Detection V2

Refine `src/smc_engine/regime.py` to use **structure-aware** signals instead of
price-path-only heuristics.

### Replace / extend current logic with

- BOS density (same-direction continuation frequency)
- CHoCH density (reversal frequency)
- sweep density (liquidity-take frequency)
- optional ATR percentile (keep internal, not user-exposed)

### Target behavior

- many same-direction BOS, low CHoCH => `trending`
- frequent CHoCH + frequent sweeps => `ranging`
- mixed signal => `mixed`

### Guardrail

No new **engine** parameters unless a hard-coded constant clearly fails.
UI can expose the resulting regime state and reasoning, but not a large new
tuning surface.
## Phase 2 — Liquidity Pool Layer (EQH / EQL)

Add `eqh_eql.py` or similarly named pure module.

### What it should do

- detect equal highs / equal lows from confirmed swings
- cluster nearby levels using a fixed ATR-relative tolerance
- mark whether liquidity pool has been swept

### Why it helps

- improves sweep quality context
- gives better confluence for manual review
- can later feed regime logic and backtester selection

### Guardrail

Do not expose tolerance to the UI initially.
Pick one fixed internal tolerance and test it.

## Phase 3 — Minimal integration + usable UI

Integrate new signals into the **decision layer first**, then expose them in a
small, practical UI so the user can backtest immediately.

### Allowed integrations

- regime uses EQH/EQL density internally
- backtester uses improved regime state
- app shows regime explanation text
- app may expose **small strategy controls** that switch already-computed modes
  on/off (for example: `regime_mode`, `liquidity_mode`, or a single
  explanation/visibility toggle)

### Not allowed in this plan

- five new checkboxes
- per-module thresholds everywhere
- turning every heuristic into a slider
- duplicating the same concept in both engine config and UI config

### UI principle

The user can have **buttons/selectors to test the strategy quickly**, but the
engine should still have a narrow decision contract.

Good UI:

- choose mode
- see explanation
- compare results

Bad UI:

- tune ten thresholds blindly
- expose every internal tolerance
- let the UI drift ahead of the engine contract

## File Plan

### Create

- `plans/260829-0223-smc-signal-quality-refinement/phase-01-regime-v2.md`
- `plans/260829-0223-smc-signal-quality-refinement/phase-02-liquidity-pools.md`

### Likely modify later (not in this planning step)

- `src/smc_engine/regime.py`
- `src/backtester.py`
- `src/smc_signals.py`
- `app.py` (regime explanation + small practical controls)

### Likely create later (not in this planning step)

- `src/smc_engine/eqh-eql.py` or `src/smc_engine/liquidity-pools.py`
- `tests/test_smc_regime.py`
- `tests/test_smc_liquidity_pools.py`
- `tests/test_backtest_regime_v2.py`
- `tests/test_app_regime_ui.py` [optional]

## Success Criteria

- baseline `regime_mode=off` stays unchanged
- full test suite still passes
- smoke checksum unchanged on the baseline path
- `auto` no longer blindly mirrors `on` on the shipped EURUSD dataset
- auto decisions become easier to explain in plain language
- UI exposes the new decision path in a simple way the user can backtest
  immediately
- no more than **two or three** new user-facing controls are introduced
- docs remain understandable without another major glossary pass

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

## Recommendation After Review

### Is this plan good for the current engine?

**Yes, if kept narrow.**

### Is it likely to become rắc rối / phức tạp?

**Yes, immediately, if expanded beyond Regime V2 + fixed-liquidity-pool layer.**

### Practical recommendation

Do **only Regime V2 first**.
Then re-measure.

If Regime V2 alone materially improves `auto`, stop there.
Only then consider EQH/EQL as a second pass.

That is the cleanest path that matches the user goal.
