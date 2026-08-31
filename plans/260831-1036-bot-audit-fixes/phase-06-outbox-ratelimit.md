# Phase 06 — Outbox + Rate Limit + DB Lifecycle

## Context

Audit finding H1 (High) + H3 (High) + M5 (Medium) + L4 (Low) + L5
(Low) + L6 (Low).

- `H1`: `MT5_OUTBOX_DIR` accepted as any path. `OutboxWriter.__init__`
  blindly `mkdir(parents=True)` — pollutes user dirs, no symlink
  check, no ownership check.
- `H3`: `_RateLimiter._buckets` grows unbounded with unique fake IPs.
- `M5`: `os.replace` Windows semantics: not atomic across volumes,
  fails silently on SMB mount.
- `L4`: `_ThrottledLogger` key lacks reason context.
- `L5`: `/healthz` reads `validator._admin_override` private attr.
- `L6`: No cap on `pending/` files — disk can fill.

## Goals

1. Validate `MT5_OUTBOX_DIR` at startup: must be a directory the
   process can write to, not a symlink, ownership = current user.
2. LRU cap on `_RateLimiter._buckets` (default 10000, env
   `SMC_RATE_LIMIT_BUCKETS_MAX`).
3. Detect SMB/non-POSIX volume and log warning, fall back to
   copy+unlink.
4. Improve `_ThrottledLogger` key to include `from_user_id` and
   `action`.
5. Add `/api/admin/override` (admin only) to read override state
   via public API, remove private attr access in `/healthz`.
6. Cap `pending/` files at `SMC_OUTBOX_MAX_PENDING` (default 256).
   Beyond cap → refuse write + return `SignalAlreadyWrittenError`
   (caller treats as duplicate).

## Architecture

```
build_executor(EXECUTOR_TRANSPORT=file):
  ├─ resolve MT5_OUTBOX_DIR
  ├─ check not symlink
  ├─ check ownership = current uid
  ├─ check writable
  ├─ OutboxWriter(out_dir)
  └─ return FileBridgeExecutor(...)

OutboxWriter.__init__:
  ├─ mkdir pending/, processing/, done/, failed/
  └─ count files in pending/; if > MAX → refuse

OutboxWriter.write_atomic(sid, record):
  ├─ if is_pending(sid) or pending_count > MAX:
  │    raise SignalAlreadyWrittenError
  └─ tmp + fsync + replace (existing)

_RateLimiter.hit(key):
  ├─ if len(buckets) > MAX_BUCKETS:
  │    evict oldest (LRU)
  └─ bucket logic (existing)
```

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/executor.py`:
  - `_validate_outbox_dir(path) -> Path` — resolve, check not symlink,
    check ownership, check writable.
  - `build_executor` — call validator first, raise with clear msg.
- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/signal_writer.py`:
  - `OutboxWriter.__init__` — accept `max_pending` param, cap
    existing files.
  - `is_pending` — count files in `pending/` lazily.
  - `write_atomic` — pre-check cap.
  - `OutboxWriter.write_atomic` — detect SMB (`os.replace` fails on
    cross-volume), fall back to `shutil.copy` + `os.unlink` with
    warning log.
- `packages/smc_bot_webhook/src/smc_bot_webhook/server.py`:
  - `_RateLimiter.__init__` — accept `max_buckets` env, default 10000.
  - `_RateLimiter.hit` — LRU eviction.
  - `_ThrottledLogger.log` — accept `from_user_id` and `action` in
    key.
  - `/healthz` — use public method `validator.admin_override` instead
    of `_admin_override`.
  - Add `validator.admin_override` property.

## Files to create

- `packages/smc_bot_webhook/tests/test_outbox_validation.py`:
  - Reject symlink.
  - Reject non-existent (no auto-mkdir).
  - Reject non-writable.
  - Reject file (not dir).
  - Accept valid dir.
- `packages/smc_bot_webhook/tests/test_outbox_cap.py`:
  - 256 files in `pending/` → 257th write raises
    `SignalAlreadyWrittenError`.
- `packages/smc_bot_webhook/tests/test_rate_limiter.py`:
  - 10001 unique IPs hit → 10001st returns False (rate limit hit)
    or LRU evicts oldest (configurable).

## Implementation steps

1. Add `_validate_outbox_dir` helper.
2. Wire into `build_executor`.
3. Add `max_pending` to `OutboxWriter`.
4. Add SMB detection + fallback.
5. Add `max_buckets` to `_RateLimiter` + LRU.
6. Improve `_ThrottledLogger` key.
7. Add `validator.admin_override` property, update `/healthz`.
8. Write tests.

## Todo

- [ ] `_validate_outbox_dir` + executor integration
- [ ] `OutboxWriter.max_pending` cap
- [ ] SMB detection + fallback
- [ ] `_RateLimiter` LRU
- [ ] `_ThrottledLogger` key
- [ ] `validator.admin_override` public property
- [ ] Write tests (≥ 5 cases per file)

## Success criteria

- Existing tests still pass.
- New tests pass.
- Manual: set `MT5_OUTBOX_DIR=~/Documents` (no `pending/`) → bot
  refuses startup with clear error.

## Risk

- **LRU eviction timing**: under sustained DoS, attacker IPs evict
  legitimate user IPs. Mitigation: LRU on idle > 60s only.
- **SMB fallback correctness**: copy+unlink is not atomic. Mitigation:
  warn loudly; if trader uses SMB, switch to local mount + Syncthing.

## Next steps

Phase 07 — End-to-end smoke + rollback.
