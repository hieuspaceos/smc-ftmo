# Phase 04 — Telegram MarkdownV2 + Retry Backpressure

## Context

Audit finding C4 (Critical) + H5 (High) + M6 (Medium) + M8 (Medium).

- `C4`: Telegram `parse_mode="Markdown"` (legacy) is fragile. Pine
  payload fields like `reason`, `state`, `symbol` may contain
  `_ * [ ] ( )` etc., causing Telegram API 400. Bot retries 3×, then
  `notified_failed`. Trader misses valid alerts.
- `H5`: `_do_send` retry 1-2-4s = 7s blocking per alert. No
  concurrency cap. Burst of alerts can stall event loop.
- `M6`: Discord mirror has no client-side rate limit. 5+ alerts/min
  triggers Discord 429 → retry storm.
- `M8`: Body cap 4 KB too small for richer payloads.

## Goals

1. Switch Telegram to `MarkdownV2` with full free-text escape.
2. Add per-dispatcher send semaphore (max 5 concurrent).
3. Discord client-side rate limit (5 msg / 10s).
4. Body cap raised to 8 KB.

## Architecture

```
format_telegram_message(payload, gate_states):
  ├─ free-text fields: payload.symbol, payload.tf, payload.dir,
  │   payload.state, payload.reason, gate_states
  │   → pass through _md2_escape()
  ├─ structured fields: payload.level, payload.bar_time, payload.ob_id,
  │   payload.bos_id, payload.signal_id
  │   → wrap in inline code (`...`)
  └─ return escaped MarkdownV2 text

_do_send(payload, text, keyboard):
  ├─ acquire semaphore (max 5)
  ├─ try transport.send_message(parse_mode='MarkdownV2')
  ├─ on failure: backoff 1-2-4s (existing)
  └─ on success / final fail: release semaphore
```

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/notify/formatting.py`:
  - Add `_md2_escape(s: str) -> str` — escape
    `_*[]()~`>`#+-=|{}.!` per Telegram MarkdownV2 spec.
  - `format_telegram_message` — escape free-text fields, wrap
    structured fields in `` ` ``.
  - `build_inline_keyboard`, `build_ack_keyboard` — already use dict
    format, no change needed.
- `packages/smc_bot_webhook/src/smc_bot_webhook/notify/telegram.py`:
  - `TelegramDispatcher.__init__` — add `send_semaphore:
    asyncio.Semaphore(5)`.
  - `_do_send` — wrap in `async with self._send_semaphore:`.
  - Switch `parse_mode="MarkdownV2"`.
- `packages/smc_bot_webhook/src/smc_bot_webhook/notify/discord.py`:
  - `DiscordMirror.__init__` — add `rate_limiter` state.
  - `send_signal` — pre-check + post-sleep to stay under 5 msg / 10s.
- `packages/smc_bot_webhook/src/smc_bot_webhook/security.py`:
  - `DEFAULT_BODY_MAX_BYTES` 4096 → 8192.

## Files to create

- `packages/smc_bot_webhook/tests/test_formatting.py`:
  - `_md2_escape` test: `_*[]()~`>`#+-=|{}.!` all escaped.
  - `format_telegram_message` test: free text escaped, structured
    fields in inline code.
- `packages/smc_bot_webhook/tests/test_telegram_semaphore.py`:
  - 10 concurrent `send_signal` calls — at most 5 run in parallel
    (use mocked transport with sleep).
- `packages/smc_bot_webhook/tests/test_discord_rate.py`:
  - 10 messages sent in 1s — 5 succeed, 5 sleep then succeed.

## Implementation steps

1. Add `_md2_escape` to formatting.py.
2. Refactor `format_telegram_message` to use it.
3. Add `send_semaphore` to `TelegramDispatcher`.
4. Wrap `_do_send` in semaphore.
5. Switch parse_mode to `MarkdownV2`.
6. Add Discord client rate limit.
7. Bump `DEFAULT_BODY_MAX_BYTES`.
8. Write tests.

## Todo

- [ ] `_md2_escape` + formatter refactor
- [ ] Telegram send_semaphore
- [ ] parse_mode = MarkdownV2
- [ ] Discord rate limit
- [ ] Body cap 4 KB → 8 KB
- [ ] Write tests (≥ 4 cases per file)

## Success criteria

- Existing `test_notify.py` (21 KB) still passes — no message
  regression.
- New tests pass all.
- Manual: send an alert with `reason="Sweep_/_test_"` and verify
  Telegram receives escaped string.
- Load test: 20 alerts in 1s, all delivered within 10s, no 429 from
  Discord.

## Risk

- **MarkdownV2 stricter**: any existing message template that works
  in legacy Markdown may break. Mitigation: existing test_notify
  snapshots must be regenerated.
- **Semaphore deadlock**: if semaphore never released (transport
  never returns), all sends block forever. Mitigation: per-send
  timeout (10s) via `asyncio.wait_for`.

## Next steps

Phase 05 — Payload hardening.
