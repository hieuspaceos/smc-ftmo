---
phase: 5
title: "Order Block Lifecycle"
status: pending
priority: P1
dependencies: [2, 3]
effort: "2-3 days"
---

# Phase 5: Order Block Lifecycle
<!-- Updated: Validation Session 1 - 200-bar expiry, 128-zone cap, first-touch bar entry confirmed; breakers deferred. -->


## Overview
Create BOS-activated order block zones with explicit provenance, first-touch, invalidation, expiry, and historical as-of state. Breakers are not part of MVP.

## Requirements
- Functional: OB unavailable before the structure break that validates it.
- Functional: distinguish first touch from invalidation.
- Non-functional: chronological lifecycle processing; no suffix scan per zone.

## Architecture
```python
@dataclass(frozen=True)
class OrderBlockEvent:
    id: int
    direction: Literal["bullish", "bearish"]  # expected setup direction
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp        # BOS/CHoCH break close
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None
    invalidation_timestamp: pd.Timestamp | None
    expiry_timestamp: pd.Timestamp | None
    structure_event_id: int

    def is_active_at(self, ts): ...
    def is_first_test_at(self, ts): ...
```

### Candidate and Activation
- Bullish OB: last bearish candle in `[break-lookback, break-1]` before bullish BOS.
- Bearish OB: last bullish candle before bearish BOS.
- Default zone: full candle `[low, high]`.
- Require range expansion at break bar or immediately previous bar.
- Deterministic MVP expiry: 200 bars after activation. Store `expiry_timestamp`.
- Bound active state with `max_active_zones_per_direction=128`; expire oldest active zone if the cap is reached and record a diagnostic. This keeps lifecycle processing bounded.

### Lifecycle
- First touch (bullish): later `low <= top`; bearish: later `high >= bottom`.
- Invalidation (bullish): later `close < bottom`; bearish: later `close > top`.
- `is_active_at(ts)`: activated and not invalidated/expired before `ts`.
- `is_first_test_at(ts)`: active and `first_touch_timestamp is None or ts <= first_touch_timestamp` according to entry timing convention. Lock exact inclusive boundary in tests.

### Complexity
Use one chronological lifecycle sweep with bounded active-zone collections. Do not rescan the full future suffix for every OB. Record expiry/cap diagnostics and enforce the scaling benchmark.

### Optional Upgrades (Post-MVP)
- Body-only zone.
- Breaker role flip.
- Volume strength.

## Related Code Files
- Create: `src/smc_engine/order_blocks.py`
- Create: `tests/test_smc_order_blocks.py`

## Implementation Steps
1. Generate candidates only from structure events and expansion proximity.
2. Store origin and activation separately.
3. Maintain first-touch/invalidation lifecycle chronologically.
4. Add `price` compatibility property as midpoint only; chart/backtester should prefer top/bottom.
5. Add prefix-invariance and before/after activation fixtures.

## Success Criteria
- [ ] Candidate revisit before BOS is not an active OB.
- [ ] Zone activates exactly at break close.
- [ ] First touch and invalidation are distinct timestamps.
- [ ] Historical `is_active_at` matches prefix computation.
- [ ] No trade can reference OB before activation or after invalidation.
- [ ] Scaling ratio remains below 2.5 on 2N fixture.

## Risk Assessment
- **Future leak**: controlled by activation/lifecycle timestamps and prefix tests.
- **OB proliferation**: constrained by range-expansion requirement, deterministic expiry, and active-zone cap.
