# Bot Cảnh Báo + Demo Execution + Replay Architecture

## Executive Summary

Build as a staged, safety-first signal router around the locked Pine/Python SMC engine:

- **P0 / Phase A**: TradingView alert webhook -> FastAPI -> rulebook gate state -> Telegram Accept/Reject -> durable SQLite audit + signal CSV. No MT5 required.
- **P1 / Phase B**: run replay in parallel with P0 using existing frozen-feed/parity tooling; TradingView Bar Replay is manual/visual, Python replay is deterministic.
- **P2 / Phase C**: demo execution only after P0 has been stable for 4-8 weeks. Recommended macOS-safe transport is MetaAPI cloud. File-based MT5 bridge is a Windows/VPS/VM option when an MT5 terminal can read the outbox.
- **Never default to native `MetaTrader5` Python on macOS/M4**. It is only acceptable behind an explicit Windows/VPS prerequisite.

KISS decision: **Telegram is the manual approval authority**. Discord is mirror-only. No auto-trade without all six manual gates acknowledged.

## Evidence From Repo

| Claim | Evidence |
|---|---|
| Current architecture separates causal engine and consumption layer | `docs/system-architecture.md:10-14` |
| Compatibility surfaces are `src/smc_signals.py`, `src/backtester.py`, `app.py` | `docs/code-standards.md:22-23` |
| Event visibility must be confirmed-bar causal | `docs/smc-engine-event-pipeline.md:34-37` |
| Pine alert schema already documented | `docs/smc-engine-tradingview-guide.md:114-120` |
| Pine script is an `indicator()`, not a `strategy()`; no in-Pine order execution | `tradingview/smc-engine-indicator.pine:2` |
| Existing Pine alerts are still `alertcondition()` and plain static messages | `tradingview/smc-engine-indicator.pine:1149-1156` |
| Pine manual gates are six inputs | `tradingview/smc-engine-indicator.pine:49-54` |
| Pine derives all-gates-ok from those six inputs | `tradingview/smc-engine-indicator.pine:73-74` |
| Pine chart-qualified/watch/blocked state is computed after candidate selection | `tradingview/smc-engine-indicator.pine:1062-1074` |
| Manual checklist requires six block-A gates before trade | `docs/smc-manual-trade-checklist.md:124-143` |
| Rule book freezes EURUSD, strict D/H4, regime off, risk constraints | `journal/rule-book.md:12-25`, `journal/rule-book.md:29-41` |
| Existing backtester returns trades + equity curve | `src/backtester.py:149-152` |
| Existing backtest loop builds SMC outputs once and iterates M15 bars causally | `src/backtester.py:287-393` |
| Existing journal uses SQLite at `output/trades.db` | `src/journal.py:13-18` |
| Journal already has query/export surface for dashboard reuse | `src/journal.py:151-197`, `src/journal.py:242-246` |
| Streamlit app already renders Plotly charts, metrics, and journal table | `app.py:15-17`, `app.py:822-920` |
| Existing parity/replay tooling emits normalized OHLC/reference/Pine placeholder bundle | `scripts/capture-frozen-feed.py:4-12`, `scripts/capture-frozen-feed.py:116-123` |
| Comparator compares Python reference vs Pine output CSV | `scripts/compare-pine-parity.py:129-145` |

External constraints used:

- TradingView webhooks send POST body to a configured URL; JSON messages get `application/json`, otherwise `text/plain`; allowed ports are only 80/443; webhook times out after 3 seconds; official IP allowlist is published; 2FA is required. Source: TradingView Help Center webhook article.
- Telegram supports inline keyboards and callback buttons. Source: Telegram Bot Features / Inline Keyboards.
- Discord supports buttons/interactions, but this plan keeps Discord notification-only to avoid doubling approval state. Source: Discord component reference.
- `MetaTrader5` PyPI package is an API connector to a local MT5 terminal. Source: PyPI `MetaTrader5` package page. On macOS/M4, default to MetaAPI cloud or a file bridge to Windows/VPS MT5, not native `MetaTrader5`.

## Target Data Flow

