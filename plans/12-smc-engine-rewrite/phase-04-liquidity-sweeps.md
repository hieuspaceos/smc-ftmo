---
phase: 4
title: "Liquidity Sweeps"
status: pending
priority: P1
dependencies: [1, 2]
effort: "1-2 days"
---

# Phase 4: Liquidity Sweeps

## Overview
Detect one-shot liquidity grabs against activated swing levels. `direction` means expected setup direction: bullish sweep expects long; bearish sweep expects short.

## Requirements
- Functional: exact sweep identity, threshold, and level lifecycle.
- Non-functional: causal and prefix-invariant.

## Architecture
```python
@dataclass(frozen=True)
class SweepEvent:
    id: int
    direction: Literal["bullish", "bearish"]
    activation_pos: int
    activation_timestamp: pd.Timestamp
    source_swing_id: int
    swept_level: float
    wick_atr: float
    close_location: float
    range_expansion: bool
```

### Baseline Rules
- Bullish sweep: `low < swing_low - ATR×buffer` and `close > swing_low`.
- Bearish sweep: `high > swing_high + ATR×buffer` and `close < swing_high`.
- Equality does not sweep except wick threshold uses `>=` after a strict level crossing.
- Only activated, unconsumed swing levels are eligible.
- MVP emits at most one sweep per source swing; the level is consumed after the event until a newer swing replaces it.
- A candle that sweeps both high and low is ambiguous; emit no directional sweep and record diagnostic.
- Process sweep checks before swing activations that occur at the same close.

### Optional Quality Score (Post-MVP)
- Range expansion on reclaim candle.
- Close near directional extreme.
- Wick/body ratio.
These metrics may be stored in the event but must not gate MVP behavior.

## Related Code Files
- Create: `src/smc_engine/sweeps.py`
- Create: `tests/test_smc_sweeps.py`

## Implementation Steps
1. Track latest activated high/low swing and consumed IDs.
2. Validate ATR availability.
3. Apply direction-specific inequalities.
4. Emit one event and consume source level.
5. Add dual-sided, repeated-wick, replacement-level, exact-threshold, NaN, and timezone fixtures.

## Success Criteria
- [ ] Downside grab/reclaim emits one bullish sweep.
- [ ] Upside grab/reject emits one bearish sweep.
- [ ] Repeated wicks on one source level do not duplicate events.
- [ ] New replacement swing enables a new sweep.
- [ ] Dual-sided bar emits no directional event.
- [ ] Prefix/full-history results match.

## Risk Assessment
- **Multiple retests**: intentionally one-shot in MVP; repeat-event policy is optional.
- **Direction confusion**: exact naming is encoded in tests and adapter docs.
