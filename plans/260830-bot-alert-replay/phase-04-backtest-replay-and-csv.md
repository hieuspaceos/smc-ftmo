# Phase 04: Python Replay Engine + Signal CSV

## Context

- [Plan](./plan.md)
- Depends on [Phase 01](./phase-01-webhook-receiver.md) — payload schema
- Existing: `scripts/capture-frozen-feed.py`, `scripts/compare-pine-parity.py`

## Goal

Deterministic Python replay từ frozen OHLC bundle → signal CSV same schema as live webhook → parity compare với Pine manual export.

## Requirements

### Replay engine (`bot/backtest/replay_engine.py`)

- [ ] Read frozen OHLC bundle (output of `scripts/capture-frozen-feed.py`)
- [ ] Reuse existing Python engine surfaces (`src/smc_engine/`)
- [ ] Walk bars confirmed-by-confirmed; emit `SMC|v1`-equivalent rows
- [ ] Same idempotency: signal_id = hash(event + symbol + tf + bar_time + ...)
- [ ] Never send webhook; write to CSV only
- [ ] Preserve causal semantics per `docs/smc-engine-event-pipeline.md`

### Signal CSV capture (`bot/backtest/capture.py`)

- [ ] Schema:
  ```csv
  source,run_id,signal_id,event,symbol,tf,side,level,entry,sl,tp1,tp2,tp3,bar_time,ob_id,bos_id,state,reason,score,gate_status,decision,decision_at,execution_status
  ```
- [ ] Sources:
  1. Live webhook (from `alert_log` + `signal_events` join)
  2. Python replay output
  3. Manual Pine Logs paste → normalize to same schema
- [ ] Function `capture_from_live(db_session, output_path)`
- [ ] Function `capture_from_replay(replay_engine, output_path)`
- [ ] Function `capture_from_pine_logs(paste_text, output_path)`

### Parity compare integration

- [ ] Reuse `scripts/compare-pine-parity.py` với CSV mới
- [ ] Document: chạy Python replay → CSV; export Pine Logs từ Bar Replay → capture.py → compare

## Files to Create/Modify

- Create: `bot/backtest/__init__.py`, `bot/backtest/replay_engine.py`, `bot/backtest/capture.py`
- Create: `tests/test_bot_replay_capture.py`
- Modify: existing `scripts/compare-pine-parity.py` only if schema mismatch

## Implementation Steps

1. **Replay engine** (4h):
   - Wrap existing Python engine with bar iterator
   - Emit events at same points as live webhook would
   - Determinism test: same OHLC → same CSV byte-for-byte

2. **CSV capture module** (3h):
   - Live join query (alert_log + signal_events)
   - Replay output → CSV
   - Manual Pine Logs parser (regex or line-based)

3. **Tests** (2h):
   - Replay determinism: 2 runs same fixture → same CSV
   - CSV schema: all required columns + types
   - Pine Logs parser: valid/invalid input

## Tests

- `tests/test_bot_replay_capture.py`:
  - Replay engine: same input → same output (hash)
  - CSV: schema validation; missing column → error
  - Pine Logs parser: valid paste → expected rows; invalid → skip with warning
  - End-to-end: frozen OHLC → replay → CSV → parity compare returns 0 mismatches

## Risks and Rollback

- **Risk**: Python replay semantics drift from Pine (e.g., BOS detection difference)
  - **Mitigation**: existing parity tests (15 passing); expand to replay path
- **Risk**: Bar Replay không reproducible (different start time)
  - **Mitigation**: frozen OHLC bundle + checksum; deterministic Python engine
- **Rollback**: delete replay folders + signal CSV; existing parity tooling untouched

## Unresolved Questions

- Default replay window size? (recommend 1 month M15 ~ 2000 bars)
- Score field in CSV: from rule book (≥4 threshold) or raw engine score?
- Should capture.py support multi-symbol batches?
