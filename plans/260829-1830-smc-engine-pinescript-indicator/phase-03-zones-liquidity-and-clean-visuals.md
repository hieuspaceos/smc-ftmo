# Phase 03: Rulebook Selector + Visual Policy

## Context

- [Plan](./plan.md)
- Depends on [Phase 02](./phase-02-causal-structure-core.md)

## Goal

Turn the baseline core into a deterministic Rulebook 8W assistant with a
readable chart policy and a separate Engine Audit profile.

## Requirements

- Product profiles are `Rulebook 8W` (default) and `Engine Audit`.
- Display presets inside those profiles are `Decision`, `Context`, `Debug`, and `Custom`.
- Display-preset precedence is fixed; only `Custom` respects individual toggles.
- `Decision` is the default Rulebook view.
- `Engine Audit` is a secondary profile for parity and rejection inspection.
- Rulebook default stays locked to EURUSD M15 only.
- Strict completed D+H4 structure bias is mandatory.
- H4 premium/discount is required for Rulebook scoring.
- Full-wick base OB is required.
- No breaker in Rulebook v1.
- Sweep overlay stays at `0.05`, but Rulebook score only credits directional clean sweep `>= 0.25`.
- Score `>= 4` requires displacement, bias, and first-test as mandatory gates, with P/D or sweep bonus.
- OB close invalidation, first-test only, and rejection after an intervening CHoCH are required.
- Reject OBs that are not aligned to the newer BOS after CHoCH.
- Entry must be within `1.5 ATR`; SL edge is `+/- 0.2 ATR` and total SL distance must be `<= 1.2 ATR`.
- 2R must not touch or cross the nearest confirmed D/H4 swing or EQH/EQL wall.
- London and New York sessions are allowed; the first 15 minutes of London are excluded.
- The indicator may show `chart-qualified`, `watch`, or `blocked`, but not a green actionable claim when manual gates are unknown.

## Deterministic Candidate Pipeline

The Rulebook selector must be deterministic:

1. linked BOS provenance
2. direction matches strict bias
3. active and first-test eligible
4. no later CHoCH before the entry decision
5. proximity to entry
6. SL width
7. nearest HTF wall check
8. score
9. most recent qualifying activation
10. nearest edge
11. OB id

Debug output must show rejection reason codes and linked OB/BOS ids.
Do not inherit current Python bugs: displacement-as-sweep, any-direction sweep,
M15 P/D, entry-bar displacement, or blindly choosing the last OB.

The HTF wall is the nearest confirmed level in the trade direction among D/H4
external swings and active D/H4 EQH/EQL pools. A 2R target that exactly touches
the wall fails. Entry UX is `WATCH` before touch and `CONFIRMED` only at the
confirmed close of the first-touch bar; neither state promises a historical
limit fill at the OB edge.

Manual status fields cover risk `0.55%`, trades today, daily R, existing
position, spread/news, and trader judgment. Missing or unknown manual fields
prevent an actionable/green state.

## Visual Policy

- `Decision` default shows compact D/H4 status, selected fresh OB, linked
  qualified BOS, current H4 P/D, entry/SL/TP reference, and rejection or
  manual-gate state.
- `Context` adds bounded FVG, sweep, and liquidity-pool context.
- `Debug` adds parity fields and rejection reasons.
- `Custom` unlocks individual toggles.
- Raw swings, displacement, FVG, sweeps, and EQH/EQL are off by default.
- Direction must not rely on color alone.
- Group inputs into `Quick Setup`, `Rulebook Status`, `Structure`, `Zones`,
  `Liquidity`, `Alerts`, `Style`, and `Diagnostics`.
- Fixed Rulebook inputs are read-only semantics and profile controls, not
  sliders.
- Rulebook score credits displacement from the selected OB's linked BOS, never
  coincidental displacement on the retest/entry bar.

## UI Gates

- 500-bar frozen EURUSD M15 window.
- Identify bias, selected OB, and state without settings.
- Maximums: `<= 24` structure labels, `<= 8` OB boxes, `Context <= 8` FVG and
  `<= 12` liquidity or sweep objects.
- Decision view `<= 50` drawings; Context `<= 80`.
- Pine declaration caps: lines `200`, boxes `150`, labels `200`; internal
  working caps stay `<= 160 / 120 / 160`.
- Plot count `<= 48`.
- Unique request contexts `<= 8`.
- Explicit deletes only; do not rely on garbage collection.
- Screenshots required at `1366x768`, `1440x900`, and mobile portrait in dark
  and light modes.
- Grayscale and color-blind users must still distinguish the states.
- No overlap or clipping.
- Candles remain visually strongest.
- Use `format.mintick`.
- Current Streamlit screenshots do not validate Pine UI because the Pine file
  does not exist yet.

## Implementation Steps

1. Define preset precedence and the read-only Rulebook inputs.
2. Implement the deterministic candidate pipeline and rejection codes.
3. Add the compact Decision view and bounded Context and Debug views.
4. Bound drawing counts and request contexts explicitly.
5. Add visual QA captures for dark/light desktop and mobile portrait.
6. Verify the Rulebook state labels and manual-gate states without settings access.

## Validation

- The default chart shows the chart-qualified, watch, or blocked state.
- The selected OB is the most recent qualifying activation under the pipeline.
- Rejection reasons point at linked OB and BOS ids.
- Raw overlays remain hidden unless the profile explicitly exposes them.
- No overlaps, clipping, or label spam appear in the frozen window.

## Completion Checklist

- [ ] Rulebook default is deterministic and locked to EURUSD M15.
- [ ] Profile precedence is working.
- [ ] Decision, Context, Debug, and Custom behave as specified.
- [ ] Object and plot budgets stay within limits.
- [ ] Screenshots are captured at the required sizes and modes.
- [ ] Manual-gate state is visible but not overclaimed.

## Risks and Rollback

- The main risk is visual clutter, not logic drift; reduce retained drawings instead of removing semantics.
- If the full Rulebook view is too heavy, keep the compact Decision view and defer non-essential context to Custom.
- Keep the selector separate from the causal core so parity debugging stays clean.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
