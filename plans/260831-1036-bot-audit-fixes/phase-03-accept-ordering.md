# Phase 03 — Accept Ordering + Idempotency

## Context

Audit finding C3 (Critical) + M7 (Medium) + L3 (Low).

- `C3`: `_accept_signal` clears signal-specific gates **before**
  calling executor. If executor fails, the next signal arrives with
  cleared ack and the trader must re-ack. Worse: 2 concurrent Accept
  callbacks on the same `signal_id` can both pass validation if the
  state read happens between clear+execute.
- `M7`: `dispatcher.edit_signal` failure is logged but not retried.
  Telegram message keeps old Accept/Reject buttons, trader can
  double-click.
- `L3`: `OutboxWriter.is_pending` race with EA rename.

## Goals

1. `gate_store.clear_signal_specific()` runs **after** executor
   success.
2. Per-`signal_id` asyncio lock to serialize Accept calls.
3. `edit_signal` retries once with 1s backoff, then marks `edit_failed`.
4. `is_pending` uses a sentinel file (`.lock`) instead of
   `.exists()` to avoid EA-rename race.

## Architecture

```
Telegram Accept callback
  │
  ▼
_acquire_signal_lock(signal_id)  ── per-signal_id asyncio.Lock (LRU 1024)
  │
  ├─ re-validate gates
  ├─ edit Telegram message (mark "Accepting...")
  ├─ executor.execute(record)        ← can fail
  ├─ on success: clear_signal_specific() + record_decision(accept)
  └─ on failure: record_decision(reject) + edit message "failed"
```

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/server.py`:
  - Add `_signal_locks: dict[str, asyncio.Lock]` in `app.state`,
    LRU cap 1024.
  - `_acquire_signal_lock(signal_id)` — context manager that creates
    lock if missing, evicts oldest if over cap.
  - `_accept_signal` — wrap in lock, move `clear_signal_specific` to
    after executor success branch.
- `packages/smc_bot_webhook/src/smc_bot_webhook/notify/telegram.py`:
  - `_edit_with_retry` private method, 1 retry with 1s sleep.
- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/signal_writer.py`:
  - `is_pending` — check for `<sid>.lock` sentinel file in addition
    to `.json`. Acquire: write `.lock` with O_EXCL before
    `write_atomic`. Release: rename to `.json`, leave `.lock` for EA
    to delete.

## Files to create

- `packages/smc_bot_webhook/tests/test_accept_ordering.py`:
  - Test `clear_signal_specific` is **not** called on executor failure.
  - Test 2 concurrent Accepts on same `signal_id` serialize
    (second waits or refuses).
  - Test `_edit_with_retry` retries once.
  - Test `OutboxWriter.is_pending` sees `.lock` sentinel.
  - Test LRU cap evicts oldest lock.

## Implementation steps

1. Add `_signal_locks` state + `_acquire_signal_lock` helper.
2. Refactor `_accept_signal` to use lock and move
   `clear_signal_specific` after success.
3. Add `_edit_with_retry` to `TelegramDispatcher`.
4. Add `.lock` sentinel logic to `OutboxWriter`.
5. Write tests.

## Todo

- [ ] Per-signal-id lock state + helper
- [ ] Refactor `_accept_signal` ordering
- [ ] `_edit_with_retry` in TelegramDispatcher
- [ ] `.lock` sentinel in OutboxWriter
- [ ] Write tests (≥ 5 cases)

## Success criteria

- `test_mt5_bridge.py::TestWebhookAcceptExecutesSignal` still passes.
- New tests pass 5/5.
- Manual: simulate executor raising → confirm `clear_signal_specific`
  not called, next signal still has stale ack (correct behavior).

## Risk

- **Lock leak**: if request handler crashes mid-Accept, lock held
  until process restart. Mitigation: per-request timeout on lock
  acquire (5s) via `asyncio.wait_for`.
- **LRU eviction race**: lock evicted while another coroutine holds
  it. Mitigation: use `weakref.WeakValueDictionary` instead of LRU.
  Refactor: locks are coroutine-scoped, store per-signal-id in
  `asyncio.Lock` factory.

## Next steps

Phase 04 — Telegram MarkdownV2.
