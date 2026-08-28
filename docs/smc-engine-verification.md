---
status: active
title: "SMC Engine Verification"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Verification

## Test Inventory

Current engine + integration coverage:

| File | Scope |
|---|---|
| `tests/test_smc_swings.py` | confirmed swing activation semantics |
| `tests/test_smc_displacement.py` | ATR warmup + range-expansion metrics |
| `tests/test_smc_structure.py` | BOS/CHoCH state machine |
| `tests/test_smc_sweeps.py` | liquidity sweep detection |
| `tests/test_smc_order_blocks.py` | BOS-activated OB lifecycle |
| `tests/test_smc_fvg_context.py` | FVG lifecycle + context |
| `tests/test_smc_breaker_blocks.py` | breaker causality oracle |
| `tests/test_smc_ob_body_mode.py` | OB body-mode geometry transform |
| `tests/test_smc_regime.py` | regime heuristic |
| `tests/test_backtest.py` | baseline characterization backtest |
| `tests/test_backtest_breakers.py` | breaker + regime integration into backtester |

Current full suite: **197 passed**.

## Smoke Invariants

`python scripts/smoke-phase12.py`

Stable baseline:

- `trade_total = 32`
- `winrate = 0.8125`
- `profit_factor = 8.285761610711116`
- `max_dd_pct = 1.1661968861126697`
- `m15_close_sha256 = 4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a`

Meaning:

- default path still matches the shipped Phase 12 baseline
- Plan 13 / 14 additions do not mutate baseline behavior when their toggles
  are left at defaults

## Characterization Results

### Baseline vs Breakers vs Auto

On EURUSD M15 2026:

| Mode | Trades | WR | PF | Total R | Max DD |
|---|---|---|---|---|---|
| `regime_mode="off"` | 32 | 81.2% | 8.29 | 60.5 | 1.17% |
| `regime_mode="on"` | 21 | 57.1% | 2.75 | 27.3 | 3.23% |
| `regime_mode="auto"` | 21 | 57.1% | 2.75 | 27.3 | 3.23% |

Interpretation:

- breakers are active and being consumed by the backtester when enabled
- they degrade edge on this specific dataset
- the current `auto` regime heuristic classifies the dataset as `ranging`, so
  it currently behaves the same as `on`

### Breaker activation count

On EURUSD M15 2026:

- 59 breaker events detected
- monthly spread: Jan 9, Feb 4, Mar 7, Apr 10, May 8, Jun 8, Jul 11, Aug 2
- direction mix: 37 bullish, 22 bearish

This proves the breaker layer is wired correctly even though it is not
currently beneficial for this market regime.

## What Is Verified vs What Is Still Heuristic

### Verified

- swing confirmation timing
- BOS/CHoCH causality
- OB/FVG lifecycle queries
- completed-bar HTF alignment onto M15
- deterministic replay on the shipped dataset
- breaker promotion causality (`invalidation < CHoCH`)
- body-mode geometry transform
- backtester integration guards (`off` preserves baseline)

### Still heuristic / research-grade

- regime auto-switching
- whether breakers improve edge on other pairs or other years
- whether body-only OB zones outperform full-range OB zones on live data
- whether `auto` should incorporate structure frequency (BOS/CHoCH density),
  ATR percentile, session context, or volume

## Recommended Operational Defaults

For the current shipped EURUSD M15 2026 dataset:

- `bias_mode = "strict"` or `"h4_only"` depending entry appetite
- `regime_mode = "off"`
- `promotion_lookback_bars = 50`
- classic OB entries only

Use `regime_mode = "on"` or `"auto"` only for research until the regime
heuristic is improved.