```text
REAL-TIME PATH

TradingView Pine indicator
  alert() dynamic payload: SMC|v1|event=...|symbol=...|tf=...|dir=...|...
        |
        | HTTPS POST, 80/443, <=3s response budget
        v
FastAPI webhook /webhooks/tradingview
  - verify source: IP allowlist + shared URL secret
  - parse payload into typed AlertPayload
  - idempotency key: version + event + symbol + tf + bar_time + ob_id + bos_id
        |
        v
SQLite alert_log + signal_events
  - raw payload, parse result, dedupe state, delivery state
        |
        v
Gate Validator
  - chart gates from payload/state
  - manual gates from latest gate_ack rows
  - risk state from open orders/day counters when available
        |
        +--> rejected/blocked -> Telegram/Discord notify + audit only
        |
        v
Telegram Dispatcher
  message: signal summary + six-gate checklist + Accept / Reject buttons
        |
        | callback_query: accept:<signal_id> or reject:<signal_id>
        v
Approval Handler
  - verify authorized Telegram user
  - require all six manual gate acks fresh for the trading day
  - mark accepted/rejected exactly once
        |
        +--> reject -> audit + disabled buttons
        |
        v
Execution Queue
  - P2 preferred: MetaAPI cloud executor
  - P2 optional: file bridge atomic JSON signal in outbox
        |
        v
MT5 Demo Executor
  - reads one signal once
  - checks symbol, side, volume, SL/TP, duplicate id
  - sends demo order
        |
        v
Execution Result
  - ack file/API response -> SQLite execution_log -> Telegram + dashboard
```

```text
REPLAY PATH

TradingView Bar Replay / manual visual session
        |
        | cannot send webhook during replay
        v
Option A: Pine Logs / manual CSV paste
        |
        v
bot/backtest/capture.py normalizes rows into signal CSV
        |
        v
scripts/compare-pine-parity.py against Python reference

Option B: Python engine replay (default deterministic)
        |
        v
load frozen OHLC bundle -> replay SMC engine bar by bar -> emit same signal CSV schema
        |
        v
dashboard replay page: candles + SMC overlays + signal markers + accept/reject history
```

## File Structure

Planned new files keep bot code isolated from existing engine/app contracts.

```text
bot/
  __init__.py
  webhook/
    __init__.py
    server.py                 # FastAPI app, webhook endpoints, health
    payload.py                # SMC|v1 parser + Pydantic models
    security.py               # IP allowlist, URL secret, rate limit helpers
  gates/
    __init__.py
    validator.py              # 11-gate rulebook decision engine
    state.py                  # gate_ack persistence and freshness windows
  notify/
    __init__.py
    telegram.py               # Telegram inline keyboard + callback handlers
    discord.py                # optional mirror-only webhook messages
  mt5_bridge/
    __init__.py
    signal_writer.py          # atomic outbox writer, idempotency, retention
    mql5_reader.mq5           # EA/poller: read JSON file, place demo trade
    metaapi_executor.py        # P2 macOS-safe alternative to native MT5 lib
  backtest/
    __init__.py
    capture.py                # normalize Pine Logs/manual CSV/Python replay signals
    replay_engine.py           # wraps existing Python SMC engine for local replay
  dashboard/
    __init__.py
    streamlit_app.py          # history/replay dashboard; may later merge into app.py
  storage/
    __init__.py
    db.py                     # SQLite connection + schema migrations
    schema.sql                # alert_log, gate_ack, signal_events, execution_log

tests/
  test_bot_payload.py
  test_bot_gates.py
  test_bot_webhook.py
  test_bot_signal_writer.py
  test_bot_replay_capture.py

plans/260830-bot-alert-replay/
  architecture.md             # this document
```

User-requested paths preserved:

- `bot/webhook/server.py`
- `bot/gates/validator.py`
- `bot/notify/telegram.py`
- `bot/mt5_bridge/signal_writer.py`
- `bot/mt5_bridge/mql5_reader.mq5`
- `bot/backtest/capture.py`
- `bot/dashboard/streamlit_app.py`

## Component Responsibilities

### 1. Webhook Receiver — `bot/webhook/server.py`

Responsibilities:

- Expose `POST /webhooks/tradingview` and `GET /healthz`.
- Reply fast: verify + persist + enqueue notification; never block on Telegram/MT5.
- Accept `text/plain` payload for `SMC|v1|...`; optionally accept JSON wrapper later.
- Enforce source controls: TradingView IP allowlist, shared URL secret, body size cap, rate limit.
- Return `202 Accepted` for new valid events, `200 OK` for duplicate events, `4xx` for invalid/auth failures.

Data in:

- Raw request body from TradingView.
- Query secret, e.g. `/webhooks/tradingview?token=<shared-secret>`.
- Request client IP / reverse proxy forwarded IP.

Transform:

- Parse delimited payload into `AlertPayload`.
- Normalize `symbol`, `tf`, `dir`, `bar_time`, numeric ids.
- Compute idempotency key.
- Insert into `alert_log`.

Data out:

- Stored alert row.
- Internal notification job.

Failure modes + mitigations:

- TradingView 3s timeout -> persist before any external API calls; background dispatch.
- Duplicate alert after TV retry/reload -> unique idempotency key.
- Webhook has no custom headers -> do not design header HMAC as P0 auth. Use shared URL secret + IP allowlist.
- Pine sends malformed payload -> store raw row as rejected and notify ops only after rate-limited threshold.

