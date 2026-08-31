# Bot Webhook Audit Report — 2026-08-31

> Static review of `smc_bot_webhook` (server, payload, security,
> gates/{state,validator}, notify/{telegram,discord,formatting},
> mt5_bridge/{executor,signal_writer,ftmo_guard}) and
> `smc_bot_core/db_impl.py`. ~2k LOC, 7 test files.
>
> **Result**: 4 Critical, 6 High, 8 Medium, 6 Low.
> **Verdict**: Bot is **not safe** for live FTMO trading in current
> state. C1 + C2 are show-stoppers. C3 + C4 are high-probability
> misses during normal operation.
>
> Fix plan: `plans/260831-1036-bot-audit-fixes/plan.md`

## Top 4 Critical

### C1. FTMO guard always passes (stub)
`ftmo_guard.build_guard_state_from_db` returns zeros. `_execute_via_executor`
hardcodes `GuardState(0, 0, {})`. Result: **no trade is ever blocked by
the FTMO guard**, even at -2R daily loss or 3rd trade of the day.

**File**: `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/ftmo_guard.py:123-136`
**File**: `packages/smc_bot_webhook/src/smc_bot_webhook/server.py:353`

### C2. Telegram callback no real auth
`_verify_source` only checks IP + URL secret. `from_user_id` comes from
request body. Anyone with `SMC_WEBHOOK_TOKEN` + TradingView IP can POST
`{"callback_data":"accept:<sid>:<nonce>","from_user_id":12345}` to force
execute a trade.

**File**: `packages/smc_bot_webhook/src/smc_bot_webhook/server.py:266-317`

### C3. Gate clear before execute
`_accept_signal` calls `gate_store.clear_signal_specific()` **before**
`executor.execute()`. If executor fails, the trader must re-ack. Worse,
2 concurrent Accepts on the same signal_id can both pass.

**File**: `packages/smc_bot_webhook/src/smc_bot_webhook/server.py:460-465`

### C4. Telegram parse_mode="Markdown" unsafe
Pine payload free-text fields (`reason`, `state`) may contain
`_*[]()` etc. Telegram API 400 → 3 retries fail → `notified_failed`.
Trader misses valid alert.

**File**: `packages/smc_bot_webhook/src/smc_bot_webhook/notify/telegram.py:332`

## High (6)

### H1. Outbox path unsafe
`OutboxWriter.__init__` blindly mkdir on `MT5_OUTBOX_DIR`. No symlink
check, no ownership check, no writability check. Pollutes user dirs;
fails on SMB mount without clear error.

**File**: `mt5_bridge/executor.py:104-106` + `signal_writer.py:158-160`

### H2. FTMO config mismatch
`FtmoGuard()` hardcodes `-0.011` (1.1% = -2R of 0.55% risk), but
`config.yaml` says `max_daily_loss: 0.05` (5% FTMO). Two different
semantics. Server doesn't read yaml.

**File**: `server.py:585` + `ftmo_guard.py:23`

### H3. Rate limiter memory leak
`_RateLimiter._buckets` grows unbounded. Attacker with many fake IPs
→ O(N) memory.

**File**: `server.py:117-133`

### H4. signal_id float precision
`compute_signal_id` hashes `level:{:.8f}`. Two near-identical levels
(1.10000 vs 1.10000001) → different signal_ids → 2 accepts possible
for what trader sees as same OB.

**File**: `payload.py:112-139`

### H5. Telegram retry blocks loop
`_do_send` 1-2-4s = 7s blocking per alert. 10 alerts burst → 70s
queue. No concurrency cap.

**File**: `notify/telegram.py:325-348`

### H6. received_at overwritten on reconstruct
`_accept_signal` re-builds payload with `received_at=now()` instead of
reading from alert row. Audit timestamps wrong.

**File**: `server.py:431`, `server.py:505`

## Medium (8)

- **M1**: `_ThrottledLogger` log key lacks reason context.
- **M2**: `parse_ack_callback` accepts empty signal_id.
- **M3**: `AlertPayload.model_config = ConfigDict(frozen=False)` — mutable.
- **M4**: `record_event` truncation uses `errors="replace"` silently.
- **M5**: `os.replace` Windows semantics — fails on SMB volume.
- **M6**: Discord mirror no client-side rate limit.
- **M7**: `dispatcher.edit_signal` failure not retried → double Accept possible.
- **M8**: Body cap 4 KB too small for richer payloads.

## Low (6)

- **L1**: `AppSettings.from_env` raises plain RuntimeError on missing token.
- **L2**: Non-ASCII payload not covered by tests.
- **L3**: `OutboxWriter.is_pending` races with EA rename.
- **L4**: `_ThrottledLogger` key uses monotonic time, no reason context.
- **L5**: `/healthz` reads `validator._admin_override` private attr.
- **L6**: No cap on `pending/` files — disk fill on EA outage.

## Top 4 to fix before live

1. **C1** — guard is stub; bot approves every signal.
2. **C2** — anyone with URL secret can force-execute.
3. **C3** — race on double Accept.
4. **C4** — trader misses alerts on special chars.

## Plan reference

- `plans/260831-1036-bot-audit-fixes/plan.md` (overview, 7 phases)
- `plans/260831-1036-bot-audit-fixes/phase-01..07-*.md` (per-phase spec)

## Constraints

- 100% backward compat with Pine `SMC|v1` payload.
- No new third-party deps.
- All fixes ship with reproducer test that fails before fix,
  passes after.
