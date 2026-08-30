# Phase 02: SQLite Storage + Telegram Dispatcher

## Context

- [Plan](./plan.md)
- Depends on [Phase 01](./phase-01-webhook-receiver.md) — webhook + parser + initial storage

## Goal

Wire webhook payload → Telegram inline keyboard Accept/Reject. No execution yet (Phase 03 gates + Phase 06 MT5).

## Requirements

### Storage schema complete

- [ ] `signal_events` table: track signal lifecycle (received → notified → accepted/rejected → expired)
- [ ] `gate_ack` table: store manual gate acknowledgments with expiry
- [ ] Idempotency persistence: dedupe_count in alert_log

### Telegram dispatcher (`bot/notify/telegram.py`)

- [ ] `python-telegram-bot` v21+ async handlers
- [ ] Send message with signal summary:
  - Symbol + TF + direction
  - State + reason
  - OB/BOS ids
  - Bar time (UTC)
  - Gate checklist (6 manual gates status)
- [ ] Inline keyboard: `[Accept]` `[Reject]` (and optionally `[Ack gates]`)
- [ ] Callback query handler: `accept:<signal_id>:<nonce>` / `reject:<signal_id>:<nonce>`
- [ ] Authorize fixed allowlist of Telegram user ids (env: `TELEGRAM_ALLOWED_USERS`)
- [ ] Edit message after decision — disable buttons, show final state
- [ ] Audit every send/edit in `signal_events`

### Discord mirror (`bot/notify/discord.py`)

- [ ] Mirror-only webhook messages (no buttons, no decisions)
- [ ] Same payload format as Telegram but simpler text
- [ ] Document: Telegram is sole approval authority

### Delivery semantics

- [ ] Background dispatch (don't block webhook return)
- [ ] Retry on transient failure (max 3 with exponential backoff)
- [ ] Mark `notified_failed` after exhausted retries
- [ ] Dashboard surfaces failed deliveries for manual resend

## Files to Create/Modify

- Modify: `bot/storage/schema.sql` (add signal_events, gate_ack, execution_log tables)
- Create: `bot/notify/__init__.py`, `bot/notify/telegram.py`, `bot/notify/discord.py`
- Modify: `bot/webhook/server.py` (enqueue notification after persist)
- Modify: `requirements-bot.txt` (add `python-telegram-bot`, `httpx`)
- Create: `tests/test_bot_notify.py`

## Implementation Steps

1. **Schema extension** (1h): add signal_events, gate_ack, execution_log tables
2. **Telegram bot skeleton** (2h): token from env, allowed users list, basic send_message
3. **Message formatter** (2h): signal summary + gate checklist rendering
4. **Inline keyboard + callback handler** (3h): parse `accept:<sid>:<nonce>` format, authorization check, state transition
5. **Message edit on decision** (1h): after Accept/Reject, edit message text to disable buttons + show final state
6. **Discord mirror** (1h): webhook URL, basic text-only
7. **Background dispatch** (2h): FastAPI BackgroundTasks or asyncio queue
8. **Smoke test** (1h): run end-to-end webhook → Telegram → Accept → audit row

## Tests

- Unit: message formatter correctness; callback parsing; nonce validation
- Integration: full webhook → Telegram → callback flow with mocked bot
- Manual: real Telegram bot with test user

## Risks and Rollback

- **Risk**: Telegram bot token leak
  - **Mitigation**: env file outside repo; `.gitignore` it
- **Risk**: User taps stale Accept button from old message
  - **Mitigation**: nonce in callback data; re-validate freshness on callback
- **Risk**: Telegram outage → alert lost
  - **Mitigation**: alert persists in SQLite; dashboard `notified_failed`; manual resend
- **Rollback**: disable Telegram by unsetting `TELEGRAM_BOT_TOKEN`; webhook persists alert but no notification

## Unresolved Questions

- Number of authorized Telegram users? (default 1, can extend)
- Bot message formatting: Markdown or plain text? (Markdown recommended)
- Should Discord mirror be optional via env flag?
