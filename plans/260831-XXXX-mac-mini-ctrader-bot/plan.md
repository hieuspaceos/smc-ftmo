# Plan — Mac mini cTrader Signal Bot (no MT5, no VPS)

> **Context**: User rejected TradingView (canceled Premium) and MT5
> (unstable on Mac M4 Apple Silicon). Decided to use **cTrader Open API**
> (Spotware) running on Mac mini M4 as a 24/7 local server. Bot pulls
> live M15 candle data from cTrader, runs `smc_engine` to detect chart-
> qualified setups, and sends Telegram alerts. User manually executes
> on cTrader Mac.

## Goal

```
[Mac mini M4 — 24/7]
  ├── cTrader Mac native (Apple Silicon)
  │     └── FTMO demo account (or live after pass)
  ├── Python bot (Mac native, arm64)
  │     ├── bot/ctrader_client.py  (Spotware Open API client)
  │     ├── bot/data_feed.py       (poll M15 every 15 min)
  │     ├── bot/signal_engine.py   (smc_engine on new bars)
  │     ├── bot/validator.py        (Phase 1.5 cross-check)
  │     ├── bot/watcher.py         (orchestrator: fetch→detect→validate→notify)
  │     └── bot/notify/telegram.py (existing)
  ↓
[Telegram → user's phone]
  ↓
[cTrader Mac → user manually executes]
```

## Why cTrader (not MT5)

| | cTrader | MT5 |
|---|---|---|
| Mac M4 native | ✅ Yes (Apple Silicon) | ⚠️ Crashes reported |
| FTMO supported | ✅ Yes | ✅ Yes (default) |
| Python API | ✅ Official (`ctrader-open-api`) | ✅ Official (`MetaTrader5`) |
| Free demo | ✅ $100k virtual | ✅ Free demo |
| Open API auth | OAuth 2.0 + Playground | Direct install |
| Async framework | Twisted (reactive) | Blocking poll |

cTrader is the only stable native Mac M4 option that supports FTMO.

## Requirements

### Hardware
- **Mac mini M4** (Apple Silicon, 8GB+ RAM recommended)
- **24/7 power** (no sleep, no shutdown) — System Settings → Energy → disable sleep
- **Stable internet** (Ethernet cable recommended over WiFi for 24/7)

### Software
- **macOS 12+** (Monterey or later)
- **Python 3.11+** (via Homebrew or official installer)
- **cTrader Mac** (download from cTrader.com, install .dmg)
- **FTMO demo account** (cTrader platform selected at signup)

