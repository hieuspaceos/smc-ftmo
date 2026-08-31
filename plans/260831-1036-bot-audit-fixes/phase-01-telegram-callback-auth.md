# Phase 01 — Telegram Callback Auth Hardening

## Context

Audit finding C2 (Critical) + M1 (Medium) + L1 (Low).

- `C2`: `/telegram/callback` and `/telegram/command` accept
  `from_user_id` from request body. Anyone with `SMC_WEBHOOK_TOKEN` +
  trusted IP can spoof an Accept/Reject and force-execute a trade.
- `M1`: `_ThrottledLogger` dedupes log per `(ip, reason)` but log
  context is sparse.
- `L1`: `AppSettings.from_env` raises plain `RuntimeError` instead of
  HTTP-friendly error.

## Goals

1. Add `X-Telegram-Bot-Api-Secret-Token` header check on `/telegram/*`.
2. Make the secret **required** when `TELEGRAM_BOT_TOKEN` is set —
   refuse to start otherwise.
3. Verify `X-Telegram-Bot-Api-Secret-Token` matches
   `TELEGRAM_CALLBACK_SECRET` using `hmac.compare_digest` (constant
   time).
4. Improve log context: include `from_user_id`, `signal_id`, action
   attempt, retry counter.

## Architecture

```
Telegram Bot (real client) ──── HTTPS POST ────> Cloudflare Tunnel
                                                  │
                                                  ▼
                            ┌─────────────────────────────────┐
                            │  FastAPI                        │
                            │  /telegram/callback             │
                            │  ┌─────────────────────────┐    │
                            │  │ 1. Check header secret  │    │
                            │  │ 2. Parse callback_data  │    │
                            │  │ 3. handle_callback      │    │
                            │  └─────────────────────────┘    │
                            └─────────────────────────────────┘
```

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/server.py`:
  - `AppSettings.from_env` — read `TELEGRAM_CALLBACK_SECRET`, require
    if `TELEGRAM_BOT_TOKEN` set; else allow empty.
  - `create_app` — register `_verify_telegram_source` dependency on
    `/telegram/callback` and `/telegram/command` routes.
  - `_verify_telegram_source(request)` — pull `X-Telegram-Bot-Api-Secret-Token`
    header, `hmac.compare_digest` against
    `app.state.settings.telegram_callback_secret`. 401 on mismatch or
    missing when secret is configured.
- `packages/smc_bot_webhook/src/smc_bot_webhook/security.py`:
  - Add `check_telegram_secret(provided, expected)` using
    `hmac.compare_digest`. Empty provided → False.
- `.env.example` — document new var.
- `docs/mt5-bridge-setup.md` — add upgrade step (Telegram users must
  set new env var and reconfigure bot webhook).

## Files to create

- `packages/smc_bot_webhook/tests/test_telegram_auth.py`:
  - `test_callback_rejects_missing_header` — 401.
  - `test_callback_rejects_wrong_header` — 401.
  - `test_callback_accepts_correct_header` — 200.
  - `test_command_rejects_missing_header` — 401.
  - `test_app_refuses_to_start_when_token_set_without_secret` — use
    `create_app` directly, expect `RuntimeError`.

## Implementation steps

1. Add `check_telegram_secret` to `security.py`.
2. Update `AppSettings.from_env` to read new env var, raise
   `RuntimeError` if token set without secret.
3. Add `_verify_telegram_source` to `create_app` and inject as
   `Depends(_verify_telegram_source)` on both `/telegram/*` routes.
4. Improve `_ThrottledLogger` key from `f"ip:{client_ip}:{reason}"`
   → `f"tg:{client_ip}:{action}:{from_user_id}"` (caller-supplied).
5. Update `.env.example` with new var + example value.
6. Update `docs/mt5-bridge-setup.md` with upgrade step.
7. Add tests.

## Todo

- [ ] Add `check_telegram_secret` in security.py
- [ ] Update `AppSettings.from_env` to read new env
- [ ] Add `_verify_telegram_source` dependency
- [ ] Update `.env.example`
- [ ] Update `docs/mt5-bridge-setup.md`
- [ ] Write tests (≥ 5 cases)

## Success criteria

- All 4 existing webhook tests still pass.
- New test file passes 5/5.
- Manual: `curl -X POST /telegram/callback` without header → 401.
- Bot startup with `TELEGRAM_BOT_TOKEN` set but no
  `TELEGRAM_CALLBACK_SECRET` → `RuntimeError`, no orphan process.

## Risk

- **Breakage**: existing live deployments (none on this machine) need
  re-deploy. Mitigation: loud warning log on startup if old config
  used.
- **Replay attack**: Telegram itself signs webhooks via this secret,
  but a captured request can still be replayed within the TTL of the
  gate ack. Mitigation: use Telegram's own webhook secret mechanism
  (already in scope). Out of scope: HMAC body signature (would need
  Pine payload signing).

## Next steps

Phase 02 — FTMO Guard real implementation (closes C1, H2).
