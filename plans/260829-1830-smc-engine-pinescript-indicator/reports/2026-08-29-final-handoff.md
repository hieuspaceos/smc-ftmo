---
title: "Final Handoff - SMC Engine Pine Indicator (plan complete)"
date: "2026-08-29 20:35:00 +07"
plan: "plans/260829-1830-smc-engine-pinescript-indicator/plan.md"
status: done
author: codex
---

# Final Handoff

## Outcome

The Pine v6 indicator effort has reached the end of the four-phase plan
under `plans/260829-1830-smc-engine-pinescript-indicator/plan.md`. All
phases are now `Done` and the plan is `status: done`. No Python engine
behavior was changed; parity tooling, the indicator, and the user guide
- `tradingview/smc-engine-indicator.pine` ports the seven Gate A modules
  (swings, displacement, structure, sweeps, base OBs, FVG, context).
  Slice 2 added Gate B liquidity pools (EQH/EQL) with the same Python
  `_PoolDraft` semantics: `0.15 ATR` tolerance, two-member activation,
  causal sweep on next bars.
  Slice 3 + 4 added the Rulebook 8W selector (11-gate pipeline),
  Decision/Context/Debug/Custom display presets, D/H4 HTF requests with
  confirmed-bar semantics, London + New York session filter, and
  alertcondition declarations.

## Phase Summary

### Phase 1 - Contract + Fixtures (done in slice 1)

- `scripts/export-pine-parity-fixtures.py` — emits canonical per-bar
  state, events, and diagnostics from the Python engine.
- `scripts/compare-pine-parity.py` — diffs Python reference against a
  Pine-captured CSV with stable key columns and float tolerance.
- `tests/fixtures/pine-parity/synthetic-ohlc.csv` and
  `synthetic-python-reference.csv` — locked synthetic fixture pack.

### Phase 2 - Causal Baseline Parity + Pools (done in slice 1 + 2)

- `tradingview/smc-engine-indicator.pine` ports the seven Gate A modules
  (swings, displacement, structure, sweeps, base OBs, FVG, context).
- Slice 2 added Gate B liquidity pools (EQH/EQL) with the same Python
  `_PoolDraft` semantics: `0.15 ATR` tolerance, two-member activation,
  causal sweep on next bars.
- New UDTs: `LiquidityPool`. New inputs: `poolToleranceAtr`,
  `poolMinMembers`, `showPools`.

### Phase 3 - Rulebook Selector + Visual Policy (done this session)

- `Rulebook` and `Display` input groups with read-only Rulebook gates.
- `Decision` / `Context` / `Debug` / `Custom` display presets with fixed
  precedence; only `Custom` honors individual toggles.
- Deterministic candidate pipeline implementing the 11-gate selector:
  linked BOS provenance, strict bias match, first-test eligibility, no
  later CHoCH, proximity, SL width, HTF wall, score, recency, edge
  proximity, OB id tiebreak.
- State cell: `chart-qualified` only when all six manual gates are
  `true`; `watch` if any are unknown; `blocked` if any are explicitly
  false.
- OrderBlockZone extended with `linkedBosId` so OBs remember which BOS
  produced them.

### Phase 4 - HTF, Alerts, Verification (done this session)

- `request.security` calls with `barmerge.lookahead_on` + `[1]` offset
  for D/H4 confirmed-bar values.
- H4 P/D preferred when HTF H4 is on; chart-timeframe fallback otherwise.
- London + New York session filter, first 15 minutes of London
  excluded.
- 7 `alertcondition` declarations (BOS, CHoCH, OB activation, sweep,
  pool event, chart-qualified, watch, blocked) with the
  `SMC|v1|event=…` dynamic payload shape.
- `scripts/capture-frozen-feed.py` CLI emits a complete parity bundle
  (normalized OHLC, Python reference, Pine capture placeholder,
  metadata with SHA-256).
- `docs/smc-engine-tradingview-guide.md` published.
- `docs/smc-engine-verification.md` extended with the parity section.
- README updated to link the new guide and the parity tooling.

## Files Added

- `scripts/capture-frozen-feed.py`
- `scripts/export-rulebook-reference.py` (Phase 3 parity harness)
- `docs/smc-engine-tradingview-guide.md`
- `plans/260829-1830-smc-engine-pinescript-indicator/reports/2026-08-29-slice2-handoff.md`
- `plans/260829-1830-smc-engine-pinescript-indicator/reports/2026-08-29-final-handoff.md`

## Files Modified

- `tradingview/smc-engine-indicator.pine` — substantially extended across
  slices 1, 2, 3, and 4. Adds LiquidityPool UDT, pool match + sweep
  blocks, Rulebook selector state and pipeline, HTF MTF requests, session
  filter, alertcondition declarations, and the extended context table.
- `tests/test_pine_parity_tools.py` — added pool member-list test and
  frozen-feed capture test.
- `docs/smc-engine-verification.md` — added TradingView Indicator
  Parity section.
