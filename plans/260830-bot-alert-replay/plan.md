---
title: "Bot Cảnh Báo + Demo MT5 + Backtest Replay"
description: "Build signal router around SMC Engine: TradingView alert → FastAPI → 11-gate Rulebook validator → Telegram Accept/Reject → Demo MT5 execution + deterministic Python replay for backtest."
status: pending
priority: P1
branch: "master"
tags: [bot, telegram, mt5, fastapi, parity, rulebook, replay]
blockedBy: []
blocks: []
created: "2026-08-30T21:00:00+07:00"
createdBy: "codex"
source: direct-request
architecture: "./architecture.md"
---

# Bot Cảnh Báo + Demo MT5 + Backtest Replay

## Overview

Xây dựng một **signal router** an toàn xung quanh Pine/Python SMC engine đã có:

1. **P0 — Alert intake + manual approval audit** (no MT5)
   - TradingView Pine `alert()` payload → FastAPI webhook → SQLite → 11-gate validator → Telegram Accept/Reject
2. **P1 — Replay capture + dashboard**
   - Deterministic Python replay từ frozen OHLC → signal CSV → Streamlit dashboard
   - Manual TradingView Bar Replay + Pine Logs export → parity compare
3. **P2 — Demo MT5 execution** (sau khi P0 stable 4-8 tuần)
   - Telegram Accept → validator re-check → **file-based MT5 bridge** (free, gọn — user chọn)
   - MQL5 EA đọc outbox JSON → execute trên MT5 Demo (Windows/VPS/VM terminal)
   - Demo account only, 0.01 lot test order, FTMO guard
   - MetaAPI cloud là optional fallback nếu file bridge không khả thi
**Nguyên tắc bất di bất dịch**:

- Không bao giờ auto-trade mà không có 6 manual gates fresh acknowledged
- Telegram là **manual approval authority duy nhất** (Discord mirror-only)
## Dependencies

- **External services**:
  - TradingView Premium (đã có, 40s execution budget — Pine migration phải benchmark)
  - **Cloudflare Tunnel** (free, user chọn) — cung cấp HTTPS public URL cho webhook
  - Telegram Bot token (cần tạo qua @BotFather — user sẽ cung cấp qua `.env`)
  - MT5 Demo account (P2 only — chạy trên Windows/VPS/VM)
  - MetaAPI cloud (P2 optional fallback, KHÔNG default — user đã chọn file bridge)
  - **Live alert scope**: cả `chart-qualified`, `watch`, và `blocked` (user chọn cả 2)



- **Existing code**:
  - `tradingview/smc-engine-indicator.pine` (v1.2 — đã commit)
  - `scripts/capture-frozen-feed.py` (đã có)
  - `scripts/compare-pine-parity.py` (đã có)
  - `src/smc_engine/` Python engine (224 tests passing)
  - `output/trades.db` (existing journal — không touch)
- **New libraries** (P0):
  - `fastapi` + `uvicorn`
  - `python-telegram-bot` v21+
  - `httpx` (cho Discord webhook mirror)
  - `python-dotenv` (env management)

## Acceptance Criteria

### P0 done
- [ ] Pine script có `alert()` dynamic payload thay thế một số `alertcondition()`
- [ ] `SMC|v1|...` payload parser chấp nhận schema + reject malformed
- [ ] FastAPI endpoint trả <500ms trong local test
- [ ] Duplicate signal_id → 1 Telegram prompt, không duplicate
- [ ] Telegram Accept bị refuse nếu thiếu 6 manual gates
- [ ] SQLite lưu raw payload + parsed event + gate decisions + user decision
- [ ] Live TradingView test alert reach backend qua HTTPS 443

### P1 done
- [ ] Frozen OHLC replay produce deterministic signal CSV
- [ ] Pine manual replay CSV normalize được và compare với Python
- [ ] Dashboard show live + replay history, filter signal states

### P2 done
- [ ] MetaAPI executor disabled by default, cần explicit env config
- [ ] Accepted fresh signal → exactly 1 execution request
- [ ] File bridge EA refuse expired/duplicate/wrong-symbol/non-demo
- [ ] 1 explicit demo test order executes + log
- [ ] Executor disable được không ảnh hưởng P0/P1

## Files Created

```
bot/
  __init__.py
  webhook/
    __init__.py, server.py, payload.py, security.py
  gates/
    __init__.py, validator.py, state.py
  notify/
    __init__.py, telegram.py, discord.py
  mt5_bridge/
    __init__.py, signal_writer.py, mql5_reader.mq5, metaapi_executor.py
  backtest/
    __init__.py, capture.py, replay_engine.py
  dashboard/
    __init__.py, streamlit_app.py
  storage/
    __init__.py, db.py, schema.sql

tests/
  test_bot_payload.py
  test_bot_gates.py
  test_bot_webhook.py
  test_bot_signal_writer.py
  test_bot_replay_capture.py

tradingview/smc-engine-indicator.pine  (modify: dynamic alert)
```

## Rollback

- **P0/P1 không destructive**: chỉ thêm files mới + SQLite tables mới + 1 Pine alert toggle
- **P2**: feature flag `EXECUTOR_TRANSPORT=disabled` default. Rollback bằng cách tắt env var
- **Pine dynamic alert**: giữ `alertcondition()` làm fallback, có thể revert bằng cách tắt input toggle

## Unresolved Questions

1. **MT5 runtime target**: MetaAPI cloud (macOS-safe) hay file bridge cần Windows/VPS?
2. **Deployment**: local tunnel (cloudflared) cho forward test hay VPS riêng?
3. **Telegram users**: 1 trader only hay multiple authorized reviewers?
4. **Order type**: market immediate hay limit tại OB edge?
5. **Live alert scope**: chỉ `chart-qualified` hay cả `watch`/`blocked` cho audit?
6. **Replay UI**: visual trên dashboard với replay buttons (prev bar, next bar) hay read-only?

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| `alertcondition()` không emit dynamic payload | High | High | migrate sang `alert()` builder; benchmark trên Premium 40s |
| Pine 40s budget vượt | Medium | High | build payload chỉ on state transitions; giảm alert paths |
| Webhook auth yếu hơn HMAC | High | Medium | URL token + IP allowlist + rate limit + edge proxy optional |
| Manual gates stale | Medium | High | daily/session expiry + Accept callback revalidates |
| Native MT5 fail trên macOS | High | Medium | MetaAPI default; file bridge chỉ với Windows/VPS/VM |
| Duplicate demo order | Medium | High | idempotency key + EA processed list + magic number |
| Replay diverge từ Pine | Medium | High | parity CSV diff + frozen checksums |
| Telegram API outage | Low | Medium | durable queue + dashboard status `notified_failed` |

## User Decisions (resolved 2026-08-30)

- [x] **MT5 transport**: **file-based bridge** (free, gọn) — MetaAPI chỉ optional fallback nếu file bridge không khả thi
- [x] **Deployment**: **Cloudflare Tunnel** (free, nhanh, không cần VPS riêng)
- [x] **Telegram users**: cung cấp sau qua `.env` (`TELEGRAM_ALLOWED_USERS`)
- [x] **Live alert scope**: cả `chart-qualified`, `watch`, và `blocked` (audit đầy đủ)
- [x] **Web admin access** (resolved 2026-08-30): trader muốn quản lý bot từ bất kỳ đâu qua web admin panel — dùng **Cloudflare Access** password-protect + cùng tunnel với webhook
