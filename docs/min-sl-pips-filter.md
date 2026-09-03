# min_sl_pips — live SL floor

## Decision (2026-09-03)

EURUSD M15 alerts/trades require **SL ≥ 10 pips**.

### Why

1. **Spread** (~0.5–1 pip FTMO): sub-3 pip SL is not tradeable.
2. **Manual lag**: signal → chart confirm → order. Price often moves before fill.
   Thin OB SL is already gone by the time the human enters.

`min_sl_atr` (0.3×ATR) is **not** enough: quiet M15 ATR ~3 pip → 0.3×ATR ≈ 0.9 pip still passes.

## Config

```yaml
# config.yaml strategy:
min_sl_pips:
  EURUSD: 10
  XAUUSD: 100   # pip_size 0.01 → $1.00 price distance
```

## Code path

- `src/strategy.check_entry` — rejects if `sl_pips < min_sl_pips`
- `src/backtester` — snapshot carries map/scalar
- `smc_bot_signal` — `SignalBotConfig.min_sl_pips` (default 10) on alert build

## Empirical (10y, before pip floor)

EURUSD mean/median SL ≈ **7.0 / 6.1 pip**; cluster 5–10.  
min observed **0.86 pip** (reject under new floor).

Re-run: `python -m scripts.btest_eur_xau_same_cfg_pips`  
Report: `output/backtest_10y_eur_xau/REPORT.md`
