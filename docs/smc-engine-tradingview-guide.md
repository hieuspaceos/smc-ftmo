---
status: active
title: "SMC Engine TradingView Guide"
created: "2026-08-29"
updated: "2026-08-30"
version: "v1.2"
---

# SMC Engine TradingView Guide

This guide covers the private Pine v6 indicator that ports the Python SMC
engine. The indicator ships two profiles and four display presets, and it
targets parity on the same `FXPRO:EURUSD` M15 feed the Python engine was
tuned on.

## 1. Add The Indicator To TradingView

1. Open TradingView Pine Editor.
2. Paste the contents of `tradingview/smc-engine-indicator.pine`.
3. Save and add to chart. Default symbol: `FXPRO:EURUSD`, timeframe `M15`.
4. Confirm the chart-timeframe is on `M15`; the indicator is locked to
   that timeframe for Rulebook semantics.

## 2. Profiles

| Profile | Purpose | Default |
|---|---|---|
| `Rulebook 8W` | Decision assistant. Compact view, default `Decision` preset. | yes |
| `Engine Audit` | Parity and rejection inspection. All overlays available. | no |

Switch with the `Profile` input under the `Profile` group.

## 3. Display Presets (Rulebook Profile)

Precedence is fixed: `Decision` is the read-only default; `Context` adds
bounded FVG, sweep, and pool context; `Debug` adds raw swings, displacement,
and rejection reasons; `Custom` honors the individual toggles under
`Display > Custom: …`.

| `Decision` | Structure (BOS / CHoCH), selected fresh OB, current bias, H4 P/D, Rulebook state, entry/SL/TP |
| `Context` | Everything in `Decision` + bounded FVG, sweep, pool context (when toggled) |
| `Debug` | Force-on all overlays: swings + step lines + sweeps + FVGs + pools + displacement |
| `Custom` | Whatever the Custom toggles enable |

Raw swings, step lines, equilibrium, sweeps, and EQH/EQL pools are hidden by
default in the Decision / Context presets to keep the chart clean. Use
`Engine Audit` profile or `Debug` preset for parity verification. The
TradingView built-in `Visible Range Volume Profile` is recommended for
visual structure (POC, Value Area) alongside this indicator.


## 4. Rulebook Manual Gates

The Rulebook 8W selector is **never** green-actionable when any of these is
unknown. Default to `false`; flip them on only when the trader has actually
acknowledged them on the live trading day.

| Gate | Meaning |
|---|---|
| `Risk 0.55% acknowledged` | Today's risk budget has been sized |
| `Trades today left` | Open slots remaining toward the 3-trade cap |
| `Daily loss -2R acknowledged` | Daily drawdown budget is not yet breached |
| `No open position` | No carry-over exposure on the symbol |
| `Spread/news clean` | Manual filter is clear |
| `Trader judgment clear` | Human go/no-go is on |

The state cell in the context table reports `chart-qualified` only when
all six gates are `true`. Partial acknowledgement surfaces as `watch`;
any `false` with intent surfaces as `blocked`.

## 5. Deterministic Candidate Pipeline

The selector runs in this fixed order on every confirmed bar:

1. linked BOS provenance (OB is BOS-driven)
2. direction matches strict bias (`1 == structureTrend` or `-1 == structureTrend`)
3. active and first-test eligible (OB has not been touched yet)
4. no later CHoCH on the OB's side after the linked BOS
5. proximity to entry within `1.5 ATR` (configurable)
6. SL edge at `±0.2 ATR`, total SL distance `<= 1.2 ATR` (configurable)
7. nearest HTF wall does not touch the 2R target
8. score `>= 4` with displacement + bias + first-test mandatory
9. most recent qualifying activation
10. nearest edge
11. lowest OB id

If a candidate fails any gate, the rejection reason is written to the
`Reject` cell of the context table and the linked OB/BOS ids are kept so
the user can investigate.

## 6. Visual Policy

Decision view caps: `<= 24` structure labels, `<= 8` OB boxes, `<= 8` FVG,
`<= 12` liquidity or sweep objects. The script uses explicit
`box.delete` / `label.delete` plus bounded queues; no garbage collection
is relied on. Pine declaration caps stay under lines `200` / boxes `150`
/ labels `200`. Internal working caps are `160` / `120` / `160`.
Plot count target is `<= 48`. Unique request contexts are `<= 8`.

## 7. HTF (D / H4) Requests

The indicator requests Daily and H4 values with the
`barmerge.lookahead_on` + `[1]` offset pattern. Values are confirmed-only
and never repaint on reload. H4 P/D is used for premium/discount
classification when `Use H4 HTF` is on. The Daily wall is part of the
nearest-HTF gate.

## 8. Session Filter

Only London (08:00-16:00 exchange local) and New York (13:00-21:00) are
allowed. The first 15 minutes of London are excluded to skip the
opening-range noise.

## 9. Alerts

Create alerts manually in TradingView. The dynamic payload is:

```
SMC|v1|event=<event>|symbol=<ticker>|tf=<interval>|dir=<dir>|level=<mintick>|bar_time=<epoch>|ob_id=<id>|bos_id=<id>|state=<state>|reason=<code>
```

Alerts cover:

- `SMC BOS` and `SMC CHoCH` on confirmed close
- `SMC OB activated` on BOS-driven OB activation
- `SMC sweep` and `SMC pool event` on first-touch
- `SMC chart-qualified` / `SMC watch` / `SMC blocked` on state transitions

Alerts are deduped by the linked event id (synthetic BOS key, OB id, etc.)
so a refresh does not re-fire finalized events.

## 10. Limitations

- Chart-timeframe event parity only. Lower-timeframe reconstruction from
  intrabars is out of scope.
- Public-script publication is blocked until source / license review.
- The Rulebook profile does not include breaker, body-mode, or regime
  behavior (deferred per locked plan decision).

## 11. Verification Procedure

1. Run the parity tooling on the synthetic fixture:
   ```
   .venv/bin/python -m pytest -q tests/test_pine_parity_tools.py
   ```
2. Capture a frozen `FXPRO:EURUSD` M15 window:
   ```
   .venv/bin/python scripts/capture-frozen-feed.py \
     --input <ohlc.csv> --dataset fxpro-eurusd-m15 \
     --symbol "FXPRO:EURUSD" --feed FXPRO --timeframe M15 \
     --timezone "America/New_York" --session "America/New_York" \
     --window-start <iso> --window-end <iso> \
     --out-dir <bundle-dir>
   ```
3. Export the same window from the Pine indicator (Bar Replay or Pine
   Logs) into the same canonical shape and diff with `compare-pine-parity.py`.
4. Record event counts, mismatches, and any feed or timezone drift.
5. Bar Replay the same window end-to-end and confirm no finalized event
   moves.
6. Re-run the full Python suite to confirm no engine regression.
