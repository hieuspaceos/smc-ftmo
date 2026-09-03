# Plan — Mac mini cTrader Signal Bot

> **Status**: PHASES 01–04 IMPLEMENTED (2026-09-03)  
> **Created**: 2026-09-03  
> **Supersedes**: `plans/260831-XXXX-mac-mini-ctrader-bot/` (draft)
>
> Live OpenApiPy fetch_fn wiring + user smoke = Phase 05 (docs done; live optional).

## Outcome

Bot chạy 24/7 trên **Mac mini M4**, kéo M15 live từ **cTrader Open API**
(FTMO demo/live), detect chart-qualified bằng `smc_engine`, bắn **Telegram**.
User **manual** đặt lệnh trên cTrader Mac. **Không** auto-trade. **Không** MT5. **Không** VPS.

## Constraints

- Mac mini M4 Apple Silicon only (no MT5 Wine)
- Reuse: `smc_engine`, `smc_bot_webhook.payload`, `notify/formatting`, Telegram dispatcher
- Secrets only in local env (`~/.smc-bot.env`), never git
- Package layout: `packages/smc_bot_signal/` (workspace sibling)
- KISS/DRY; files < 200 LOC when practical
- Alert-only; execution stays human

## Non-goals

- Auto-order placement on cTrader
- Port full Pine 11-gate rulebook in v1 (engine OB first-touch + config.yaml SL/TP)
- TradingView / Pine webhook path
- VPS / Docker production deploy (Mac mini first)
- Multi-account / multi-broker

## Acceptance (done when)

1. `pip install -e packages/smc_bot_signal` works in workspace
2. Offline tests pass without live cTrader (fake feed)
3. With real credentials: bot pulls M15 EURUSD, detects new bar, may emit Telegram
4. Dedup: same `signal_id` not re-sent inside window
5. Mac launchd + no-sleep docs exist; dry-run mode works
6. README + plan phases updated; no secrets in repo

## Architecture (one glance)

```
cTrader Open API (demo/live)
        │ poll / trendbars
        ▼
 packages/smc_bot_signal/
   data_feed → signal_engine (smc_engine) → state (SQLite dedup)
        │
        ▼
   notify → Telegram (reuse smc_bot_webhook)
        │
        ▼
 User phone → manual trade on cTrader Mac
```

## Phases

| # | Phase | Status | Detail |
| 01 | Package scaffold + config + state | **done** | [phase-01](./phase-01-package-scaffold-config-state.md) |
| 02 | Data feed abstraction + cTrader client | **done** (mock/live hook) | [phase-02](./phase-02-data-feed-ctrader-client.md) |
| 03 | Signal engine + watcher loop | **done** | [phase-03](./phase-03-signal-engine-watcher.md) |
| 04 | Telegram notify + dry-run | **done** | [phase-04](./phase-04-telegram-notify.md) |
| 05 | Mac deploy docs + live smoke | **docs done** / smoke user | [phase-05](./phase-05-mac-deploy-live-smoke.md) |
| 05 | Mac deploy docs + live smoke | pending | [phase-05](./phase-05-mac-deploy-live-smoke.md) |

## Dependencies

- Open API app **done** (Client ID/Secret exist; tokens still needed)
- Need before Phase 05 live: accessToken, refreshToken, accountId, Telegram token/chat
- Optional dep: `ctrader-open-api` + Twisted (Phase 02 real transport)

## Effort

| Phase | Est. |
|-------|------|
| 01–04 code + tests | ~4–5 days |
| 05 deploy + 1w smoke | docs 0.5d + user runtime |

## Open blockers (user)

1. Playground **accessToken + refreshToken** saved?
2. **CTRADER_ACCOUNT_ID** known?
3. Telegram bot token + chat id still valid?
4. Symbols v1: EURUSD only OK?
5. Approve this plan → implement 01→04?

## Refs

- Spotware Open API: https://help.ctrader.com/open-api/
- OpenApiPy: https://github.com/spotware/OpenApiPy
- Engine: `packages/smc_engine/`
- Alert model: `packages/smc_bot_webhook/.../payload.py`
- Strategy numbers: root `config.yaml` (`sl_atr_buffer`, TP R ladder 2/3/4)
