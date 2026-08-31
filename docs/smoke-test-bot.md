# Smoke Test Runbook — `smc-ftmo` bot

> **Last updated:** 2026-08-31 (Phase 07 of the audit fix plan)
> **Scope:** Manual rehearsal of the bot webhook → MT5 file bridge
> pipeline. Run before the first live trade and after any major
> change to `smc_bot_webhook`.

## 0. Prerequisites

- Python 3.11+
- All `requirements-bot.txt` deps installed (`pip install -r requirements-bot.txt`).
- `config.yaml` present and populated (real risk + FTMO blocks).
- (Optional) Telegram bot token + chat ID for the notifier.
- (Optional) MT5 EA installed at the configured outbox path.

## 1. Generate a fresh webhook token

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output. This becomes `SMC_WEBHOOK_TOKEN`.

## 2. Fill `.env`

Copy `.env.example` to `.env` and set:

```dotenv
SMC_WEBHOOK_TOKEN=<paste-the-token-from-step-1>
SMC_BOT_DB_PATH=output/bot.db
SMC_TRUSTED_PROXY=1
SMC_CONFIG_PATH=config.yaml

# Phase 01+ — REQUIRED when TELEGRAM_BOT_TOKEN is set
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CALLBACK_SECRET=<generate-another-32-byte-secret>
TELEGRAM_CHAT_ID=<your-chat-id>
TELEGRAM_ALLOWED_USERS=<your-telegram-user-id>

# Phase 06+ — optional
EXECUTOR_TRANSPORT=file
MT5_OUTBOX_DIR=output/mt5_outbox
SMC_OUTBOX_MAX_PENDING=256
```

Verify the app refuses to start when the secret pair is wrong:

```bash
SMC_WEBHOOK_TOKEN=x TELEGRAM_BOT_TOKEN=1 python -c \
  "from smc_bot_webhook.server import create_app, AppSettings; create_app(AppSettings.from_env())"
# Expected: RuntimeError: TELEGRAM_CALLBACK_SECRET is required when TELEGRAM_BOT_TOKEN is set
```

## 3. Start the webhook

```bash
PYTHONPATH=packages/smc_engine/src:packages/smc_bot_core/src:packages/smc_bot_webhook/src \
  uvicorn smc_bot_webhook.server:app --host 127.0.0.1 --port 8000
```

Expected log:

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO  bot.webhook: bot webhook ready: db=output/bot.db telegram=True discord=False
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

## 4. Send a synthetic Pine alert

```bash
curl -X POST "http://127.0.0.1:8000/webhooks/tradingview?token=$SMC_WEBHOOK_TOKEN" \
  -H "Content-Type: text/plain" \
  -H "X-Forwarded-For: 52.89.214.238" \
  --data "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7|state=chart-qualified|reason=ok"
```

Expected: HTTP 202 + JSON body containing `"state": "chart-qualified"` and a 16-char `signal_id`.

## 5. Verify the alert is in the DB

```bash
sqlite3 output/bot.db \
  "SELECT id, signal_id, state, dedupe_count FROM alert_log ORDER BY id DESC LIMIT 1;"
```

Expected: 1 row, dedupe_count = 1.

## 6. Approve the alert in Telegram

In your Telegram chat, the bot should have posted a message with
✅ Accept / ❌ Reject buttons. Tap ✅ Accept. The bot should:

1. Edit the message to show `Decision: ACCEPT by <user-id>`.
2. Record a row in `signal_events` with `event_type='accept'`.
3. Write the signal JSON to `<outbox>/pending/<signal_id>.json`.
4. Record a row in `execution_log` with `state='queued'`.

Verify:

```bash
sqlite3 output/bot.db "SELECT event_type, actor FROM signal_events ORDER BY id DESC LIMIT 1;"
# expected: accept|456

sqlite3 output/bot.db "SELECT signal_id, transport, state FROM execution_log ORDER BY id DESC LIMIT 1;"
# expected: <sig>|file|queued
```

## 7. Confirm MT5 EA picks up the signal

Wait 1-2 seconds, then:

```bash
ls -la output/mt5_outbox/done/
# expected: <signal_id>.json
```

If `done/` is empty after 5 seconds, check `<outbox>/processing/` —
the EA may have crashed mid-OrderSend. Read `docs/mt5-bridge-setup.md`
for the EA troubleshooting section.

## 8. Refusal path (negative test)

Re-send the same alert with the same `bar_time` + `ob_id` +
`bos_id` + `level`. Pine will produce a new `signal_id` only if
level precision changed (level rounds to 5 decimals in Phase 05).
If the level is identical, you should see:

```
{"alert_id": 1, "signal_id": "<same-sig>", "is_new": false, "state": "chart-qualified"}
```

with HTTP 200 (not 202) and `is_new=false`. The webhook deduped
the duplicate. The `alert_log.dedupe_count` should now be 2.

## 9. Refusal path 2: missing gates

`/ack` all 6 gates (or none, then try Accept):

```bash
curl -X POST "http://127.0.0.1:8000/telegram/command?token=$SMC_WEBHOOK_TOKEN" \
  -H "X-Forwarded-For: 52.89.214.238" \
  -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_CALLBACK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"text": "/ack risk_ok", "from_user_id": 456}'
```

Then send a new alert and try to Accept it. Expected: 409 with
`reason` mentioning `risk_ok` (or whichever gate is missing).

## 10. Refusal path 3: bad secret on Telegram callback

```bash
curl -X POST "http://127.0.0.1:8000/telegram/callback?token=$SMC_WEBHOOK_TOKEN" \
  -H "X-Forwarded-For: 52.89.214.238" \
  -H "X-Telegram-Bot-Api-Secret-Token: wrong-secret" \
  -d '{"callback_data": "accept:sig:nonce", "from_user_id": 456}'
```

Expected: HTTP 401 with detail `bad or missing telegram secret`.

## 11. Rollback

If anything misbehaves, kill the uvicorn process and revert to a
known-good branch:

```bash
pkill -f "uvicorn smc_bot_webhook"
git checkout audit-fixes/phase-06-outbox  # last stable known-good
git log --oneline -10
```

The `audit-fixes/phase-N-*` branches are designed to be reverted
individually. Each is a single phase that closes specific audit
findings; reverting one is safe because the branches are
non-overlapping in code paths (mostly).

## 12. CI smoke (optional, for unattended environments)

```bash
PYTHONPATH=packages/smc_engine/src:packages/smc_bot_core/src:packages/smc_bot_webhook/src \
  python -m pytest packages/smc_bot_webhook/tests/ -q
```

Expected: all tests pass (~300 tests in <30s).
