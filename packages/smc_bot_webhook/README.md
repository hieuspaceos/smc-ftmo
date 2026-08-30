# smc_bot_webhook

FastAPI webhook server + Telegram dispatcher + 11-gate rulebook validator
+ MT5 file-bridge executor. Phase 01–03 + Phase 06 wiring.

## Endpoints

- `POST /webhooks/tradingview` — Pine alert intake (Phase 01)
- `POST /telegram/callback` — Telegram inline button handler (Phase 02)
- `GET /healthz` — liveness probe
- `POST /telegram/command` — `/ack <gate>` text commands

## Run standalone

```bash
pip install -e packages/smc_engine -e packages/smc_bot_core -e packages/smc_bot_webhook
SMC_WEBHOOK_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  PYTHONPATH=src:packages/smc_engine/src:packages/smc_bot_core/src:packages/smc_bot_webhook/src \
  python -m uvicorn smc_bot_webhook.server:app --host 127.0.0.1 --port 8000
```

## Notes

Uses `smc_bot_core` for DB + settings + payload models (re-exported
transitionally). When `smc_bot_core` moves the canonical implementation
permanently into `smc_bot_core.db`, this package drops the re-export
shim.
