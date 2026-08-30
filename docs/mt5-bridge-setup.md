# MT5 Bridge Setup Guide (Phase 06)

> File-based signal bridge between the SMC bot and MetaTrader 5 demo accounts.
> Per plan §Phase 06, this is the **free** path (no MetaAPI subscription).
> For paper-trading or different setups, the same Python outbox contract works.

## Architecture

```
[Bot host (Mac / Linux / VPS)]
  ├── FastAPI webhook (:8000)
  ├── Telegram dispatcher
  └── Python signal_writer → writes <outbox>/pending/<sid>.json
                                ↓ shared folder (SMB / Syncthing / local)
[MT5 host (Windows / VM / VPS)]
  └── MQL5 EA (mql5_reader.mq5) → polls pending/ → OrderSend → writes <outbox>/done/<sid>.json
                                ↓ (same shared folder, polled by bot)
[Bot host (background task)]
  └── reads <outbox>/done/ → records execution_log → Telegram confirmation
```

## 1. Bot-side setup (Python)

### Enable file-bridge transport

Set in `.env` (or shell env):
```bash
EXECUTOR_TRANSPORT=file
MT5_OUTBOX_DIR=/Users/you/SMCBridge   # absolute path to shared folder
```

Or use the path you choose for your shared folder (SMB / Syncthing / local mount).

The bot will:
1. On Accept callback (Phase 03): validate gates → write JSON to `<outbox>/pending/<sid>.json` atomically.
2. On done/ write by MQL5 EA: read ACK JSON → update `execution_log` → send Telegram confirmation.

### Folder layout (auto-created on first run)

```
<outbox>/
├── pending/      # bot writes here; MQL5 reads oldest first
├── processing/   # MQL5 moves file here while placing OrderSend
├── done/         # MQL5 writes ACK JSON here after OrderSend
└── failed/       # MQL5 writes failure JSON here (validation/OrderSend errors)
```

File naming convention: `<signal_id>.json` (no `.tmp` ever visible — MQL5 must skip `.tmp`).

## 2. MQL5 host setup

### Prerequisites

- **MT5 demo account** opened at any broker (IC Markets, Pepperstone, FTMO Demo).
- **MT5 terminal** running on Windows, VPS, or Mac via Parallels/VMware/VirtualBox.
- **Shared folder** accessible from BOTH the bot host AND the MT5 host:
  - **Same machine**: use a local folder
  - **Cross-machine (Mac + Windows VM)**: Syncthing peer-to-peer sync (free, no port forwarding needed)
  - **Mac + Windows VPS**: SMB share mounted on both
  - **Mac + Linux VPS**: NFS or SSHFS
- **MQL5 EA compiled** and attached to a chart.

### EA compilation

1. Open MT5 → `Tools → MetaQuotes Language Editor`.
2. `File → New → Expert Advisor (template)` → name it `mql5_reader`.
3. Replace contents with `bot/mt5_bridge/mql5_reader.mq5` from the repo.
4. Click `Compile` (F7). Must compile with 0 errors and 0 warnings.
5. Close MetaEditor.

### EA inputs (when attaching to chart)

| Input | Default | Description |
|---|---|---|
| `OutboxPath` | `"C:\\SMCBridge"` | Absolute path to the shared folder on the MT5 host side |
| `PollSeconds` | `5` | How often to check `pending/` |
| `DefaultLot` | `0.01` | FTMO minimum test lot |
| `MaxLot` | `0.05` | Hard cap regardless of risk_pct |
| `ProcessedFile` | `"SMC_processed.csv"` | Persistent dedupe log in MT5's MQL5/Files/ |

Example MT5 host layout:
```
C:\SMCBridge\          ← OutboxPath
├── pending\            ← bot writes here
├── processing\         ← EA moves here while OrderSend
├── done\               ← EA writes ACK
└── failed\
C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\SMC_processed.csv
```

### EA attach

1. Open MT5, open an **EURUSD M15 chart**.
2. `Navigator → Expert Advisors → mql5_reader → double-click → drop on chart`.
3. Confirm the smiley face appears in the top-right (green = OK).
4. `Tools → Experts → Journal` should show:
   ```
   SMC mql5_reader v0.1.0 init — outbox=C:\SMCBridge poll=5s lot=0.01 magic=990001 demo=YES
   ```
   If `demo=NO`, the EA refuses to run on real account (safety guard).

