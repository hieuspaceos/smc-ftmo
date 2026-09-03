# Phase 04 — Telegram notify + dry-run

## Overview

| | |
|--|--|
| Priority | P0 |
| Status | pending |
| Depends | Phase 03 |

Send alerts using existing webhook notify stack. No duplicate formatter.

## Requirements

### Functional
- `SignalNotifier` protocol: `send(payload) -> message_id | None`
- Live impl wraps `TelegramDispatcher` + `FakeTelegramTransport` for tests
- Reuse `format_telegram_message` (MarkdownV2 + trade levels)
- Optional Phase 1.5: if M15 df available, call `validate_pine_signal` for annotation only
- `dry_run=True` → log formatted text, no HTTP
- Missing `TELEGRAM_BOT_TOKEN` → disabled notifier (warn once), bot still runs

### Non-functional
- Async dispatcher called via `asyncio.run` or long-lived loop inside watcher thread carefully
- Prefer single-event-loop policy documented (Mac)

## Architecture

```
smc_bot_signal/notify.py
  ├── LoggingNotifier (dry_run / no token)
  └── TelegramSignalNotifier
        └── smc_bot_webhook.notify.telegram.TelegramDispatcher
              └── format_telegram_message(payload, validation=...)
```

## Related files

**Create**
- `src/smc_bot_signal/notify.py`
- `tests/test_notify.py`

**Reuse**
- `smc_bot_webhook.notify.telegram`
- `smc_bot_webhook.notify.formatting`
- `smc_bot_webhook.smc_validator.validate_pine_signal` (optional)

## Implementation steps

1. Protocol + LoggingNotifier
2. TelegramSignalNotifier.from_env / from_config
3. Optional validation annotation when df passed
4. Watcher wires notifier
5. Tests with FakeTelegramTransport — assert message_id + body contains symbol

## Todo

- [ ] notify module
- [ ] fake transport test
- [ ] dry_run test
- [ ] disabled when no token

## Success criteria

- Test send returns message_id
- Dry-run never calls network
- Live path only when token set (manual Phase 05)

## Risks

| Risk | Mitigation |
|------|------------|
| Nested asyncio | document `asyncio.run` per send in sync watcher OR run watcher async |
| MarkdownV2 escape bugs | reuse proven formatter only |

## Next

Phase 05 — Mac deploy + live smoke
