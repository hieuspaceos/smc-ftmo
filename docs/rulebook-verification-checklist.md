---
status: active
title: "Rule Book Verification Checklist (TradingView manual pass)"
created: "2026-08-29"
updated: "2026-08-29"
---

# Rule Book Verification Checklist (TradingView manual pass)

Use this checklist after pasting `tradingview/smc-engine-indicator.pine`
into the Pine Editor. It maps each rule book section to a manual check
that can be done in a TradingView chart session. Every step is paired
with the Python parity test that already pins the same behavior.

**Before you start**

1. Open TradingView Pine Editor.
2. Paste the contents of `tradingview/smc-engine-indicator.pine`.
3. Save and Add to chart.
4. Set the chart to `FXPRO:EURUSD` M15.
5. Set the chart timezone to `America/New_York` (critical for §14).
6. Open the **Pine Logs** panel (Editor → Pine Logs) so you can see
   `log.warning` / `log.info` from the script.
7. Open the **TradingView Profiler** (Editor → Profiler) to capture
   execution time and object counts.

Use the **Decision** display preset (default) for the cleanest view, then
flip to **Context** / **Debug** when you need to inspect individual
overlays.

---

## §0 Setup freeze

- [ ] Inputs match the frozen values: `Swing left/right = 5`, `ATR period
      = 14`, `Displacement ATR = 1.5`, `Sweep wick buffer ATR = 0.05`,
      `OB lookback = 20`, `OB expiry bars = 200`, `OB cap per side = 128`,
      `FVG expiry bars = 200`, `FVG cap per side = 128`,
      `Pool tolerance ATR = 0.15`, `Pool min members = 2`,
      `Rulebook score threshold = 4`, `Rulebook clean sweep ATR = 0.25`,
      `Entry proximity ATR = 1.5`, `SL edge buffer ATR = 0.2`,
      `Max SL distance ATR = 1.2`, `Minimum 2R target = 2`.
- [ ] Profile input = `Rulebook 8W`, display preset = `Decision`.
- [ ] Pine Logs shows no syntax errors after Save.

## §1 Account & Risk

- [ ] Manual gates all default to `false` / 0. The state cell in the
      context table reads `watch` (because gates unknown) or
      `no-signal` (no qualifying OB) for every bar.
- [ ] Set every manual gate to `true` / 3. State cell flips to
      `chart-qualified` only for bars that pass the 11-gate pipeline.
- [ ] Confirm: even with all manual gates `true`, a chart-qualified bar
      only happens when all 8 other gates pass — manual gates do not
      override a rejection from Gate 1–9.

## §2 Reading order

- [ ] Walk down the chart from Daily → H4 → M15.
- [ ] On the **Engine Audit** profile with `Use Daily HTF` and
      `Use H4 HTF` enabled, the request.security expressions fire on
      confirmed bars. Reload the chart and verify the daily and H4
      values do not repaint.

## §3 Mandatory setup

- [ ] Pick a bar with a confirmed BOS on M15. Verify the context
      table `Bias` cell shows the matching direction (`bull` or
      `bear`).
- [ ] Verify the table `State` cell shows `chart-qualified` only if
      the underlying OB is BOS-driven, undisplaced nearby, and
      untouched.

## §4 Bias strict — manual check

The hardest rule to verify visually. Use the following procedure:

1. Set the chart to a 4-hour window where D trend and H4 trend visibly
   disagree. For example, D is bull but H4 has just printed a
   bear CHoCH.
2. Confirm the indicator is on `Rulebook 8W` profile with HTF inputs
   enabled.
3. Look at any bullish OB that activates while H4 is bear.
4. The state cell **must not** become `chart-qualified` for that OB.
5. The Pine Logs should not show the candidate's selection because
   Gate 2 short-circuits before any score computation.

Compare with `tests/test_pine_parity_tools.py::TestRulebookGaps::test_bias_strict_requires_d_and_h4_alignment`.

## §5 Structure: BOS vs CHoCH

- [ ] Find a bar where the engine prints `CHoCH↑` or `CHoCH↓`. Verify
      **no** order block zone appears in the bar window immediately
      after the CHoCH (only BOS creates OBs).
- [ ] After the CHoCH, walk forward: any older OB on the same side
      must be ignored by the candidate pipeline (Gate 4).

## §6 Order block

- [ ] Bullish OB box top/bottom = origin candle `[low, high]`. Hover
      the OB to verify, then compare with a chart drawing tool.
- [ ] Wick into the zone = first touch (zone gets dimmed but stays
      alive). A subsequent close **beyond** the opposite edge = OB
      invalidated (zone fully grayed out).
- [ ] SL buffer on a fresh OB: long SL = `ob_bottom - 0.2× ATR(M15)`,
      short SL = `ob_top + 0.2× ATR(M15)`. Verify with the
      `Entry/SL/TP` cell in the context table.
- [ ] Walk the price far from the OB (> 1.5× ATR). The candidate
      should not become `chart-qualified` even if other gates pass.
- [ ] Find a fat OB (SL distance > 1.2× ATR). Even with bias aligned,
      the state cell must stay `no-signal` (Gate 6 freeze).

## §7 Displacement

- [ ] On any BOS bar, check the Pine Logs: if `(high-low) <= 1.5× ATR`
      the line `SMC skip_ob_no_expansion @ <bar_index> range_atr=<…>`
      must be present.