### Accounts & Credentials
- **cTrader ID** (cTID): single account, used to log in to all cTrader apps
- **Open API app** (register at https://openapi.ctrader.com/apps):
  - Client ID
  - Client Secret
  - Redirect URI: `http://localhost:5000/callback`
- **Access token** (get via Playground, valid ~30 days):
  - accessToken
  - refreshToken (save for long-running bot)
- **FTMO demo account ID** (numeric ctidTraderAccountId, visible in cTrader Mac)
- **Telegram bot** (already set up — token + chat ID from previous session)

### Python packages
```
pip install ctrader-open-api twisted protobuf pandas pyarrow httpx python-dotenv python-telegram-bot
```

`smc_engine` and `pandas` are already in the repo.

## Architecture

### File layout
```
packages/smc_bot_signal/   ← NEW package
├── __init__.py
├── config.py              ← env-based settings (env vars)
├── state.py               ← SQLite alert history (dedup)
├── data_feed.py           ← cTrader Open API → M15 candles
├── signal_engine.py       ← smc_engine wrapper
├── validator.py           ← Phase 1.5 cross-check
├── watcher.py             ← main loop: fetch → detect → validate → notify
├── notify/
│   ├── __init__.py
│   └── telegram.py        ← reuse from smc_bot_webhook
└── tests/
    ├── test_config.py
    ├── test_state.py
    ├── test_data_feed.py
    ├── test_signal_engine.py
    └── test_watcher.py
```

### Flow

```
┌─ bot/watcher.py (main loop, every 60s)
│
├─ bot/data_feed.py
│    └─ cTrader Open API → poll latest M15 candle
│
├─ bot/signal_engine.py
│    └─ if new bar → run smc_engine (swings, structure, OB, sweep)
│
├─ bot/validator.py
│    └─ if chart-qualified → run smc_engine again for cross-check
│
├─ bot/notify/telegram.py
│    └─ if diverges (matched=False) → send "⚠️ diverge" annotation
│       if matched=True → send "✓ matched"
│       if validated=None → send "⚠️ skipped"
│
└─ bot/state.py
     └─ log alert_id, send_id, timestamp to SQLite (dedup window)
```

### Data flow detail

1. **Watcher** runs every 60s (configurable)
2. Calls `data_feed.get_latest_bar(symbol="EURUSD", timeframe="M15")`
3. `data_feed` uses cTrader Open API (Twisted event loop) to subscribe
   to spot feeds and emit new bars via callback
4. When new bar arrives, `signal_engine.run(bar)` is called
5. `signal_engine` loads 500 prior bars, runs smc_engine full pipeline
   (swing, structure, OB, sweep, displacement, regime)
6. If `bestObId != bestObId[1]` (new chart-qualified setup) → validate
7. `validator.run(payload)` calls `validate_pine_signal()` (Phase 1.5)
8. `telegram.send(payload, validation=...)` formats message with trade
   levels + Python SMC validation tag
9. `state.record_alert(signal_id, ...)` saves to SQLite (dedup)

### Concurrency model

cTrader Open API uses **Twisted** (async event loop). Our bot is
single-threaded async:

```python
# bot/watcher.py
from twisted.internet import reactor, task

def main():
    cfg = load_config()
    feed = CTraderDataFeed(cfg)
    engine = SignalEngine(cfg)
    validator = Validator(cfg)
    notify = TelegramNotifier(cfg)
    state = StateDB(cfg)
    
    # Periodic check every 60s
    def check_loop():
        try:
            latest = feed.get_latest_bar("EURUSD", "M15")
            signal = engine.process_bar(latest)
            if signal and state.should_notify(signal.signal_id):
                validation = validator.run(signal)
                notify.send(signal, validation)
                state.record_alert(signal)
        except Exception:
            logger.exception("check_loop error")
    
    loop = task.LoopingCall(check_loop)
    loop.start(60.0)  # every 60 seconds
    
    reactor.run()
```

### Phase 1.5 reuse

The `validate_pine_signal()` function in
`packages/smc_bot_webhook/src/smc_bot_webhook/smc_validator.py`
is already implemented and tested. It accepts any DataFrame — we just
import it and pass the data we already loaded for `signal_engine`.

## Configuration

`packages/smc_bot_signal/config.py` reads from `.env`:

```python
@dataclass(frozen=True)
class Config:
    # cTrader Open API
    ctrader_client_id: str
    ctrader_client_secret: str
    ctrader_access_token: str
    ctrader_refresh_token: str
    ctrader_account_id: int
    ctrader_host: str = "demo.ctraderapi.com"  # demo by default
    
    # Symbols to watch
    symbols: tuple[str, ...] = ("EURUSD",)
    timeframe: str = "M15"
    
    # Watch loop
    poll_interval_seconds: int = 60
    
    # Validation
    validate_signal: bool = True
    validation_tolerance_pips: float = 5.0
    
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: int
    
    # State
    state_db_path: str = "output/signal_state.db"
    dedup_window_minutes: int = 60  # suppress duplicate alerts within window

    @classmethod
    def from_env(cls):
        ...
```

## Phases

### Phase 1 — cTrader connection (3-4 days)

**Goal**: Bot can authenticate with cTrader demo and pull M15 candle
data reliably.

**Files**:
- `packages/smc_bot_signal/config.py` — env-based Config
- `packages/smc_bot_signal/ctrader_client.py` — Twisted client wrapper
  with reconnect logic
- `packages/smc_bot_signal/data_feed.py` — M15 polling layer
- `tests/test_ctrader_client.py` — connection / reconnect (mocked)

**Acceptance**:
- Bot connects to demo.ctraderapi.com within 30s
- Auth succeeds with stored access token
- Bot receives M15 bar callback within 1s of bar close
- Reconnect after network blip within 30s

### Phase 2 — Signal engine (2 days)

**Goal**: Run `smc_engine` on each new M15 bar, detect chart-qualified.

**Files**:
- `packages/smc_bot_signal/signal_engine.py` — wraps `smc_engine`
- `packages/smc_bot_signal/state.py` — alert dedup (SQLite)
- `tests/test_signal_engine.py` — offline replay from CSV

**Acceptance**:
- Bot detects chart-qualified setups that match Pine script behavior
- Reuses existing `validate_pine_signal()` for cross-check
- Alerts persisted to SQLite, never duplicated within dedup window

### Phase 3 — Telegram dispatcher (1 day)

**Goal**: Send message with trade levels + validation tag.

**Files**:
- `packages/smc_bot_signal/notify/telegram.py` — reuse `format_telegram_message`
- `packages/smc_bot_signal/validator.py` — wraps `validate_pine_signal`

**Acceptance**:
- Telegram message arrives within 5s of detection
- Message includes: side, entry, SL, TP1/2/3, score, Python validation tag
- Validation tag matches 3 states (matched / diverge / skipped)

### Phase 4 — Mac mini deployment (1 day)

**Goal**: Bot runs 24/7 on Mac mini.

**Files**:
- `deploy/mac-mini-setup.sh` — Homebrew install, no-sleep config, autostart
- `deploy/launchd/com.smc.signal.plist` — auto-restart on boot
- `docs/deploy-mac-mini-ctrader.md` — step-by-step guide

**Acceptance**:
- Bot auto-starts on Mac mini boot
- Survives WiFi reconnect (reconnect within 30s)
- Logged to `~/Library/Logs/smc-signal.log`

### Phase 5 — Live validation (1 week)

**Goal**: Verify on FTMO demo account.

**Tasks**:
- Run bot 24/7 for 1 week
- Cross-check signals against cTrader Mac manual analysis
- Iterate on false positives / missed setups

## Risks

| Risk | Mitigation |
|---|---|
| Access token expires (30 days) | Refresh token + scheduled refresh job |
| cTrader server disconnect | Twisted auto-reconnect with backoff |
| Mac sleeps despite settings | Caffeine app or `caffeinate -i` |
| Power outage | UPS ($30-50) or accept downtime |
| Internet outage | Ethernet cable (WiFi fails silently) |
| SMC logic divergence (Python vs Pine) | Validate against historical data first |

## Effort summary

| Phase | Effort | Code |
|---|---|---|
| 1. cTrader connection | 3-4 days | `ctrader_client.py`, `data_feed.py`, `config.py` |
| 2. Signal engine | 2 days | `signal_engine.py`, `state.py` |
| 3. Telegram dispatcher | 1 day | `validator.py`, `notify/telegram.py` |
| 4. Mac deploy | 1 day | `deploy/`, `docs/` |
| 5. Live validation | 1 week | manual |
| **Total code** | **~7-8 days** | |
| **Total wall time** | **~10 days** (with validation) | |

**Cost**: €0/mo (Mac mini + cTrader demo + Telegram).

## Open questions before starting

1. **cTrader demo account**: bạn đã có chưa? (Free, tạo tại cTrader.com nếu chưa)
2. **Open API app**: bạn đã register chưa? (https://openapi.ctrader.com/apps — cTID + app name + redirect URI)
3. **Mac mini Python**: đã có Python 3.11+ chưa? (`brew install python@3.11`)
4. **Mac mini chạy 24/7 OK**: sleep tắt, internet ổn? (cần test 1-2 ngày)
5. **Symbols quan tâm**: EURUSD only, hay nhiều cặp (GBPUSD, XAUUSD, USDJPY)?

## References

- cTrader Open API docs: https://help.ctrader.com/open-api/
- Python SDK (OpenApiPy): https://github.com/spotware/OpenApiPy
- cTrader Mac install: https://help.ctrader.com/ctrader-mac/
- smc_engine package (existing in repo): `packages/smc_engine/src/smc_engine/`

## Next step

Trả lời 5 câu trên, tôi sẽ bắt đầu implement Phase 1.