### EA logs

When a signal is picked up, you see:
```
SMC skip duplicate signal_id=abc...
SMC JSON parse failed for ...
SMC validation failed for abc...: schema mismatch
SMC OrderSend failed for abc...: retcode=10004 comment=Requote
SMC ORDER PLACED signal_id=abc... ticket=1234567890 price=1.10005 vol=0.01
SMC ACK written: C:\SMCBridge\done\abc....json
```

## 3. Round-trip verification

Once everything is running:

1. Send a test webhook (or use a real Pine alert).
2. Telegram Accept → bot writes `<outbox>/pending/<sid>.json` (visible from both hosts).
3. Within `PollSeconds` (default 5), MQL5 EA picks up the file:
   - Validates schema, symbol, expiry, demo account, duplicate.
   - If passed: OrderSend at market → writes ACK to `<outbox>/done/<sid>.json`.
   - If rejected: writes failure JSON to `<outbox>/failed/<sid>.json`.
4. Bot's background task reads `done/` (Phase 06 wiring), updates `execution_log`,
   sends Telegram confirmation message with the MT5 ticket + fill price.

Verify via dashboard:
- `http://127.0.0.1:5173/execution` shows the row with `transport='file'`, `state='acked'`, `mt5_ticket=...`.

## 4. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| EA refuses to init (`account is NOT demo`) | MT5 logged into real account | Open MT5 demo account; re-login |
| `pending/*.json` accumulates, EA never reads | Path mismatch / permissions | Verify `OutboxPath` matches the actual shared folder; test read/write from MT5 |
| `processed list` blocks valid signals | EA crashed mid-OrderSend → dedupe file persists | Delete `C:\Users\<you>\...\MQL5\Files\SMC_processed.csv` (will re-process all) |
| `OrderSend failed: retcode=10004 (Requote)` | Normal market volatility | EA logs and writes to `failed/`; bot records failure; trader retries |
| Telegram confirmation not received | Telegram bot not configured | Phase 02: set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| Outbox `pending/` files appear then disappear too fast | EA deletes them on move to `done/` — normal | Verify `done/` and `failed/` have the ACK |
| Dashboard `/api/execution` empty | `execution_log` not populated yet | Check MQL5 EA logs; ensure folder write permissions |

## 5. Safety guards (Phase 06)

| Guard | Default | Configurable |
|---|---|---|
| Daily loss threshold | -1.1% (= -2R of 0.55% risk) | `FtmoGuard(max_daily_pnl=...)` |
| Trades per day | 3 | `FtmoGuard(max_trades_per_day=...)` |
| Open positions per symbol | 1 | `FtmoGuard(max_open_positions=...)` |
| Lot size hard cap | 0.05 lots | `MaxLot` EA input |
| Magic number | EURUSD=990001 | Edit `MagicEURUSD` in MQL5 |
| Account must be demo | `ACCOUNT_TRADE_MODE_DEMO` check | Hard-coded in MQL5 EA |

If FTMO guard fails on the bot side, the Accept callback returns 409 with the guard reason
(no outbox write, no Telegram edit). The dashboard surfaces the failure.

## 6. Rollback

If something goes wrong:

```bash
# Stop the EA in MT5 (remove from chart)
# Stop the bot
EXECUTOR_TRANSPORT=disabled   # disable outbox writes
# Quarantine <outbox>/pending/
mv <outbox>/pending <outbox>/pending.quarantine
```

No code change required — the feature flag is env-driven.

## 7. Cross-machine setup: Syncthing (recommended for Mac + Windows)

1. Install Syncthing on both hosts.
2. Create a folder `~/SMCBridge` on the Mac; share with MT5 host via Syncthing.
3. On Windows MT5 host, set `OutboxPath` to the Syncthing sync folder (e.g. `C:\Users\<you>\Sync\SMCBridge`).
4. Start Syncthing on both hosts; verify the test file syncs.

