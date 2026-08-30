# Phase 05 Implementation Plan: FastAPI Backend + Vue 3 SPA on Cloudflare Pages

**Date locked**: 2026-08-30
**Stack confirmed by user**: FastAPI backend + Vue 3 SPA + Vite build → Cloudflare Pages + Cloudflare Tunnel for FastAPI

## Scope

Read-only admin dashboard (per plan §Read-only first, then admin):
1. **Live Queue** — alerts joined with decisions
2. **Execution Log** — Phase 06 stub (execution_log empty until P6)
3. **Replay** — signal CSV list + Plotly candlestick + BOS markers
4. **Audit** — accept/reject event history with CSV export

**Deferred to Phase 06**: admin actions (toggle executor, edit users, manual override).

## Architecture

```
[Trader browser]
     │
     │ HTTPS (Cloudflare Access password + email OTP)
     ▼
[Cloudflare CDN]
     │
     ├── /admin/*         → [Cloudflare Pages] ── static Vue SPA (built dist/)
     │                          │
     │                          │ fetch /api/* (CORS allowed via CF Access)
     ▼                          ▼
[Cloudflare Tunnel]   ←────  [FastAPI on 127.0.0.1:8000]
     │
     ├── /webhooks/tradingview (Pine webhook from Phase 01)
     ├── /telegram/callback   (Telegram inline button presses)
     ├── /api/alerts           (Live Queue JSON)
     ├── /api/execution        (Execution JSON, stub)
     ├── /api/replay           (Replay file list + CSV JSON)
     └── /api/audit            (Audit events JSON)
```

Two services:
- **Bot service** (always-on): webhook + Telegram + MT5 — runs on user's Mac/VPS via `cloudflared tunnel`
- **Dashboard service** (web admin): Vue SPA on Pages + FastAPI API via same Tunnel

## Tech stack

### Backend (Python)
- `fastapi` + `uvicorn` (already in requirements)
- `jinja2` for SSR fallback (admin pages can use if Vue fails)
- `python-multipart` for file uploads (Phase 06 — not needed for P5a)
- `httpx` (already in) for outbound if needed

### Frontend (Vue SPA)
- `vue@3` (Composition API)
- `pinia` for state (filter selections, user prefs)
- `vue-router` for client-side routing
- `tailwindcss` for utility-first styling (dark mode default)
- `plotly.js-dist-min` for charts (candlestick + BOS markers)
- `vite` for build pipeline
- `vue-chartjs` (optional, only if we wrap Plotly)

### Auth (Cloudflare Access)
- Cloudflare Access free tier (50 users)
- One-time setup: email allowlist + 2FA mandatory
- NO auth logic in FastAPI or Vue (zero-trust at edge)
- Documented in `docs/cloudflare-access-setup.md` (already exists, extend for SPA)

## File structure

```
bot/dashboard/
├── __init__.py              # exports
├── web.py                   # FastAPI app + JSON endpoints
├── admin.py                 # Phase 06 admin actions (stubs now)
├── templates/               # Jinja2 SSR fallback
│   └── base.html            # single SSR fallback page
├── spa/                      # Vue SPA source (built → Pages)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router.ts
│   │   ├── stores/
│   │   │   └── filters.ts   # Pinia store
│   │   ├── api/
│   │   │   └── client.ts    # fetch wrapper
│   │   ├── components/
│   │   │   ├── NavBar.vue
│   │   │   ├── FilterBar.vue
│   │   │   ├── DataTable.vue
│   │   │   └── PlotlyChart.vue
│   │   └── views/
│   │       ├── LiveQueueView.vue
│   │       ├── ExecutionView.vue
│   │       ├── ReplayView.vue
│   │       └── AuditView.vue
│   └── public/
└── static/                  # built dist/ symlink target (gitignored)
```

```
docs/cloudflare-access-setup.md   # EXTEND with Vue SPA section
tests/test_bot_dashboard.py        # FastAPI page + API tests
package.json (root)                 # workspace marker
```

## Routes

### FastAPI (bot/dashboard/web.py)

SSR fallback (Jinja2):
- `GET /` → redirect to `/admin/` (Cloudflare Pages handles the SPA)
- `GET /healthz` → JSON health check
- `GET /admin-legacy` → Jinja2 SSR fallback if SPA down (optional, see "graceful degradation" below)

JSON API (consumed by Vue SPA):
- `GET /api/alerts?limit=N&state=...&since=ISO` → latest alerts + decisions
- `GET /api/execution?limit=N` → execution_log rows (stub returns empty for P5a)
- `GET /api/replay` → list signal CSV files in `output/`
- `GET /api/replay/csv/{name}` → rows of specific CSV (path-traversal guard)
- `GET /api/audit?decision=accept|reject&user=...&since=ISO&signal_csv=...` → events + optional CSV rows
- `GET /api/health` → bot health (last alert time, last Telegram send, etc.)

