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

Matches `journal/rule-book.md` / `src/confluence.py`:

1. OB first-touch on last closed M15 bar (expansion-qualified BOS OB)
2. **Displacement** required (1.5× ATR)
3. **D + H4 bias aligned** with trade side (resampled from M15)
4. **Score ≥ 4** (disp + bias + first_test + P/D or sweep)
5. SL buffer 0.2×ATR, proximity ≤ 1.5×ATR, SL in [0.3, 4.0] ATR
6. TP ladder 2R / 3R / 4R

If bias not aligned → **no Telegram** (stand aside).

## Run

```bash
# secrets in ~/.smc-bot.env
SMC_SIGNAL_FEED_MODE=memory SMC_SIGNAL_DRY_RUN=1 python -m smc_bot_signal
pytest packages/smc_bot_signal/tests -q
```

## Known limits (v0.1)

- Live Open API transport not auto-wired yet
- EURUSD only (`AlertPayload` allowlist)
- HTF bias from M15 **resample**, not native H4/D broker bars
- Sweep not scored yet (`sweep_clean=False`) — need P/D for score 4 if no sweep
- Session filter (London/NY) not enforced
- **Always confirm on cTrader chart before order**

Plan: `plans/260903-1620-mac-mini-ctrader-signal-bot/`
