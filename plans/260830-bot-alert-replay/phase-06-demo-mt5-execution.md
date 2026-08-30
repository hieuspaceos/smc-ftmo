# Phase 06: Demo MT5 Execution (File-Based Bridge)

## Context

- [Plan](./plan.md)
- Depends on [Phase 03](./phase-03-rulebook-gate-validator.md) stable 4-8 weeks + Telegram Accept flow proven

## Goal

Accept signal → file-based MT5 bridge (user đã chọn: free, gọn) → MQL5 EA đọc outbox JSON → execute trên MT5 Demo (Windows/VPS/VM terminal). Demo-only, 0.01 lot test order, FTMO guard.

**User decision 2026-08-30**: **File-based bridge preferred** (zero cost) thay vì MetaAPI cloud (có free tier nhưng vẫn cần account + có thể có giới hạn). MetaAPI chỉ optional fallback nếu user không có MT5 terminal trên Windows/VPS/VM.

## Requirements

### Signal writer (`bot/mt5_bridge/signal_writer.py`)

- [ ] Default **disabled** cho tới khi `EXECUTOR_TRANSPORT=file`
- [ ] Outbox folders: `pending/`, `processing/`, `done/`, `failed/`
- [ ] Atomic write contract:
  1. Write JSON to `pending/<sid>.json.tmp`
  2. `fsync` file
  3. Rename to `pending/<sid>.json`
  4. MQL5 reader only opens `.json` (never `.tmp`)
- [ ] Signal JSON schema (`SMC_EXECUTION_V1`):
  ```json
  {
    "schema": "SMC_EXECUTION_V1",
    "signal_id": "...",
    "symbol": "EURUSD",
    "side": "long",
    "entry": 1.1000,
    "sl": 1.0950,
    "tp": [1.1100, 1.1150, 1.1200],
    "risk_pct": 0.0055,
    "bar_time": "2026-08-30T12:00:00Z",
    "expires_at": "2026-08-30T12:05:00Z",
    "ob_id": 123,
    "bos_id": 456,
    "approved_by": "telegram_user_id"
  }
  ```
- [ ] Idempotency: write `done/<sid>.json` after MQL5 ACK; reject duplicate signal_id from being written twice

### MQL5 reader EA (`bot/mt5_bridge/mql5_reader.mq5`)

- [ ] Polls `pending/` folder every N seconds (default 5s)
- [ ] Validates:
  - Schema = `SMC_EXECUTION_V1`
  - `expires_at` not passed
  - Symbol in allowlist (EURUSD only P0)
  - signal_id not in processed list
  - AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO (refuse non-demo)
- [ ] Volume: respect min/max lot + max cap (default 0.01 test lot, hard cap 0.05)
- [ ] Magic number: per-symbol constant (e.g., 990001 for EURUSD)
- [ ] Comment: include signal_id cho audit
- [ ] OrderSend → write ACK to `done/<sid>.json` with MT5 ticket, fill price, timestamp
- [ ] Persist processed signal_id list to file (avoid duplicate execution on EA restart)

### File bridge prerequisites (user cần chuẩn bị)

- [ ] MT5 Demo account opened (broker nào cũng được — IC Markets, Pepperstone, FTMO Demo)
- [ ] MT5 terminal chạy trên **Windows**, **VPS**, hoặc **Mac VM (Parallels/VMware/VirtualBox)**
- [ ] Shared folder accessible between MT5 terminal và FastAPI host:
  - **Option A**: Cùng máy → folder local
  - **Option B**: SMB share (Windows VPS + local Mac)
  - **Option C**: Syncthing / Dropbox folder (sync giữa 2 máy)
- [ ] EA `mql5_reader.mq5` compiled + attached to 1 chart (any symbol)

### Executor transport feature flag

- [ ] `EXECUTOR_TRANSPORT=disabled|file|metaapi`
- [ ] Default `disabled` until manual approval flow proven
- [ ] Switch via env var; no code change to flip
- [ ] MetaAPI executor stubbed nhưng disabled mặc định (optional future)

