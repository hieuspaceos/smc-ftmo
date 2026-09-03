# Plan — Pine → Webhook → MT5 → Telegram Integration

> **Context**: User wants the SMC Pine indicator (TradingView) to emit
> trade signals via webhook to a Python bot, which executes trades on
> MT5 and sends notifications to Telegram.

## Goal

End-to-end pipeline:
```
[Pine chart M15]
   ↓ (TradingView alert with webhook URL)
[Bot webhook server :8000]
   ↓ parse SMC|v1 payload
[11-gate validator]
   ↓ if all pass
[MT5 file bridge] → writes pending/sid.json to shared folder
   ↓
[MT5 EA mql5_reader.mq5] → polls pending/, OrderSend, writes done/sid.json
   ↓
[Bot webhook] → reads done/, updates execution_log
   ↓
[Telegram bot] → sends "LONG EURUSD @ 1.0850, SL 1.0790" + later "CLOSED +1.5R"
```

## Current state

✅ **Already built**:
- `tradingview/smc-engine-indicator.pine` — Pine indicator với full SMC pipeline (BOS/CHoCH/OB/FVG/sweep/pool)
- `packages/smc_bot_webhook/` — FastAPI webhook + 11-gate validator + MT5 file bridge + Telegram/Discord dispatcher
- `docs/mt5-bridge-setup.md` — MT5 setup guide (existing)
- `packages/smc_bot_webhook/src/smc_bot_webhook/payload.py` — SMC|v1 payload parser
- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/signal_writer.py` — atomic JSON writer

❌ **Missing**:
- Pine script emit JSON payload (currently only `alertcondition` title + message, no side/entry/SL/TP)
- Cloudflare Tunnel (optional, for public webhook URL)
- End-to-end test doc

## Architecture (recap from `docs/mt5-bridge-setup.md`)

```
[Bot host (Mac / Linux / VPS)]
  ├── FastAPI webhook (:8000)
  ├── Telegram dispatcher
  └── Python signal_writer → writes <outbox>/pending/<sid>.json
                                ↓ shared folder (SMB / Syncthing / local)
[MT5 host (Windows / VM / VPS)]
  └── MQL5 EA (mql5_reader.mq5) → polls pending/ → OrderSend → writes <outbox>/done/<sid>.json
                                ↓ (same shared folder, polled by bot)
[Bot webhook background task]
  └── reads <outbox>/done/ → records execution_log → Telegram confirmation
```

## Phases

### Phase 1 — Pine emit JSON payload (2-3h, code)
**Goal**: TradingView alert fires with full SMC|v1 payload (side, entry, SL, TP1/2/3, OB id, BOS id, score).

**Files**:
- `tradingview/smc-engine-indicator.pine`: replace `alertcondition(rulebookState == "chart-qualified", ...)` with `alert()` call emitting `SMC|v1|...` formatted string

**Pine code pattern** (around line 1216):
```pine
chartQualifiedJSON = str.format(
    "SMC|v1|event=chart-qualified|symbol={0}|tf={1}|dir={2}|entry={3}|sl={4}|tp1={5}|tp2={6}|tp3={7}|ob_id={8}|bos_id={9}|state={10}|score={11}",
    syminfo.ticker,
    timeframe.period,
    bestObDir == 1 ? "long" : "short",
    str.tostring(entry, format.mintick),
    str.tostring(slEdge, format.mintick),
    str.tostring(scaleInTrigger, format.mintick),
    str.tostring(scaleInTrigger + (finalTp - scaleInTrigger) * 0.5, format.mintick),
    str.tostring(finalTp, format.mintick),
    str.tostring(bestObId),
    str.tostring(bestBosId),
    "chart-qualified",
    str.tostring(bestScore)
)

alert("SMC chart-qualified", chartQualifiedJSON)
```

**Acceptance**:
- Pine alert fires when `bestObId != bestObId[1]` (new chart-qualified setup)
- Payload contains all required SMC|v1 fields
- Payload parsable by `payload.parse_smc_v1_payload()`

---

### Phase 2 — Local webhook test (1-2h, manual)
**Goal**: Verify Pine → webhook works end-to-end on local network.

**Setup**:
1. Run bot locally: `uvicorn smc_bot_webhook.server:app --host 0.0.0.0 --port 8000`
2. Get local IP: `ifconfig | grep inet`
3. In TradingView: add alert with webhook URL `http://<local-ip>:8000/webhook/tradingview`
4. Trigger chart-qualified setup on chart → alert fires
5. Check webhook receives POST → verify in bot logs

**Acceptance**:
- Webhook returns 200 OK on POST
- Payload parsed correctly (signal_id computed)
- Bot logs show "SMC chart-qualified received"

---

### Phase 3 — Telegram bot setup (30min, manual)
**Goal**: Telegram bot can send messages to user.

**Setup**:
1. Create bot via @BotFather on Telegram → get `TELEGRAM_BOT_TOKEN`
2. Get your chat ID via @userinfobot → `TELEGRAM_CHAT_ID`
3. Set in `.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=123456789
   ```
4. Test: `python -c "from smc_bot_webhook.notify.telegram import send; send('hello')"`

**Acceptance**:
- Bot token valid
- Test message received in Telegram chat

---

### Phase 4 — MT5 host setup (2-3h, manual)
**Goal**: MT5 demo account + EA running + connected to bot.

