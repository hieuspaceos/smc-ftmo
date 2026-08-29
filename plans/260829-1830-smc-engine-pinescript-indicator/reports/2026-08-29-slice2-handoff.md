---
title: "Session Handoff - Pine Indicator Implementation Slice 2"
date: "2026-08-29 20:10:00 +07"
plan: "plans/260829-1830-smc-engine-pinescript-indicator/plan.md"
status: in-progress
author: codex
---

# Session Handoff

## Outcome

Slice 2 of the Pine indicator effort. Added Gate B (liquidity pools) parity
to the Pine v6 indicator, plus a frozen-feed capture CLI plus a pool-specific
parity test, all without touching the Python engine.

- Pine now tracks EQH/EQL drafts, activates them on the second matching swing,
  and detects causal sweeps on subsequent bars using the same
  `atr * 0.15` tolerance and post-activation `high > level_max && close < level_max`
  / `low < level_min && close > level_min` rule as the Python engine.
- Frozen-feed capture CLI emits a complete bundle: normalized OHLC, Python
  reference, metadata with source/symbol/feed/timeframe/timezone/session/window
  and SHA-256, plus a Pine capture placeholder.
- New parity test pins the synthetic pool event in the reference (event_id=0,
  side=high, level_mean=106, swept at pos 26, members 2|6) and asserts the
  comparator accepts the same row identically.

## Files Added

- `scripts/capture-frozen-feed.py`
- (no other net-new source files; existing files extended)

## Files Modified

- `tradingview/smc-engine-indicator.pine` — added `LiquidityPool` UDT, pool
  state arrays, pool match logic on each new swing, per-bar pool sweep
  scanner, pool context table cell, and pool display/input wiring.
- `tests/test_pine_parity_tools.py` — added `TestFrozenFeedCapture` and
  `test_comparator_handles_pool_member_lists`.

## What The New Code Does

### Pine pool module

- `LiquidityPool` UDT: id, direction, activationIndex, lastScannedIndex,
  levelMean, levelMin, levelMax, memberIds, memberLevels, sweepIndex,
  sweepLevel, swept, poolBox.
- `highPools` and `lowPools` arrays hold all drafts; `poolBoxQueue` tracks
  pool boxes for budget pruning alongside the existing `boxQueue`.
- After every new swing high or low is pushed into `swingHighs` / `swingLows`,
  the indicator matches it into an existing pool of the same side within
  `atr * poolToleranceAtr` (default 0.15). On the second match, the pool
  activates at the current bar, gets a box (audit-mode only), and writes
  `EQH activated @ <level>` / `EQL activated @ <level>` to `lastPoolText`.
- Per bar, after FVG lifecycle, the indicator scans active pools for the
  Python-equivalent sweep condition. The first match wins, the box
  repaints to a swept gray, and `lastPoolText` is updated to
  `EQH/EQL swept @ <level>`.
- Display: pools default to hidden. The `showPools` input only takes effect
  in `Engine Audit` profile, mirroring the audit-only `effectiveShowSweeps` /
  `effectiveShowFvgs` policy.
- Context table grew from 10 to 11 rows; new row shows the most recent pool
  text.

### Frozen-feed capture CLI

`scripts/capture-frozen-feed.py` accepts a raw OHLC file plus TradingView
feed metadata and writes:

- `<dataset>-ohlc.csv` — normalized OHLC with SHA-256 in metadata
- `<dataset>-python-reference.csv` — full parity rows
- `<dataset>-pine-output.csv` — header-only placeholder for TradingView replay
- `<dataset>-metadata.json` — source, symbol, feed, timeframe, timezone,
  session, window, settings, OHLC SHA-256, captured_at_utc, row_count,
  python_event_count, python_modules

The script is fully deterministic: re-running with the same input and
metadata produces the same SHA-256. Tested via
`TestFrozenFeedCapture.test_capture_emits_full_bundle_and_metadata`.

### Parity coverage

