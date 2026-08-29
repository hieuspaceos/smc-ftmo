---
status: research
title: "Competitor Verification Checklist"
created: "2026-08-29"
updated: "2026-08-29"
---

# Competitor Verification Checklist

Use this to compare a named premium TradingView SMC indicator against
the in-repo private indicator. The questions are objective; the answer
for the private indicator is "yes / no / partial" and the source is the
matching gate or input in `tradingview/smc-engine-indicator.pine`.

The five named products below are widely cited. Verify on the
TradingView marketplace before relying on prices and exact feature
names.

## 1. LuxAlgo — "AI Backtesting & Signals" (SMC pack)

- [ ] Does the indicator compute BOS / CHoCH via close (not wick)?
      Compare with `Gate 1` in our pipeline.
- [ ] Does the OB activation require displacement (`range > 1.5× ATR`)
      in the same causal pass? Compare with `expansionNearBreak`.
- [ ] Does the indicator distinguish Rulebook clean sweep (0.25× ATR)
      from engine overlay sweep (0.05× ATR)? Compare with
      `rulebookCleanSweepAtr` input and `sweepBullClean` /
      `sweepBearClean`.
- [ ] Are manual gates surfaced as inputs (risk, daily loss, trades
      left, etc.)? Compare with the `Rulebook` group of inputs.
- [ ] Is there a published rule book → gate mapping? We have one
      (`docs/rulebook-pine-mapping.md`). LuxAlgo does not.

## 2. AlgoAlpha — "AlgoAlpha SMC"

- [ ] Does the indicator expose BOS / CHoCH / OB / FVG / EQH / EQL
      as separate modules? Compare with the module-like sections of
      the in-repo Pine file.
- [ ] Does the candidate selector produce a single OB id per bar
      with deterministic tie-breaks (recency, edge, id)? Compare
      with the candidate pipeline tie-break block.
- [ ] Are alerts deduplicated by linked event id? Compare with the
      `bosKey` pattern in the alert block.
- [ ] Does the indicator run on a synthetic fixture for testing?
      Compare with `tests/fixtures/pine-parity/synthetic-ohlc.csv`.

## 3. TrendSpider — "Smart Money Concepts"

- [ ] Does the indicator support `request.security` for D/H4 with
      confirmed-bar semantics? Compare with the
      `barmerge.lookahead_on` + `[1]` offset pattern.
- [ ] Does it gate Rulebook score on strict D+H4+M15 alignment (no
      neutral)? Compare with `Gate 2` in the candidate pipeline.
- [ ] Does it draw on-chart entry/SL/TP lines for the selected OB?
      We do not (gap). Note this as a feature parity gap.
- [ ] Is the score formula exposed and documented? Compare with
      `docs/rulebook-pine-mapping.md` §13.

## 4. PineIndicators — "SMC Pro"

- [ ] Does the indicator use manual True Range + SMA ATR(14) instead
      of `ta.atr()`? Compare with `trueRange` / `ta.sma` lines.
- [ ] Does the OB invalidation use close (not wick)? Compare with
      the OB lifecycle block.
- [ ] Is breaker / body-mode / regime behavior available? They
      should be toggles in their product. We deliberately omit them
      from the Rulebook 8W profile.
- [ ] Does the indicator carry out-of-the-box LTF reconstruction
      (M1 inside M15)? We do not. Note as feature gap.

## 5. TradingView built-in "SMC" indicator

- [ ] Compare defaults. Built-in typically uses L=5, R=5, but the
      ATR threshold, sweep buffer, OB expiry are not always
      user-configurable to the locked plan values.
- [ ] Does the built-in publish a score formula? No.
- [ ] Does the built-in apply a Rulebook-style strict bias gate?
      No, it surfaces raw structure events for the trader to
      interpret.

## Cross-cutting checks (apply to all 5)

- [ ] **Documentation depth**: do they publish a rule book → gate
      mapping like `docs/rulebook-pine-mapping.md`?
- [ ] **Verification artifact**: do they publish a synthetic
      fixture for parity testing? We do.
- [ ] **Parity test count**: do they publish a test suite that
      pins gate decisions? We do (15 parity tests + 160 SMC tests).
- [ ] **Manual verification checklist**: do they publish a
      step-by-step manual check like
      `docs/rulebook-verification-checklist.md`?
- [ ] **Frozen-feed round-trip**: do they publish a SHA-256
      checksum of the frozen feed they tuned on? We do (via
      `scripts/capture-frozen-feed.py`).
- [ ] **MTF anti-repaint**: do they explicitly use
      `barmerge.lookahead_on` + offset? We do.
- [ ] **Alert payload schema**: do they document the alert JSON
      shape? We do (`SMC|v1|event=…`).
- [ ] **Decision / Context / Debug / Custom preset hierarchy**: do
      they enforce a fixed precedence? We do.
- [ ] **Manual gate state surface**: do they expose 6 manual inputs
      and never claim `chart-qualified` when any is unknown? We do.

## Recording your comparison

For each named product, fill in:

```
Product: ____________________
Price tier: _________________
Notes on §1–§9 of competitive-comparison.md:
- engine parity: ____
- rulebook layer: ____
- ux: ____
- alerts: ____
- backtest: ____
- documentation: ____
- gaps that matter to me: ____
- gaps that do not matter to me: ____
Verdict: prefer this / prefer private / both
```

This forces an objective comparison instead of marketing-driven
anecdote. When you have filled in 3+ products, the pattern will tell
you whether the private indicator is competitive for your use case.
