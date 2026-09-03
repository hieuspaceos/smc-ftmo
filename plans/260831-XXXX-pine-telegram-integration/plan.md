# Plan — Pine → Webhook → Telegram (NO MT5)

> **Context**: User trades manual on TradingView. Wants SMC Pine
> indicator to send trade signals to Telegram via webhook. NO MT5
> bridge — user places orders manually on TradingView chart.

## Goal

End-to-end pipeline:
```
[TradingView Pine chart M15]
   ↓ (alert with webhook URL)
[Bot webhook server :8000]
   ↓ parse SMC|v1 payload
[11-gate validator]
   ↓ if all pass
[Telegram bot]
   ↓ send message
[User's phone] 🔔 nhận notification
   ↓
[User manual action] → vào TradingView → place order manual
```

## Simplified vs original plan

| Removed | Reason |
|---|---|
| MT5 host setup (Phase 4) | User trade manual trên TradingView |
| Cloudflare Tunnel (Phase 5) | Optional, only if bot on VPS without public IP |
| Order filled message | No MT5 fill event |
| Trade closed message | User closes manual, can notify bot via reply |

## Current state

✅ **Already built**:
- `tradingview/smc-engine-indicator.pine` — Pine indicator với full SMC pipeline (BOS/CHoCH/OB/FVG/sweep/pool)
- `packages/smc_bot_webhook/` — FastAPI webhook + 11-gate validator + Telegram dispatcher
- `packages/smc_bot_webhook/src/smc_bot_webhook/payload.py` — SMC|v1 payload parser

❌ **Missing**:
- Pine script emit JSON payload (currently only `alertcondition` title + message)
- Optional: Cloudflare Tunnel (for public webhook)

## Architecture (simplified)

```
┌─────────────────────────────────────────────────┐
│ TradingView (Cloud)                              │
│   Pine chart M15                                 │
│   Alert with webhook URL → POST                  │
└────────────────┬────────────────────────────────┘
                 │ HTTP POST
                 ↓
┌─────────────────────────────────────────────────┐
│ Bot host (your machine or VPS)                   │
│   FastAPI webhook :8000                          │
│   - parse SMC|v1 payload                        │
│   - 11-gate validator                            │
│   - if pass → Telegram send                      │
└────────────────┬────────────────────────────────┘
                 │ HTTPS POST
                 ↓
┌─────────────────────────────────────────────────┐
│ Telegram Bot API (cloud)                          │
│   → User's phone                                 │
│   🔔 Notification                                │
└─────────────────────────────────────────────────┘

[User sees notification → opens TradingView → places order manual]
```

## Phases

### Phase 1 — Pine emit JSON payload (2-3h, code)
**Goal**: TradingView alert fires with full SMC|v1 payload (side, entry, SL, TP1/2/3, OB id, BOS id, score).

**File**:
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

### Phase 4 (optional) — VPS + Cloudflare Tunnel (1h, manual)
**Goal**: Run bot 24/7 on VPS so you don't need your PC always on.

**Setup** (if needed):
1. Rent cheap VPS (DigitalOcean $4-6/month, Hetzner €3.79/month, AWS Lightsail $3.50/month)
2. SSH in, install Python + dependencies, copy code
3. Run webhook as systemd service: `systemctl enable smc-webhook`
4. Install cloudflared: `brew install cloudflared` (or apt on Linux)
5. Login: `cloudflared tunnel login`
6. Create tunnel: `cloudflared tunnel create smc-bot`
7. Configure DNS: `cloudflared tunnel route dns smc-bot smc.your-domain.com`
8. Run: `cloudflared tunnel --url http://localhost:8000 run smc-bot`
9. Use Cloudflare URL in TradingView alert: `https://smc.your-domain.com/webhook/tradingview`

**Alternative**: If VPS has public IP, skip Cloudflare, use `http://<vps-ip>:8000/webhook/tradingview` directly.

**Acceptance**:
- TradingView alert reaches bot via Cloudflare URL
- Latency acceptable (<500ms)
- Webhook stays up 24/7

---

### Phase 5 — Live manual trade (continuous)
**Goal**: Validate full pipeline + trader behavior over weeks/months.

