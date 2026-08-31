# Phase 07 — End-to-End Smoke + Rollback Plan

## Context

All 6 prior phases must be validated together before declaring the
audit fix complete. This phase adds the rehearsal + safety net.

## Goals

1. Integration test: webhook → Telegram → Accept → MT5 outbox →
   done poll → DB updated.
2. Failure injection test: executor fails → gates not cleared,
   message edited to "failed".
3. Manual rehearsal script (markdown checklist).
4. Rollback plan if any phase regresses prod.

## Architecture

```
Test: test_end_to_end_accept.py
  1. Build TestClient with real components
     (no mocking executor, no mocking telegram).
  2. POST /webhooks/tradingview → 202.
  3. Simulate Telegram Accept callback (POST /telegram/callback
     with new secret header).
  4. Assert:
     - execution_log row state='queued' (or 'filled' if EA mocked).
     - alert_log row state unchanged.
     - Telegram message was edited.
     - gate_ack signal-specific rows cleared AFTER success.
  5. Failure variant: patch executor.execute to raise.
     Assert:
     - execution_log state='failed' or row absent.
     - gate_ack NOT cleared.
     - Telegram message edited to "failed".

Manual: docs/smoke-test-bot.md
  - 1. Start uvicorn with .env filled
  - 2. POST sample alert via curl
  - 3. Verify Telegram message
  - 4. Click Accept inline button
  - 5. Verify outbox file written
  - 6. (Optional) Run MT5 EA in demo, verify /done/ file
  - 7. Verify execution_log row state='filled'
  - 8. Verify dashboard reads new state
```

## Files to modify

- `docs/mt5-bridge-setup.md` — add `smoke-test-bot.md` reference.
- `docs/smoke-test-bot.md` — new file with manual checklist.
- `README.md` — note "Run smoke test before first live trade".

## Files to create

- `packages/smc_bot_webhook/tests/test_end_to_end_accept.py`:
  - `test_accept_happy_path_writes_outbox`.
  - `test_accept_failure_path_keeps_gates`.
  - `test_concurrent_accepts_serialize`.
  - `test_double_accept_idempotent` (second hits lock, sees state
    changed, refuses).
- `docs/smoke-test-bot.md` — manual runbook.

## Implementation steps

1. Write integration test 1 (happy path).
2. Write integration test 2 (failure path).
3. Write integration test 3 (concurrent).
4. Write manual runbook.
5. Update README.
6. Update changelog.
7. Update roadmap.

## Todo

- [ ] Integration test happy path
- [ ] Integration test failure path
- [ ] Integration test concurrent
- [ ] Manual runbook
- [ ] README update
- [ ] Changelog + roadmap

## Success criteria

- All 4 new integration tests pass.
- All existing tests pass (regression-free).
- Manual runbook executable in < 10 min on a fresh VM.
- Coverage report for `smc_bot_webhook` ≥ 80% (target).

## Risk

- **Test flakiness**: integration test with real SQLite + asyncio
  can have ordering issues. Mitigation: use `pytest-asyncio` strict
  mode, deterministic time fixtures.
- **Manual runbook drift**: docs go stale. Mitigation: link the
  runbook to a CI check that verifies mentioned env vars exist in
  `.env.example`.

## Rollback

If any phase regresses prod:

1. **Phase 01-04 (auth, guard, ordering, markdown)**: server refuses
   to start without new env vars. Old `.env` fails fast → restore
   previous image.
2. **Phase 05 (payload hardening)**: `frozen=True` may break code
   that mutated payload. Mitigation: rollback commit + re-fix
   incrementally.
3. **Phase 06 (outbox)**: `MT5_OUTBOX_DIR` validation may reject
   legitimate paths. Mitigation: `SMC_OUTBOX_SKIP_VALIDATION=1`
   kill-switch (added in this phase).

Each phase ships as a separate commit, not a squash, so `git revert
<sha>` is precise.

## Next steps

- Approve plan.
- Phase 01 starts.
- Each phase ends with `git commit` + push to feature branch.
- Phase 07 ends with merge to master + tag `v0.4.0-audit-fixed`.
