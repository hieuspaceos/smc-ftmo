# Phase 11 — Multi-pair + Regime

## Context

Phases 08-10 đã validate single-pair (EURUSD) logic realistic + statistical
significance + Pine parity. Nhưng:

1. **Single-pair strategy** ≠ robust strategy. EURUSD 10 năm có regime đặc
   thù (SNB unpeg 2015, COVID 2020, rate hike 2022-2024). Edge có thể chỉ
   work trên EURUSD, không generalize.
2. **Regime tagging** chưa có trong trade dict. `packages/smc_engine/regime.py`
   đã compute regime labels (trending/ranging/mixed) nhưng
   `src/backtester.py:605-630` không tag trades với regime.

Pro trader / quant desk đánh giá strategy bằng **edge persistence across
regimes và asset classes**.

## Goal

Prove rằng strategy có **edge generalizable** bằng cách:

1. **Multi-pair validation:** Run scale_in backtest trên XAUUSD + BTCUSD
   (2-3 năm data), verify PF ≥ 1.5 mỗi pair.
2. **Regime-tagged metrics:** Phân tích performance theo
   trend/range/high-vol regimes, identify which regime produces edge.
3. **Cross-pair correlation check:** Nếu EURUSD + XAUUSD cùng long direction
   → check correlation, flag nếu > 0.7.

## Steps

### Step 1 — Download/extend data cho XAUUSD + BTCUSD (1 ngày)

**Current state:**
- `data/eurusd_m15.parquet` — 10 năm ✅
- `data/xauusd_m15.parquet` — verify duration (có thể chỉ 2-3 năm)
- `data/btcusd_m15.parquet` — verify duration (có thể chỉ 1-2 năm)

**Process:**
1. Check `data/*.parquet` sizes + date ranges
2. Nếu XAUUSD < 3 năm hoặc BTCUSD < 3 năm:
   - Download thêm từ histdata.com (XAUUSD) hoặc Binance API (BTCUSD)
   - Hoặc accept shorter period và document trong NOTES.md
3. Update `scripts/process_histdata.py` nếu cần format mới

### Step 2 — Multi-pair backtest sweep (1-2 ngày)

**Process:**
1. Modify `scripts/btest_10y.py` → `scripts/btest_multipair.py`
2. Loop qua `[EURUSD, XAUUSD, BTCUSD]` với cùng config
3. Per-pair output:
   - `output/btest_<pair>_v2.csv` — trades
   - `output/btest_<pair>_v2_metrics.md` — PF, winrate, max DD, total R

**Acceptance per pair:**
- Profit factor ≥ 1.5
- Total trades ≥ 50 (sample size đủ để meaningful)
- Max DD < 10%
- Winrate ≥ 30% (lower bound với R:R 2.5)

**Fail handling:**
- Nếu pair nào fail → note trong `output/btest_multipair_verdict.md`
- Không block Track B vẫn có thể move on với EURUSD-only strategy
- Nhưng document rõ rằng strategy không generalize

### Step 3 — Regime tagging in trade dict (2-3 ngày)

**Process:**
1. `src/backtester.py`: Ở entry time, query regime từ
   `packages/smc_engine.regime.RegimeState.is_active_at(ts)`
2. Add field `regime: str` vào trade dict (values:
   `trending | ranging | mixed | high_vol`)
3. Tag cả `ob_weight`, `breaker_weight`, `choppiness` từ RegimeState

**Code:**
```python
# At entry time, src/backtester.py
regime_state = compute_regime(df_m15, ts)
trade_dict = {
    ...,
    "regime": regime_state.label,
    "regime_choppiness": regime_state.choppiness,
    "regime_atr_ratio": regime_state.atr_ratio,
}
```

