# smc_bot_signal

cTrader Open API → `smc_engine` → Telegram alerts (manual execution).

Designed for **Mac mini M4** 24/7. No MT5. No auto-trade.

## Install

```bash
pip install -e packages/smc_engine \
            -e packages/smc_bot_core \
            -e packages/smc_bot_webhook \
            -e packages/smc_bot_signal

# optional live cTrader deps
pip install -e "packages/smc_bot_signal[ctrader]"
```

## Configure

Put secrets in `~/.smc-bot.env` (never commit):

```bash
CTRADER_CLIENT_ID=
CTRADER_CLIENT_SECRET=
CTRADER_ACCESS_TOKEN=
CTRADER_REFRESH_TOKEN=
CTRADER_ACCOUNT_ID=
CTRADER_HOST=demo.ctraderapi.com

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

SMC_SIGNAL_SYMBOLS=EURUSD
SMC_SIGNAL_TF=M15
SMC_SIGNAL_FEED_MODE=memory   # memory | csv | ctrader | auto
SMC_SIGNAL_DRY_RUN=1
SMC_SIGNAL_DB_PATH=output/signal_state.db
```

See plan: `plans/260903-1620-mac-mini-ctrader-signal-bot/`.

## Run

```bash
# dry-run offline (memory feed empty → idle)
SMC_SIGNAL_FEED_MODE=memory SMC_SIGNAL_DRY_RUN=1 python -m smc_bot_signal

# or
smc-signal
```

Live cTrader: set credentials, `SMC_SIGNAL_FEED_MODE=ctrader`, inject transport
after OpenApiPy connect (Phase 02 live wiring — see plan phase-02/05).

## Tests

```bash
pytest packages/smc_bot_signal/tests -q
```

## Layout

| Module | Role |
|--------|------|
| `config.py` | env settings |
| `state.py` | SQLite dedup |
| `data_feed.py` | Protocol + CSV/memory |
| `ctrader_client.py` | trendbar transport + CTraderFeed |
| `signal_engine.py` | OB first-touch → AlertPayload |
| `notify.py` | dry-run + Telegram |
| `watcher.py` | poll loop |
