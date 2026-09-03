# Deploy — Mac mini cTrader signal bot

Plan: `plans/260903-1620-mac-mini-ctrader-signal-bot/`.

## 1. Disable sleep

```bash
sudo pmset -a displaysleep 0 sleep 0 disksleep 0
sudo pmset -c sleep 0
caffeinate -dims &
```

Prefer Ethernet over Wi‑Fi.

## 2. Python + install

```bash
brew install python@3.11
cd /path/to/smc-ftmo
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e packages/smc_engine \
            -e packages/smc_bot_core \
            -e packages/smc_bot_webhook \
            -e packages/smc_bot_signal
# when ready for live Open API:
pip install -e "packages/smc_bot_signal[ctrader]"
```

## 3. Secrets

```bash
cp packages/smc_bot_signal/.env.example ~/.smc-bot.env
chmod 600 ~/.smc-bot.env
# edit: Client ID/Secret, Playground tokens, account id, Telegram
```

Get token: https://openapi.ctrader.com → app → Playground → scope `accounts` → Get token.

## 4. Dry-run first

```bash
source .venv/bin/activate
export $(grep -v '^#' ~/.smc-bot.env | xargs)   # or use python-dotenv auto-load
SMC_SIGNAL_FEED_MODE=memory SMC_SIGNAL_DRY_RUN=1 python -m smc_bot_signal
```

Ctrl+C to stop. Memory feed with no frames idles safely.

CSV mode:

```bash
SMC_SIGNAL_FEED_MODE=csv SMC_SIGNAL_CSV_PATH=/path/to/eurusd_m15.csv \
  SMC_SIGNAL_DRY_RUN=1 python -m smc_bot_signal
```

## 5. Live cTrader feed (Phase 02 transport)

`CTraderFeed` needs a `TrendbarTransport` after OpenApiPy auth:

1. Connect `demo.ctraderapi.com:5035`
2. App auth + account auth
3. Resolve symbol id for EURUSD
4. `ProtoOAGetTrendbarsReq` period M15
5. Inject `LiveOpenApiTransport(fetch_fn=...)` into `CTraderFeed`

See Spotware ConsoleSample: https://github.com/spotware/OpenApiPy

Until that hook is wired on your Mac, keep `FEED_MODE=csv` or `memory`.

## 6. launchd (optional)

Example plist: `deploy/mac-mini/com.smc.signal.plist.example`

```bash
cp deploy/mac-mini/com.smc.signal.plist.example \
   ~/Library/LaunchAgents/com.smc.signal.plist
# edit paths
launchctl load ~/Library/LaunchAgents/com.smc.signal.plist
```

Logs: `~/Library/Logs/smc-signal.log`

## 7. Smoke checklist

- [ ] Sleep disabled overnight
- [ ] `pytest packages/smc_bot_signal/tests -q` green
- [ ] Dry-run starts without traceback
- [ ] Access token + account id set
- [ ] Telegram test with dry_run=0 after feed works
- [ ] First alert matches cTrader chart OB first touch

## Security

Never commit `~/.smc-bot.env`. Rotate Client Secret if exposed in chat.
