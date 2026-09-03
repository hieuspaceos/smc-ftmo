# Phase 01 — Package scaffold + config + state

## Overview

| | |
|--|--|
| Priority | P0 |
| Status | pending |
| Depends | none |

Create installable workspace package `smc_bot_signal` with env config and
SQLite dedup store. No live network.

## Requirements

### Functional
- Editable install via setuptools `src/` layout (match siblings)
- `SignalBotConfig.from_env()` loads cTrader + Telegram + engine knobs
- `SignalStateStore` records `signal_id` + timestamp; `should_notify` respects dedup window
- Console entrypoint stub `smc-signal` exists (may no-op until Phase 03)

### Non-functional
- No secrets defaults in code
- Tests run offline
- File size discipline

## Architecture

```
packages/smc_bot_signal/
  pyproject.toml
  README.md
  src/smc_bot_signal/
    __init__.py
    __main__.py          # python -m smc_bot_signal
    config.py
    state.py
  tests/
    test_config.py
    test_state.py
```

Root `README.md` + root `pyproject` docs updated to list package (install line).

## Related files

**Create**
- `packages/smc_bot_signal/pyproject.toml`
- `packages/smc_bot_signal/README.md`
- `packages/smc_bot_signal/src/smc_bot_signal/{__init__,__main__,config,state}.py`
- `packages/smc_bot_signal/tests/test_config.py`
- `packages/smc_bot_signal/tests/test_state.py`

**Modify**
- Root `README.md` — package layout + install `-e packages/smc_bot_signal`

## Implementation steps

1. Add `pyproject.toml` deps: pandas, dotenv, smc_engine, smc_bot_webhook; optional `ctrader`
2. `config.py`: frozen dataclass; `_env` helpers; `require_ctrader` flag
3. `state.py`: SQLite table `sent_alerts(signal_id PK, sent_at, symbol, bar_time)`
4. `should_notify(signal_id)` → False if row exists and age < `dedup_window_minutes`
5. `record_alert(...)` upsert
6. Unit tests with tmp_path DB + monkeypatched env
7. `__main__` prints version / “not configured” until watcher lands

## Todo

- [ ] pyproject + package init
- [ ] config.from_env + tests
- [ ] state SQLite + tests
- [ ] README package section
- [ ] root README install line

## Success criteria

- `pytest packages/smc_bot_signal/tests/test_config.py test_state.py -q` green
- `from_env` raises clear error when `require_ctrader=True` and secrets missing
- Dedup: second notify same id within window → False; after window → True (or delete row test)

## Risks

| Risk | Mitigation |
|------|------------|
| DB path missing parent dir | `mkdir parents` on open |
| Windows path vs Mac | use `pathlib.Path` only |

## Security

- Never log client_secret / access_token
- Example env file: `.env.example` keys only, empty values

## Next

Phase 02 — data feed protocol + cTrader transport
