# Phase 04: HTF, Alerts, and Verification

## Context

- [Plan](./plan.md)
- Depends on [Phase 03](./phase-03-zones-liquidity-and-clean-visuals.md)

## Goal

Finish the TradingView integration, prove the indicator against the frozen feed,
and package the runtime and UI evidence.

## Requirements

- D/H4 values use only completed bars.
- `request.security()` expressions use confirmed previous HTF values with the correct offset and `lookahead_on` pattern.
- Alerts cover confirmed-close events, one-shot and deduped linked event ids, candidate or watch states, first-touch-confirmed, chart-qualified, blocked or revoked, and BOS/CHoCH/OB or sweep debug events as appropriate.
- Alert conditions must not depend on whether a visual toggle is hidden.
- The alert payload must stay machine-readable and consistent.
- Dynamic payload schema is
  `SMC|v1|event=<event>|symbol=<ticker>|tf=<interval>|dir=<dir>|level=<mintick>|bar_time=<epoch>|ob_id=<id>|bos_id=<id>|state=<state>|reason=<code>`.
- TradingView alerts are created manually.
- Replay proves marker logic, not historical delivery.
- Do not promise a fill at the OB edge from a close-confirmed alert.

## Frozen-Feed Verification

1. Export the Python reference output for the frozen `FXPRO:EURUSD` M15 window.
2. Capture Pine output from the identical TradingView feed and window.
3. Compare timestamps, direction, level or origin, and lifecycle fields.
4. Classify each mismatch as feed, timezone or session, precision, or algorithm.
5. Zero algorithm mismatches is the target on identical frozen OHLC.
6. Tick tolerance is for rendering only.

## Implementation Steps

1. Add confirmed D/H4 structure and bias requests after single-timeframe parity is stable.
2. Add H4 dealing-range P/D and confirmed D/H4 swings/pools for the nearest-wall gate.
3. Add London/New York filtering plus the first-15-minute London exclusion after the session-timezone decision is locked.
4. Add alert conditions, dynamic payloads, and one-shot deduplication by linked event id.
5. Capture Pine event output from the frozen feed/window.
6. Compare outputs and write a mismatch report with evidence.
7. Profile Pine runtime and remove redundant loops or drawings without changing semantics.
8. Document setup, limitations, visual modes, alert creation, and parity procedure.

## Files

- Modify `tradingview/smc-engine-indicator.pine`.
- Create `docs/smc-engine-tradingview-guide.md`.
- Modify `docs/smc-engine-verification.md`.
- Modify `README.md`.

## Validation

- Full Python suite passes.
- Focused SMC tests stay green.
- Pine compiles and runs over the target window without execution errors.
- Synthetic Gate A, Gate B, and Rulebook fixtures have zero algorithm mismatches.
- Same-feed EURUSD outputs have zero algorithm mismatches on identical frozen OHLC.
- Realtime Bar Replay, refresh, and script reload preserve finalized events.
- HTF values change only when the relevant HTF bar is confirmed.
- Price normalization uses `syminfo.mintick` where display precision is required.
- Plot count is `<= 48`, unique request contexts are `<= 8`, internal drawing caps are respected, and no unexpected garbage collection occurs.
- Dark/light desktop and mobile evidence passes the Phase 03 UI gates.

## Completion Checklist

- [ ] MTF anti-repaint behavior demonstrated.
- [ ] Alerts tested on replay.
- [ ] Parity report records counts and mismatch reasons.
- [ ] Pine Profiler results recorded.
- [ ] User guide documents feed dependence and limitations.
- [ ] Evidence bundle records compiler version/result, symbol/feed/timeframe/window, input settings, comparator output, profiler measurements, object/plot/request counts, replay/reload comparison, and UI screenshots.
- [ ] Public release remains blocked until source or license review if requested.

## Risks and Rollback

- MTF parity is invalid if feeds or bar boundaries differ.
- If MTF requests exceed limits or runtime budget, keep chart-timeframe v1 and ship bias separately.
- Disable the MTF module without modifying the proven single-timeframe core.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
