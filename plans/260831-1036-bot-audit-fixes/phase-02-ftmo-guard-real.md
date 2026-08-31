# Phase 02 — FTMO Guard Real Implementation

## Context

Audit finding C1 (Critical) + H2 (High).

- `C1`: `FtmoGuard.check()` is called with a hardcoded
  `GuardState(daily_pnl=0.0, trades_today=0, open_positions={})`. The
  function that *should* compute real state (`build_guard_state_from_db`)
  is a stub returning zeros. Result: **no trade is ever blocked by
  the FTMO guard**, even when limits are hit.
- `H2`: Hardcoded thresholds `max_daily_pnl=-0.011` etc. don't match
  `config.yaml` (`max_daily_loss: 0.05`). Mismatch can cause
  false-negative passes when risk config changes.

## Goals

1. `FtmoGuard.check()` uses **real** `daily_pnl`, `trades_today`,
   `open_positions` from `execution_log` + `alert_log`.
2. Thresholds read from `config.yaml` (`ftmo.*` + `risk.*`).
3. `daily_pnl` = sum of `execution_log` rows in current NY trading
   session with `state IN ('filled', 'closed')` and `pnl` column
   populated. Schema needs a new `pnl` column.
4. `trades_today` = count of `execution_log` rows in current session
   with `state IN ('queued', 'filled', 'closed')`.
5. `open_positions` = distinct symbols with `state = 'filled'` and
   no `closed_at` / `pnl` set.
6. Kill-switch `SMC_FTMO_GUARD_ENABLED=false` for emergency disable.

## Architecture

```
                    ┌──────────────────────────┐
                    │ config.yaml              │
                    │ ftmo.max_daily_loss=0.05 │
                    │ risk.per_trade_pct=0.0055│
                    │ risk.daily_loss_limit_r=2│
                    └──────────────────────────┘
                                │ load
                                ▼
                    ┌──────────────────────────┐
                    │ FtmoGuard.from_config()  │
                    │ max_daily_pnl =          │
                    │  -(0.0055 * 2) = -0.011  │
                    │ max_trades = 3           │
                    │ max_open = 1             │
                    └──────────────────────────┘
                                │ check(state)
                                ▼
                    ┌──────────────────────────┐
                    │ build_guard_state()      │
                    │  ├─ SUM(execution_log    │
                    │  │   .pnl WHERE date=     │
                    │  │   today)               │
                    │  ├─ COUNT(WHERE state IN  │
                    │  │  ('queued',...))       │
                    │  └─ DISTINCT(symbol)     │
                    │    WHERE state='filled'  │
                    └──────────────────────────┘
```

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/ftmo_guard.py`:
  - `build_guard_state_from_db` — implement real queries (Phase 06
    in original spec, deferred to here).
  - `FtmoGuard.from_config(config: dict)` — classmethod.
- `packages/smc_bot_core/src/smc_bot_core/db_impl.py`:
  - Schema migration: add `pnl REAL` to `execution_log`.
  - `upsert_execution(..., pnl: float | None = None, ...)` — accept
    pnl on update.
  - `get_daily_pnl(trade_date) -> float`.
  - `get_trades_today(trade_date) -> int`.
  - `get_open_positions() -> dict[str, int]`.
- `packages/smc_bot_webhook/src/smc_bot_webhook/server.py`:
  - `_execute_via_executor` — call `build_guard_state_from_db` instead
    of hardcoded `GuardState(...)`.
  - `create_app` — call `FtmoGuard.from_config(load_config())`.
- `config.yaml`:
  - Already has correct values. No change.

## Files to create

- `packages/smc_bot_webhook/tests/test_ftmo_guard_real.py`:
  - Populate `execution_log` with synthetic rows, assert
    `build_guard_state_from_db` returns correct counts.
  - Test daily loss blocks when sum exceeds threshold.
  - Test trade count blocks at 3.
  - Test open position blocks second EURUSD.
  - Test `FtmoGuard.from_config` reads yaml correctly.
  - Test kill-switch.

## Implementation steps

1. Add `pnl` column to `execution_log` schema (idempotent migration).
2. Add `get_daily_pnl`, `get_trades_today`, `get_open_positions` to
   `BotDB`.
3. Implement `build_guard_state_from_db` (real version).
4. Add `FtmoGuard.from_config` classmethod.
5. Update `server._execute_via_executor` to call real builder.
6. Wire config load in `create_app`.
7. Write tests.

## Todo

- [ ] Schema migration `pnl` column
- [ ] Add BotDB aggregation methods
- [ ] Implement real `build_guard_state_from_db`
- [ ] Add `FtmoGuard.from_config`
- [ ] Wire into `_execute_via_executor`
- [ ] Wire config into `create_app`
- [ ] Write tests (≥ 6 cases)

## Success criteria

- Existing `test_mt5_bridge.py::TestFtmoGuard` still passes.
- New tests pass 6/6.
- Manual rehearsal: open 1 trade, mark as filled, open 2nd → blocked
  by `open_position`.
- Bot refuses to start if `config.yaml` missing required keys.

## Risk

- **Aggregation bug**: `daily_pnl` sum can double-count if same
  signal updates `execution_log` row. Mitigation: `upsert_execution`
  already keyed on `(signal_id, transport)`. Confirm `pnl` is set
  only on final state, not on queued.
- **Timezone bug**: "today" must use NY session date, not UTC date.
  Mitigation: reuse `ny_session_date()` from `gates.state`.
- **Migration risk**: existing `output/bot.db` from previous runs
  may not have `pnl` column. Mitigation: `PRAGMA table_info(...)`
  check + `ALTER TABLE` if missing.

## Next steps

Phase 03 — Accept ordering + idempotency.
