# Plan — Mac mini cTrader Signal Bot

> **Status**: PHASES 01–04 DONE + rulebook harden + min_sl_pips (2026-09-03)  
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
- EURUSD SL live floor **≥ 10 pips** (manual lag + spread)

## Non-goals (still)

- Auto-order cTrader
- Full Pine 11-gate parity
- Live OpenApiPy session auto-wire (hook only)

## Progress log (2026-09-03)

| Item | Status |
|------|--------|
| Phase 01 scaffold/config/state | **done** |
| Phase 02 feed protocol + CTrader transport hook | **done** (live fetch_fn not wired) |
| Phase 03 signal_engine + watcher | **done** |
| Phase 04 Telegram dry-run | **done** |
| Phase 05 Mac deploy docs | **docs done**; live smoke user |
| Fix: `detect_order_blocks(df, structure, expansion)` | **done** (was always TypeError) |
| Fix: feed_from_config credentials-without-transport | **done** |
| Fix: dedup only on successful notify | **done** |
| Rule-book gate (disp + D/H4 bias + score≥4) | **done** |
| `min_sl_atr` / `max_sl_atr` in multipair scripts | **done** |
| **`min_sl_pips` EURUSD≥10** (strategy + backtest + bot) | **done** |
| 10y backtest EUR+XAU **with** pip floor | **done** — EUR 125 tr min SL 10.06; XAU 560 tr min 100.5 |
| Live cTrader OpenApiPy connect | **not done** (Open API app still **Submitted**) |
| 02 | Data feed + cTrader client | **done** (mock/live hook) | [phase-02](./phase-02-data-feed-ctrader-client.md) |
| 03 | Signal engine + watcher | **done** + rulebook | [phase-03](./phase-03-signal-engine-watcher.md) |
| 04 | Telegram notify + dry-run | **done** | [phase-04](./phase-04-telegram-notify.md) |
| 05 | Mac deploy + live smoke | **docs done** | [phase-05](./phase-05-mac-deploy-live-smoke.md) |
| 06 | Live OpenApiPy trendbars | **todo** | next |
| 07 | min_sl_pips validation re-backtest | **code done** | `output/backtest_10y_eur_xau/` |

## Entry logic (signal bot)

1. OB first-touch on last closed M15 bar (expansion-qualified BOS OB)
2. Displacement required (1.5× ATR)
3. D+H4 bias aligned (resampled from M15)
4. Confluence score ≥ 4
5. SL ATR band 0.3–4.0 + **min_sl_pips** (EUR 10)
6. Proximity ≤ 1.5 ATR; TP 2R/3R/4R

## Backtest snapshot (ATR filters; before pip floor)

| Pair | N | mean SL pip | min SL | PF | Net |
|------|--:|------------:|-------:|---:|----:|
| EURUSD | 663 | 7.0 | 0.86 | 3.27 | +$370k |
| XAUUSD | 690 | 270* | 35 | 3.33 | +$382k |

\*XAU pip_size=0.01 → mean ≈ $2.70 SL distance.

See `output/backtest_10y_eur_xau/REPORT.md`.

## Next

1. Finish/confirm 10y re-run with `min_sl_pips` map → update REPORT table  
2. Wire OpenApiPy live transport on Mac mini  
3. User smoke: dry-run → live demo Telegram  

## Refs

- `packages/smc_bot_signal/`
- `config.yaml` → `min_sl_pips`
- `src/strategy.py` → `check_entry`
- `docs/deploy-mac-mini-ctrader.md`