**Pros**: no port forwarding, free, encrypted.
**Cons**: ~5-10s sync delay (fine for M15 timeframe).

For ultra-low latency (< 1s), use SMB share on a LAN.

## 8. Cross-machine setup: SMB share (Windows VPS)

1. On Windows VPS: share `C:\SMCBridge` with read/write access for the MT5 service user.
2. On Mac bot host: `mount_smbfs //user@vps/SMCBridge /Users/you/SMCBridge`.
3. Add to `/etc/fstab` for persistent mount on reboot.

Use `ls -la /Users/you/SMCBridge/pending` from Mac to verify shared folder is mounted.

## 9. Phase 06 → Phase 06.5 (MetaAPI alternative)

If you ever switch to MetaAPI (no local MT5 needed):

```bash
EXECUTOR_TRANSPORT=metaapi
# Phase 06.5 will implement this in bot/mt5_bridge/executor.py
# See plan §Phase 06.5 for details.
```

For now this raises `NotImplementedError` — switch to `EXECUTOR_TRANSPORT=file` for the local outbox flow.

## 10. Scale-in Exit Mode — backtest only (Phase 06 limitation)

**Status (milestone 2026-08-31):** ScaleInExit (`src/scale_in_exit.py`) is
validated via `run_backtest(exit_mode='scale_in')` on EURUSD 2016-2026
(1326 trades, PF 2.74, +23% PnL, -44% DD vs ladder). **The MT5 bridge does
NOT yet support scale-in mode.**

### Why the gap exists

The current MT5 execution path (`signal_writer.py` → `mql5_reader.mq5`)
places a single order with a single TP level:

```cpp
// mql5_reader.mq5 line 189-191
// TP: take the first TP level for simplicity.
CJSONValue tpArr = jv["tp"];
double tp = (tpArr.IsArray() && tpArr.Size() > 0) ? tpArr[0].ToDouble() : 0;
```

Scale-in needs **multi-order orchestration**:

1. Open leg1 with SL @ OB edge (1R). TP1 ignored (leg1 closes 50% at 2R via partial).
2. Detect 2R hit (via MQL5 position monitor polling `OrderHistory` or
   watching price).
3. Close 50% of leg1 at 2R (lock +1R).
4. Move SL of remaining 0.5 lot → entry (BE).
5. **Open leg2**: separate market order at 2R with SL @ entry, TP @ 4R.
6. Close both legs at 4R OR cascade-close when SL hits.

Step 5 (open leg2 at runtime) is the missing piece. The current MQL5 EA
only processes signals from the outbox; it has no logic to detect a
partial-fill event and write a follow-up `leg2` signal back to the
bridge.

### Ladder mode works

Ladder 40/30/30 has the same limitation in theory (partial closes), but
FTMO-friendly behavior allows placing leg1 at the **2R TP** as the single
`tp` field. The bot currently doesn't do partial TP either — it just
sets TP1 = entry + 2R and lets MT5 close 100% at the first TP hit.
Backtest simulates the partial ladder; live MT5 only sees TP1. This is a
pre-existing compromise, not specific to scale-in.

### Workaround: ladder mode for live FTMO

For FTMO Challenge / Verification right now:

1. Set `strategy.exit_mode = ladder` (default) in `config.yaml`.
2. Bot sends entry with `tp = entry + 2R` to MT5.
3. MT5 closes 100% at 2R. Misses the 3R/4R extension. Live PnL ≈ backtest's
   conservative case.
4. Scale-in 2R/4R payoff (max +4R per trade) is **unrealized** until MQL5
   orchestration ships.

### What's needed for scale-in live support

| Piece | Status | Effort |
|---|---|---|
| MQL5 partial-close detection (watch for 2R fill) | not started | medium |
| `leg2` signal write from MQL5 back to outbox | not started | medium |
| `run_backtest` parity test for live execution path | not started | low |
| Phase 06.5 MetaAPI alternative (cloud MT5) — reuses same logic | blocked on above | — |

Until those ship, treat scale_in mode as a **research artifact**: use it
for backtest exploration + Pine v1.3 visual overlay (manual chart study),
but **do not deploy to live FTMO**. Ladder mode is the only validated
live path.

