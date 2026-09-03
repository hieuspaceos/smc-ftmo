# SL floor + loosened entry gates (2026-09-03)

## Locked: min_sl_pips

| Pair | Floor | Why |
|------|------:|-----|
| **EURUSD** | **≥ 17 pips** | Manual lag (signal→chart→order) + spread — **do not lower** |
| **XAUUSD** | ≥ 100 pips | $1.00 @ pip=0.01 |

## Loosened (more trades) while keeping floor 17

| Param | Before | After | Effect |
|-------|--------|-------|--------|
| `min_confluence_score` | 4 | **3** | disp+bias+first_test enough (no need PD/sweep) |
| `bias_mode` | strict (D+H4) | **h4_only** | H4 bias enough; D counter still blocked |
| `displacement_atr_mult` | 1.5 | **1.2** | easier displacement |
| `rulebook_entry_proximity_atr` | 1.5 | **2.0** | entry farther from OB OK |
| `max_sl_atr` | 4.0 | **5.0** | slightly fatter OBs allowed |

Still required: displacement, bias aligned (per mode), first-touch OB.

## Config snippet

```yaml
min_confluence_score: 3
bias_mode: h4_only
displacement_atr_mult: 1.2
rulebook_entry_proximity_atr: 2.0
max_sl_atr: 5.0
min_sl_pips:
  EURUSD: 17
  XAUUSD: 100
```

## Backtest

```bash
python -m scripts.btest_eur_xau_same_cfg_pips
```

Compare vs floor-10-only / floor-17-strict baselines in `output/backtest_10y_eur_xau/`.
