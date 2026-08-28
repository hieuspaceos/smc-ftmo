---
status: active
title: "System Architecture"
created: "2026-08-27"
---

# System Architecture

Phase 12 replaced the third-party `smartmoneyconcepts` library with a custom
causal ICT/SMC engine. All swing, BOS/CHoCH, sweep, order block, FVG,
bias, and premium/discount logic now lives in `src/smc_engine/`.

## Custom Engine Modules

| Module | Role |
|---|---|
| `src/smc_engine/swings.py` | Confirmed Williams/fractal swings with explicit activation time |
| `src/smc_engine/displacement.py` | Causal ATR and range-expansion metrics |
| `src/smc_engine/structure.py` | BOS/CHoCH state machine with full-lifecycle trend |
| `src/smc_engine/sweeps.py` | One-shot liquidity grabs with consumed-level tracking |
| `src/smc_engine/order_blocks.py` | BOS-activated OBs with first-touch/invalidation/expiry lifecycle |
| `src/smc_engine/fvg.py` | Three-candle fair value gaps with touch/fill lifecycle |
| `src/smc_engine/context.py` | Structure-derived bias Series and dealing-range P/D context |

## API Guarantees

- **Events are immutable**. Each event records `activation_timestamp` and
  `origin_timestamp` separately; consumers never reconstruct confirmation
  timing.
- **Lifecycle queries are as-of-time**. OB and FVG expose
  `is_active_at(ts)` / `is_first_test_at(ts)`; backtesters and the UI
  must use them instead of terminal mitigation flags.
- **Higher-timeframe alignment is completed-bar**. The daily and H4 bias
  states are merged onto M15 only after the corresponding HTF bar closes
  (`pd.merge_asof(...direction="backward")`).

## Adapter Cutover

`src/smc_signals.py` is now a thin compatibility adapter that exposes the
six-key dict, the `SMCSignals` class, and `get_smc_overlays()`. The legacy
`Signal` dataclass shape is preserved.

## Verification

- `pytest tests/` covers swing, structure, sweeps, OB, FVG, displacement,
  context, and the legacy backtest regression.
- Backtest tests use only characterization thresholds; PF, winrate, and
  max DD are reported for review, not gates.

## External Dependencies

`smartmoneyconcepts` has been removed from `requirements.txt`. The runtime
stack now consists of `pandas`, `numpy`, `pyarrow`, `ta`, `sqlalchemy`,
`pyyaml`, `streamlit`, `plotly`, plus standard library utilities.
