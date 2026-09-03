# Plan — Mac mini cTrader Signal Bot

> **Status**: PHASES 01–04 DONE + rulebook + min_sl_pips **17** (2026-09-03)  
> **Created**: 2026-09-03  
> **Supersedes**: `plans/260831-XXXX-mac-mini-ctrader-bot/` (draft)

## Outcome

Bot 24/7 trên **Mac mini M4**: M15 từ **cTrader Open API** → `smc_engine` +
**rule-book gates** → **Telegram**. User **manual** trên cTrader.  
Không auto-trade · không MT5 · không VPS.

## Constraints

- Mac mini M4 only; secrets in `~/.smc-bot.env`
- Package `packages/smc_bot_signal/`
- Alert-only; fail-closed entry (disp + bias + score + SL floors)
- EURUSD SL live floor **≥ 17 pips** (manual lag: signal→confirm→order + spread)

## Non-goals (still)

- Auto-order cTrader
- Full Pine 11-gate parity
- Live OpenApiPy session auto-wire (hook only)

## Progress log (2026-09-03)

| Item | Status |
|------|--------|
| Phase 01–04 bot package | **done** |
| Phase 05 Mac deploy docs | **docs done** |
| Fix OB API + rulebook gates | **done** |
| `min_sl_pips` EURUSD **10** then raised to **17** | **done** (code) |
| 10y BT floor=10 | **done** — EUR 125 tr, min SL 10.06, PF 3.02, +$68k |
| 10y BT floor=17 | **running / pending** |
| Live cTrader OpenApiPy | **not done** (app **Submitted**) |

## Phases

| # | Phase | Status |
|---|--------|--------|
| 01 | Package scaffold | **done** |
| 02 | Data feed + cTrader hook | **done** (no live session) |
| 03 | Signal engine + watcher + rulebook | **done** |
| 04 | Telegram dry-run | **done** |
| 05 | Mac deploy docs | **docs done** |
| 06 | Live OpenApiPy trendbars | **todo** |
| 07 | min_sl_pips backtest | floor 10 done; floor 17 in progress |

## Entry logic

1. OB first-touch last M15 bar  
2. Displacement 1.5×ATR  
3. D+H4 bias aligned  
4. Score ≥ 4  
5. SL ATR 0.3–4.0 + **min_sl_pips EUR 17 / XAU 100**  
6. Proximity 1.5 ATR; TP 2/3/4R  

## Refs

- `config.yaml` → `min_sl_pips`
- `docs/min-sl-pips-filter.md`
- `output/backtest_10y_eur_xau/REPORT.md`
- `docs/deploy-mac-mini-ctrader.md`
