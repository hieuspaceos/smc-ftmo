# min_sl_pips — live SL floor

## Decision

| Pair | Floor | Updated |
|------|------:|---------|
| **EURUSD** | **≥ 17 pips** | 2026-09-03 (was 10; user: still tight for manual lag) |
| **XAUUSD** | ≥ 100 pips ($1.00 @ pip=0.01) | 2026-09-03 |

### Why EUR ≥ 17

1. Spread ~0.5–1 pip  
2. **Manual lag**: Telegram → open chart → confirm → place order — price often runs  
3. Mean EUR M15 SL in unfiltered BT ~7 pip; floor 10 still left many “barely room” setups  
4. User: floor **17** so entry still makes sense after delay  

`min_sl_atr` (0.3×ATR) alone is not enough (quiet ATR → sub-pip SL).

## Config

```yaml
# config.yaml strategy:
min_sl_pips:
  EURUSD: 17
  XAUUSD: 100
```

Bot env: `SMC_SIGNAL_MIN_SL_PIPS=17` (default).

## Code

- `src/strategy.check_entry`
- `src/backtester` snapshot
- `smc_bot_signal` alert build
- `scripts/btest_*`

## Backtest notes

- Floor **10**: EUR 125 trades, min SL 10.06, mean 13.6, PF 3.02, +$68k  
- Floor **17**: re-run via `python -m scripts.btest_eur_xau_same_cfg_pips`
