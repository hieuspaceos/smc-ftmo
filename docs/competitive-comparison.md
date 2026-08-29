---
status: research
title: "Indicator Comparison: Private vs. Premium TradingView SMC"
created: "2026-08-29"
updated: "2026-08-29"
---

# Indicator Comparison: Private vs. Premium TradingView SMC

This document compares `tradingview/smc-engine-indicator.pine` against
the typical premium SMC indicator category on TradingView. It is honest
about gaps and does not claim specific products were audited — the
comparison is by feature category, not by named competitor.

## Methodology

- The "private" column describes what the in-repo indicator does today.
- The "premium category" column describes the **typical** feature set
  found in paid SMC indicators on TradingView, based on public
  documentation and marketplace listings (LuxAlgo, AlgoAlpha,
  TrendSpider Signals, PineIndicators SMC, etc.).
- The "gap" column flags a real shortfall in the private indicator.
  "Match" means the private indicator is at parity for that feature.
  "Advantage" means the private indicator does something better or
  does not rely on the typical paid-only feature.
- Specific products may differ. Use §5 to do a name-by-name check.

## 1. Causal engine coverage

| Module | Private | Premium category | Gap |
|---|---|---|---|
| Manual True Range + SMA ATR(14) | yes | yes | match |
| Symmetric fractal swings (L=R=5) | yes | yes | match |
| BOS / CHoCH via close (no wick) | yes | yes | match |
| Displacement `range > 1.5× ATR` strict | yes | yes | match |
| BOS-only OB activation | yes | yes | match |
| OB invalidation by close through edge | yes | yes | match |
| First-touch once | yes | yes | match |
| OB lookback 20, expiry 200, cap 128 | yes | yes | match |
| 3-candle FVG | yes | yes | match |
| Liquidity pools EQH/EQL | yes | yes | match |
| HTF D/H4 structure via `request.security` | yes | yes | match |
| HTF D/H4 P/D + EQH/EQL wall | yes | yes | match |
| Lower-timeframe reconstruction (LTF) | no | yes (some) | gap |
| Multi-symbol on one chart | no | yes | gap |
| Auto breaker (regime=on) | no (deliberate) | yes | match by design |
| Body-mode OB | no (deliberate) | yes | match by design |
| Regime classifier | no (deliberate) | yes | match by design |

The private indicator is **at parity** for the 7 baseline + 1
extension modules the plan commits to. The three "deliberate" matches
are intentional per the locked plan decision: 8 weeks EURUSD only, no
breaker, no body-mode.

## 2. Rulebook / signal layer

| Feature | Private | Premium category | Gap |
|---|---|---|---|
| Deterministic candidate selector (gates) | yes (11 gates) | yes (varies) | match |
| Score formula documented | yes (rule book §13) | varies | advantage |
| Manual gate state | yes (6 inputs) | varies | match |
| Chart-qualified / watch / blocked states | yes | yes | match |
| 2R target | yes (configurable) | yes | match |
| HTF wall check (D/H4 swings + EQH/EQL) | yes | varies | match |
| Sweep clean threshold (0.25× ATR) | yes | varies | match |
| Auto-trade via webhook to broker | no | yes (some) | gap |
| Strategy tester integration | no | yes (some) | gap |

## 3. UX / display

| Feature | Private | Premium category | Gap |
|---|---|---|---|
| Multiple display presets | yes (Decision/Context/Debug/Custom) | yes | match |
| Profile switcher (Rulebook 8W vs Engine Audit) | yes | varies | match |
| Audit-mode raw overlays (swings, FVG, sweeps) | yes (audit only) | yes | match |
| Visual on-chart trade levels (entry/SL/TP) | yes (text in table only) | yes (lines on chart) | gap |
| Heatmap / footprint | no | yes (some) | gap |
| Multi-timeframe panel layout | no (uses 1 chart + HTF text) | yes (some) | gap |
| Color-blind palette | not audited | usually yes | gap |
| Mobile portrait layout | not audited | varies | unknown |
| Dark / light tested | not audited | yes (premium) | unknown |

## 4. Alerts and automation

| Feature | Private | Premium category | Gap |
|---|---|---|---|
| `alertcondition` declarations | yes (8) | yes | match |
| Dynamic payload schema | yes (`SMC\|v1\|event=…`) | varies | match |
| One-shot dedup by linked event id | yes (manual via id) | yes | match |
| Webhook / bot integration | no (TradingView built-in only) | yes (some) | gap |
| JSON API for backtest | no | varies | gap |
| Alert firing on watch/block transitions | yes | varies | match |

