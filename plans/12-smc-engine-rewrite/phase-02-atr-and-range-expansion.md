---
phase: 2
title: "ATR and Range Expansion"
status: pending
priority: P1
dependencies: []
effort: "1 day"
---

# Phase 2: ATR and Range Expansion
<!-- Updated: Validation Session 1 - Causal NaN ATR warmup confirmed. -->


## Overview
Move ATR and baseline displacement logic into the custom engine. Call the MVP signal `range_expansion`; retain `displacement` as adapter vocabulary.

## Requirements
- Functional: causal ATR with explicit warmup behavior.
- Functional: expose quality metrics without requiring them for MVP.
- Non-functional: vectorized O(n), exact index alignment.

## Architecture
```python
@dataclass(frozen=True)
class ExpansionMetrics:
    range_atr: pd.Series
    body_atr: pd.Series
    body_ratio: pd.Series
    close_location: pd.Series   # 0=low, 1=high
    direction: pd.Series        # bullish | bearish | neutral
    qualified: pd.Series        # baseline range_atr > multiplier

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series: ...
def detect_range_expansion(df, atr, multiplier=1.5) -> ExpansionMetrics: ...
```

### Locked Warmup Contract
Use causal `NaN` until `period` true-range observations exist. Do **not** backfill warmup bars with the first future ATR. Consumers must skip unavailable ATR.

This intentionally differs from legacy `calculate_atr()`, which backfills early values. Record this delta in adapter characterization.

### Baseline Rule
`qualified = (high - low) > multiplier * ATR`.

### Optional Quality Filters (Disabled in MVP)
- `body_ratio >= 0.5`.
- Bullish close location `>= 0.7`; bearish `<= 0.3`.
- Volume above rolling mean when reliable volume exists.

## Related Code Files
- Create: `src/smc_engine/displacement.py`
- Create: `tests/test_smc_displacement.py`
- Modify later: `src/smc_signals.py` re-export `calculate_atr`

## Implementation Steps
1. Validate OHLC, `period > 0`, `multiplier > 0`.
2. Preserve existing true-range formula.
3. Implement causal rolling ATR with NaN warmup.
4. Compute expansion quality metrics.
5. Add golden tests for gaps, NaNs, zero ranges, exact threshold, and direction.

## Success Criteria
- [ ] First valid ATR occurs only after causal warmup.
- [ ] No warmup bar is tradable as range expansion.
- [ ] Exact threshold uses strict `>`.
- [ ] Index/timezone preserved.
- [ ] `runtime(2N)/runtime(N) < 2.5` on synthetic scaling fixture.

## Risk Assessment
- **Legacy metric drift**: expected from causal warmup; characterize, do not hide.
- **Overclaiming displacement**: MVP uses objective range expansion; ICT-quality refinements are optional.
