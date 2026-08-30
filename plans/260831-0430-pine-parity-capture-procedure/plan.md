---
status: ready
title: "Pine↔Python Parity Capture Procedure"
created: "2026-08-31"
author: codex
milestone: 2026-08-31 (scale-in + honest parity label)
---

# Pine↔Python Parity Capture Procedure

## Why this exists

`docs/smc-engine-verification.md` previously claimed
`pine-status: parity-achieved` based only on tooling tests (15/15 pass
on Python exporter determinism, comparator logic, schema). Actual
Pine↔Python event diff on real data has never been performed — there
is no Pine-captured CSV in `tests/fixtures/pine-parity/`. As of
2026-08-31 the label was corrected to `parity-tooling-complete`.

This plan executes the missing half: capture real Pine output, diff it
against the Python reference, fix any mismatches found, and (only then)
upgrade the label back to `parity-achieved`.

## Goal

Produce **one committed Pine capture** that diffs clean against the
Python reference for `FXPRO:EURUSD` M15 (or equivalent frozen window),
with all mismatches either fixed or documented as accepted deviations.

## Non-goals

- Multi-pair parity (XAUUSD, BTCUSD) — defer until EURUSD is clean.
- Multi-timeframe parity (H1, H4) — defer.
- Pine code refactor for performance — separate concern.
- Capturing more than one window — one clean capture is enough to
  upgrade the label; more captures can come later as regression guards.

## Prerequisites

- TradingView Premium account (Bar Replay is gated behind paid tier).
- Browser pointed at TradingView with the Pine indicator loaded.
- Local checkout of `smc-ftmo` on `master` with `pytest 15/15` green.
- ~2-3 hours of focused time, no rush.

## Phase 1 — Pick a frozen window (15 min)

Goal: choose a 200-500 bar window that exercises the engine end-to-end
without being so long that Bar-Replay becomes painful.

1. Open `data/eurusd_m15.parquet` and pick a contiguous slice that has
   at least:
   - 1 BOS event
   - 1 CHoCH event
   - 1 OB activation + first touch
   - 1 sweep (clean, wick ≥ 0.25×ATR + reclaim)
   - 1 FVG formation + fill
   - 1 displacement candle (range > 1.5×ATR)
2. Suggested start: search for a window with ≥3 BOS over ~300 bars.
   A good pragmatic choice: any 7 trading-day window in 2024 with
   normal volatility (not a holiday gap, not an NFP storm).
3. Write down the ISO window bounds (start inclusive, end inclusive,
   NY-local time so the Pine session filter matches).

## Phase 2 — Generate Python reference (5 min)

Goal: produce a CSV with all the per-bar state, events, and diagnostics
the Python engine emits for the chosen window.

1. Make sure `data/eurusd_m15.parquet` covers the chosen window. If
   not, export from `histdata/DAT_ASCII_EURUSD_M1_*.csv` via
   `scripts/format_histdata.py` (already part of the repo).
2. Run:
   ```
   .venv/bin/python scripts/capture-frozen-feed.py \
     --input data/eurusd_m15.parquet \
     --dataset fxpro-eurusd-m15 \
     --symbol "FXPRO:EURUSD" \
     --feed FXPRO \
     --timeframe M15 \
     --timezone "America/New_York" \
     --session "America/New_York" \
     --window-start <iso-start> \
     --window-end <iso-end> \
     --out-dir tests/fixtures/pine-parity/<run-id>/
   ```
3. Verify the bundle contains 4 files:
   - `<dataset>-ohlc.csv` (normalized OHLC)
   - `<dataset>-python-reference.csv` (51 columns of engine output)
   - `<dataset>-pine-output.csv` (header-only placeholder)
   - `<dataset>-metadata.json` (settings + SHA-256 of OHLC + counts)
4. Confirm `metadata.python_event_count > 0` and that `python_modules`
   includes `swings`, `structure`, `displacement`, `sweeps`,
   `order_block`, `fvg`, `liquidity_pool` (Gate A + B both).

## Phase 3 — Capture Pine output via Bar Replay (60-90 min)

Goal: dump every per-bar state, event, and diagnostic the Pine
indicator emits into the same canonical CSV shape.

1. In TradingView, open `FXPRO:EURUSD` chart at M15 timeframe.
2. Add the `smc-engine-indicator.pine` indicator with default inputs
   (Rulebook 8W profile, Decision preset).
3. Open Bar Replay, set the start bar to the chosen window start.
4. Pin the indicator settings — do NOT change them mid-replay. The
   settings used MUST match `metadata["settings"]` in the bundle.
5. Step through every bar (or set replay speed to maximum and wait).
   The indicator emits `alertcondition` events for each BOS / CHoCH /
   OB-activated / sweep / pool / chart-qualified / watch / blocked.
6. Export Pine outputs to CSV. Two viable paths:

   **Path A (preferred): Pine Logs**
   - Open Pine Logs (View → Pine Logs in the Editor).
   - Filter for the indicator name and the replay timeframe.
   - Each log line is JSON-ish; write a one-off Python parser that
     maps `log.info("SMC ...")` lines into the canonical 51-column
     schema. Output goes to `<dataset>-pine-output.csv`.

   **Path B (fallback): Manual entry**
   - Walk the replay visually, transcribe each event into the
     placeholder CSV manually. Painful but works for short windows.
7. Validate the Pine CSV has the same 51 columns and key column
   combinations as the Python reference (use `KEY_COLUMNS` constant
   in `scripts/compare-pine-parity.py` as the schema source of truth).

## Phase 4 — Diff and triage (30 min)

Goal: classify every mismatch as fix-now / fix-later / accepted.