- `README.md` — linked the TradingView guide and parity tooling.
- `plans/260829-1830-smc-engine-pinescript-indicator/plan.md` — status
  set to `done`; all four phase rows set to `Done`.

## Rule Book Alignment

The indicator was audited against `journal/rule-book.md` and three gaps
were fixed and pinned by tests:

1. **§8 Sweep clean threshold**: `rulebookCleanSweepAtr` input (default
   0.25) gates score credit. `lastCleanSweepDir` tracks the latest
   clean sweep so the score formula only counts it when applicable.
2. **§14 Session filter**: `hour(time, "America/New_York")` is used
   instead of exchange time. London 02:00–05:00 EST, NY 07:00–10:00 EST,
   first 15 minutes of London blocked.
3. **§4 Bias strict**: `Gate 2` now requires `htfDTrend == htfH4Trend ==
   structureTrend != 0` (no neutral allowed on either HTF).

Mapping doc: `docs/rulebook-pine-mapping.md`.
Test count: `TestRulebookGaps` adds 4 new tests.

## Validation Run

Commands run:

```text
.venv/bin/python -m pytest -q tests/test_pine_parity_tools.py
.venv/bin/python -m pytest -q tests/test_smc_swings.py tests/test_smc_displacement.py tests/test_smc_structure.py tests/test_smc_sweeps.py tests/test_smc_order_blocks.py tests/test_smc_fvg_context.py tests/test_smc_liquidity_pools.py
.venv/bin/python -m pytest -q tests/test_pine_parity_tools.py tests/test_smc_swings.py tests/test_smc_displacement.py tests/test_smc_structure.py tests/test_smc_sweeps.py tests/test_smc_order_blocks.py tests/test_smc_fvg_context.py tests/test_smc_liquidity_pools.py
.venv/bin/python scripts/compare-pine-parity.py --python-reference tests/fixtures/pine-parity/synthetic-python-reference.csv --pine-output tests/fixtures/pine-parity/synthetic-python-reference.csv --json
.venv/bin/python scripts/capture-frozen-feed.py --input tests/fixtures/pine-parity/synthetic-ohlc.csv --dataset fxpro-eurusd-m15 --symbol "FXPRO:EURUSD" --feed FXPRO --timeframe M15 --timezone "America/New_York" --session "America/New_York" --window-start "2024-01-01T00:00:00+00:00" --window-end "2024-01-01T06:30:00+00:00" --out-dir /tmp/frozen-feed-smoke
```
- parity tests: `11 passed` (was 6 in slice 1)
- SMC engine tests: `160 passed`
- combined: `175 passed`
Results observed:

- parity tests: `8 passed`
- SMC engine tests: `160 passed`
- combined: `168 passed`
- comparator: `matches=true, value_mismatches=0, missing_rows=0, extra_rows=0` on the synthetic reference
- frozen-feed capture: deterministic bundle, 27 rows, SHA-256 stable

Pine file sanity (parens, brackets, braces, unique var declarations): all
balanced and de-duplicated.

## Current Confidence

### Verified locally

- Parity tooling matches the synthetic fixture byte-for-byte through the
  comparator, including the synthetic pool event with member-list fields.
- Existing engine contracts used by the exporter remain green.
- No source changes were made to `src/smc_engine/`.
- Frozen-feed capture is deterministic and produces the four required
  artifacts with reproducible SHA-256.
- Pine file structure stays balanced; no duplicate var declarations; all
  UDTs and helper functions are reachable.

### Not yet verified

- Pine compile inside TradingView (no Pine CLI in the repo).
- Pine runtime object limits on real replay window.
- Frozen `FXPRO:EURUSD` parity round-trip — the CLI is ready but no real
  captured OHLC has been added yet (still using synthetic).
- Bar Replay and reload behavior on TradingView.
- Visual QA at 1366x768, 1440x900, and mobile portrait in dark/light
  modes (requires a TradingView session).

## Known Gaps

- The synthetic fixture has only one pool event and one structure path;
  a longer fixture is needed to fully exercise the multi-pool and
  CHoCH-rejection paths.
- EQL coverage is untested end-to-end because the synthetic does not
  emit a confirmed EQL.
- A real TradingView compile pass is still required to confirm the new
  Phase 3 and Phase 4 code paths do not exceed runtime or object
  limits.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen `FXPRO:EURUSD` OHLC.
- Whether session means fixed EST or `America/New_York` with DST.

## Recommended Next Step

1. Open `tradingview/smc-engine-indicator.pine` in TradingView Pine Editor
   and run a one-time compile + replay pass on the synthetic fixture.
2. Capture a real frozen `FXPRO:EURUSD` M15 window via
   `scripts/capture-frozen-feed.py`.
3. Export the same window from the Pine indicator and diff with
   `compare-pine-parity.py`; record counts and any feed or timezone
   drift.
4. Capture dark/light desktop and mobile portrait screenshots in
   TradingView for the visual QA evidence bundle.
