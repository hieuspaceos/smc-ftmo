---
status: active
title: "System Architecture"
created: "2026-08-27"
updated: "2026-08-29"
---

# System Architecture

The project has two architectural layers:

1. **Core engine** — causal ICT/SMC structure detection in `src/smc_engine/`
2. **Consumption layer** — `src/smc_signals.py`, `src/backtester.py`, and
   `app.py`

Phase 12 replaced the third-party `smartmoneyconcepts` library with a custom
causal engine. Phase 13 added non-invasive breaker/body extensions. The
signal-quality refinement upgraded `regime.py` to structure-aware Regime V2,
then added `liquidity_pools.py` so EQH/EQL density can enrich auto-regime
selection without widening the user config surface.

## Split Engine Docs

The engine is documented as a separate doc set:

### Đọc nhanh bằng tiếng Việt

- [SMC Engine Giải Thích Bằng Tiếng Việt](./smc-engine-vietnamese-guide.md)
- [SMC Engine Usage Guide](./smc-engine-usage-guide.md)

### Tài liệu kỹ thuật chi tiết

- [SMC Engine Overview](./smc-engine-overview.md)
- [SMC Engine Event Pipeline](./smc-engine-event-pipeline.md)
- [SMC Engine Module Reference](./smc-engine-module-reference.md)
- [SMC Engine Extensions](./smc-engine-extensions.md)
- [SMC Engine Verification](./smc-engine-verification.md)

## Core Engine Modules

| Module | Role |
|---|---|
| `src/smc_engine/events.py` | Shared immutable event contracts |
| `src/smc_engine/swings.py` | Confirmed Williams/fractal swings with explicit activation time |
| `src/smc_engine/displacement.py` | Causal ATR and range-expansion metrics |
| `src/smc_engine/structure.py` | BOS/CHoCH state machine with full-lifecycle trend |
| `src/smc_engine/sweeps.py` | One-shot liquidity grabs with consumed-level tracking |
| `src/smc_engine/order_blocks.py` | BOS-activated OBs with first-touch/invalidation/expiry lifecycle |
| `src/smc_engine/fvg.py` | Three-candle fair value gaps with touch/fill lifecycle |
| `src/smc_engine/context.py` | Structure-derived bias Series and dealing-range P/D context |

## Extension Layers

| Module | Role |
|---|---|
| `src/smc_engine/breaker_blocks.py` | Pure breaker promotion layer over invalidated OBs |
| `src/smc_engine/ob_body_mode.py` | Pure full/body geometry transform for OB zones |
| `src/smc_engine/liquidity_pools.py` | Fixed-tolerance EQH/EQL clustering with causal sweep state |
| `src/smc_engine/regime.py` | Structure-aware Regime V2 for OB vs breaker switching |

## API Guarantees

- **Events are immutable.** Consumers receive typed dataclasses and must use
  their activation fields directly.
- **Lifecycle queries are as-of-time.** OB and FVG expose
  `is_active_at(ts)` / `is_first_test_at(ts)`; historical decisions must use
  them instead of terminal flags.
- **Higher-timeframe alignment is completed-bar only.** Daily and H4 bias are
  merged onto M15 only after the corresponding HTF bar closes.
- **Compatibility surface is preserved.** `src/smc_signals.py` keeps the
  legacy `Signal` shape and `SMCSignals.get_signals()` signature; breaker
  overlays are additive via `get_breaker_overlays()`.

## Verification

- Current suite: **209 passed**
- Baseline smoke checksum:
  `4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`
- Breaker and body-mode layers are tested separately and do not mutate the
  default baseline when disabled
- Regime V2 + liquidity pools keep `regime_mode=off` and smoke baseline
  identical; on shipped EURUSD M15, `auto` still resolves to `mixed` with
  `breaker_weight=0` (32 trades) while explanation now includes EQH/EQL density
