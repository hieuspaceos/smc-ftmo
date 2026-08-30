# smc_engine

Causal Smart Money Concepts pipeline:
swing detection → market structure (BOS/CHoCH) → order blocks → fair value gaps
→ liquidity pools → regime classification.

Re-exported by `smc_ftmo` package as the engine backend. Used standalone by
`scripts/export-pine-parity-fixtures.py` for parity checks.

## Usage

```python
from smc_engine.swings import detect_swings_symmetric
from smc_engine.events import SwingResult

result: SwingResult = detect_swings_symmetric(ohlc_df, swing_length=5)
for ev in result.events:
    print(ev.pivot_pos, ev.activation_pos, ev.level, ev.direction)
```

## Install (workspace mode)

Inside the workspace root:
```bash
pip install -e packages/smc_engine
```

## Tests

Inside `packages/smc_engine/tests/` (TODO: split out tests for engine
independently of the bot integration tests).