**Test:** `tests/test_regime_tagging.py`
- Verify regime tag present in trade dict
- Verify regime values are valid enum
- Verify backtest still produces same trade count (regime tag is
  observational, doesn't filter)

### Step 4 — Regime-tagged metrics (1-2 ngày)

**Process:**
1. Extend `src/journal.py`: thêm `Journal.stats_by_regime()`
2. Aggregate metrics per regime:
   - Winrate, PF, AvgR, TotalR, TotalUSD, MaxDD, trade count
3. Run trên full EURUSD 10 năm trade list
4. Output `output/regime_metrics/eurusd_by_regime.csv`

**Acceptance:**
- Identify which regime produces edge (PF > 2)
- Identify which regime kills PnL (PF < 1, totalR < 0)
- Optional: add config filter `strategy.active_regimes = [trending]`

**Decision:**
- Nếu 1 regime chiếm > 80% PnL → cân nhắc filter strategy chỉ chạy regime đó
- Nếu PnL distributed đều → strategy robust

### Step 5 — Cross-pair correlation (1 ngày)

**Process:**
1. Load trade lists cho EURUSD + XAUUSD + BTCUSD
2. For each pair, compute direction series (long=+1, short=-1)
3. Compute Pearson correlation giữa direction series
4. Output `output/correlation_matrix.csv`

**Acceptance:**
- Average correlation < 0.5 (good — pairs independent)
- If any pair > 0.7 → flag trong NOTES.md, add config filter
  `strategy.max_correlated_positions = 1`

**Code:** `scripts/correlation_analysis.py` — short script.

### Step 6 — Aggregate report + commit (1 ngày)

1. Tổng hợp outputs từ Steps 1-5 vào
   `output/multi_pair_regime_validation_<date>/REPORT.md`
2. Per-pair verdict table + regime breakdown + correlation verdict
3. Commit scripts + outputs + REPORT.md

## Files to modify / create

**Modify:**
- `src/backtester.py` — regime tag in trade dict
- `src/journal.py` — `stats_by_regime()` method
- `scripts/btest_10y.py` — refactor to `btest_multipair.py`

**Create:**
- `scripts/btest_multipair.py`
- `scripts/correlation_analysis.py`
- `tests/test_regime_tagging.py`
- `tests/test_multipair_backtest.py`
- `output/btest_<pair>_v2.csv` (3 files)
- `output/regime_metrics/eurusd_by_regime.csv`
- `output/correlation_matrix.csv`
- `output/multi_pair_regime_validation_<date>/REPORT.md`

## Todo

- [ ] Verify/extend XAUUSD + BTCUSD data
- [ ] Correlation guard spec (UI warning, no auto-block)
- [ ] Regime tagging in backtester
- [ ] Regime-tagged metrics
- [ ] Cross-pair correlation analysis
- [ ] Aggregate REPORT.md + commit

## Success criteria

- 3 pairs backtested với cùng config, output metrics per pair
- Each pair (nếu data đủ): PF ≥ 1.5, trades ≥ 50, max DD < 10%
- Regime breakdown identifies which regime(s) drive edge
- Correlation matrix shows pair independence
- REPORT.md có verdict pass/fail per check

## Risk

- **Shorter data for XAUUSD/BTCUSD** → smaller sample, noisier metrics.
  Mitigation: document sample size limitation, use longer window if data
  available.
- **Strategy không generalize** → EURUSD-only viable strategy nhưng cần
  document limitation rõ.
- **Regime tag overhead** → minor perf impact (one extra query per trade).
  Mitigation: cache regime state ở index level.
- **Correlation > 0.7** → portfolio-level risk không accounted. Per user
  decision (2026-08-31): NO auto-block, UI warning only. See section below.

## Correlation Warning (UI-only, no auto-block)

### Context

Multi-pair backtest 2026-08-31 (post-bug-fix baseline) showed strategy
profitable on EURUSD, XAUUSD, GBPUSD — but **EURUSD + GBPUSD correlation
~0.70** means they often move together (both are USD-denominated pairs).
Trading both simultaneously does NOT give 2× diversification:

```
Pair        Correlation
─────────────────────────
EURUSD/GBPUSD   +0.70  → effective risk multiplier = 1.87× (per trade pair)
EURUSD/XAUUSD   +0.20  → effective risk multiplier = 1.10× (good diversify)
EURUSD/USDCHF   -0.85  → effective risk multiplier = 0.39× (excellent)
```

**Practical implication**: 2 correlated trades (ρ=0.7) on the same day
have ~70% chance both hit SL together → effective loss ≈ 2× single trade.
FTMO 5% daily limit breached faster than expected.

### Decision (2026-8-31)

**Per user instruction: NO automatic correlation guard in code.**
Trader will self-monitorate via UI warning banner.

The correlation matrix + portfolio risk multiplier will be displayed
visually, but no pre-trade blocking. Trader's responsibility to size down
or skip correlated trades manually.

### Plan: Correlation Warning Banner (UI-only)

**Location**: `app/streamlit_app.py` sidebar OR bot's Telegram alert
formatting (`packages/smc_bot_webhook/src/smc_bot_webhook/notify/formatting.py`).

**Trigger**: Whenever signal comes in for a pair that has correlation ≥
threshold (0.65 default) with another currently-open position OR a signal
in the last N hours.

**Banner content** (example):
```
⚠️ CORRELATION WARNING
─────────────────────
Signal: GBPUSD long @ 1.2650
Open positions: EURUSD long @ 1.0850
Correlation: +0.70 (USD-pairs)
Effective risk: 1.87× of single trade
─────────────────────
If both hit SL → -2R ≈ -1.1% account
Recommendation: skip OR size down to 0.5 lot
This is informational only — no auto-block.
```

**Correlation matrix** (static table, computed once per session from
10y data):

```python
CORRELATION_MATRIX = {
    ("EURUSD", "GBPUSD"): 0.70,
    ("EURUSD", "XAUUSD"): 0.20,
    ("EURUSD", "USDJPY"): -0.30,
    ("EURUSD", "USDCHF"): -0.85,
    ("GBPUSD", "XAUUSD"): 0.15,
    ("GBPUSD", "USDJPY"): -0.20,
    ("XAUUSD", "USDJPY"): -0.10,
    # ...
}
```

Default threshold for warning: ρ ≥ |0.65| (highly correlated either way).

### Files to modify (UI warning, NOT code logic)

- `app/streamlit_app.py`: add sidebar section "Correlation matrix" +
  warning banner on signal page
- `packages/smc_bot_webhook/src/smc_bot_webhook/notify/formatting.py`:
  add correlation check in `format_signal_alert()` — if correlated
  position open, append warning text to Telegram/Discord alert

### Not implementing

- No `FTMOGuard` correlation check (per user decision)
- No automatic lot scaling
- No position closure on correlated entry

### Future (Track C — live validation)

When trader runs FTMO demo, log every correlated-trade scenario to
`journal/`. After 2-4 weeks, review whether correlation warning saved
trader from breach or was just noise. If useful → keep. If noise →
consider auto-block.

## Next steps


Phase 12 — MT5 Strategy Tester real run.
