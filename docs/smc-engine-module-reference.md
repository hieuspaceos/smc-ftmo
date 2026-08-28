---
status: active
title: "SMC Engine Module Reference"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Module Reference

## Shared Contracts

VN note:

- **contract** = giao kèo dữ liệu giữa các module
- **result object** = gói kết quả typed của từng phase

### `events.py`

| Symbol | Meaning |
|---|---|
| `SwingEvent` | confirmed pivot with `pivot_*` and `activation_*` fields *(VN: vừa có vị trí pivot gốc, vừa có thời điểm được phép dùng)* |
| `SwingResult` | chronological swing events + activation-aligned high/low series *(VN: list event + series để adapter/backtester dùng nhanh)* |
## Detection Modules

### `swings.py`

Important exports:

- `detect_swings(df, left, right)`
- `detect_swings_symmetric(df, swing_length)`

Notes:

- uses earliest-equal tie policy
- validates unique, monotonic index
- returns immutable events

### `displacement.py`

Important exports:

- `calculate_atr(df, period=14)`
- `detect_range_expansion(df, atr, multiplier=1.5)`

VN note:

- **ATR** = average true range, độ rung trung bình gần đây
- **range expansion** = cây nến mạnh hơn nền dao động bình thường

Metrics inside `ExpansionMetrics`:

- `range_atr` *(VN: biên độ cây nến / ATR)*
- `body_atr` *(VN: thân nến / ATR)*
- `body_ratio` *(VN: tỷ lệ thân so với full range)*
- `close_location` *(VN: close nằm gần high hay gần low)*
- `direction` *(VN: bullish / bearish / neutral)*
- `qualified` *(VN: có pass ngưỡng displacement không)*
### `structure.py`

Important exports:

- `StructureEvent`
- `StructureResult`
- `detect_structure(df, swings, atr=None)`

Adapter series inside `StructureResult`:

- `trend`
- `bos`
- `choch`
- `broken_level`
- `last_swing_high`
- `last_swing_low`
- `swing_direction`

### `sweeps.py`

Important exports:

- `SweepEvent`
- `SweepDiagnostic`
- `SweepResult`
- `detect_sweeps(df, swings, atr, atr_buffer, range_expansion_mult)`

Notes:

- diagnostics capture skipped / ambiguous bars
- consumes activated swing levels only

## Zone Modules

VN note:

- **zone** = vùng giá để chờ phản ứng, không phải 1 điểm giá duy nhất
- **lifecycle** = vòng đời của zone: sinh ra → active → touch / invalidate / expire

### `order_blocks.py`

Important exports:

- `OrderBlockEvent`
- `OrderBlockResult`
- `detect_order_blocks(df, structure, expansion, candidate_lookback=20, expiry_bars=200, max_active_zones_per_direction=128)`

Lifecycle helpers:

- `is_active_at(ts)` *(VN: tại thời điểm này zone còn dùng được không)*
- `is_first_test_at(ts)` *(VN: đây có còn là lần chạm đầu tiên không)*

### `fvg.py`

Important exports:

- `FairValueGapEvent`
- `FVGResult`
- `detect_fvgs(df, expiry_bars=200, max_active=128)`

Lifecycle helpers:

- `is_active_at(ts)`
- `is_first_test_at(ts)`

### `context.py`

Important exports:

- `ContextResult`
- `compute_bias_series(structure)`
- `compute_dealing_range_context(df, structure)`
- `context_snapshot(result)`
- `is_in_pd_zone(zone, direction)`

## Extension Layers

### `breaker_blocks.py`

Important exports:

- `BreakerEvent`
- `promote_breakers(ob_result, structure, df_index, promotion_lookback_bars=50)`
- `promote_breakers_with_events(...)`

Notes:

- non-invasive pure transform
- does not modify `order_blocks.py`
- uses CHoCH after invalidation only

### `ob_body_mode.py`

Important exports:

- `recompute_zones(ob_result, df, mode="full"|"body")`

Notes:

- `full` = identity
- `body` = zone from `max(open, close)` / `min(open, close)` at origin candle

### `regime.py`

Important exports:

- `RegimeState`
- `detect_regime(df, trend_lookback=14, chop_lookback=14)`

Internal metrics:

- `_directional_move_ratio`
- `_choppiness`
- `_regime_label`
- `_weights_from_regime`

## Adapter Surface

### `src/smc_signals.py`

Stable compatibility exports:

- `Signal`
- `SMCSignals`
- `get_smc_overlays()`
- `calculate_atr()`

Additive exports:

- `BreakerSignal`
- `SMCSignals.get_breaker_overlays()`

## Backtester Integration

### `src/backtester.py`

Current strategy knobs relevant to the engine:

| Config key | Meaning |
|---|---|
| `strategy.bias_mode` | `strict | h4_only | any` |
| `strategy.regime_mode` | `off | on | auto` |
| `strategy.promotion_lookback_bars` | breaker promotion distance |
| `strategy.partial_tp` | TP ladder profile |
| `strategy.displacement_atr_mult` | range-expansion multiplier |
| `pd_lookback` | dealing-range context lookback |