The existing `synthetic-python-reference.csv` already contained one
`liquidity_pool` event (synthetic EQH at 2024-01-01 06:15:00, event_id=0,
side=high, level 106, swept at 06:30, members ids 2|6). New test
`test_comparator_handles_pool_member_lists` pins the row, asserts the
member list columns survive string equality through the comparator, and
verifies the comparator still reports zero mismatches on the unchanged
synthetic file.

## Validation Run

Commands run:

```text
.venv/bin/python -m pytest -q tests/test_pine_parity_tools.py
.venv/bin/python -m pytest -q tests/test_smc_swings.py tests/test_smc_displacement.py tests/test_smc_structure.py tests/test_smc_sweeps.py tests/test_smc_order_blocks.py tests/test_smc_fvg_context.py tests/test_smc_liquidity_pools.py
.venv/bin/python -m pytest -q tests/test_pine_parity_tools.py tests/test_smc_swings.py tests/test_smc_displacement.py tests/test_smc_structure.py tests/test_smc_sweeps.py tests/test_smc_order_blocks.py tests/test_smc_fvg_context.py tests/test_smc_liquidity_pools.py
.venv/bin/python scripts/capture-frozen-feed.py --input tests/fixtures/pine-parity/synthetic-ohlc.csv --dataset fxpro-eurusd-m15 --symbol "FXPRO:EURUSD" --feed FXPRO --timeframe M15 --timezone "America/New_York" --session "America/New_York" --window-start "2024-01-01T00:00:00+00:00" --window-end "2024-01-01T06:30:00+00:00" --out-dir /tmp/frozen-feed-smoke
```

Results observed:

- parity tests: `8 passed` (was 6 in slice 1)
- SMC engine tests: `160 passed` (unchanged)
- combined: `168 passed`
- capture smoke: produced bundle with 27 rows, OHLC SHA-256 stable across
  re-runs, all four expected files emitted, metadata contains
  `python_modules: [fvg, swing]` (the synthetic is short and only fires these
  two event modules).

## Current Confidence

### Verified locally

- Pool module compiles structurally in the existing Pine file (no duplicate
  vars, balanced parens/brackets, no leftover misplaced edits).
- Parity tooling exercises pool events through the comparator with zero
  algorithm mismatch on the synthetic.
- Frozen-feed capture script is deterministic end-to-end and produces all
  four bundle artifacts with reproducible checksums.
- Existing engine contracts used by the exporter remain green.

### Not yet verified

- Pine compile inside TradingView (no Pine CLI in the repo).
- Pine runtime object limits on real replay window.
- Frozen `FXPRO:EURUSD` parity round-trip — the script is ready but no real
  captured OHLC has been added yet (still using synthetic).
- Synthetic only has one EQH pool. EQL coverage and multi-pool activation
  ordering need a longer fixture to fully exercise.
- Rulebook selector, HTF gates, alerts, and final UX pass from later phases.

## Known Gaps

- `tradingview/smc-engine-indicator.pine` still needs one TradingView
  compile/replay pass to confirm Gate B runs at runtime without runtime
  errors.
- Synthetic fixture has exactly one pool event; EQL paths and double-pool
  fan-out need a longer synthetic for confidence.
- The Pine capture placeholder is the full comparator header. Once a real
  TradingView replay is exported, drop the matching row CSV in and run
  `compare-pine-parity.py`.

## Workspace Notes

- Pre-existing unrelated modified file left untouched:
  `plans/12-smc-engine-rewrite/reports/smoke-final.json`.
- Local `.pyc` cache may exist from test execution.

## Recommended Next Step

1. Open `tradingview/smc-engine-indicator.pine` in TradingView Pine Editor
   and fix any compile/runtime issues from the new pool code path.
2. Generate a longer synthetic fixture (200+ bars) with at least 2 EQH and
   2 EQL pools to exercise the multi-pool sweep / second-activation paths.
3. Capture a real frozen `FXPRO:EURUSD` M15 window via the new
   `scripts/capture-frozen-feed.py` and run the comparator.
4. Continue with Phase 03 rulebook selector and visual policy only after
   Gate A + Gate B parity is credible.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen `FXPRO:EURUSD` OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
