# Phase 02 — Data feed abstraction + cTrader client

## Overview

| | |
|--|--|
| Priority | P0 |
| Status | pending |
| Depends | Phase 01 |

Abstract market data behind a protocol. Ship **fake/CSV feed** for tests and
a **cTrader Open API transport** for Mac live (optional extra deps).

## Requirements

### Functional
- `MarketDataFeed.get_ohlc(symbol, timeframe, bars) -> pd.DataFrame`
  - columns: `open, high, low, close` (+ optional `volume`)
  - DatetimeIndex UTC, unique, monotonic increasing
- `InMemoryFeed` / `CsvFeed` for offline + tests
- `CTraderFeed` authenticates app+account, fetches trendbars (M15)
- Clear error if `ctrader-open-api` not installed when live feed selected
- Symbol map: logical `EURUSD` → broker symbol name/id resolution helper

### Non-functional
- No Twisted imports required to import package (lazy optional)
- Reconnect policy documented (retry with backoff in feed or watcher)
- Heartbeat responsibility documented (Open API ≤10s)

## Architecture

```
MarketDataFeed (Protocol)
├── CsvFeed / InMemoryFeed     ← tests, dry local replay
└── CTraderFeed
      └── CTraderSession (OpenApiPy Client + auth sequence)
            1. TCP SSL connect demo.ctraderapi.com:5035
            2. ProtoOAApplicationAuthReq
            3. ProtoOAAccountAuthReq
            4. ProtoOAGetTrendbarsReq (PERIOD_M15)
```

Watcher (Phase 03) only depends on `MarketDataFeed` — never Open API types.

## Related files

**Create**
- `src/smc_bot_signal/data_feed.py` — Protocol + Csv/InMemory
- `src/smc_bot_signal/ctrader_client.py` — session + trendbars adapter
- `tests/test_data_feed.py`
- `tests/test_ctrader_client.py` — mocked transport only

**Do not** call live API in CI tests.

## Implementation steps

1. Define `MarketDataFeed` Protocol + OHLC normalize helper
2. Implement `InMemoryFeed` (dict of frames) and `CsvFeed(path)`
3. Implement `CTraderSession` behind try/import OpenApiPy
4. Auth sequence + `get_trendbars(symbol_id, period, from_ts, to_ts)`
5. Map period string `M15` → protobuf enum
6. Convert trendbar list → DataFrame (ms timestamps → UTC index)
7. Factory `feed_from_config(cfg, *, mode=auto|csv|ctrader|memory)`
8. Tests: normalize, empty frame, CSV round-trip, mock session bars

## Todo

- [ ] Protocol + normalizer
- [ ] Csv/InMemory feeds + tests
- [ ] CTrader client skeleton + mock tests
- [ ] Optional deps documented in package README
- [ ] `.env.example` cTrader keys

## Success criteria

- Offline feeds produce valid OHLC for engine
- Importing `smc_bot_signal` without ctrader package succeeds
- Selecting ctrader mode without install → RuntimeError with install hint
- Mocked client returns ≥ N bars DataFrame shape-correct

## Risks

| Risk | Mitigation |
|------|------------|
| Twisted reactor blocks pytest | never start reactor in unit tests; mock session |
| Symbol id unknown | cache symbols list after account auth; map by name |
| Token expiry (30d) | refresh token helper stub; Phase 05 ops doc |
| Demo vs live host mixup | `CTRADER_HOST` default demo; live explicit |

## Security

- Tokens only in env
- No request dumping secrets in logs

## Next

Phase 03 — signal_engine + watcher
