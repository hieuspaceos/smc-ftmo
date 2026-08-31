# Phase 09 — Statistical Validation

## Context

Phase 08 đã làm backtest realistic (spread, commission, next-bar-open,
session filter). Bây giờ cần **prove edge có thật** chứ không phải curve-fit.

Audit (`plans/reports/260831-trading-system-audit.md`) chỉ ra **0 statistical
tests** trong repo. PF 3.57 trên 603 trades nghe hay nhưng có thể là:
- Curve-fit vào 1 cú COVID crash (PnL concentrated ở 1 trade)
- Lucky timing (70% PnL đến từ 1 tháng 3/2020)
- Sample luck (variance lớn, true mean R gần 0)

Pro trader / quant desk **luôn** chạy 4 tests sau trước khi trust backtest.

## Goal

Chứng minh **với confidence ≥ 95%** rằng:
1. **OOS performance** match IS performance (không curve-fit)
2. **Edge persists** khi perturb ±20% tham số (không fragile)
3. **Ruin probability** < 5% (với max DD distribution thực tế)
4. **Mean R > 0** với statistical significance (không sample luck)

## Steps

### Step 1 — Out-of-Sample split (1-2 ngày)

**Config:** Tách 10 năm data thành:
- **In-sample (IS):** 2016-01-01 → 2022-12-31 (7 năm)
- **Out-of-sample (OOS):** 2023-01-01 → 2026-08-21 (3.5 năm)

**Process:**
1. Optimize parameters trên IS (nếu chưa fix — repo dùng config.yaml cố
   định, nhưng có thể sweep trên IS để verify default đã tối ưu)
2. Run backtest trên OOS với parameters đã chốt từ IS
3. Compare IS vs OOS metrics

**Acceptance:**
- OOS PF ≥ 0.7 × IS PF (cho phép degrade ~30%)
- OOS Sharpe ≥ 0.5 (lower bound cho profitable)
- OOS Winrate ≥ 0.7 × IS Winrate

**Code:** `scripts/oos_split.py` — single CLI script, output 2 DataFrames +
comparison table.

**Test:** `tests/test_oos_split.py` — verify IS/OOS date boundaries không
overlap, metrics computed correctly.

### Step 2 — Walk-forward analysis (3-4 ngày)

**Config:**
- IS window: 6 tháng (rolling)
- OOS window: 2 tháng
- Step: 1 tháng
- Total: 2016-01 → 2026-08 → ~50 rolling windows

**Process:**
1. Với mỗi window:
   - Run backtest trên 6 tháng IS
   - Apply same parameters cho 2 tháng OOS tiếp theo
   - Record OOS trades + metrics
2. Aggregate OOS metrics across tất cả 50 windows
3. Compare aggregate OOS vs full-period IS

**Acceptance:**
- Aggregate OOS PF ≥ 1.5
- Aggregate OOS Max DD < 5%
- ≥ 80% windows có profitable OOS (nếu < 80% → strategy không robust)

**Code:**
- `scripts/walk_forward.py` — main orchestrator
- `src/backtester.py:run_backtest()` không đổi signature, chỉ thêm
  optional `start_date`/`end_date` params (đã có sẵn)

**Output:**
- `output/walk_forward/per_window.csv` — 50 rows × {window_start,
  window_end, is_pf, oos_pf, oos_dd, oos_trades}
- `output/walk_forward/aggregate.md` — summary table + verdict

**Test:** `tests/test_walk_forward.py` — verify date arithmetic không overlap,
aggregation logic đúng.

### Step 3 — Monte Carlo simulation (2-3 ngày)

**Config:**
- Shuffles: 1000 (có thể bump lên 10000 nếu CPU cho phép)
- Source: trade list đã backtest từ full 10 năm EURUSD
- Method: shuffle trade order, recompute equity curve + max DD + final PnL

**Process:**
1. Load trades từ `output/btest_10y_v2_realistic.csv` (sau Phase 08)
2. For each shuffle:
   - Random permutation of trade order
   - Compute equity curve with same lot size
   - Record max DD, final PnL, max consecutive losses, ruin equity (< 50%)
3. Aggregate across 1000 shuffles:
   - **Max DD distribution**: 5th, 50th, 95th percentile
   - **Ruin probability**: % shuffles where equity drops below 50% of start
   - **PnL distribution**: 5th, 50th, 95th percentile

**Acceptance:**
- 95th percentile Max DD < 10% (FTMO limit)
- Ruin probability < 5%
- 5th percentile final PnL > 0

**Code:** `scripts/monte_carlo.py` — uses numpy random, không cần scipy.

**Output:**
- `output/monte_carlo/distributions.png` — histograms (matplotlib)
- `output/monte_carlo/summary.md` — percentile table + verdict

**Test:** `tests/test_monte_carlo.py` — verify shuffle preserves trade
distribution, max DD computation correct trên known sequences.

