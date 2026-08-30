# Phase 05: Streamlit Web Admin + Replay Dashboard

## Context

- [Plan](./plan.md)
- Depends on [Phase 02](./phase-02-bot-storage-and-telegram.md) + [Phase 04](./phase-04-backtest-replay-and-csv.md)
- User decision 2026-08-30: trader muốn quản lý bot từ bất kỳ đâu qua web admin

## Goal

Streamlit web admin panel — accessible qua **Cloudflare Tunnel + Cloudflare Access** (password) — cung cấp:

1. **Live view**: alerts, gate state, decisions, execution status (read-only first)
2. **Replay view**: signal CSV + OHLC chart (read-only first)
3. **Admin actions**: bật/tắt executor, edit Telegram users, manual override, force accept/reject

Trader có thể truy cập từ bất kỳ đâu qua browser → `https://your-bot.trycloudflare.com/admin` (sau khi login Cloudflare Access).

## Requirements

### Streamlit pages (`bot/dashboard/streamlit_app.py`)

- [ ] **Live Queue** page:
  - Latest alerts (last 24h, filter by state)
  - Gate checklist per alert
  - Telegram delivery state (sent/failed/pending)
- [ ] **Execution** page (P2+):
  - Pending/done/failed outbox rows
  - MT5/MetaAPI response details
  - Filter by symbol, date, status
- [ ] **Replay** page:
  - Upload/select signal CSV + frozen OHLC bundle
  - Render Plotly candles with SMC overlays (BOS/CHoCH/OB markers)
  - Compare Python replay CSV vs Pine manual export
- [ ] **Audit** page:
  - Export decisions CSV cho journal review
  - Filter by user, date, decision type
- [ ] **Admin** page (Phase 06+):
  - Toggle `EXECUTOR_TRANSPORT` (disabled/file/metaapi)
  - Edit `TELEGRAM_ALLOWED_USERS` (write to .env hoặc SQLite config)
  - Manual override: force accept/reject cho stale signal
  - View FTMO guard status (daily loss, trades left)

### Authentication

- [ ] **Cloudflare Access** (free tier) protect `/admin*` path
- [ ] One-time setup: Cloudflare account + email allowlist
- [ ] Streamlit runs behind Cloudflare tunnel, no auth logic in app
- [ ] Document setup steps in `docs/cloudflare-access-setup.md`

### Layout

- Sidebar: page selector, date range, signal state filter
- Main: page-specific content
- Reuse Plotly pattern từ existing `app.py:15-17`

### Read-only first, then admin

- P5a (live + replay): read-only — admin actions disable
- P5b (admin actions): require explicit `ADMIN_ENABLED=true` env flag

## Files to Create/Modify

- Create: `bot/dashboard/__init__.py`, `bot/dashboard/streamlit_app.py`
- Create: `bot/dashboard/admin.py` (Phase 06+ actions)
- Create: `docs/cloudflare-access-setup.md` (user guide)
- Modify: existing `app.py` chỉ thêm link tới admin dashboard
- Modify: `requirements-bot.txt` (add `streamlit`)

## Implementation Steps

1. **Cloudflare Access setup** (1h):
   - Cloudflare account (free)
   - Add domain hoặc dùng `*.trycloudflare.com` (quick tunnel)
   - Enable Access → add policy cho email allowlist
   - Test login flow

2. **Dashboard skeleton** (2h): multi-page structure, sidebar, page router
3. **Live Queue page** (3h): query alert_log + signal_events, render table với state colors
4. **Execution page** (2h): query execution_log, show pending/done/failed với timestamps
5. **Replay page** (4h): file upload, parse OHLC + signal CSV, Plotly candle chart
6. **Audit export** (1h): CSV export of decisions + filter UI
7. **Admin actions** (Phase 06, 3h): toggle executor, edit users, manual override
8. **Smoke test** (1h): run dashboard locally, verify pages load + data displays

## Tests

- Manual: run `streamlit run bot/dashboard/streamlit_app.py` + verify each page
- Integration: insert mock data into SQLite, verify dashboard renders correctly
- Manual: deploy via Cloudflare Tunnel + Access → verify login từ browser khác

## Risks and Rollback

- **Risk**: Dashboard duplicates `app.py` logic → maintenance burden
  - **Mitigation**: read-only, no business logic; merge later only if duplication painful
- **Risk**: Slow Plotly render với large CSV
  - **Mitigation**: paginate; downsample for >10K bars
- **Risk**: Cloudflare Access email allowlist bypass
  - **Mitigation**: dùng email cá nhân + 2FA bắt buộc; document security
- **Risk**: Admin actions ghi nhầm config
  - **Mitigation**: tất cả admin actions ghi audit log; có confirmation prompt; test on staging first
- **Rollback**: just delete dashboard files; existing app.py untouched; Cloudflare Access policy disable

## Unresolved Questions

- Cloudflare Access: 1 email owner-only (đơn giản) hay multiple emails (cho team)?
- Admin actions: ghi trực tiếp vào .env hay qua SQLite config table?
- Dashboard có cần mobile-friendly không? (Streamlit responsive by default)
- Replay page: visual với replay buttons (prev/next bar) hay read-only?