**Daily workflow**:
1. Open TradingView EURUSD M15 chart
2. Pine indicator runs, alerts fire on chart-qualified setups
3. Receive Telegram notification with entry/SL/TP levels
4. Open TradingView → place order manual (limit order on Pine's entry level)
5. Set SL + TP1 + TP2 manually
6. Journal trade in `journal/manual_trades_2026.md`

**Acceptance**:
- Alerts arrive within 5 seconds of Pine signal
- No missed signals (24/7 monitoring)
- Trader follows Pine signals consistently (adherence metric)
- Equity curve matches backtest expectations (+~$30K/month)

---

## Telegram message format

### 1. Trade signal detected
```
🟢 SMC SIGNAL — LONG EURUSD

Entry:  1.08500
SL:     1.07900 (-50 pips, 1.0×ATR)
TP1:    1.09700 (2R) — close 50%
TP2:    1.10900 (4R) — close remaining

Score: 4.5/5
HTF: D=bull H4=bull ✓
OB id: 42 | BOS id: 17

→ Mở TradingView EURUSD M15, place limit order @ 1.0850
→ Set SL 1.0790, TP1 1.0970 (50%), TP2 1.1090 (50%)

Time: 2026-09-03 14:30 UTC
Signal ID: abc123...
```

### 2. (optional) Order placed confirmation
```
✋ ORDER PLACED — manual entry

Pair: EURUSD
Side: LONG
Entry: 1.08500
SL: 1.07900
TP1: 1.09700 (50%)
TP2: 1.10900 (50%)

→ Reply /placed in Telegram to log
```

### 3. (optional) Close confirmation
```
✅ TRADE CLOSED — +1.5R (+$825)

Pair: EURUSD
Side: LONG
Closed at: TP1 (1.09700)
P&L: +$550 (gross)
R-multiple: +1.5R
Account: $100,825

→ Reply /closed to log
```

---

## Files to modify/create

| File | Phase | Action |
|---|---|---|
| `tradingview/smc-engine-indicator.pine` | 1 | Modify — add `alert()` with JSON payload |
| `packages/smc_bot_webhook/src/smc_bot_webhook/payload.py` | 1 | Verify parser accepts new fields |
| `tests/test_pine_payload.py` | 1 | Create — validate Pine payload format |
| `docs/pine-telegram-setup.md` | 1,2,3 | Create — step-by-step guide for user |
| `.env.example` | 3 | Update — add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID docs |

## Dependencies

- **Pine Script v6** (TradingView)
- **FastAPI** (already installed)
- **Telegram Bot API** (need user to create bot via @BotFather)
- **Cloudflare Tunnel** (optional, only if VPS without public IP)
- **VPS** (optional, for 24/7 uptime)

## Effort summary

| Phase | Effort | Type |
|---|---|---|
| 1 | 2-3h | Code |
| 2 | 1-2h | Manual test |
| 3 | 30min | Manual setup |
| 4 (optional) | 1h | Manual setup |
| 5 | Continuous | Manual trade |
| **Total** | **~4-5h** | |

## Success criteria

After all phases:
- ✅ Pine script fires `alert()` with SMC|v1 JSON payload on chart-qualified
- ✅ Bot webhook receives payload, validates 11 gates, sends Telegram
- ✅ User receives Telegram alert within 5 seconds of Pine signal
- ✅ User can manually execute trade on TradingView within 1 minute
- ✅ Full pipeline runs 24/7 (if VPS + cloudflare deployed)
- ✅ Trader follows Pine signals consistently (adherence metric tracked)

## Risks

- **TradingView alert webhook URL change**: TradingView may change webhook format. Pin to specific TradingView API version in payload parser.
- **Telegram rate limits**: Free tier ~30 msgs/min to same chat. Bot sends 2-3 msgs/trade, well under limit.
- **Local bot downtime**: If bot crashes, signals lost. Mitigation: VPS + systemd service.
- **Network split**: TradingView → bot path broken. Mitigation: VPS with stable connection.
- **Pine script errors**: Bad payload breaks webhook. Mitigation: JSON validation + reject malformed.
- **Trader non-adherence**: User may not place order when alert fires. Track adherence in journal.

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

- MT5 bridge (user trades manual on TradingView)
- News filter (separate plan)
- Multi-pair alerts (one Telegram message per pair, or one summary)
- Strategy parameter tuning via live data
- Adaptive lot sizing based on volatility
