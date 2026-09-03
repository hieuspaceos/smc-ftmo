# Plan — Mac mini cTrader Signal Bot

> **Status**: 01–04 done · SL floor **17** locked · other gates **loosened** (2026-09-03)

## Outcome

Mac mini M4 bot: cTrader M15 → smc_engine + gates → Telegram · manual exec.

## Locked vs loosened (user)

| | |
|--|--|
| **KEEP** | `min_sl_pips` EURUSD **≥ 17** (manual lag + spread) |
| **LOOSEN** | score 4→**3**, bias strict→**h4_only**, disp 1.5→**1.2**, proximity 1.5→**2.0**, max_sl_atr 4→**5** |

Goal: more trades without thin SL.

## Progress

| Item | Status |
|------|--------|
| Bot package 01–04 | **done** |
| Rulebook fail-closed + OB API fix | **done** |
| min_sl_pips 17 + loosened gates in config/scripts/bot | **done** |
| BT floor=10 | **done** (EUR 125, +$68k) |
| BT floor=17 + loosened gates | **running** |
| Live OpenApiPy (app Submitted) | **todo** |

## Entry

disp · bias (h4_only) · score≥3 · first-touch OB · SL≥17 pip EUR · TP 2/3/4R

## Refs

`config.yaml` · `docs/min-sl-pips-filter.md` · `packages/smc_bot_signal/`