1. Run:
   ```
   .venv/bin/python scripts/compare-pine-parity.py \
     --python-reference tests/fixtures/pine-parity/<run-id>/<dataset>-python-reference.csv \
     --pine-output tests/fixtures/pine-parity/<run-id>/<dataset>-pine-output.csv \
     --json --max-examples 50
   ```
2. The summary prints `matches=False` plus counts of:
   - `missing_rows` — keys present in Python but not Pine.
   - `extra_rows` — keys present in Pine but not Python.
   - `value_mismatches` — same key, different value beyond `1e-9`.
3. For each mismatch category, classify:

   | Class | Action |
   |---|---|
   | Missing row | Pine didn't fire when Python did. Check Pine gate logic, FVG/sweep thresholds, OB lookback. |
   | Extra row | Pine fired when Python didn't. Check Pine `barstate.isconfirmed` semantics, OB re-activation, sweep double-counts. |
   | Value mismatch | Float drift. Check ATR warmup, rounding, EMA seed values. Most are 1-2 ULP — bump `--abs-tol` if justified. |

4. Document each triage decision in `tests/fixtures/pine-parity/<run-id>/NOTES.md`:
   - Mismatch category + count
   - Root cause hypothesis (line number in Pine or Python)
   - Fix action: open issue / commit fix / accept with justification

## Phase 5 — Fix or accept (60-90 min)

Goal: resolve fix-now mismatches so `matches=True`.

For each Pine-vs-Python mismatch:

1. **Reproduce in isolation.** Use the smaller synthetic fixture in
   `tests/fixtures/pine-parity/synthetic-ohlc.csv` to bisect.
2. **Diagnose.** Read both implementations side-by-side for the
   specific event type (BOS, sweep, OB, FVG, pool). Common root
   causes:
   - Pine `barstate.isconfirmed` vs Python `confirmed_bar_only`.
   - Pine `ta.barssince` edge cases vs Python list search.
   - Pine `request.security` lookahead semantics vs Python shift-by-1.
   - ATR warmup (Pine `ta.atr` vs Python EMA seed).
   - Displacement threshold units (Pine uses `ta.atr` directly,
     Python uses cached ATR — drift over time).
3. **Fix.** Apply the smallest change that closes the gap. Add a
   parity test that asserts the fix on the synthetic fixture so it
   doesn't regress.
4. **Re-run.** Repeat Phase 4 until `matches=True` or all remaining
   mismatches are documented and accepted.

If after 90 minutes there are still mismatches you can't fix, ship what
you have — partial parity with documented accepted mismatches is
strictly better than the current "tooling only" state.

## Phase 6 — Commit + bump parity status (15 min)

Goal: lock the capture in git and upgrade the label.

1. Commit the bundle:
   ```
   git add tests/fixtures/pine-parity/<run-id>/
   git commit -m "test(parity): capture real Pine↔Python diff for FXPRO:EURUSD M15

   First real TradingView Bar Replay capture. <N> events, <M> mismatches.
   All mismatches either fixed or documented in NOTES.md."
   ```
2. If `matches=True`, edit `docs/smc-engine-verification.md`:
   - Bump version v1.3 → v1.4
   - Change `pine-status: parity-tooling-complete` →
     `pine-status: parity-achieved`
   - Update the honest note to reflect the actual capture:
     ```
     > **Note (v1.4):** parity-achieved now backed by real diff at
     > tests/fixtures/pine-parity/<run-id>/. See NOTES.md for the
     > accepted-mismatches ledger.
     ```
3. If `matches=False` with accepted mismatches, keep
   `parity-achieved` but add a clear "with N documented deviations"
   suffix and link the NOTES file.
4. Re-run full test suite to confirm no regression:
   ```
   .venv/bin/pytest -q
   ```

## Acceptance criteria

- [ ] Phase 2 produces a 4-file bundle under
      `tests/fixtures/pine-parity/<run-id>/`
- [ ] Phase 4 diff summary is committed as `NOTES.md`
- [ ] Either `matches=True` OR all mismatches documented with rationale
- [ ] Parity test added for any fix (`tests/test_pine_parity_tools.py`)
- [ ] `pine-status` upgraded honestly to reflect the new state
- [ ] Full pytest suite still green

## Risks

- **TradingView Bar Replay time.** 200 bars × variable seconds = 30-60
  minutes of waiting. Budget accordingly.
- **Pine Logs format drift.** TradingView may change how `log.info`
  lines render. If the parser breaks, fall back to Path B (manual).
- **Float tolerance creep.** Don't accept `--abs-tol=1e-3` to silence
  real bugs. Document per-column tolerances in NOTES.md instead.
- **Pine can't see into the future, Python can (look-ahead).** If
  diffs show extra Python events at the last bar of the window, the
  window likely needs to end one bar earlier.

## Out of scope (deferred)

- Multi-pair parity (XAUUSD, BTCUSD).
- Multi-timeframe parity (H1, H4, D).
- Pine code performance optimization.
- More than one capture window per release.
- Automated nightly parity diff (could be a future plan once the
  workflow is proven).

## Files this plan touches

- `tests/fixtures/pine-parity/<run-id>/*.csv` (new bundle)
- `tests/fixtures/pine-parity/<run-id>/*-metadata.json` (new)
- `tests/fixtures/pine-parity/<run-id>/NOTES.md` (new)
- `tests/test_pine_parity_tools.py` (extended if any fix needs a test)
- `docs/smc-engine-verification.md` (label + honest note update)
- `tradingview/smc-engine-indicator.pine` (only if fix-now required)
- `packages/smc_engine/src/smc_engine/*.py` (only if fix-now required)

## Verification

After commit:
```
.venv/bin/pytest -q tests/test_pine_parity_tools.py   # 15+ pass
.venv/bin/pytest -q                                    # full suite green
grep pine-status docs/smc-engine-verification.md      # reflects new state
```