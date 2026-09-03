# SMC FTMO Bot — Workspace

![tests](https://img.shields.io/badge/tests-571%20passed-brightgreen)

Multi-package workspace for the SMC (Smart Money Concepts) FTMO trading bot.
Each package is independently installable + testable.

## Package layout

```
packages/
├── smc_engine/          ← Python SMC engine (swing, BOS/CHoCH, OB, FVG, liquidity, regime)
├── smc_bot_core/        ← Shared DB + settings + payload models
├── smc_bot_webhook/     ← FastAPI webhook + Telegram + 11-gate validator + MT5 file bridge
├── smc_bot_signal/      ← cTrader Open API M15 signal bot (Mac mini, no MT5)
├── smc_bot_backtest/    ← Phase 04: replay engine + signal CSV capture
└── smc_bot_dashboard/  ← Phase 05: FastAPI admin + Vue 3 SPA on Cloudflare Pages

app/                    ← Streamlit analysis app (Phase 12+)
scripts/                ← Parity tooling (Python ↔ Pine reference)
tradingview/            ← Pine indicator (v1.2)
data/, histdata/, journal/   ← Historical OHLC + manual trade journal
docs/                   ← Cloudflare Access + MT5 bridge + design system
plans/                  ← Phase plans (260830-bot-alert-replay/)
design-system/         ← (legacy) ak-ui-ux-pro-max tokens
output/                 ← Runtime artifacts (gitignored)
```

## Install (workspace mode)

```bash
# Install all packages in editable mode
pip install -e packages/smc_engine \
            -e packages/smc_bot_core \
            -e packages/smc_bot_webhook \
            -e packages/smc_bot_signal \
            -e packages/smc_bot_backtest \
            -e packages/smc_bot_dashboard
```

Or single package:
```bash
pip install -e packages/smc_engine
```

## Run

### Webhook server (accepts Pine alerts)

```bash
SMC_WEBHOOK_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  PYTHONPATH=packages/smc_engine/src:packages/smc_bot_core/src:packages/smc_bot_webhook/src \
  uvicorn smc_bot_webhook.server:app --host 127.0.0.1 --port 8000
```

### Admin dashboard (Phase 05)

```bash
# Backend (FastAPI on :8501)
PYTHONPATH=packages/smc_engine/src:packages/smc_bot_core/src:packages/smc_bot_webhook/src \
  uvicorn smc_bot_dashboard.web:app --host 127.0.0.1 --port 8501

# Frontend (Vue 3 SPA on :5173, proxies /api → :8501)
cd packages/smc_bot_dashboard/spa
npm install
npm run dev
```

Open http://127.0.0.1:5173 (Vue SPA) or http://127.0.0.1:8501/admin-legacy (SSR fallback).

### Streamlit app

```bash
streamlit run app/streamlit_app.py
```

### MT5 file bridge (Phase 06)

Set `EXECUTOR_TRANSPORT=file` + `MT5_OUTBOX_DIR=/path/to/shared/folder`. See
`docs/mt5-bridge-setup.md` for full setup including MQL5 EA compilation.

## Run tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ packages/ -q
```

Latest: **303 webhook tests passing, 571 total repo tests, 0 regressions.** (Audit hardening 2026-08-31: +88 tests across 6 audit-fix branches.)

## Phase plan

Full 6-phase rollout:
- [plans/260830-bot-alert-replay/plan.md](plans/260830-bot-alert-replay/plan.md)
- Phase 01: Pine webhook + payload parser
- Phase 02: Telegram + Discord dispatchers
- Phase 03: 11-gate rulebook validator
- Phase 04: Python replay engine + CSV capture
- Phase 05: FastAPI admin + Vue 3 SPA
- Phase 06: MT5 file bridge + FTMO guard

Each phase has its own sub-plan + audit + commit history.

## Documentation

- [docs/cloudflare-access-setup.md](docs/cloudflare-access-setup.md) — deploy webhook + dashboard behind Cloudflare Tunnel + Access
- [docs/mt5-bridge-setup.md](docs/mt5-bridge-setup.md) — MT5 demo + EA + shared folder
- [docs/design-system.md](docs/design-system.md) — color/typography tokens from ak-ui-ux-pro-max

## License

Private — internal SMC FTMO bot project.