- [ ] On a bar with displacement, the `Score` cell in the context
      table should be at least 1 (the mandatory displacement point).

## §8 Sweep clean

This is the most common source of "Pine vẽ sweep nhưng Rulebook không
tính điểm" confusion.

- [ ] Find a bar with a sweep. The Pine Logs show
      `SMC skip_ob_no_expansion` or just a normal sweep event. Either
      way, the **score** only credits sweep when wick ≥ 0.25× ATR.
- [ ] Compare two sweeps back-to-back:
      1. First sweep: wick 0.10× ATR (clean fail per rule book).
         Context table `Score` cell stays at 3 (disp + bias + first-test
         only, no sweep bonus).
      2. Second sweep: wick 0.30× ATR (clean). Context table `Score`
         cell shows 4.
- [ ] When `Score` = 3 and the candidate is otherwise perfect, the
      state cell must read `no-signal` because the threshold is 4
      and no P/D bonus is available either.

## §9 FVG

- [ ] FVG boxes are visible only on `Engine Audit` profile. On the
      Rulebook profile, default Decision view, FVGs are hidden.
- [ ] Verify FVG is not used as an entry trigger anywhere. The score
      formula does not credit FVG.

## §10 Premium / Discount

- [ ] On the H4 dealing range visible in the chart, the context
      table's `P/D` cell should read `premium` when close is above the
      H4 midpoint, `discount` when below, `neutral` when H4 is
      unavailable.
- [ ] Disable `Use H4 HTF`. The P/D cell falls back to the chart-time
      swing range. Verify the fallback value differs from the H4
      value.

## §11 Liquidity pools

- [ ] Find a bar where two swing highs are within 0.15× ATR. The
      Pine Logs should show `SMC pool_activated @ <bar> side=high
      level=<…> members=<idA|idB>`.
- [ ] When a third member joins, the Pine Logs do **not** fire
      again (activation is one-shot).
- [ ] When price sweeps the EQH (high > level_max && close < level_max),
      the box repaints to gray. Pine Logs do not log this (it is
      already covered by the existing sweep event log).

## §12 Breaker

- [ ] On Rulebook profile, there should be no breaker overlay, no
      breaker alert, no breaker reference in the context table.
- [ ] Switch to `Engine Audit` profile. Breaker behavior is still
      off in the indicator code (out of scope for v1).

## §13 Confluence score

- [ ] Find a `chart-qualified` bar. Hover the OB and verify the
      `Score` cell in the context table. The score must be exactly
      one of {3, 4, 5}, never 2 or 6.
- [ ] Toggle the `Rulebook score threshold` input to 5. The
      `chart-qualified` state should disappear for any bar that
      scored 4 with a single bonus.

## §14 Session filter

This is timezone-sensitive. Before testing:

- [ ] Set the chart timezone to `America/New_York` (not exchange).
- [ ] Walk to a bar that prints at exactly 02:00, 02:14, 02:15, 05:00,
      07:00, 10:00 EST.
- [ ] For each boundary, verify the state cell and Pine Logs.
- [ ] At 02:00–02:14 EST: even with all other gates green, the state
      must NOT be `chart-qualified`. The Pine Logs may show
      `SMC rulebook_reject @ <bar> reason=…`.

Compare with
`tests/test_pine_parity_tools.py::TestRulebookGaps::test_session_helper_matches_rule_book_windows`.

## §15 Pairs & timeframes

- [ ] Switch the symbol to `XAUUSD` and timeframe to M15. The
      indicator should still compile and run, but the Rulebook
      profile's manual trade decision should stay
      `no-signal` / `watch` (the indicator does not lock the
      symbol; that is the trader's responsibility per rule book).
- [ ] Switch to H1. The chart-timeframe OB detection should run on
      H1 swings (with `Swing left/right` still 5). HTF requests will
      shift to H4 / D1.

---

## Profiler / object count check

After verifying the rules above, capture Profiler numbers and confirm:

- [ ] Plot count ≤ 48
- [ ] Unique request contexts ≤ 8
- [ ] Total runtime per bar < 50 ms on a typical EURUSD M15 bar
- [ ] No "execution limit" warnings in Pine Logs

If any limit is hit, reduce the `Recent label budget` /
`Recent box budget` inputs first; do not disable the causal core.

## Replay verification

For Bar Replay, replay the same 4-hour window three times and verify
that the same OB and same `Score` value appear at the same bar index
every time. Finalized events must not move on reload.

## Alert sanity

- [ ] Set up a TradingView alert on `SMC BOS` and `SMC CHoCH`
      conditions. Trigger Bar Replay and confirm the alert payload
      starts with `SMC|v1|event=bos|...` or `SMC|v1|event=choch|...`.
- [ ] Confirm a `chart-qualified` transition fires the
      `SMC chart-qualified` alert exactly once (no duplicates on
      subsequent bars unless the state toggles).
- [ ] Confirm an alert fires only on confirmed close. Right-click
      the alert in the list and verify the bar time matches the
      confirmed close, not the live tick.

## Sign-off

When every box above is checked and the parity tests in
`tests/test_pine_parity_tools.py::TestRulebookGaps` are all green, the
indicator is verified against the rule book for the 4-hour window you
replayed. Repeat this checklist on a different window (different day,
different session) at least once before going live.
