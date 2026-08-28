---
phase: 6
title: "FVG Bias and Context"
status: pending
priority: P1
dependencies: [1, 2, 3]
effort: "2-3 days"
---

# Phase 6: FVG Bias and Context
<!-- Updated: Validation Session 1 - Structure dealing range, 200-bar expiry/cap, and first-touch entry confirmed. -->


## Overview
Implement three-candle FVG lifecycle, structure-derived bias, and structure-leg premium/discount context. This replaces the final SMC library dependency and improves the rolling-window P/D approximation.

## Requirements
- Functional: FVG activation/fill timestamps and historical state.
- Functional: `bull`/`bear`/`neutral` bias Series.
- Functional: P/D context anchored to the latest confirmed dealing range.
- Non-functional: causal, prefix-invariant, index aligned.

## Architecture
```python
@dataclass(frozen=True)
class FairValueGapEvent:
    id: int
    direction: Literal["bullish", "bearish"]
    origin_timestamp: pd.Timestamp            # middle impulse candle
    activation_timestamp: pd.Timestamp        # third candle close
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None
    fill_timestamp: pd.Timestamp | None

    def is_active_at(self, ts): ...
    def is_first_test_at(self, ts): ...
```

### FVG Definition
For activation bar `i` (third candle):
- Bullish: `high[i-2] < low[i]`; zone `[bottom=high[i-2], top=low[i]]`.
- Bearish: `low[i-2] > high[i]`; zone `[bottom=high[i], top=low[i-2]]`.
- Equality does not create a gap.
- Event is unavailable before candle `i` closes.

### MVP Fill Policy
- First touch (bullish): later `low <= top`; bearish: later `high >= bottom`.
- Full fill (bullish): later `low <= bottom`; bearish: later `high >= top`.
- Active until full fill or deterministic expiry.
- Lifecycle starts at `i+1`; activation candle cannot instantly fill its own gap.
- Deterministic MVP expiry: 200 bars after activation with at most 128 active FVGs per direction; expire oldest at the cap and record diagnostic.

### Bias
`compute_bias_series(structure)` returns the structure trend exactly: neutral before first structure break, then bull/bear through transitions. Never silently replace neutral with prior bias outside the state machine.

### Premium/Discount Context
MVP dealing range uses latest activated external swing low/high pair consistent with current structure leg. Equilibrium is `(range_high + range_low)/2`; long context is discount, short context is premium. If a valid ordered pair is unavailable, context is neutral. Preserve existing rolling-lookback functions as compatibility wrappers until caller migration.

### Optional Upgrades (Post-MVP)
- Consequent encroachment (50% FVG midpoint).
- Minimum FVG size in ATR.
- Displacement/body requirement for middle candle.
- Multiple internal/external dealing ranges.

## Related Code Files
- Create: `src/smc_engine/fvg.py`
- Create: `src/smc_engine/context.py`
- Create: `tests/test_smc_fvg_context.py`
- Modify later: `src/premium_discount.py`

## Implementation Steps
1. Implement FVG creation and single-pass lifecycle.
2. Implement bias wrapper over structure trend.
3. Implement dealing-range P/D Series from activated swings/structure.
4. Preserve compatibility wrapper output keys used by `app.py`.
5. Add exact equality, activation, touch/fill, neutral, and prefix fixtures.

## Success Criteria
- [ ] No FVG appears before third candle close.
- [ ] Zone boundaries are ordered `bottom < top`.
- [ ] Touch/fill lifecycle matches prefix computation.
- [ ] Bias enum is exactly `bull`, `bear`, `neutral`.
- [ ] P/D is neutral without a valid dealing range.
- [ ] Translation/scale invariance holds.

## Risk Assessment
- **Definition variants**: MVP locks full-fill and full-gap policy; alternatives are post-cutover.
- **P/D behavior delta**: retain rolling wrapper during cutover and report characterization difference.