### 2. Payload Parser — `bot/webhook/payload.py`

Payload format:

```text
SMC|v1|event=<event>|symbol=<ticker>|tf=<interval>|dir=<dir>|level=<mintick>|bar_time=<epoch>|ob_id=<id>|bos_id=<id>|state=<state>|reason=<code>
```

Required fields:

| Field | Type | Notes |
|---|---|---|
| `prefix` | literal | `SMC` only |
| `version` | literal | `v1` only |
| `event` | enum | `bos`, `choch`, `ob_activated`, `sweep`, `pool`, `chart_qualified`, `watch`, `blocked` |
| `symbol` | string | allow configured symbols only; P0 `EURUSD` |
| `tf` | string | P0 `M15` only for rulebook semantics |
| `dir` | enum | `long`, `short`, `bullish`, `bearish`, `none` normalized to side |
| `level` | decimal | price/level from Pine |
| `bar_time` | int datetime | epoch seconds/millis normalized to UTC |
| `ob_id` | int optional | `-1` or missing allowed for non-OB events |
| `bos_id` | int optional | linked provenance |
| `state` | enum | `chart-qualified`, `watch`, `blocked`, `no-signal` |
| `reason` | string | normalized rejection/diagnostic code |

Output model adds:

- `signal_id`: deterministic hash from event identity.
- `received_at`: server time.
- `raw_payload`: audit copy.

### 3. Gate Validator — `bot/gates/validator.py`

Scope: convert alert + stored daily state into one of: `notify_only`, `needs_manual_ack`, `blocked`, `accepted_ready`, `expired`.

The validator must split gates into **chart gates** and **manual gates**. Pine already calculates chart state, but backend re-checks what it can to prevent a Telegram button from overriding a blocked chart setup.

#### 11 Rulebook Gates

| # | Gate | Source | Automated? | Block condition |
|---:|---|---|---|---|
| 1 | Symbol is EURUSD for 8-week sample | payload/config | yes | `symbol != EURUSD` |
| 2 | Timeframe M15 | payload/config | yes | `tf != M15` |
| 3 | Pine state is chart-qualified/watch, not blocked/no-signal | payload | yes | `state in blocked,no-signal` for execution |
| 4 | Direction exists and maps to long/short | payload | yes | no side |
| 5 | OB provenance exists for trade event | payload | yes | missing `ob_id`/`bos_id` for execution candidate |
| 6 | Freshness window | server time vs `bar_time` | yes | expired; default 5 minutes live, configurable |
| 7 | Risk 0.55% acknowledged | Telegram daily ack | manual | false/stale |
| 8 | Trades today left | Telegram/backend counter | manual + derived | `<=0` |
| 9 | Daily loss -2R acknowledged/not breached | Telegram + execution log | manual + derived | false/stale or breached |
| 10 | No open position | Telegram + executor position check when available | manual + derived | false/stale or open exposure |
| 11 | Spread/news clean + trader judgment clear | Telegram ack | manual | either false/stale |

Note: Pine exposes six manual inputs (`manualRiskOk`, `manualTradesLeft`, `manualDailyROk`, `manualPosOk`, `manualSpreadOk`, `manualJudgmentOk`) in `tradingview/smc-engine-indicator.pine:49-54`; backend stores the same six concepts as daily acks. The table above folds `spread/news` and `trader judgment` into one row only to keep the 11-gate rulebook view aligned with chart + backend gates. In implementation, store them as separate boolean fields.

Manual gate freshness:

- Daily gates reset at New York session date boundary.
- Signal-specific gates (`no_open_position`, `spread_news_clean`, `trader_judgment_clear`) expire after 10 minutes or after one Accept/Reject.
- Accept callback re-runs validator, never trusts button message state.

### 4. Notification Dispatcher — `bot/notify/telegram.py`

Responsibilities:

- Send signal message with:
  - symbol/timeframe/direction
  - state/reason
  - OB/BOS ids
  - bar time
  - gate checklist
  - buttons: `Accept`, `Reject`, optional `Ack gates` flow
- Handle Telegram callback queries.
- Authorize a fixed allowlist of Telegram user ids.
- Edit message after decision so buttons cannot be reused.

Recommended SDK:

- `python-telegram-bot` v21+ / current stable supports async handlers and `InlineKeyboardMarkup`.

Callback design:

```text
accept:<signal_id>:<nonce>
reject:<signal_id>:<nonce>
ack:<signal_id>:risk
ack:<signal_id>:trades_left
ack:<signal_id>:daily_loss
ack:<signal_id>:no_position
ack:<signal_id>:spread_news
ack:<signal_id>:judgment
```

Nonce prevents stale copied callback data from approving a different signal.

