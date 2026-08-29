# Phase 01: Contract + Fixtures

## Context

- [Plan](./plan.md)
- [Research](./research/smc-market-comparison-and-pine-feasibility.md)
- Reference modules: `src/smc_engine/`

## Goal

Freeze the machine-comparable contract before writing Pine. This phase locks the
shared causal core, the Rulebook policy fixture, and the frozen-feed parity
fixture shape.

## Requirements

- Record the locked current-app defaults, not the `SMCSignals` constructor default.
- Separate baseline parity fixtures from Rulebook policy fixtures.
- Define four separate schemas: frozen OHLC; per-bar ATR/expansion/structure/context;
  immutable event/lifecycle rows; diagnostics, rejections, and manual-gate state.
- Preserve pivot position separately from activation position.
- Identify every row by bar-open epoch; record separately that decisions finalize
  on the confirmed bar close.
- Include source swing and origin identifiers and lifecycle timestamps where
  applicable.
- Use a frozen `FXPRO:EURUSD` M15 sample with metadata and checksum.
- Do not label local HistData as FXPRO.
- Keep the fixture schema reusable for later XAUUSD and BTCUSD datasets.

## Files

- Create `scripts/export-pine-parity-fixtures.py`.
- Create `scripts/compare-pine-parity.py`.
- Create `tests/fixtures/pine-parity/synthetic-ohlc.csv`.
- Create `tests/fixtures/pine-parity/synthetic-python-reference.csv`.
- Create or privately supply `tests/fixtures/pine-parity/fxpro-eurusd-m15-ohlc.csv`.
- Create `tests/fixtures/pine-parity/fxpro-eurusd-m15-metadata.json` with source,
  timezone, session, window, settings, and SHA-256 checksum.
- Create `tests/fixtures/pine-parity/eurusd-m15-python-reference.csv`.
- Capture `tests/fixtures/pine-parity/eurusd-m15-pine-output.csv`.
- Create `tests/fixtures/pine-parity/rulebook-policy-events.csv`.
- Create comparator/exporter tests and
  `plans/260829-1830-smc-engine-pinescript-indicator/reports/parity-verification.md`.

## Implementation Steps

1. Specify canonical columns and numeric precision for OHLC, per-bar state,
   lifecycle fields, and rejection diagnostics. Event identity, bar epoch, and
   direction compare exactly; derived floats use a documented tight numeric
   tolerance; tick-size tolerance is rendering-only.
2. Build deterministic synthetic OHLC cases for first-bar/NaN/zero-range ATR,
   equal pivots, same-bar activation, wick-only and equality breaks, consumed-level
   replacement, invariant/dual-break suppression, displacement boundary, doji OB
   exclusion, OB/FVG expiry precedence, same-bar touch plus invalidation/fill,
   dual-sided sweeps, CHoCH without OB, later pool members, cap eviction, and
   manual-gate blocked states.
3. Export reference events from the current engine for the frozen
   `FXPRO:EURUSD` M15 sample.
4. Record feed, timezone, timeframe, date range, and engine settings in fixture
   metadata.
5. Add prefix-invariance checks for exported event prefixes and policy rows.
6. Add a comparator that can diff Python reference output, Pine captured output,
   and the frozen fixture set.
7. Add separate Rulebook cases for linked BOS/OB ids, opposite-direction and
   `0.25 ATR` boundary sweeps, H4-vs-M15 P/D disagreement, intervening CHoCH,
   multiple OB candidates, exact `1.2/1.5 ATR` boundaries, 2R wall
   before/at/beyond target, session boundaries, and DST behavior.

## Validation

- Run focused engine tests and fixture-export tests.
- Re-run the exporter twice and compare checksums.
- Manually inspect at least one bullish and bearish full lifecycle.
- Verify the frozen-feed sample does not drift across exports.

## Completion Checklist

- [ ] Event schema approved.
- [ ] Synthetic fixture covers every strict boundary.
- [ ] Rulebook policy fixture covers chart-qualified, watch, and blocked states.
- [ ] Frozen-feed metadata is reproducible.
- [ ] Export is deterministic.
- [ ] No future data appears in activation rows.

## Risks and Rollback

- Float formatting can create false mismatches; use the locked derived-float tolerance, not display tick rounding, for parity.
- Feed mismatch must be classified separately from algorithm mismatch.
- Fixture work is additive; rollback by removing only new exporter or fixture files.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
