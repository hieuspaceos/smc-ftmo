---
status: active
title: "SMC Engine Verification"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Verification

## Đọc nhanh bằng tiếng Việt

Phần verify này trả lời câu hỏi:

> \"Mình có thể tin engine này tới mức nào?\"

Câu trả lời thực tế:
- Nhưng **không nên tin tuyệt đối** rằng backtest đẹp = sẽ kiếm tiền ngoài thị trường thật
- Có thể chạy parity tooling để so sánh output Pine với Python engine
- Có thể tin nó **đọc cấu trúc nhất quán**
- Có thể tin nó **không nhìn tương lai**
- Có thể tin nó **cho cùng input => cùng output**

Nói dễ hiểu:

- test pass = engine làm đúng luật nó đã định nghĩa
- smoke checksum ổn = engine không bị drift ngẫu nhiên
- winrate đẹp = chỉ là kết quả trên dataset hiện tại, chưa chắc là chân lý

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
| `tests/test_backtest_breakers.py` | breaker + regime integration into backtester |
| `tests/test_smc_liquidity_pools.py` | EQH/EQL clustering + causal pool sweep lifecycle |

Current full suite: **209 passed**.

## TradingView Indicator Parity

The Pine v6 indicator (`tradingview/smc-engine-indicator.pine`) targets
event parity on the same `FXPRO:EURUSD` M15 feed the Python engine was
tuned on. Parity tooling:

- `scripts/export-pine-parity-fixtures.py` — emits canonical rows
  (per-bar state, events, diagnostics) from the current Python engine.
- `scripts/compare-pine-parity.py` — diffs Python reference against
  Pine-captured CSV with stable key columns and float tolerance.
- `scripts/capture-frozen-feed.py` — captures a frozen TradingView
  window (OHLC + reference + metadata + SHA-256) for the same dataset.

Tests: `tests/test_pine_parity_tools.py` covers exporter determinism,
comparator float tolerance, pool member-list equality, and the frozen
feed capture smoke path. Current parity count: **8 passed** (was 6
before Gate B and the capture CLI).

See `docs/smc-engine-tradingview-guide.md` for the user guide and
`plans/260829-1830-smc-engine-pinescript-indicator/reports/` for the
slice-by-slice handoff.

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
- Plan 13 / 14 additions and the Regime V2 refinement do not mutate baseline
  behavior when toggles stay at defaults

## Characterization Results

### Baseline vs Breakers vs Auto

On EURUSD M15 2026:

| Mode | Trades | WR | PF | Notes |
|---|---|---|---|---|
| `regime_mode="off"` | 32 | 81.2% | 8.29 | baseline OB-classic |
| `regime_mode="on"` | 21 | 57.1% | 2.7475 | forced breakers |
| `regime_mode="auto"` | 32 | 81.2% | 8.29 | still matches `off` |

Interpretation:

- breakers remain active and consumed when forced `on`
- they still degrade edge on this specific dataset (21 trades, PF 2.7475)
- Regime V2 still classifies the shipped path as `mixed` with `breaker_weight=0`
- Phase 02 adds EQH/EQL density to the explanation and ranging-pressure score,
  but it does not destabilize the shipped baseline path

### Liquidity pool characterization

On EURUSD M15 2026:

- 495 confirmed EQH/EQL liquidity pools detected
- recent-window density seen by `detect_regime`: about **7.2 / 100 bars**
- app auto explanation now includes `EQH/EQL pools ... /100`

This proves the pool layer is wired into regime reasoning without changing the
default trade set on the shipped dataset.

## What Is Verified vs What Is Still Heuristic

### Verified

- swing confirmation timing
- BOS/CHoCH causality
- OB/FVG lifecycle queries
- completed-bar HTF alignment onto M15
- deterministic replay on the shipped dataset
- breaker promotion causality (`invalidation < CHoCH`)
- body-mode geometry transform
- EQH/EQL confirmation at the second matching swing
- pool sweep semantics require reclaim, not breakout continuation
- pool extensions are causal: later members do not rewrite earlier sweep outcomes
- backtester integration guards (`off` preserves baseline)

### Still heuristic / research-grade

- whether breakers improve edge on other pairs or other years
- whether body-only OB zones outperform full-range OB zones on live data
- whether `auto` ranging calls transfer beyond the shipped EURUSD window
- whether session context or volume should refine the structure densities

## Recommended Operational Defaults

For the current shipped EURUSD M15 2026 dataset:

- `bias_mode = "strict"` or `"h4_only"` depending entry appetite
- `regime_mode = "off"`
- `promotion_lookback_bars = 50`
- classic OB entries only

Use `regime_mode = "on"` only for research. Prefer `off` or `auto` on the
shipped EURUSD path; both currently keep the baseline OB-only trade set.