### FTMO guard integration

- [ ] Daily loss -2R check before order (compute from execution_log)
- [ ] 3 trades/day max (counter from execution_log)
- [ ] 1 open position per symbol (from EA position query + backend state)
- [ ] Backend refuses new signal if guard breached

## Files to Create/Modify

- Create: `bot/mt5_bridge/__init__.py`, `bot/mt5_bridge/signal_writer.py`, `bot/mt5_bridge/mql5_reader.mq5`
- Modify: `bot/gates/validator.py` (add open_position check hook)
- Modify: `bot/storage/schema.sql` (execution_log fields if missing)
- Create: `tests/test_bot_signal_writer.py`
- Create: `docs/mt5-bridge-setup.md` (user guide cho setup shared folder + EA)

## Implementation Steps

1. **Signal writer** (3h):
   - Atomic JSON write với fsync
   - Schema validation
   - Idempotency (track written signal_ids in SQLite)
   - Move to `processing/` khi write done

2. **MQL5 reader skeleton** (4h):
   - EA polls outbox
   - Validate schema + expiry + symbol + duplicate
   - Check demo account
   - OrderSend with magic number + comment
   - ACK file

3. **Feature flag wiring** (1h): env-based transport selector (disabled default)

4. **FTMO guard** (2h):
   - Daily loss counter từ execution_log
   - Trades today counter
   - Open position check
   - Backend refuses if guard breached

5. **MQL5 compile + attach** (1h):
   - User compiles `mql5_reader.mq5` trong MetaEditor
   - Attach to any EURUSD chart
   - Verify polling logs

6. **Test execution on demo** (2h):
   - 0.01 lot EURUSD long
   - Verify file moves `pending/` → `processing/` → `done/`
   - Verify Telegram confirmation message
   - Verify dashboard shows executed row

7. **User setup docs** (1h):
   - Step-by-step guide for shared folder + EA compile + account config
   - Troubleshooting checklist

## Tests

- `tests/test_bot_signal_writer.py`:
  - Atomic write: `.tmp` never visible; duplicate signal_id rejected
  - Schema validation: missing field → reject
  - Expiry: expired signal_id → reject (TTL passed)
- Manual MQL5 dry-run:
  - EA reads sample JSON → logs "would place order" without OrderSend
  - Refuses expired/wrong-symbol/non-demo config
- Integration: Accept → writer → file → (manual MQL5 poll) → ACK → execution_log row → Telegram confirmation

## Risks and Rollback

- **Risk**: Shared folder not accessible (network issue)
  - **Mitigation**: backend marks `pending/` signal as `queued_failed` after N retries; alert trader
- **Risk**: EA executes wrong volume
  - **Mitigation**: hard max lot cap (0.01 default for test, 0.05 absolute max); broker min/max validation
- **Risk**: Duplicate order on EA restart
  - **Mitigation**: persist processed `signal_id` list to file; backend unique status; magic number/client_id
- **Risk**: MT5 terminal disconnect → EA stops polling
  - **Mitigation**: heartbeat signal_id `keepalive.json`; backend alerts if no ACK after 60s
- **Risk**: User không có Windows/VPS/VM
  - **Mitigation**: implement MetaAPI stub (Phase 06.5); user có thể switch bằng env var
- **Rollback**: `EXECUTOR_TRANSPORT=disabled`; stop EA; quarantine `pending/` folder

## Unresolved Questions

- Shared folder mechanism: **SMB share** (cần Windows VPS) hay **Syncthing** (peer-to-peer sync) hay **cùng máy** (cần MT5 chạy local)?
- Default test lot size 0.01 OK?
- FTMO auto-close behavior on breach — best-effort (close positions qua EA) hay notify only (trader tự close)?
- MetaAPI cloud account cần setup trước không, hay Phase 06.5 sau?