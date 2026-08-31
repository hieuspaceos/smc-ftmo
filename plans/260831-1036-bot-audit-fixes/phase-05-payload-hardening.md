# Phase 05 — Payload Hardening

## Context

Audit finding H4 (High) + H6 (High) + M2 (Medium) + M3 (Medium) +
M4 (Medium) + L2 (Low).

- `H4`: `signal_id = SHA256(... level:{:.8f} ...)` — fine in theory
  but floats at 1e-8 sensitivity → 2 different signal_ids for what
  trader sees as the same OB. Multiple Accepts possible.
- `H6`: `_accept_signal` reconstructs payload with
  `received_at=datetime.now(...)`, overwriting original timestamp.
- `M2`: `parse_ack_callback` accepts any-length signal_id, including
  empty. Empty string can be passed to `gate_store.upsert`.
- `M3`: `AlertPayload.model_config = ConfigDict(frozen=False)` —
  mutable after parse. Risk of accidental mutation bypassing
  validators.
- `M4`: `record_event` payload truncation uses `errors="replace"` —
  safe but loses fidelity silently.
- `L2`: Body UTF-8 decode not covered by tests with non-ASCII Pine
  payloads.

## Goals

1. `signal_id` level rounded to broker tick (0.00001) before hash.
2. `AlertPayload` re-construction reads `received_at` from DB row.
3. `signal_id` length must equal 16 chars (hex).
4. `AlertPayload` is `frozen=True` (or `model_config(frozen=True)`).
5. `record_event` truncation logs warning with original size.
6. Add tests for non-ASCII payload (emoji, Vietnamese).

## Files to modify

- `packages/smc_bot_webhook/src/smc_bot_webhook/payload.py`:
  - `compute_signal_id` — `level=round(level, 5)` before format.
  - `AlertPayload.model_config` → `frozen=True`.
  - `parse_ack_callback` — `if len(signal_id) != 16: return None`.
  - `AlertPayload.model_construct` — accept `received_at` from kwargs
    instead of `now()`.
- `packages/smc_bot_webhook/src/smc_bot_webhook/server.py`:
  - `_accept_signal`, `_reject_signal` — read
    `alert["received_at"]` from row, pass to `model_construct`.
- `packages/smc_bot_core/src/smc_bot_core/db_impl.py`:
  - `record_event` — log original + truncated size.

## Files to create

- `packages/smc_bot_webhook/tests/test_payload_hardening.py`:
  - `test_signal_id_same_for_float_within_tick` — 1.10000 vs
    1.10000001 → same signal_id.
  - `test_signal_id_different_across_ticks` — 1.10000 vs 1.10001 →
    different.
  - `test_payload_frozen` — `payload.level = 1.2` raises.
  - `test_received_at_preserved_on_reconstruct` — read alert row,
    reconstruct, check `received_at` matches.
  - `test_ack_callback_rejects_short_signal_id` — `ack:risk_ok:abc`
    → None.
  - `test_payload_with_emoji_in_reason` — parse OK, raw preserved.
  - `test_payload_with_vietnamese` — parse OK.

## Implementation steps

1. Round `level` in `compute_signal_id`.
2. Set `frozen=True` on `AlertPayload`.
3. Length-check in `parse_ack_callback`.
4. Read `received_at` from row in `_accept_signal` and `_reject_signal`.
5. Improve `record_event` log.
6. Write tests.

## Todo

- [ ] Round level in `compute_signal_id`
- [ ] `frozen=True` on AlertPayload
- [ ] Length-check in `parse_ack_callback`
- [ ] Read `received_at` from row
- [ ] `record_event` size log
- [ ] Write tests (≥ 7 cases)

## Success criteria

- Existing `test_payload.py` still passes.
- New tests pass all.
- Manual: send `reason="Sweep 1.0 — test 🚀"`, receive alert with raw
  text preserved.

## Risk

- **`frozen=True` regression**: any code that mutates `payload.X` will
  fail. Mitigation: audit call sites; if any, refactor to
  `model_copy(update={...})`.
- **Level rounding change**: existing signal_ids in DB become
  unmatchable. Mitigation: only affects in-flight signals (≤ 1
  hour window for `signal-specific` gates). Accept re-validates
  anyway.

## Next steps

Phase 06 — Outbox + rate-limit + DB lifecycle.
