# Phase 03 — Signal engine + watcher loop

## Overview

| | |
|--|--|
| Priority | P0 |
| Status | pending |
| Depends | Phase 01, 02 |

Run `smc_engine` on each **new closed M15 bar**. Emit `AlertPayload` when a
BOS order block records **first touch on the latest bar**, with SL/TP from
`config.yaml` conventions. Watcher orchestrates feed → engine → state → notify hook.

## Requirements

### Functional
- Pipeline: `detect_swings` → `calculate_atr` → `detect_structure` → `detect_order_blocks`
- Swing windows default `left=5, right=5` (match `smc_validator`)
- Emit only when `ob.first_touch_timestamp == last_bar_ts` and `is_first_test_at(last_ts)`
- Levels:
  - long: `entry = ob.top`, `sl = ob.bottom - sl_atr_buffer * ATR`
  - short: `entry = ob.bottom`, `sl = ob.top + sl_atr_buffer * ATR`
  - `tp1/2/3 = entry ± {2,3,4}R` (scale_in ladder from config.yaml)
- Filters from config.yaml:
  - `|close - entry| <= entry_proximity_atr * ATR`
  - `min_sl_atr <= |entry-sl|/ATR <= max_sl_atr`
- Build `AlertPayload` via existing model (`event=chart_qualified`, `state=chart-qualified`)
- Watcher: poll interval; skip if bar time unchanged; multi-symbol loop
- Notify injected as callable / protocol (Phase 04 fills Telegram)

### Non-functional
- Engine errors logged; do not crash loop
- Deterministic signal_id via existing `compute_signal_id`
- No look-ahead: only closed bars from feed

## Architecture

```
Watcher.tick(symbol):
  df = feed.get_ohlc(...)
  if df.index[-1] == last_seen[symbol]: return
  last_seen[symbol] = df.index[-1]
  for payload in SignalEngine.scan(df, symbol, tf):
      if not state.should_notify(payload.signal_id): continue
      notifier.send(payload)   # Phase 04
      state.record_alert(...)
```

## Related files

**Create**
- `src/smc_bot_signal/signal_engine.py`
- `src/smc_bot_signal/watcher.py`
- `tests/test_signal_engine.py`
- `tests/test_watcher.py`

**Reuse**
- `smc_engine.swings/structure/order_blocks/displacement`
- `smc_bot_webhook.payload.AlertPayload`

## Implementation steps

1. `SignalEngine(cfg)` with scan(df, symbol) → list[AlertPayload]
2. Unit tests with synthetic OHLC that produces known OB touch (or fixture CSV if available)
3. `Watcher` holds feed, engine, state, notifier, last_seen map
4. `run_forever` sleep/poll; `run_once` for tests
5. Dry-run: notifier logs payload instead of network when `cfg.dry_run`
6. Wire `__main__` → `watcher.main()`

## Todo

- [ ] signal_engine.scan + level math tests
- [ ] filter proximity + sl atr tests
- [ ] watcher new-bar gate + dedup integration test
- [ ] dry_run path
- [ ] entrypoint

## Success criteria

- Synthetic first-touch bar → exactly one chart_qualified payload with entry/sl/tp set
- Second scan same bar → empty or deduped by watcher
- Invalid ATR / empty df → no throw, empty list
- `run_once` with InMemoryFeed exercises full path offline

## Risks

| Risk | Mitigation |
|------|------------|
| Engine noisy (many OBs) | first-touch-on-last-bar only + proximity filter |
| Parity gap vs Pine 11-gate | document v1 = engine OB first-touch; full rulebook later |
| bar_time tz | force UTC epoch seconds |

## Security

- N/A beyond existing payload fields

## Next

Phase 04 — Telegram
