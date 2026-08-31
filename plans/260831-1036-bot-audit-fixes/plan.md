# Plan — Bot Audit Fixes

> Hardening pass for `smc_bot_webhook` + `smc_bot_core` after full static
> audit on 2026-08-31. Findings: 4 Critical, 6 High, 8 Medium, 6 Low.
> Out of scope: SMC parity (already done in `993a829`), Pine ↔ Python
> displacement sync.

## Goal

Bring the live-trading bot from "demo-credible" to "safe for FTMO
challenge" by closing the Critical/High findings and shoring up the
Medium/Low items that compound risk.

## Constraints

- 100% backward compat with Pine `SMC|v1` payload — no breaking changes
  to the wire format.
- No new third-party deps. `requirements-bot.txt` stays the same.
- All fixes ship with a unit/integration test that reproduces the bug
  *before* the fix and passes *after*.
- `pytest packages/smc_bot_webhook/tests/ -q` must pass 100% (current
  baseline: unknown, measure first).
- Follow repo's existing module boundaries — fix in the package that
  owns the contract (gate logic in `gates/`, MT5 in `mt5_bridge/`, etc).

## Contract

### New env vars
| Var | Purpose | Default |
|---|---|---|
| `TELEGRAM_CALLBACK_SECRET` | Secret header required on `/telegram/*` | (none — required to enable) |
| `SMC_OUTBOX_MAX_PENDING` | Max files in `pending/` before refuse-write | 256 |
| `SMC_FTMO_GUARD_ENABLED` | Kill-switch for FTMO guard check (false = no-op) | true |
| `SMC_RATE_LIMIT_BUCKETS_MAX` | LRU cap for rate limiter | 10000 |

### New env config read
`ftmo_guard.from_config(config: dict)` reads `ftmo.max_daily_loss`,
`risk.per_trade_pct`, `risk.daily_loss_limit_r` instead of hardcoded
constants.

### API contract
- `POST /telegram/callback` and `POST /telegram/command` now require
  header `X-Telegram-Bot-Api-Secret-Token: <TELEGRAM_CALLBACK_SECRET>`.
  Missing/wrong header → 401.
- Webhook body cap raised 4 KB → 8 KB.
- `TelegramDispatcher._do_send` switches `parse_mode` to
  `MarkdownV2` + escapes free text (`symbol`, `tf`, `dir`, `reason`,
  `state`).
- `SignalRecord` writes use `Decimal` for `level/sl/tp` rounded to 5
  digits (5-digit broker tick = 0.00001).
- `AlertPayload.model_config` → `frozen=True`.
- `gate_store.clear_signal_specific()` moves **after**
  `executor.execute()` success.

## Phases

1. **[Auth hardening](phase-01-telegram-callback-auth.md)** — C2, H5
   partial, M1, L1.
2. **[FTMO guard real impl](phase-02-ftmo-guard-real.md)** — C1, H2.
3. **[Accept ordering + idempotency](phase-03-accept-ordering.md)** —
   C3, M7, L3.
4. **[Telegram MarkdownV2 + escape](phase-04-telegram-markdownv2.md)** —
   C4, M6, M8.
5. **[Payload hardening](phase-05-payload-hardening.md)** — H4, H6,
   M2, M3, M4, L2.
6. **[Outbox + rate-limit + DB lifecycle](phase-06-outbox-ratelimit.md)** —
   H1, H3, M5, L4, L5, L6.
7. **[End-to-end smoke + rollback](phase-07-smoke-rollback.md)** — gate
   all 6 phases with integration test + manual rehearsal.

## Acceptance

- `pytest packages/smc_bot_webhook/tests/ -q` → all pass, ≥ 1 new test
  per finding.
- Audit findings 1-4 (Critical) and 5-10 (High) all closed.
- Manual rehearsal: webhook can receive an alert, dispatch Telegram,
  receive Accept callback (with new secret), write outbox, EA picks up,
  result back to DB.
- Bot **refuses** to start if `SMC_WEBHOOK_TOKEN` is shorter than 32
  chars (raise early, not 16).
- Bot **refuses** to start if `EXECUTOR_TRANSPORT=file` and
  `TELEGRAM_CALLBACK_SECRET` unset (chain of trust broken).

## Status snapshot

| # | Finding | Phase | Severity |
|---|---|---|---|
| C1 | FTMO guard stub | 02 | Critical |
| C2 | Telegram callback no auth | 01 | Critical |
| C3 | Gate clear before execute | 03 | Critical |
| C4 | Markdown parse_mode unsafe | 04 | Critical |
| H1 | Outbox path unsafe | 06 | High |
| H2 | FTMO config mismatch | 02 | High |
| H3 | Rate limiter leak | 06 | High |
| H4 | signal_id float precision | 05 | High |
| H5 | Telegram retry blocks loop | 04 | High |
| H6 | received_at overwritten | 05 | High |
| M1..M8 | Various | 01-06 | Medium |
| L1..L6 | Various | 01-06 | Low |

## Dependencies

- All phases can be merged independently except:
  - Phase 02 reads `config.yaml` (already exists) — no new dep.
  - Phase 04 needs Phase 01 if we want unified secret handling — but
    can ship independently.
  - Phase 07 needs 01-06 done.
- Recommended merge order: 01 → 02 → 03 → 04 → 05 → 06 → 07.

## Risk

- Telegram secret change is a **breaking change** for any running
  bot. Mitigation: log loudly on missing secret, doc the upgrade path
  in `docs/mt5-bridge-setup.md`.
- Decimal migration in Phase 05 may regress backtest floats — run
  `pytest packages/ -q` after Phase 05.

## Next step

Approve this plan → start Phase 01.
