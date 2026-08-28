---
phase: 3
title: "Structure State Machine"
status: pending
priority: P1
dependencies: [1, 2]
effort: "2-3 days"
---

# Phase 3: Structure State Machine
<!-- Updated: Validation Session 1 - Confirmed swing is break-eligible from the next bar. -->


## Overview
Implement an exhaustive causal state machine for BOS, CHoCH, and trend using activated swing events.

## Requirements
- Functional: mutually exclusive BOS/CHoCH events with exact broken level/source swing.
- Functional: suppress repeated breaks until a new swing replaces the level.
- Non-functional: one pass O(n), prefix-invariant.

## Architecture
```python
@dataclass(frozen=True)
class StructureEvent:
    id: int
    type: Literal["bos", "choch"]
    direction: Literal["bullish", "bearish"]
    activation_pos: int
    activation_timestamp: pd.Timestamp
    broken_level: float
    source_swing_id: int
    prior_trend: Literal["bull", "bear", "neutral"]
    next_trend: Literal["bull", "bear"]

def detect_structure(df, swings: SwingResult, atr=None,
                     close_break_buffer_atr=0.0) -> StructureResult: ...
```

`StructureResult` includes events and index-aligned `trend`, `bos`, `choch`, `broken_level`, `last_swing_high`, `last_swing_low`, and `swing_direction` columns for adapter/OB compatibility.

## State Decision Table
| Prior trend | Upper close break | Lower close break | Event | Next trend |
|---|---:|---:|---|---|
| neutral | yes | no | bull BOS | bull |
| neutral | no | yes | bear BOS | bear |
| bull | yes | no | bull BOS | bull |
| bull | no | yes | bear CHoCH | bear |
| bear | yes | no | bull CHoCH | bull |
| bear | no | yes | bear BOS | bear |
| any | no | no | none | unchanged |

A valid level invariant is `last_swing_low < last_swing_high`. If malformed data makes both close breaks true or violates the invariant, emit no event and record a diagnostic; never emit dual events.

### Event Rules
- Close-only break; wick-only crossing is not structure break.
- Optional buffer: bull requires `close > level + ATR × buffer`; bear is symmetric.
- Equality does not break.
- CHoCH is not also BOS in MVP.
- At bar `i`: evaluate the current close using levels activated strictly before `i`; after break checks, register swing events whose activation timestamp is `i` for use from the next bar. This conservative order prevents immediate confirm-and-break artifacts and is locked in fixtures.
- Once a level breaks, mark it consumed until replaced by a newer activated swing.

### Upgrade Ideas (Post-MVP)
- MSS requiring CHoCH plus range expansion.
- Internal/external structure layers.
- Four-swing sequence validation.

## Related Code Files
- Create: `src/smc_engine/structure.py`
- Create: `tests/test_smc_structure.py`

## Implementation Steps
1. Encode the decision table as pure transition logic.
2. Implement consumed-level tracking by swing ID.
3. Add optional ATR break buffer.
4. Emit aligned output DataFrame plus typed events.
5. Freeze golden transition fixtures.

## Success Criteria
- [ ] Every table row has a failing-if-wrong test.
- [ ] Repeated closes beyond one level emit one event only.
- [ ] Wick-only/equality cases emit no break.
- [ ] No dual BOS/CHoCH event occurs.
- [ ] Appending bars leaves prior events unchanged.
- [ ] Both bullish and bearish transitions are proven on deterministic fixtures.

## Risk Assessment
- **Sideways noise**: optional ATR buffer available, default remains 0 until characterized.
- **Ambiguous same-bar activation**: ordering is explicit and golden-tested.