**Setup** (per `docs/mt5-bridge-setup.md`):
1. Install MT5 on Windows / VPS / VM
2. Open FTMO demo account (free) at ftmo.com
3. Compile `packages/smc_bot_webhook/mt5_bridge/mql5_reader.mq5` in MetaEditor
4. Configure shared folder (SMB / Syncthing / local mount)
5. Enable AutoTrading in MT5
6. Run EA on M15 chart of EURUSD

**Acceptance**:
- EA polls <outbox>/pending/ every 1 second
- When pending file appears, EA places OrderSend
- Writes <outbox>/done/<sid>.json after fill

---

### Phase 5 — Cloudflare Tunnel (optional, 1h, manual)
**Goal**: Public webhook URL without exposing bot host.

**Setup** (if bot runs on home network without public IP):
1. Install `cloudflared`: `brew install cloudflared`
2. Login: `cloudflared tunnel login`
3. Create tunnel: `cloudflared tunnel create smc-bot`
4. Configure: `cloudflared tunnel route dns smc-bot smc.your-domain.com`
5. Run: `cloudflared tunnel --url http://localhost:8000 run smc-bot`
6. Use Cloudflare URL in TradingView alert

**Alternative**: Skip if bot runs on VPS with public IP.

**Acceptance**:
- TradingView alert reaches bot via Cloudflare URL
- Latency acceptable (<500ms)

---

### Phase 6 — Live FTMO demo (2-4 weeks, manual)
**Goal**: Validate trader behavior + bot end-to-end with real demo.

**Setup**:
1. Use FTMO demo account (free) instead of regular broker demo
2. Risk per trade: 0.55% ($550 on $100K)
3. Monitor Telegram for trade alerts
4. Manual override available (close position via MT5 if needed)
5. Journal trades in `journal/manual_trades_2026.md`

**Acceptance**:
- Bot trades 24/7 without crash
- Telegram alerts arrive within 5 seconds of Pine signal
- No missed trades due to downtime
- Equity curve matches backtest expectations (+~30K/month)

---

## Files to modify/create

| File | Phase | Action |
|---|---|---|
| `tradingview/smc-engine-indicator.pine` | 1 | Modify — add `alert()` with JSON payload |
| `packages/smc_bot_webhook/src/smc_bot_webhook/payload.py` | 1 | Maybe update — verify parser accepts new fields |
| `docs/pine-webhook-setup.md` | 1,2,3 | Create — step-by-step Pine → Telegram guide |
| `.env.example` | 3 | Update — add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID docs |
| `docs/mt5-bridge-setup.md` | 4 | Already exists — reference |
| `tests/test_pine_payload.py` | 1 | Create — validate Pine payload format |

## Dependencies

- **Pine Script v6** (TradingView)
- **FastAPI** (already installed)
- **Telegram Bot API** (need user to create bot via @BotFather)
- **Cloudflare Tunnel** (optional, if public webhook needed)
- **MT5** + MetaEditor (Windows / VPS)

## Effort summary

| Phase | Effort | Type |
|---|---|---|
| 1 | 2-3h | Code |
| 2 | 1-2h | Manual test |
| 3 | 30min | Manual setup |
| 4 | 2-3h | Manual setup |
| 5 | 1h | Manual (optional) |
| 6 | 2-4 weeks | Live validation |
| **Total manual setup** | **~5-7h** | |
| **Total automation** | **~3h** | |

## Success criteria

After all 6 phases:
- ✅ Pine script fires `alert()` with SMC|v1 JSON payload on chart-qualified
- ✅ Bot webhook receives payload, validates 11 gates, writes to <outbox>/pending/
- ✅ MT5 EA reads pending/, places OrderSend on FTMO demo
- ✅ Bot reads done/, sends Telegram notification ("LONG EURUSD @ 1.0850")
- ✅ Trade closed → Telegram notification ("CLOSED +1.5R, +$825")
- ✅ End-to-end latency < 5 seconds (Pine → Telegram)
- ✅ 2-4 weeks FTMO demo validates full pipeline
- ✅ Edge verified: equity curve matches backtest expectations

## Risks

- **TradingView alert webhook URL change**: TradingView may change webhook format. Pin to specific TradingView API version in payload parser.
- **Telegram rate limits**: Free tier ~30 msgs/min to same chat. Bot sends 2-3 msgs/trade, well under limit.
- **MT5 EA disconnection**: If Windows reboots, EA may stop. Need auto-restart script.
- **Shared folder sync delay**: SMB/Syncthing may delay file visibility by 1-2 seconds. Acceptable for swing trading.
- **Pine script errors**: Bad payload breaks webhook. Add JSON validation + reject malformed.

## Verification commands

```bash
# Phase 1: validate Pine payload format
python -c "
from packages.smc_bot_webhook.src.smc_bot_webhook.payload import parse_smc_v1_payload
sample = 'SMC|v1|event=chart-qualified|symbol=EURUSD|tf=M15|dir=long|entry=1.0850|sl=1.0790|tp1=1.0970|tp2=1.1030|tp3=1.1090|ob_id=42|bos_id=17|state=chart-qualified|score=4.5'
p = parse_smc_v1_payload(sample)
print(p.signal_id, p.side, p.entry_price)
"

# Phase 2: test webhook locally
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: text/plain" \
  -d "SMC|v1|event=chart-qualified|symbol=EURUSD|..."

# Phase 3: test Telegram
python -c "from smc_bot_webhook.notify.telegram import send; send('test from SMC bot')"
```

## Out of scope

- News filter (separate plan)
- Multi-account (one MT5 → one FTMO demo)
- Strategy parameter tuning via live data
- Adaptive lot sizing based on volatility