### Step 4 — Parameter sensitivity (2-3 ngày)

**Config:**
- Parameters to perturb: `swing_length` (10 ± 50%), `sl_atr_buffer`
  (0.2 ± 50%), `min_confluence_score` (4 ± 1), `displacement_atr_mult`
  (1.5 ± 30%)
- Method: one-at-a-time (OAT) sweep, 5-7 points per param

**Process:**
1. Default config → baseline
2. For each param:
   - Run backtest với values [-50%, -25%, -10%, default, +10%, +25%, +50%]
   - Record total R, PF, Max DD
3. Identify "fragile" parameters (PF drops > 30% với ±10% perturbation)

**Acceptance:**
- All 4 params survive ±10% perturbation (PF drop < 30%)
- Document fragile params trong NOTES.md

**Code:** `scripts/sensitivity.py` — parallel execution qua
`concurrent.futures.ProcessPoolExecutor` để giảm time.

**Output:**
- `output/sensitivity/swing_length_sweep.csv` — 7 rows × metrics
- `output/sensitivity/sl_atr_buffer_sweep.csv`
- `output/sensitivity/min_confluence_score_sweep.csv`
- `output/sensitivity/displacement_atr_mult_sweep.csv`
- `output/sensitivity/summary.md` — verdict per param

**Test:** `tests/test_sensitivity.py` — verify OAT logic, baseline match.

### Step 5 — Statistical significance (1-2 ngày)

**Tests:**
1. **t-test** trên R-multiples: H0 = mean R = 0, reject với p < 0.05
2. **Bootstrap CI** trên Sharpe ratio: 10000 bootstrap resamples, report
   95% CI
3. **Winrate binomial test**: H0 = winrate = random (50%), reject p < 0.05

**Process:**
1. Load R-multiples từ `output/btest_10y_v2_realistic.csv`
2. `scipy.stats.ttest_1samp(R, 0)` → t-statistic + p-value
3. `scipy.stats.bootstrap(R, statistic=lambda x: x.mean()/x.std())`
4. `scipy.stats.binom_test(wins, trials, 0.5)` → p-value

**Acceptance:**
- t-test p-value < 0.05 (mean R ≠ 0)
- Bootstrap CI for Sharpe > 0 (lower bound > 0)
- Winrate p-value < 0.05

**Code:** `scripts/statistical_tests.py` — single script, outputs table.

**Output:** `output/statistical_tests/results.md`

**Test:** `tests/test_statistical_tests.py` — verify scipy calls correct.

### Step 6 — Aggregate report + commit (1 ngày)

1. Tổng hợp outputs từ Steps 1-5 thành
   `output/statistical_validation_<date>/REPORT.md`
2. Pass/fail verdict cho mỗi test
3. Nếu fail bất kỳ test nào → KHÔNG move on Track C, quay lại Phase 08
   hoặc re-design strategy
4. Commit scripts + outputs + REPORT.md

## Files to create

- `scripts/oos_split.py`
- `scripts/walk_forward.py`
- `scripts/monte_carlo.py`
- `scripts/sensitivity.py`
- `scripts/statistical_tests.py`
- `tests/test_oos_split.py`
- `tests/test_walk_forward.py`
- `tests/test_monte_carlo.py`
- `tests/test_sensitivity.py`
- `tests/test_statistical_tests.py`
- `output/statistical_validation_<date>/` — outputs + REPORT.md

## Dependencies

- `scipy >= 1.10` (cho stats functions) — check `requirements.txt`, có thể
  cần add
- `matplotlib >= 3.5` (cho Monte Carlo histograms) — check requirements

## Todo

- [ ] OOS split script + test
- [ ] Walk-forward script + test
- [ ] Monte Carlo script + test
- [ ] Sensitivity script + test
- [ ] Statistical tests script + test
- [ ] Aggregate REPORT.md + commit
- [ ] Tag `v0.6.0-statistically-validated` nếu pass hết

## Success criteria

- 5 new scripts chạy được end-to-end trên Phase 08 backtest output
- 5 new test files pass
- REPORT.md có verdict pass/fail cho từng test
- Nếu pass hết → confidence ≥ 95% edge có thật

## Risk

- **OOS performance sụp** → curve-fit confirmed → block Track C, re-design
- **Walk-forward > 20% windows fail** → strategy không robust → block
- **Monte Carlo ruin% > 5%** → position sizing quá aggressive → giảm risk
- **Sensitivity quá fragile** → overfit → giảm số params hoặc regularize
- **CPU time** cho walk-forward 50 windows × full backtest = 30-60 min,
  Monte Carlo 1000 shuffles × equity calc = 5-10 min. Mitigation: cache
  intermediate results.

## Next steps

Phase 10 — Pine Parity real capture (TradingView Bar Replay).
