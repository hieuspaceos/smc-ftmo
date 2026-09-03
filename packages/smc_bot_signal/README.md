# smc_bot_signal

cTrader Open API → `smc_engine` + **rule-book gates** → Telegram (manual exec).

Designed for **Mac mini M4** 24/7. No MT5. No auto-trade.

## Install

```bash
pip install -e packages/smc_engine \
            -e packages/smc_bot_core \
            -e packages/smc_bot_webhook \
            -e packages/smc_bot_signal
```

## Entry gate (fail-closed)

Matches `journal/rule-book.md` / `src/confluence.py` + live pip floor:

1. OB first-touch on last closed M15 bar (expansion-qualified BOS OB)
2. **Displacement** required (1.5× ATR)
3. **D + H4 bias aligned** (resampled from M15)
4. **Score ≥ 4**
5. SL buffer 0.2×ATR; SL in [0.3, 4.0] ATR; proximity ≤ 1.5 ATR
6. **`min_sl_pips` default 17** (EURUSD) — manual lag + spread
7. TP ladder 2R / 3R / 4R

Missing gate → **no Telegram**.

## Run

```bash
SMC_SIGNAL_FEED_MODE=memory SMC_SIGNAL_DRY_RUN=1 python -m smc_bot_signal
pytest packages/smc_bot_signal/tests -q
```

Env: `SMC_SIGNAL_MIN_SL_PIPS=10` (default).

## Known limits (v0.1)

- Live Open API transport not auto-wired yet
- EURUSD only (`AlertPayload` allowlist)
- HTF bias from M15 resample, not native broker H4/D
- Sweep not scored yet
- Session filter not enforced
- Always confirm on cTrader before order

## Docs

- Plan: `plans/260903-1620-mac-mini-ctrader-signal-bot/`
- Deploy: `docs/deploy-mac-mini-ctrader.md`
- Pip floor: `docs/min-sl-pips-filter.md`
- Backtest: `output/backtest_10y_eur_xau/REPORT.md`
