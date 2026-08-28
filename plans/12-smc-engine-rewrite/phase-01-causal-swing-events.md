---
phase: 1
title: "Causal Swing Events"
status: pending
priority: P1
dependencies: []
effort: "1-2 days"
---

# Phase 1: Causal Swing Events

## Overview
Implement confirmed Williams/fractal pivots as typed events. Activation timing is encoded once and consumed directly by all downstream phases.

## Requirements
- Functional: detect swing highs/lows with deterministic equal-level tie handling.
- Functional: expose pivot and activation positions/timestamps.
- Non-functional: O(n), prefix-invariant, timezone/index preserving.

## Architecture
Use a typed result rather than historical boolean flags that consumers can misuse:

```python
@dataclass(frozen=True)
class SwingEvent:
    id: int
    direction: Literal["high", "low"]
    level: float
    pivot_pos: int
    pivot_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp

@dataclass(frozen=True)
class SwingResult:
    events: tuple[SwingEvent, ...]
    high_at_activation: pd.Series
    low_at_activation: pd.Series
```

A pivot at `i` activates at `i + right`. No downstream function accepts a separate `right` value.

### Baseline Algorithm
- Swing high: `high[i] > max(left bars)` and `high[i] >= max(right bars)`.
- Swing low: `low[i] < min(left bars)` and `low[i] <= min(right bars)`.
- This tie rule selects the earliest equal high/low; document and test it.
- First `left` and last `right` positions cannot emit confirmed events.

### Upgrade Ideas (Post-MVP)
- ATR/deviation ZigZag or directional-change pivots.
- Displacement-qualified pivots.
- External/internal structure swing classes.
These remain alternate engines behind the same `SwingResult` contract.

## Related Code Files
- Create: `src/smc_engine/__init__.py`
- Create: `src/smc_engine/events.py`
- Create: `src/smc_engine/swings.py`
- Create: `tests/test_smc_swings.py`

## Implementation Steps
1. Validate `high`/`low`, positive `left/right`, monotonic unique index.
2. Implement causal event generation.
3. Generate activation-aligned high/low Series for O(1) consumers.
4. Freeze a small golden fixture containing isolated, equal, and asymmetric pivots.
5. Benchmark 15,895 M15 bars.

## Success Criteria
- [ ] `activation_pos == pivot_pos + right` for every event.
- [ ] No consumer needs to reconstruct confirmation delay.
- [ ] Appending future bars does not change already activated events.
- [ ] Flat/equal-level fixture matches locked tie policy.
- [ ] Translation/scale of OHLC preserves event positions.
- [ ] Real-data runtime recorded and O(n) scaling demonstrated.

## Risk Assessment
- **Repainting**: eliminated by activation timestamps and prefix-invariance tests.
- **Tie ambiguity**: eliminated by explicit earliest-equal rule.
- **Over-sensitive pivots**: optional ZigZag remains out of MVP.