Discord:

- `bot/notify/discord.py` sends mirror notifications only.
- No Discord Accept/Reject in P0; one approval system avoids split-brain gate state.

### 5. Storage — `bot/storage/db.py` + `schema.sql`

Use SQLite initially, colocated with existing `output/trades.db` pattern from `src/journal.py:13`. Keep new tables separate from `trades` to avoid breaking current dashboard queries.

Tables:

```sql
alert_log(
  id INTEGER PRIMARY KEY,
  signal_id TEXT UNIQUE NOT NULL,
  received_at TEXT NOT NULL,
  raw_payload TEXT NOT NULL,
  parse_status TEXT NOT NULL,
  event TEXT,
  symbol TEXT,
  tf TEXT,
  side TEXT,
  bar_time TEXT,
  ob_id INTEGER,
  bos_id INTEGER,
  state TEXT,
  reason TEXT,
  source_ip TEXT,
  dedupe_count INTEGER DEFAULT 0
);

gate_ack(
  id INTEGER PRIMARY KEY,
  signal_id TEXT,
  trade_date TEXT NOT NULL,
  gate_name TEXT NOT NULL,
  value TEXT NOT NULL,
  user_id TEXT NOT NULL,
  acknowledged_at TEXT NOT NULL,
  expires_at TEXT,
  UNIQUE(signal_id, trade_date, gate_name)
);

signal_events(
  signal_id TEXT PRIMARY KEY,
  status TEXT NOT NULL, -- received|notified|blocked|accepted|rejected|expired|queued|executed|failed
  decision_user_id TEXT,
  decision_at TEXT,
  decision_reason TEXT,
  outbox_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

execution_log(
  id INTEGER PRIMARY KEY,
  signal_id TEXT NOT NULL,
  transport TEXT NOT NULL, -- file|metaapi|manual
  request_payload TEXT NOT NULL,
  response_payload TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

Migration policy:

- No change to existing `trades` schema in P0.
- Dashboard can join by `signal_id` later if execution logs are promoted into trade journal.

### 6. File-Based MT5 Bridge — `bot/mt5_bridge/signal_writer.py` + `mql5_reader.mq5`

Purpose: satisfy demo execution without requiring low latency.

Important platform decision:

- P2 file bridge is valid only when an MT5 terminal can read the outbox path: Windows terminal, Windows VM, or VPS.
- On macOS-only with no MT5 terminal path, do **not** use native Python `MetaTrader5`; use P2 MetaAPI cloud connector or explicitly run MT5 on Windows/VPS.

File contract:

```text
outbox/
  pending/<signal_id>.json.tmp
  pending/<signal_id>.json
  processing/<signal_id>.json
  done/<signal_id>.json
  failed/<signal_id>.json
