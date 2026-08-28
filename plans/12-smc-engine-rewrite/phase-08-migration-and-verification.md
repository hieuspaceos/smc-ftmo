---
phase: 8
title: "Migration and Verification"
status: pending
priority: P1
dependencies: [7]
effort: "3-4 days"
---

# Phase 8: Migration and Verification
<!-- Updated: Validation Session 1 - Economic metrics are characterization, not correctness gates. -->


## Overview
Migrate bias, backtester, premium/discount, and UI callers; fix known vocabulary/causality defects; prove deterministic and causal behavior before removing the legacy dependency.

## Requirements
- Functional: preserve public bias/backtest schemas.
- Functional: completed-bar MTF alignment.
- Non-functional: deterministic, prefix-invariant, bounded runtime/memory.

## Architecture
### Bias Vocabulary
Engine/internal bias is exactly `bull`, `bear`, `neutral`. Adapter signal direction remains `bullish`, `bearish`. Fix `backtester.py` comparisons that currently compare bias to `bullish`/`bearish` when alignment is disabled.

### Completed-HTF Alignment
For M15 timestamp `t`, select the structure/bias state from each HTF bar whose **close timestamp** is the greatest value `<= t`.
- H4 bars: define resampling with explicit timezone, `label="right"`, `closed="right"`.
- Daily bars: today's state is unavailable until today's daily close.
- Use `pd.merge_asof`/equivalent over close timestamps.
- Preserve pre-window warmup history before slicing visible/backtest period; do not discard the swing/ATR history needed at `start_date`.

### Historical Zones
Backtester selects OB/FVG with `activation_timestamp <= t` and lifecycle methods:
- `is_active_at(t)` for validity.
- `is_first_test_at(t)` for first-test confluence.
Never use terminal `Signal.mitigated` for historical entry logic.

### Known Existing Issues Included
- Bias vocabulary mismatch (`bull` vs `bullish`).
- Same-day day-end HTF leakage.
- `first_test` currently treats presence of an OB as first test and ignores actual touch timing/FVG.
- Period clipping currently risks removing required HTF warmup history.
- `partial_tp` config remains dead/hardcoded; document as out of scope rather than claiming it is configurable.

## Related Code Files
- Modify: `src/bias_detector.py`
- Modify: `src/backtester.py`
- Modify: `src/premium_discount.py`
- Modify: `app.py`
- Modify: `tests/test_backtest.py`
- Create: `scripts/smoke-phase12.py`
- Create: `tests/fixtures/smc-golden-events.json`

## Implementation Steps
1. Replace bias detector internals, preserve `detect_bias`, `detect_bias_multi_tf`, `align_bias`, `trade_direction` signatures.
2. Precompute structure/bias once per timeframe; avoid per-day full recomputation.
3. Align completed HTF state to M15 with explicit close timestamps.
4. Migrate OB/FVG/first-test selection to lifecycle APIs.
5. Migrate P/D to structure context, keep compatibility functions.
6. Replace economic-threshold tests with behavior contracts where engine correctness legitimately changes metrics; retain economic metrics as recorded characterization.
7. Add verification layers below.

## Verification Layers
### 1. Golden/Decision Fixtures
Exact events for flat/equal levels, NaNs/gaps, warmup, reversals, dual-sided bars, timezone-aware indexes, activation/touch/fill boundaries.

### 2. Property Tests
- Prefix invariance.
- Index preservation.
- Legal enums.
- `bottom < top`.
- Origin <= activation <= touch <= invalidation/fill.
- Translation invariance and positive scale invariance.

### 3. Backtest Contract Tests
- Unique equity timestamps.
- No trade before zone activation or after invalidation.
- Completed H4/D fixtures immediately before/at/after close.
- Appending later same-day bars does not change earlier M15 decisions.
- Period window retains sufficient warmup history.
- Deterministic long and short trades on synthetic fixture.

### 4. Performance
Record cold runtime and peak memory on full M15 fixture. Require `runtime(2N)/runtime(N) < 2.5`. Compare to legacy baseline; unexplained major regression blocks cutover.

### 5. Characterization
Write `reports/smoke-final.json` with bias distributions, event counts, trade sides, trade count, winrate, PF, total R, max DD, runtime, and dataset checksum. Economic values require review, not fixed thresholds.

## Success Criteria
- [ ] All deterministic/causal gates pass.
- [ ] No earlier M15 result changes when future bars append.
- [ ] Synthetic fixture proves both long and short paths.
- [ ] Real-data outputs contain no NaN/index drift and counts reconcile.
- [ ] Full app/backtester test suite passes after approved test-contract updates.
- [ ] Performance budget passes.

## Risk Assessment
- **Same-day lookahead**: blocked by completed-bar boundary fixtures.
- **False confidence from PF/winrate**: removed from correctness gates.
- **Metric drift**: explicitly reported for human review.
