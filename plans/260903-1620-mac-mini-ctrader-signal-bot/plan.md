# Plan — Mac mini cTrader Signal Bot

> **Status**: 01–04 done · SL floor **17** locked · gates loosened · BT done (2026-09-03)

## Outcome

Mac mini M4: cTrader M15 → smc_engine + gates → Telegram · manual exec.

## Locked vs loosened

| | |
|--|--|
| **KEEP** | `min_sl_pips` EURUSD **≥ 17** |
| **LOOSENED** | score **3** · bias **h4_only** · disp **1.2** · prox **2.0** · max_sl_atr **5** |

## Progress

| Item | Status |
|------|--------|
| Bot package phases 01–04 | **done** |
| Rulebook / OB API fixes | **done** |
| min_sl_pips=17 + loosened gates | **done** (`97f00d6`) |
| 10y BT floor17 **strict** | **done** — EUR 20 tr, PF 1.8, +$5k |
| 10y BT floor17 **loosened** | **done** — EUR **34** tr min SL 17.2, PF 2.0, +$11k · XAU **1003** tr PF 4.77, +$704k |
| Live OpenApiPy (app Submitted) | **todo** |

## Entry

disp · bias h4_only · score≥3 · OB first-touch · **SL≥17 pip EUR** · TP 2/3/4R

## Backtest snapshot (loosened + floor 17)

| Pair | N | WR | PF | MaxDD | PnL | SL min–mean |
|------|--:|---:|---:|------:|----:|-------------|
| EURUSD | 34 | 29% | 2.0 | -3.8% | +$11k | 17.2–21.8 |
| XAUUSD | 1003 | 40% | 4.77 | -2.3% | +$704k | 100–336 |

Local: `output/backtest_10y_eur_xau/` (gitignored).

## Refs

`config.yaml` · `docs/min-sl-pips-filter.md` · `packages/smc_bot_signal/` · `docs/deploy-mac-mini-ctrader.md`
