# Phase 01: Pine Dynamic Alert + FastAPI Webhook

## Context

- [Plan](./plan.md)
- [Architecture](./architecture.md)
- Pine v6 indicator v1.2 hiện dùng `alertcondition()` static message — không emit được dynamic `SMC|v1|...` payload
- TradingView webhook chỉ POST body (text/plain nếu plain string), HTTPS port 443, ≤3s response, IP allowlist published
- Repo chưa có webhook handler nào

## Goal

Enable dynamic `alert()` payload từ Pine + FastAPI endpoint parse + persist + idempotency. **Chưa execute, chưa Telegram — đó là Phase 02-03.**

**Deployment** (user decision 2026-08-30): **Cloudflare Tunnel** (free) cung cấp HTTPS public URL cho webhook. Local FastAPI bind `127.0.0.1:8000` chạy qua `cloudflared tunnel --url http://localhost:8000`.

**Live alert scope** (user decision 2026-08-30): cả `chart-qualified`, `watch`, và `blocked` đều gửi alert để audit. Telegram hiển thị state để trader quyết định.

## Requirements

### Pine changes (`tradingview/smc-engine-indicator.pine`)

- [ ] Thêm payload builder function `f_make_alert_payload(event, symbol, tf, dir, level, bar_time, ob_id, bos_id, state, reason)`
- [ ] Replace 8 `alertcondition()` hiện tại (BOS/CHoCH/OB/sweep/pool/chart-qualified/watch/blocked) bằng `alert(payload, alert.freq_once_per_bar_close)` cho state transitions
- [ ] Giữ `alertcondition()` làm fallback human-readable trong P0
- [ ] Benchmark script trên Premium 40s budget — payload building phải string-light
- [ ] Add input toggle `Use dynamic alert payload (P0 webhook)` default `false` — bật sau khi benchmark OK

### FastAPI server (`bot/webhook/server.py`)

- [ ] `POST /webhooks/tradingview` endpoint
- [ ] `GET /healthz` endpoint
- [ ] Verify source: TradingView IP allowlist (52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7) + shared URL secret query param
- [ ] Body size cap: 4 KB
- [ ] Rate limit: per-IP + per-token (e.g., 60 req/min)
- [ ] Response: `202 Accepted` (new valid), `200 OK` (duplicate), `4xx` (invalid/auth)

### Payload parser (`bot/webhook/payload.py`)

- [ ] Pydantic model `AlertPayload`
- [ ] Required fields: prefix=`SMC`, version=`v1`
- [ ] Field validation: event enum, symbol allowlist (EURUSD P0), tf enum, dir enum, level decimal, bar_time int, ob_id int optional, bos_id int optional, state enum (chart-qualified/watch/blocked — P0 nhận cả 3), reason string
- [ ] Compute `signal_id` deterministic hash: `sha256(event + symbol + tf + dir + level + bar_time + ob_id + bos_id)[:16]`
- [ ] Reject malformed payload → 400

### Storage (`bot/storage/db.py` + `schema.sql`)

- [ ] SQLite connection helper
- [ ] Run schema migration on startup
- [ ] Tables: `alert_log`, `gate_ack`, `signal_events`, `execution_log` (chỉ `alert_log` dùng ở P0)
- [ ] Additive — không touch existing `output/trades.db` schema
- [ ] Path: `output/bot.db` (mới, không conflict)

## Files to Create/Modify

- Modify: `tradingview/smc-engine-indicator.pine` (add payload builder + dynamic alert)
- Create: `bot/__init__.py`, `bot/webhook/__init__.py`, `bot/webhook/server.py`, `bot/webhook/payload.py`, `bot/webhook/security.py`
- Create: `bot/storage/__init__.py`, `bot/storage/db.py`, `bot/storage/schema.sql`
- Create: `tests/test_bot_payload.py`, `tests/test_bot_webhook.py`
- Create: `requirements-bot.txt` (fastapi, uvicorn, pydantic, httpx, python-dotenv)
- Create: `.env.example` (`SMC_WEBHOOK_TOKEN=...`)
- Create: `cloudflared-config.yml` (quick tunnel config)

## Implementation Steps

1. **Pine payload builder** (1-2h):
   - Add `f_make_alert_payload()` Pine function
   - Add input toggle `useDynamicAlertPayload` default false
   - Wrap `alert()` calls in `if useDynamicAlertPayload`
   - Keep `alertcondition()` always for fallback

2. **Pydantic parser** (2h):
   - Define `AlertPayload` with validations
   - Signal ID hashing
   - Unit tests for valid/invalid/malformed

3. **FastAPI server** (3h):
   - Wire up endpoint with auth middleware
   - Persist to SQLite before any external calls (TradingView 3s timeout rule)
   - Background dispatch (return 202 immediately)

4. **Storage** (1h):
   - Schema migration on startup
   - Helper functions for insert/query

5. **Cloudflare Tunnel setup** (1h):
   - Install cloudflared (free binary)
   - Run `cloudflared tunnel --url http://localhost:8000` (quick tunnel) hoặc named tunnel với config file
   - Note URL output → dùng cho TradingView alert URL

6. **Smoke test** (1h):
   - Local FastAPI run with `uvicorn`
   - `cloudflared tunnel --url http://localhost:8000` chạy song song
   - `curl -X POST` qua Cloudflare URL với sample payload
   - Verify SQLite row created
   - Verify duplicate doesn't create second row

7. **Pine benchmark** (1h):
   - Save to TradingView, load EURUSD M15, check Pine Logs for runtime warnings
   - Verify 40s budget not exceeded
   - Bật `useDynamicAlertPayload` toggle

## Tests

- `tests/test_bot_payload.py`: valid/invalid/malformed payloads, idempotency hash determinism
- `tests/test_bot_webhook.py`: FastAPI test client, auth (good/bad token, IP allowlist), duplicate, malformed body
- Manual: Cloudflare Tunnel + TradingView test alert → backend row

## Risks and Rollback

- **Risk**: Pine 40s budget vượt khi build payload nhiều
  - **Mitigation**: build payload chỉ on state transitions; benchmark trước khi bật toggle
  - **Rollback**: tắt `useDynamicAlertPayload` input — Pine về `alertcondition()` fallback
- **Risk**: TradingView webhook không send custom header
  - **Mitigation**: URL secret + IP allowlist đủ cho P0; HMAC chỉ khi có edge proxy
- **Risk**: Cloudflare tunnel URL thay đổi mỗi lần restart (quick tunnel)
  - **Mitigation**: named tunnel với stable subdomain (cần Cloudflare account); hoặc accept quick tunnel + update TradingView alert URL mỗi lần
- **Risk**: Webhook URL lộ public
  - **Mitigation**: rotate token; rate limit; reverse proxy logs

## Unresolved Questions

- Cloudflare tunnel: **quick tunnel** (URL random mỗi restart) hay **named tunnel** (cần account + subdomain stable)?
- Nếu named tunnel: cần Cloudflare account free + domain owned hay dùng `*.trycloudflare.com` miễn phí?