# Phase 03: 11-Gate Rulebook Validator + Manual Ack

## Context

- [Plan](./plan.md)
- Depends on [Phase 02](./phase-02-bot-storage-and-telegram.md) — Telegram dispatcher + storage

## Goal

Wire 11 gates (5 chart + 6 manual) rule book đã lock. Accept callback revalidates gates trước khi mark accepted. Auto-trade chỉ khi tất cả 11 gates pass.

## Requirements

### Gate validator (`bot/gates/validator.py`)

- [ ] 11 gates implementation:
  - **Chart (auto, từ Pine payload)**:
    1. Symbol = EURUSD (P0)
    2. Timeframe = M15 (P0)
    3. Pine state = chart-qualified/watch (not blocked/no-signal)
    4. Direction exists + maps to long/short
    5. OB + BOS provenance exists for trade event
  - **Manual (từ Telegram ack)**:
    6. Freshness window (≤5 min, configurable)
    7. Risk 0.55% acknowledged
    8. Trades today left (>0)
    9. Daily loss -2R acknowledged OR not breached
    10. No open position (Telegram + executor position when available)
    11. Spread/news clean + trader judgment clear

- [ ] Return one of: `notify_only`, `needs_manual_ack`, `blocked`, `accepted_ready`, `expired`
- [ ] Pine backend re-checks chart gates trước khi Accept (don't trust Telegram state)
- [ ] Daily gates reset at NY session boundary
- [ ] Signal-specific gates (no_position, spread_news, judgment) expire after 10 min OR one Accept/Reject
- [ ] Accept callback re-runs validator (button state is presentation only)

### Gate state persistence (`bot/gates/state.py`)

- [ ] `gate_ack` table writes per-day gate status
- [ ] Daily reset: query gate_ack WHERE trade_date = today; expire if old
- [ ] Manual ack flow: Telegram command `/ack <gate_name>` or inline button

### Telegram ack flow

- [ ] When signal arrives: show 6 manual gates status (✓/✗/stale)
- [ ] If any manual gate false: Telegram message shows checklist + Ack buttons per gate
- [ ] After all 6 acked: show `[Accept]` `[Reject]` enabled
- [ ] Accept requires re-validation: re-query gate_ack freshness

## Files to Create/Modify

- Create: `bot/gates/__init__.py`, `bot/gates/validator.py`, `bot/gates/state.py`
- Modify: `bot/notify/telegram.py` (gate checklist rendering, ack handlers)
- Modify: `bot/webhook/server.py` (call validator before enqueue)
- Create: `tests/test_bot_gates.py`

## Implementation Steps

1. **Gate enum + chart gate logic** (2h): pure functions, take AlertPayload, return bool
2. **Manual gate state** (2h): query gate_ack, check freshness, persist new acks
3. **Validator orchestration** (3h): combine chart + manual, return decision enum
4. **Telegram ack UI** (3h): checklist render, ack buttons per gate, status check
5. **Accept revalidation** (2h): on Accept callback, re-run validator, mark accepted/blocked
6. **Daily reset** (1h): NY session boundary cron-like check on each query
7. **Tests** (2h): unit (each gate), integration (full flow with stale gates)

## Tests

- `tests/test_bot_gates.py`:
  - Chart gates: valid payload → True; wrong symbol → False; blocked state → False; missing ob_id → False
  - Manual gates: stale ack → False; fresh ack → True; expiry edge cases
  - Validator: notify_only when chart ok + manual partial; accepted_ready when all 11 True; blocked when chart fail; expired when stale

## Risks and Rollback

- **Risk**: Stale manual ack allows old Accept
  - **Mitigation**: Accept callback re-queries gate_ack; if any stale, refuse + edit message
- **Risk**: Time zone bugs in NY session boundary
  - **Mitigation**: use `datetime.now(NY_TZ)` consistently; unit tests around midnight
- **Rollback**: set `EXECUTOR_TRANSPORT=disabled`; manual accept still works but no execution

## Unresolved Questions

- NY session boundary chính xác 17:00 EST hay 17:00 ET (DST)?
- Gate ack window default 5 phút cho live signals, 10 phút cho signal-specific — đúng chưa?
- Có cần admin override (skip gates for testing)?