Vue SPA (deployed to Cloudflare Pages):
- `/` → redirect to `/live`
- `/live` → LiveQueueView (alerts + decisions table)
- `/execution` → ExecutionView (Phase 06 stub)
- `/replay` → ReplayView (file picker + Plotly chart)
- `/audit` → AuditView (events table + CSV export button)

## Data flow per page

### Live Queue
1. Vue calls `/api/alerts?limit=100&state=chart-qualified`
2. FastAPI joins `alert_log` + `signal_events` in Python, returns JSON
3. Vue renders DataTable with Tailwind styling
4. Auto-refresh every 10s (setInterval + fetch)

### Replay
1. Vue calls `/api/replay` → list of signal CSVs
2. User clicks file → Vue calls `/api/replay/csv/{name}` → array of rows
3. Vue renders Plotly chart with candlestick + BOS markers + decision markers
4. Color coding: long=green, short=red, neutral=gray

### Audit
1. Vue calls `/api/audit?decision=accept&since=2026-08-01`
2. FastAPI filters signal_events, returns events + optional CSV rows
3. Vue renders DataTable + "Export CSV" button (downloads from same endpoint)

## Reuse vs duplicate

**Reuse from existing code**:
- `bot/storage/db.py` — `BotDB` (Phase 02 thread-safe connection)
- `bot/backtest/capture.py` — `_read_csv_rows` for audit CSV export
- `bot/webhook/payload.py` — `compute_signal_id`, `AlertPayload` validation
- `app.py` Plotly pattern — borrow color schemes + axis config
- `requirements.txt` — `fastapi`, `uvicorn`, `pydantic` already pinned

**New (Phase 05-specific)**:
- `bot/dashboard/web.py` — FastAPI app + JSON endpoints (200 LOC)
- `bot/dashboard/templates/base.html` — Jinja2 SSR fallback (~50 LOC)
- `bot/dashboard/spa/` — Vue SPA (full app, ~800 LOC across files)
- `tests/test_bot_dashboard.py` — page + API tests (~300 LOC)

## Dependencies (added to requirements.txt)

```
fastapi>=0.115,<1.0         # already there
uvicorn[standard]>=0.30      # already there
jinja2>=3.0,<4.0            # NEW
python-multipart>=0.0.5      # NEW (file upload; Phase 06 use)
```

Vue SPA dependencies live in `bot/dashboard/spa/package.json`:
```json
{
  "dependencies": {
    "vue": "^3.4",
    "vue-router": "^4.2",
    "pinia": "^2.1",
    "plotly.js-dist-min": "^2.34",
    "tailwindcss": "^3.4"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0",
    "vite": "^5.0",
    "typescript": "^5.3",
    "vue-tsc": "^1.8"
  }
}
```

## Cloudflare deployment

### Cloudflare Tunnel (existing, Phase 01)
- Single `cloudflared` process exposes:
  - `https://your-bot.trycloudflare.com/webhooks/tradingview` → `127.0.0.1:8000`
  - `https://your-bot.trycloudflare.com/admin` → Pages SPA (no origin needed)
  - `https://your-bot.trycloudflare.com/api/*` → `127.0.0.1:8000` (FastAPI)

### Cloudflare Pages
1. Connect GitHub repo to Cloudflare Pages
2. Build command: `cd bot/dashboard/spa && npm ci && npm run build`
3. Build output: `bot/dashboard/spa/dist`
4. Root directory: `bot/dashboard/spa` (so relative paths work)
5. Environment vars: `VITE_API_BASE=https://your-bot.trycloudflare.com`
6. Deploy: automatic on git push to `master`

### Cloudflare Access (existing pattern)
- Application 1 (existing): webhook + api — public, no auth
- Application 2 (new): `*.pages.dev/admin*` — email allowlist + 2FA mandatory

### CORS
- FastAPI adds `Access-Control-Allow-Origin: https://your-dashboard.pages.dev` for `/api/*`
- Or use Cloudflare Access headers (no CORS needed if all traffic via CF)

## Implementation order

1. **Backend foundation** (3h):
   - `bot/dashboard/web.py` FastAPI app + JSON endpoints
   - `bot/dashboard/templates/base.html` Jinja2 SSR fallback
   - `tests/test_bot_dashboard.py` page + API tests with mock data
   - Run FastAPI on `127.0.0.1:8000` next to webhook

2. **Vue SPA scaffold** (4h):
   - `npm create vue@latest` → `bot/dashboard/spa/`
   - Configure `vite.config.ts` (base path, build output)
   - Pinia store (`stores/filters.ts`)
   - Vue Router (`router.ts`)
   - API client (`api/client.ts`)

3. **Vue views** (4h):
   - LiveQueueView + DataTable component + PlotlyChart wrapper
   - ExecutionView (stub)
   - ReplayView + CSV file picker
   - AuditView + Export button