```

Atomic write:

1. Write JSON to `pending/<signal_id>.json.tmp`.
2. `fsync` file.
3. Rename to `pending/<signal_id>.json`.
4. MQL5 reader only opens `.json`, never `.tmp`.

Signal JSON:

```json
{
  "schema": "SMC_EXECUTION_V1",
  "signal_id": "...",
  "symbol": "EURUSD",
  "side": "long",
  "entry_mode": "market_or_limit_configured",
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

MQL5 reader responsibilities:

- Poll pending folder every N seconds.
- Validate schema, expiry, symbol allowlist, duplicate signal id.
- Check demo account mode and magic number.
- Calculate/validate volume within broker min/max/step.
- Send order.
- Write ack/result file.

Failure modes + mitigations:

- Partial file read -> atomic rename contract.
- Duplicate execution -> EA persists processed `signal_id` list and backend unique status transition.
- Wrong account -> EA refuses non-demo account unless explicit config flag.
- Clock drift -> expiry window checked on both backend and EA.
- User accepts stale signal -> backend re-runs freshness gate before writing file.

### 7. MetaAPI Executor — `bot/mt5_bridge/metaapi_executor.py` (P2)

Why exists:

- User workstation is macOS/M4; native `MetaTrader5` Python path is risky/time-wasting without a Windows terminal.
- MetaAPI provides cloud MT5 terminal connectivity and works from Python on macOS.

Responsibilities:

- Keep same connector interface as file bridge:
  - `submit(signal) -> execution_result`
  - `get_open_positions(symbol)`
  - `get_account_state()`
- Implement only after P0 has 4-8 weeks stable forward-test alerts.

Rollback:

- Feature flag executor transport: `EXECUTOR_TRANSPORT=disabled|file|metaapi`.
- Default `disabled` until manual approval flow is proven.

### 8. Signal CSV Logger — `bot/backtest/capture.py`

Responsibilities:

- Write every accepted/rejected/blocked signal to canonical CSV.
- Normalize both live alerts and replay-generated events into same columns.
- Support manual Pine Logs paste -> CSV converter.

CSV schema:

```csv
source,run_id,signal_id,event,symbol,tf,side,level,entry,sl,tp1,tp2,tp3,bar_time,ob_id,bos_id,state,reason,score,gate_status,decision,decision_at,execution_status
```

Data sources:

1. Live webhook rows from SQLite.
2. Python replay output from `bot/backtest/replay_engine.py`.
3. Manual Pine Logs export/paste from TradingView Bar Replay.

### 9. Replay Engine — `bot/backtest/replay_engine.py`

Default deterministic replay path:

- Read frozen OHLC bundle created by `scripts/capture-frozen-feed.py`.
- Reuse existing Python engine/backtester surfaces; preserve confirmed-bar semantics from `docs/smc-engine-event-pipeline.md:34-37`.
- Emit `SMC|v1`-equivalent rows without sending webhook.
- Compare event CSV against Pine export using existing parity comparator.

Why not TradingView webhook replay:

- TradingView Bar Replay does not deliver webhook alerts reliably as a historical simulation path; treat it as visual/manual validation only.
- Pine script is `indicator()`, not `strategy()`, so no `strategy.entry` path can simulate broker orders inside Pine. Orders must leave Pine via live alert/webhook or be replayed by Python.

### 10. Dashboard — `bot/dashboard/streamlit_app.py`

Responsibilities:

- Show live alert history, gate state, decisions, execution result.
- Show replay runs and deterministic signal CSV over chart.
- Reuse Plotly + Streamlit pattern from existing `app.py:15-17` and journal filters from `app.py:901-920`.

Dashboard pages:

1. **Live Queue**: latest alerts, status, gate checklist, Telegram delivery state.
2. **Execution**: pending/done/failed outbox rows, MT5/MetaAPI response.
3. **Replay**: upload/select signal CSV + OHLC bundle; render Plotly candles with markers.
4. **Audit**: export decisions CSV for journal review.

Keep separate from `app.py` in P0. Merge only if duplication becomes painful.

## Pine Changes Required Before P0 Works

Blocker: current Pine uses `alertcondition()` at `tradingview/smc-engine-indicator.pine:1149-1156`. These messages are static and do not emit the requested dynamic `SMC|v1|...` payload.

Required Pine plan:

1. Add a small payload builder function near alert logic.
2. Replace/augment each relevant alertcondition path with `alert(payload, alert.freq_once_per_bar_close)` on state transition.
3. Keep existing `alertcondition()` temporarily only as human-readable fallback during migration.
4. Benchmark against TradingView Premium 40s budget before merge; payload building must be string-light and gated behind alert inputs.

Example payload shape:

```text
SMC|v1|event=chart_qualified|symbol={{ticker}}|tf={{interval}}|dir=long|level=1.1000|bar_time=1690000000|ob_id=42|bos_id=19|state=chart-qualified|reason=ok
```

Do not add broker/execution code to Pine.

## Real-Time vs Replay Architecture

| Concern | Real-time | Replay |
|---|---|---|
| Source | TradingView live alert webhook | Frozen OHLC + Python engine; optional Pine Logs paste |
| Transport | HTTPS POST | local file/CSV |
| Manual gates | Telegram required | optional annotation, no execution |
| Execution | disabled/file/MetaAPI by feature flag | never executes orders |
| Determinism | idempotent but network-dependent | deterministic by fixture checksum |
| UI | Telegram + dashboard live queue | Streamlit Plotly replay chart |
| Success metric | one alert -> one auditable decision -> optional one demo order | same input OHLC -> same signal CSV every run |

## Phase Breakdown

### P0 — Alert Intake + Manual Approval Audit

Objective: end-to-end alert capture and human decision loop, no MT5 execution.

Files owned:

- Create: `bot/webhook/server.py`
- Create: `bot/webhook/payload.py`
- Create: `bot/webhook/security.py`
- Create: `bot/gates/validator.py`
- Create: `bot/gates/state.py`
- Create: `bot/notify/telegram.py`
- Create: `bot/notify/discord.py`
- Create: `bot/storage/db.py`
- Create: `bot/storage/schema.sql`
- Modify: `tradingview/smc-engine-indicator.pine`
- Create tests: `tests/test_bot_payload.py`, `tests/test_bot_gates.py`, `tests/test_bot_webhook.py`

Dependencies:

- Existing Pine v6 parity stable.
- TradingView webhook URL on HTTPS 443.
- Telegram bot token and allowed user id.
- Shared URL secret stored outside repo.

Data flow:

- Pine event -> webhook -> parser -> SQLite -> validator -> Telegram -> callback -> SQLite decision.

Test matrix:

| Layer | Tests |
|---|---|
| Unit | payload parser valid/invalid fields; idempotency hash; gate validator daily reset/freshness/blocked states |
| Integration | FastAPI test client for auth, duplicate POST, malformed body, valid chart-qualified event |
| Bot callback | authorized vs unauthorized user; Accept with missing gates stays blocked; Reject finalizes once |
| Manual smoke | local ngrok/cloudflared webhook receives TradingView test alert; Telegram button edits message |

Risks:

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Pine dynamic `alert()` pushes script over execution budget | Medium | High | Implement behind toggle; benchmark in TradingView before removing `alertcondition()` fallback |
| TradingView webhook no custom header/HMAC | High | Medium | Use URL secret + IP allowlist + rate limit; document HMAC unavailable for direct TV POST |
| User taps stale Accept | Medium | High | Freshness gate re-run on callback; signal expires |
| Telegram outage | Low | Medium | Alert remains stored; dashboard shows `notified_failed`; manual retry command |

Rollback:

- Disable dynamic alert input in Pine.
- Set backend `EXECUTOR_TRANSPORT=disabled`.
- Remove webhook URL from TradingView alert.
- SQLite tables are additive; existing app/backtester untouched.

Success criteria:

- Valid `SMC|v1` POST persists exactly once.
- Duplicate POST increments/logs dedupe, no duplicate Telegram execution prompt.
- Accept impossible until six manual gate values are acknowledged and fresh.
- P0 produces signal CSV from live alert history.

### P1 — Replay Capture + Dashboard

Objective: deterministic replay workflow in parallel with P0; no execution.

Files owned:

- Create: `bot/backtest/capture.py`
- Create: `bot/backtest/replay_engine.py`
- Create: `bot/dashboard/streamlit_app.py`
- Create: `tests/test_bot_replay_capture.py`
- Modify only if needed: `app.py` to link to dashboard, not to merge logic

Dependencies:

- P0 payload schema, or a frozen copy of the same schema.
- Existing frozen-feed/parity scripts.
- Manual TradingView Bar Replay/Pine Logs workflow.

Data flow:

- Frozen OHLC -> Python replay -> signal CSV -> dashboard chart/history.
- Optional Pine Logs paste -> `capture.py` normalizes to same CSV -> `compare-pine-parity.py`.

Test matrix:

| Layer | Tests |
|---|---|
| Unit | CSV normalization; replay emits stable rows for same fixture |
| Integration | replay output joins OHLC timestamps and renders in Streamlit without mutating journal |
| Parity | compare Python replay CSV vs manually exported Pine CSV for sampled window |
| Manual cadence | quarterly TradingView Bar Replay session, ~30 minutes/session |

Risks:

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| TradingView Bar Replay not automatable | High | Medium | Treat Pine replay as manual visual validation; Python replay is source of deterministic CSV |
| Dashboard duplicates `app.py` logic | Medium | Low | Read-only dashboard first; reuse existing journal/query patterns; merge later only if needed |
| Replay diverges from Pine | Medium | High | Use existing parity comparator; record fixture checksums and mismatches |

Rollback:

- Replay files are additive; delete generated replay run folder if corrupt.
- Existing `app.py` and backtester remain untouched except optional link.

Success criteria:

- Same frozen OHLC input produces byte-identical signal CSV.
- Pine manual replay CSV can be normalized and compared against Python replay.
- Dashboard shows replay markers and live alert history with filterable signal states.

### P2 — Demo Execution: MetaAPI Preferred, File Bridge Optional

Objective: accepted signal executes only on Demo after P0 has been stable for 4-8 weeks.

Files owned:

- Create: `bot/mt5_bridge/metaapi_executor.py`
- Create: `bot/mt5_bridge/signal_writer.py`
- Create: `bot/mt5_bridge/mql5_reader.mq5`
- Modify: `bot/gates/validator.py` only for executor-derived `open_position`/trade count hooks
- Modify: `bot/storage/schema.sql` for execution fields if P0 omitted them
- Create: `tests/test_bot_signal_writer.py`

Dependencies:

- P0 stable approval flow.
- MetaAPI demo account for macOS-safe path, or MT5 Demo terminal on Windows/VPS/VM for file bridge.
- Broker symbol mapping known (`EURUSD` vs suffix variants).

Data flow:

- Recommended macOS path: Telegram Accept -> validator re-check -> MetaAPI executor -> demo order -> execution log -> Telegram/dashboard.
- Optional file path: Telegram Accept -> validator re-check -> `signal_writer` writes outbox JSON -> MQL5 reader polls -> demo order -> ack file -> execution log -> Telegram/dashboard.

Test matrix:

| Layer | Tests |
|---|---|
| Unit | atomic writer never exposes `.tmp`; duplicate signal id no second file; expiry serialized |
| Unit | MetaAPI executor disabled without required env; request payload validates symbol/side/risk caps |
| MQL5 dry run | EA reads sample JSON and refuses expired/wrong-symbol/non-demo config |
| Integration | accepted signal queues exactly one execution request for selected transport |
| Manual smoke | demo account receives a 0.01-lot safe test order from explicitly approved test signal |

Risks:

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| macOS cannot run native MT5 path | High | Medium | Default to MetaAPI; file bridge only with Windows/VPS/VM prerequisite |
| MetaAPI cost/vendor dependency | Medium | Medium | Feature flag; keep disabled/manual/file mode fallback |
| EA executes wrong volume | Medium | High | Hard max lot cap, demo-only check, broker min/max validation, test order at 0.01 lot |
| File share latency/missing ack | Medium | Medium | Backend marks queued/pending; retry only manually; no blind rewrite |
| Duplicate order from executor restart | Medium | High | Persist processed `signal_id`; backend unique status; magic number/client id check |

Rollback:

- Set `EXECUTOR_TRANSPORT=disabled`.
- Revoke/disable MetaAPI token or stop/remove EA from MT5 chart.
- Move outbox `pending/` to quarantine for file mode.
- Keep alert/approval P0 and replay P1 running.

Success criteria:

- MetaAPI path is off by default and cannot execute without explicit env config.
- One accepted fresh signal creates one execution request for selected transport.
- File bridge EA refuses expired/duplicate/non-demo/wrong-symbol files.
- Demo test order execution is logged and surfaced in Telegram/dashboard.

## Security Design

### Webhook Auth

Direct TradingView constraints:

- No custom auth header from TradingView.
- No direct HMAC unless Pine can generate a cryptographic signature; do not assume this.

P0 controls:

1. HTTPS only, port 443.
2. Shared random URL token: `/webhooks/tradingview?token=...`.
3. TradingView IP allowlist:
   - `52.89.214.238`
   - `34.212.75.30`
   - `54.218.53.128`
   - `52.32.178.7`
4. Reverse proxy strips/sets trusted forwarded IP headers.
5. Request body cap: 4 KB.
6. Per-IP + per-token rate limit.
7. Idempotency key for duplicate suppression.

Where HMAC fits:

- Add HMAC verification only for internal/non-TradingView clients or if a trusted edge proxy signs verified TradingView requests before forwarding to FastAPI.
- Do not block P0 on impossible direct-TV HMAC.

### Telegram Security

- Allowlist Telegram user ids.
- Store bot token outside repo.
- Callback nonce per signal.
- Accept re-runs all gates; button state is presentation only.
- Message redaction: never include broker credentials or account login.

### Execution Safety

- Default executor disabled.
- Demo-only check before order.
- Symbol allowlist P0: EURUSD only.
- Max lot cap and max risk pct cap.
- Signal expiry mandatory.
- One open position per symbol enforced by validator and executor.

## Backwards Compatibility

- Existing engine code under `src/smc_engine/` remains untouched in P0/P1/P2 except read-only imports for replay.
- Existing public adapter surfaces remain stable per repo standards: `src/smc_signals.py`, `src/backtester.py`, `app.py` (`docs/code-standards.md:22-23`).
- Existing `output/trades.db` can host additive tables, but `trades` schema is not changed in P0.
- Existing Streamlit `app.py` keeps current backtest UI; new dashboard starts separate.
- Pine alert migration should keep `alertcondition()` fallback until dynamic `alert()` is validated in TradingView.

## Dependency Graph

```text
P0.1 payload parser
  -> P0.2 storage schema
  -> P0.3 FastAPI webhook
  -> P0.4 gate validator
  -> P0.5 Telegram dispatcher
  -> P0.6 Pine dynamic alert() migration
  -> P0.7 live smoke

P1.1 replay capture depends on P0 payload schema
  -> P1.2 replay engine depends on existing Python engine/parity tools
  -> P1.3 dashboard depends on storage + replay CSV
  -> P1.4 quarterly manual Pine replay compare

P2.1 MetaAPI executor depends on P0 stable approvals + account credentials
  -> P2.2 optional signal writer depends on P0.2 + P0.4 + P0.5
  -> P2.3 optional MQL5 reader depends on signal JSON contract
  -> P2.4 demo smoke depends on selected executor transport
```

No parallel phase should touch the same file:

| Phase | File ownership |
|---|---|
| P0 Webhook/storage | `bot/webhook/*`, `bot/storage/*`, webhook tests |
| P0 Gates/notify | `bot/gates/*`, `bot/notify/*`, gate/bot tests |
| P0 Pine | `tradingview/smc-engine-indicator.pine` only |
| P1 Replay/dashboard | `bot/backtest/*`, `bot/dashboard/*`, replay tests |
| P2 Execution | `bot/mt5_bridge/*`, signal writer tests |

## Operational Runbook

### Live Alert Setup

1. Deploy FastAPI behind HTTPS 443.
2. Configure env:
   - `SMC_WEBHOOK_TOKEN`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ALLOWED_USERS`
   - `EXECUTOR_TRANSPORT=disabled`
3. TradingView alert URL: `https://<host>/webhooks/tradingview?token=<secret>`.
4. TradingView alert message from Pine dynamic `alert()` payload.
5. Send test event; verify SQLite row + Telegram prompt.
6. Keep execution disabled until P0 acceptance criteria pass.

### Manual Accept Flow

1. Alert arrives.
2. Telegram shows gate checklist.
3. Trader acknowledges six gates.
4. Trader presses Accept.
5. Backend re-runs validator.
6. If valid: mark accepted and queue execution depending on transport.
7. If invalid: message edited with block reason.

### Replay Flow

1. Create frozen OHLC bundle with `scripts/capture-frozen-feed.py`.
2. Run Python replay to emit `signals.csv`.
3. Optionally run TradingView Bar Replay and paste/export Pine Logs.
4. Normalize Pine logs with `bot/backtest/capture.py`.
5. Diff with `scripts/compare-pine-parity.py`.
6. Open dashboard replay page for visual check.

## Risk Register

| Risk | Likelihood | Impact | Phase | Mitigation | Signal It Broke | Response |
|---|---:|---:|---|---|---|---|
| `alertcondition()` cannot emit dynamic payload | High | High | P0 | migrate to `alert()` builder | webhook receives static text | block P0 until Pine migration done |
| Pine 40s budget exceeded | Medium | High | P0 | benchmark; build payload only on transitions | TV runtime warning/missed alerts | simplify payload, reduce alert paths |
| Webhook auth weaker than HMAC | High | Medium | P0 | URL token + IP allowlist + rate limit | invalid source reaches endpoint | rotate token, tighten proxy, add edge signing |
| Manual gates stale | Medium | High | P0 | daily/session expiry and callback revalidation | old Accept queues trade | mark expired, require fresh ack |
| Native MT5 on macOS fails | High | Medium | P2 | default to MetaAPI; file bridge only via Windows/VPS/VM | connector cannot initialize/read terminal | switch to MetaAPI or VM prerequisite |
| Duplicate demo order | Medium | High | P2 | idempotency key, EA processed store, magic number/client id | two orders same signal_id | disable executor, quarantine outbox/API token, investigate |
| Replay diverges from Pine | Medium | High | P1 | parity CSV diff + frozen checksums | comparator mismatch | inspect Pine payload vs Python event source |
| Telegram API outage | Low | Medium | P0 | durable queue + dashboard status | notified_failed rows | manual resend after recovery |
| Discord confirmation split-brain | Medium | High | P0 | Discord mirror-only | user expects Discord Accept | document Telegram-only authority |

## Measurable Success Criteria

P0 done:

- [ ] `SMC|v1` payload parser accepts documented schema and rejects malformed fields.
- [ ] FastAPI endpoint returns within 500 ms in local test for valid alert.
- [ ] Duplicate signal id creates no duplicate Telegram prompt.
- [ ] Telegram Accept is refused until all six manual gates are fresh.
- [ ] SQLite stores raw payload, normalized event, gate decisions, and final user decision.
- [ ] Live TradingView test alert reaches backend over HTTPS 443.

P1 done:

- [ ] Frozen OHLC replay produces deterministic signal CSV.
- [ ] Pine manual replay CSV can be normalized and compared.
- [ ] Dashboard shows live and replay history with filterable signal states.

P2 done:

- [ ] MetaAPI executor remains disabled by default and requires explicit env config.
- [ ] Accepted fresh signal writes exactly one execution request for selected transport.
- [ ] MT5 file reader refuses expired/duplicate/wrong-symbol/non-demo signals when file mode is selected.
- [ ] One explicit demo test order executes and logs result.
- [ ] Executor can be disabled without changing Pine/webhook/Telegram/replay flow.

## Open Questions

1. MT5 runtime target: Windows VPS/VM file bridge, or MetaAPI cloud from macOS?
2. Exact deployment surface for FastAPI: local tunnel for forward test, VPS, or existing hosting?
3. Telegram approval user ids: one trader only or multiple authorized reviewers?
4. Should `Accept` place market order immediately, or write limit order at OB edge and let MT5 manage fill?
5. For HMAC requirement: accept URL token + IP allowlist for direct TradingView, or add an edge proxy that signs requests before FastAPI?
6. Should live alerts include only `chart-qualified`, or also `watch`/`blocked` for training/audit noise?
