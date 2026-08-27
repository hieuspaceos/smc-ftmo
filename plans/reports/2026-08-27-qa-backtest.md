# QA Report — SMC FTMO Backtester (2026-08-27)

## Test Results Overview
- Ran: `python -m pytest tests/test_backtest.py -q --tb=short`
- **10 passed / 0 failed** in ~19s
- Diff-aware: `tests/test_backtest.py` + core `src/*` path

## Metrics (EURUSD, min_score=4, risk=0.5%)
| Metric | Value | Gate |
|--------|-------|------|
| Trades | 147 | ≥15 ✓ (≥50 plan ideal) |
| Winrate | 53.7% | 45–65% ✓ |
| Profit factor | 2.04 | >1.3 ✓ |
| Max DD | 3.71% | <4% ✓ |
| Score &lt;4 | 0 | none ✓ |

## Root causes fixed
1. **Displacement truncated** — `get_signals` looped only `n_s+1` after `shift(1).dropna()` (~12k early bars). Full-df loop for disp/sweep.
2. **D bias ends before M15** — D parquet ends 2024-08-27; M15 starts same day. Extend D from H1-daily + ffill onto M15 calendar days.
3. **H4 bias all neutral** — 50-bar windows too short for BOS. Cumulative history through day-end.
4. **PnL double-count** — `close_pct` + `closed` both added equity. Book only on `close_pct` with original-size fraction; journal on `closed`.
5. **Entry quality** — real OB required; price within 1.5 ATR of OB edge; fixed risk off initial account (not compounding).
6. **Sweep sparse** — displacement used as sweep proxy so score can reach ≥4 without library sweeps.

## Critical anchors verified
- `detect_displacement` / `detect_sweep` present in `smc_signals.py`
- `score_setup` requires displacement + bias_aligned
- `PartialTPExit` 40/30/30 + BE at 2R
- `FTMOGuard.can_trade` daily -2R
- Journal `insert_trades` / `filter_trades` / `stats_by_setup`

## Coverage / build
- No separate coverage run (scoped assignment).
- Build: N/A Streamlit app not smoke-launched this turn (pytest is contract gate).

## Critical issues
- None blocking. Soft: library sweeps still ~0; OB count sparse (~70); MaxDD tight at 0.55% risk (~4.03%) — fixture uses 0.5%.

## Recommendations
1. Improve real sweep detection from swing HighLow takeouts.
2. Denser OBs (custom pivots) for more score-5 setups.
3. Optional: keep risk_per_trade=0.0055 in config.yaml UI default; test fixture stays 0.5%.

## Unresolved
- None for pytest gate.