4. **Tailwind styling + dark mode** (2h):
   - Apply utility classes throughout
   - Responsive layout (mobile-first)
   - Dark mode toggle (Pinia store)

5. **Build + Pages deployment** (1h):
   - `npm run build` → `bot/dashboard/spa/dist/`
   - Manual deploy to Cloudflare Pages (or via wrangler)
   - Test Pages URL loads + API calls work via Tunnel

6. **Cloudflare Access + 2FA** (1h):
   - Add admin policy to `your-dashboard.pages.dev/admin*`
   - Email allowlist (single user for P5a)
   - 2FA mandatory
   - Test login flow

7. **Documentation** (1h):
   - Extend `docs/cloudflare-access-setup.md` with Vue SPA section
   - Document build + deploy steps
   - Document CORS / tunnel routing

**Total**: ~16h

## Acceptance criteria

1. ✅ `bot/dashboard/web.py` exposes `GET /`, `/healthz`, `/admin-legacy`, `/api/{alerts,execution,replay,replay/csv/{name},audit,health}`
2. ✅ FastAPI tests pass (TestClient with mock data)
3. ✅ Vue SPA builds without errors: `cd bot/dashboard/spa && npm run build`
4. ✅ Vue SPA bundles < 500KB gzipped (single trader, small data)
5. ✅ All 4 pages render with mock data
6. ✅ Replay page renders Plotly candlestick + BOS markers
7. ✅ Live Queue auto-refreshes every 10s
8. ✅ Audit page CSV export downloads file
9. ✅ Cloudflare Pages deploys SPA successfully
10. ✅ Cloudflare Access 2FA gates `/admin*` (single email allowlist)
11. ✅ Mobile-friendly (Tailwind responsive — works on phone)
12. ✅ Dark mode toggle (Tailwind `dark:` classes)
13. ✅ `bot/dashboard/web.py` has zero Phase 06 admin actions (just stubs)
14. ✅ Existing 483 tests still pass (zero regressions)

## Test plan

### FastAPI tests (`tests/test_bot_dashboard.py`, ~20 tests)
- `GET /` redirects to `/live`
- `GET /healthz` returns ok
- `GET /admin-legacy` returns 200 HTML
- `GET /api/alerts?limit=10` returns JSON with alerts
- `GET /api/alerts?state=watch` filters by state
- `GET /api/alerts?limit=N` respects limit
- `GET /api/execution` returns stub with note
- `GET /api/replay` lists signal CSVs
- `GET /api/replay/csv/{name}` returns CSV rows
- `GET /api/replay/csv/../etc/passwd` → 400 (path traversal guard)
- `GET /api/replay/csv/missing.csv` → 404
- `GET /api/audit?decision=accept` filters by decision
- `GET /api/audit?user=tester1` filters by user
- `GET /api/audit?signal_csv=signals_x.csv` includes CSV rows
- `GET /api/audit?decision=invalid` → empty (no error)
- `GET /api/health` returns dict
- Mock data: insert 5 alerts + 10 events, verify `/api/alerts` returns them
- Concurrent `/api/alerts` calls (10 threads) — no DB corruption (BotDB thread-safe)

### Vue SPA tests (lightweight, since Streamlit analog)
- Manual smoke: `npm run dev` → open `http://localhost:5173`, verify each page
- Visual: dark mode, responsive layout, Plotly renders
- Lighthouse score (optional): performance > 80, accessibility > 90

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| npm install fails (network/version conflict) | Low | High | Pin all deps in package.json with exact versions; cache `node_modules/` |
| Cloudflare Pages build fails on first push | Medium | Medium | Manual deploy via wrangler as fallback |
| 2FA email OTP delivery fails | Low | Medium | Document Gmail fallback; ensure email provider not in Access blacklist |
| Vue SPA + FastAPI version skew (Vue uses old data shape) | Medium | Medium | Add API version field `/api/version`; document breaking-change protocol |
| CORS preflight blocked | Low | High | Set CF Access to forward Origin header; or use Cloudflare Workers proxy |
| Plotly bundle too large (> 500KB) | Medium | Low | Use `plotly.js-dist-min` (smaller); lazy-load on chart render |

## Rollback

1. Delete `bot/dashboard/` directory
2. Remove from `requirements.txt`
3. Disable Cloudflare Pages project
4. Remove Cloudflare Access policy
5. Existing webhook + Telegram + MT5 (Phases 01-04) untouched

## Open questions (post-Phase 05)

1. **Realtime price feed** — integrate TradingView widget or scrape? Defer to user request.
2. **Mobile native app** — PWA? React Native? Out of scope.
3. **Multi-trader / team features** — per-user audit trails, role-based access. Defer to v2.
4. **Auto-refresh interval** — currently 10s. User-configurable later.
