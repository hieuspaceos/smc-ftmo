---
phase: 7
title: "Adapter Cutover"
status: pending
priority: P1
dependencies: [1, 2, 3, 4, 5, 6]
effort: "2 days"
---

# Phase 7: Adapter Cutover

## Overview
Rewrite `src/smc_signals.py` as an adapter over the custom engine while preserving the actual current API and serialized signal schema.

## Requirements
- Functional: preserve exact callable signatures and six return keys.
- Functional: preserve generic `Signal` fields used by app/backtester.
- Non-functional: algorithm delta only; no accidental caller/schema delta.

## Exact Current Contract
```python
@dataclass
class Signal:
    timestamp: datetime
    type: str
    price: float
    direction: str
    mitigated: bool = False
    mitigation_time: datetime | None = None
    confluence: int = 0
    top: float | None = None
    bottom: float | None = None

class SMCSignals:
    def __init__(
        self,
        swing_length: int = 20,
        displacement_atr_mult: float = 1.5,
        sweep_atr_buffer: float = 0.05,
    ): ...

    def get_signals(
        self,
        df: pd.DataFrame,
        tf: str = "M15",
        skip_mitigation: bool = False,
    ) -> dict[str, list[Signal]]: ...

def get_smc_overlays(df: pd.DataFrame, params: dict | None = None) -> dict: ...
```

Return keys: `bos`, `choch`, `fvg`, `ob`, `sweep`, `displacement`.

## Compatibility Semantics
- Preserve `tf` positional/default behavior.
- Preserve `skip_mitigation` meaning for the public adapter: when False, annotate terminal compatibility fields; when True, skip that compatibility annotation. Do not silently reinterpret it as filtering zones.
- Engine records remain immutable and as-of capable; generic `Signal.mitigated` is a terminal compatibility view only and must never drive backtester historical availability.
- `price`: broken level for BOS/CHoCH; swept level for sweep; close for displacement; midpoint for OB/FVG compatibility.
- `top`/`bottom`: populated for OB/FVG and used by updated chart/backtester.

## Architecture
1. Compute ATR/range expansion.
2. Compute swings once.
3. Compute structure, sweeps, OBs, FVGs, context.
4. Convert typed engine events to generic Signals.
5. Re-export `calculate_atr` for existing imports.
6. Preserve `get_smc_overlays()`.

## Related Code Files
- Modify: `src/smc_signals.py`
- Create: `tests/test_smc_adapter_contract.py`
- Modify: `app.py` to draw OB/FVG using top/bottom and use engine lifecycle state.

## Implementation Steps
1. Enumerate all current `.type/.price/.direction/.timestamp/.top/.bottom/.mitigated` call sites.
2. Add signature-inspection tests before rewrite.
3. Add golden JSON serialization for each signal type.
4. Implement event conversion without future-state filtering.
5. Migrate chart overlays to exact zone bounds.
6. Compare legacy/new adapter outputs as characterization, not equality of signal counts.

## Success Criteria
- [ ] `inspect.signature()` matches current constructor/get_signals/function contract.
- [ ] Default, positional `tf`, and both mitigation modes execute.
- [ ] Every current signal field remains available.
- [ ] All six keys always exist.
- [ ] App chart renders OB/FVG zones from top/bottom.
- [ ] No `smartmoneyconcepts` import remains in adapter.

## Risk Assessment
- **Hidden compatibility break**: guarded by signature and golden schema tests.
- **Terminal mitigation misuse**: backtester must consume engine lifecycle APIs, not generic boolean.