## 5. Backtest and analytics

| Feature | Private | Premium category | Gap |
|---|---|---|---|
| Bar Replay safe | yes (no repaint) | yes | match |
| Profiler under limits | not measured | yes (premium has them measured) | unknown |
| Equity curve on chart | no | yes (some) | gap |
| Win-rate / PF / drawdown panel | no | yes (some) | gap |
| Trade journal export | no (Pine Logs only) | yes (some) | gap |
| Native Pine strategy (`strategy.entry`) | no (indicator only) | yes (some) | gap |

## 6. Documentation and verification

| Feature | Private | Premium category | Gap |
|---|---|---|---|
| User guide | yes (`smc-engine-tradingview-guide.md`) | yes | match |
| Rule book → code mapping | yes (`rulebook-pine-mapping.md`) | rarely public | advantage |
| Manual verification checklist | yes (`rulebook-verification-checklist.md`) | rarely public | advantage |
| Parity test suite | yes (15 tests) | internal | match |
| Synthetic fixture | yes | varies | match |
| Frozen FXPRO EURUSD M15 round-trip | CLI ready, not yet captured | n/a | gap (data) |
| Public release | no (private indicator) | yes (some) | match by design |

## 7. Honest verdict

**Where the private indicator is competitive today**
- Causal engine parity for the 7+1 modules the plan commits to.
- Rule book alignment with documented gates and a verified test
  suite. Most premium SMC indicators do not publish a rule-book →
  gate mapping.
- Display preset hierarchy (Decision/Context/Debug/Custom) with
  profile separation (Rulebook 8W vs Engine Audit). This is on par
  with the best in the category.
- Pine Logs at 4 known events (`dual_break`, `skip_ob_no_expansion`,
  `rulebook_reject`, `pool_activated`) help the trader debug without
  a separate Profiler session.

**Where the private indicator is behind the premium category**
- **No LTF reconstruction** (e.g. M1 inside M15). Premium products
  often render M1 structure inside an M15 chart.
- **No multi-symbol dashboard** (e.g. EURUSD + GBPUSD + XAUUSD on
  one chart). The category typically has this.
- **No strategy tester integration** (no `strategy.entry` calls).
  Premium products that target automated trading ship a strategy
  variant of the indicator.
- **No webhook / bot integration**. The alert payload is
  machine-readable but the indicator does not push to a third-party
  service.
- **No on-chart trade levels** (entry/SL/TP lines drawn on price).
  Premium products usually draw these as soon as a candidate is
  selected. The private indicator surfaces the same numbers in the
  context table only.
- **No equity curve / journal export**. The trader has to keep their
  own journal for the 8 weeks.
- **Visual QA not done on TradingView**. We do not have a
  documented Profiler pass on a real EURUSD M15 window.

**What is intentionally not in the private indicator**
- Breaker blocks: out of scope per the locked plan. The Rulebook
  8W profile will never enable them.
- Body-mode OB: out of scope per the locked plan.
- Regime classifier: out of scope per the locked plan.
- Public TradingView release: not planned. The script is private.

## 8. Decision matrix

Pick the private indicator if:
- You want the exact same causal semantics as the Python engine.
- You accept "EURUSD M15 only, 8 weeks, no breaker, no body-mode" as
  the operating envelope.
- You want a documented rule book that the indicator obeys, not a
  black box.
- You are willing to do Bar Replay verification once before going
  live.
- You are willing to manage your own trade journal.

Stay on a paid indicator if:
- You trade multiple pairs on multiple timeframes on one chart.
- You want auto-trade via webhook.
- You want built-in equity curve and journal export.
- You want a strategy variant that runs in TradingView Strategy
  Tester.
- You trade XAUUSD, BTCUSD, or US100 — none of which the private
  indicator is tuned for.

## 9. Steps to close the worst gaps (if you decide to)

| Gap | Effort | Suggested scope |
|---|---|---|
| On-chart entry/SL/TP lines | low | Draw a `line.new` for each selected candidate. Same data, better UX. |
| LTF reconstruction | high | Out of plan v1; would need its own phase. |
| Multi-symbol | medium | Use `request.security` on the same chart with `tickerid`. Add per-symbol table. |
| Strategy tester variant | medium | Add a sibling script with `strategy(...)` declarations. |
| Webhook | low | Add `alert()` calls alongside `alertcondition`. |
| Equity curve on chart | medium | Track closed trades in arrays, plot cumulative R. |
| Visual QA | low (effort) / medium (TradingView account required) | Run the checklist in `rulebook-verification-checklist.md`. |
