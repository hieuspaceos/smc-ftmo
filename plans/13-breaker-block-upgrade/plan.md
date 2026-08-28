---
title: "Breaker Block + OB Body Toggle"
description: "Extend the causal SMC engine with breaker block role-flip semantics and an optional body-only OB zone mode. Both add scope without altering existing OB lifecycle invariants."
status: pending
priority: P2
branch: "master"
tags: [smc, breaker, order-block, post-cutover]
blockedBy: []
blocks: []
created: "2026-08-29T01:25:00.000Z"
createdBy: "ck:plan"
source: skill
---

# Breaker Block + OB Body Toggle

## Overview

Add two opt-in extensions to the SMC engine (delivered in Phase 12):

1. **Breaker Block role-flip**: an invalidated OB is promoted to a "breaker"
   zone when a subsequent CHoCH flips structure. Breaker zones are tradeable
   in the OPPOSITE direction from the original OB.
2. **OB body-only zone mode**: alternative OB zone definition that uses the
   origin candle's body (open↔close) instead of the full wick range (high↔low).

Both features are non-breaking: existing behavior (full candle OB, role="ob")
remains the default and is fully preserved. Breaker promotion runs as a
**second pass** after the main lifecycle sweep and only mutates drafts whose
invalidation timestamp lies strictly before a CHoCH activation timestamp.

The objective is to widen edge by recognizing role-reversal setups without
introducing lookahead. Economic effects (trade count, winrate, profit factor)
are characterized post-implementation; they are not pass/fail oracles.

## Why This Upgrade Now

From Phase 12 validation session 1, Q4 (breaker scope):

> "Breaker cần contract/test riêng; không chặn dependency replacement."

Breakers were explicitly deferred from Phase 12 MVP. After 12 successful
sessions of forward usage and 163/163 tests on the base engine, the base
causality contracts are stable enough to extend without disturbing them.

User-prioritized next-up from session 2 (2026-08-29):

- Tier 1: Breaker Block + OB body-only toggle (this plan).
- Tier 2: Volume confirmation, ZigZag (deferred post-OOS).
- Tier 3: FVG midpoint-fill (cosmetic, deferred).

## Architectural Decisions

1. **Additive only**. Breaker promotion is a second chronological pass.
   Existing OB lifecycle invariants (touch, invalidate, expire) are
   untouched. Body mode changes only the `top`/`bottom` derivation in
   `_activate_bos`; origin selection, displacement gating, and lifecycle are
   unaffected.

2. **Causality lock**. A draft can only be promoted to a breaker if
   `invalidation_timestamp < choch_activation_timestamp`. This guarantees
   the promoting CHoCH is observed strictly after the OB was invalidated,
   matching Phase 12's causal-at-completed-bar rule.

3. **Inclusive flip gate**. `is_breaker_active_at(t)` returns `True` for
   `t >= role_flip_timestamp` (the CHoCH bar itself is eligible for entry).
   This matches the established `is_first_test_at` entry-eligibility rule
   from Q7 of the Phase 12 validation.

4. **Promotion lookback bounded**. `promotion_lookback_bars` defaults to 50.
   An OB that was invalidated more than 50 bars before the CHoCH cannot
   be promoted. Bounds runtime and prevents "stale" promotion from very old
   zones.

5. **Single promotion per draft**. A draft's `role` flips to `"breaker"` once
   and only once. CHoCH events processed in chronological order ensures the
   earliest valid promotion wins.

6. **Body mode opt-in**. `ob_zone_mode="full"` (default) preserves all
   current behavior and existing test outputs verbatim. `"body"` is a
   new knob that swaps `top`/`bottom` for the origin candle's body
   endpoints.

7. **Adapter surface unchanged**. `SMCSignals.get_signals()` returns the
   same `Signal` schema. Breaker events appear as `OrderBlockEvent` with
   `role="breaker"`; downstream consumers query `is_breaker_active_at()`.

## MVP Scope

- `OrderBlockEvent.role: str` field, defaults to `"ob"`.
- `OrderBlockEvent.role_flip_timestamp: pd.Timestamp | None`.
- `OrderBlockEvent.role_flip_structure_id: int | None`.
- `OrderBlockEvent.is_breaker_active_at(ts)` method.
- `OrderBlockResult` becomes `@dataclass(frozen=True)` with default empty
  `events` tuple (preserves `OrderBlockResult()` no-arg constructor used by
  tests).
- `_Draft` mirrors the new event fields so the lifecycle pass can mutate
  them and `to_event()` can copy them.
- `detect_order_blocks(..., promotion_lookback_bars=50, ob_zone_mode="full")`.
- Second chronological pass that promotes invalidated OB drafts when a
  CHoCH activates in the same window.

## Optional Excluded From This Plan

- Volume confirmation (no data: HistData M1 CSVs lack volume).
- ATR/deviation ZigZag (existing fractal is robust on EURUSD M15).
- FVG midpoint fill (cosmetic).
- Breaker promotion driven by BOS (only CHoCH promotes; BOS just inactivates).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Event Lifecycle Extension](./phase-01-event-lifecycle-extension.md) | Pending |
| 2 | [Breaker Promotion Pass](./phase-02-breaker-promotion-pass.md) | Pending |
| 3 | [OB Body Mode](./phase-03-ob-body-mode.md) | Pending |
| 4 | [Tests & Causality Oracle](./phase-04-tests-and-causality-oracle.md) | Pending |
| 5 | [Adapter & Backtester Surface](./phase-05-adapter-and-backtester-surface.md) | Pending |
| 6 | [Smoke & OOS](./phase-06-smoke-and-oos.md) | Pending |

## Dependencies

- Phase 1, 2, 3 all modify `src/smc_engine/order_blocks.py`; they must be
  applied as a coordinated edit to avoid intermediate broken states.
- Phase 4 depends on Phases 1–3.
- Phase 5 depends on Phase 4.
- Phase 6 depends on Phases 4–5.

## Planned Files

### Modify
- `src/smc_engine/order_blocks.py`
  - Add `role`, `role_flip_timestamp`, `role_flip_structure_id` to
    `OrderBlockEvent` and `_Draft`.
  - Add `is_breaker_active_at` method on `OrderBlockEvent`.
  - Convert `OrderBlockResult` to `@dataclass(frozen=True)` with default
    empty tuple to preserve no-arg constructor.
  - Add `promotion_lookback_bars=50` and `ob_zone_mode="full"` parameters.
  - Add body-mode top/bottom branch in `_activate_bos`.
  - Add second pass: walk CHoCH events, promote invalidated drafts.
- `tests/test_smc_order_blocks.py`
  - Add `TestBreakerBlockCausality` class covering:
    - Breaker promoted only after CHoCH (origin flipped, role flipped,
      top/bottom preserved, role_flip_timestamp > invalidation_timestamp).
    - Breaker inactive before flip, active on flip bar and after.
    - No breaker without any CHoCH event.
    - `promotion_lookback_bars` honored.
  - Add `TestOBBodyMode` class covering:
    - `ob_zone_mode="body"` produces narrower zones (top ≤ full mode).
    - `ob_zone_mode="full"` matches existing 19 OB tests verbatim.
- `scripts/smoke-phase12.py`
  - No behavior change required; SHA256 of M15 close unchanged
    (signals unchanged, breakers only add role fields).

### No new files required.

## Staged Go/No-Go Gates

### Gate 1 — Existing 19 OB tests untouched
Re-run `tests/test_smc_order_blocks.py` and confirm all 19 pre-existing
tests pass **without modification** (verbatim). This proves additive
discipline: nothing in `_activate_bos`, `_lifecycle_bar`, `_natural_expire`,
or `_expire_draft` changed semantics.

**Stop/rollback**: any pre-existing test fails or requires change.

### Gate 2 — Breaker causality oracle
Run `TestBreakerBlockCausality` (new). All four tests pass. Concretely:
- Breaker exists only when CHoCH was observed after invalidation.
- Breaker direction is opposite the original OB direction.
- `role_flip_timestamp > invalidation_timestamp`.
- `promotion_lookback_bars` strictly bounds origin distance.

**Stop/rollback**: any breaker violates causality invariant.

### Gate 3 — Full suite green
`pytest tests/ -q` reports ≥163 tests pass (existing 159 + new ≥4 breaker
+ ≥2 body tests). SHA256 of M15 close unchanged in smoke.

**Stop/rollback**: any existing test breaks or smoke SHA256 changes.

### Gate 4 — Engine metrics characterization
Run `scripts/smoke-phase12.py` against EURUSD M15 8 months. Trade count,
winrate, profit factor, max DD recorded. New metric: count of
`role="breaker"` events in the OB output. Comparison:
- Breaker count > 0 on real data (proves the pass is wired in).
- Trade count may change (breakers open a new entry opportunity). We
  expect a small positive delta in trade count, exact number subject to
  data drift.

**Stop/rollback**: breakers never activate (count = 0), or trade count
crashes (>50% drop), or smoke SHA256 changes.

### Gate 5 — UI visible breaker overlays (optional)
Render breaker zones on the chart with a distinct color (cyan dashed) in
`build_main_chart`. Verify Streamlit serves the new chart without error.

**Stop/rollback**: chart exception or render timeout.

## Acceptance Criteria

- [ ] Pre-existing 19 OB tests pass verbatim.
- [ ] `TestBreakerBlockCausality` (4 tests) passes.
- [ ] `TestOBBodyMode` (≥2 tests) passes.
- [ ] Full `pytest tests/ -q` reports ≥163 passed, 0 failed.
- [ ] `scripts/smoke-phase12.py` SHA256 of M15 close unchanged.
- [ ] At least one breaker activates on the EURUSD M15 2026 fixture.
- [ ] `OrderBlockResult()` no-arg constructor still works (backwards
      compat with consumers that synthesize empty results in tests).
- [ ] `ob_zone_mode="full"` produces identical top/bottom values as the
      pre-upgrade baseline (regression guard).

## Unresolved Questions

None for MVP. Optional enhancements remain explicit in
`phase-09-acceptance-cleanup.md` of Phase 12.

## Validation Log

### Session 1 — 2026-08-29
**Trigger:** User confirmed Tier 1 priority (Breaker + OB body toggle) and
asked for a written plan before further code changes, after observing that
prior direct edits to `order_blocks.py` introduced regressions.

**Questions asked:** 6

#### Questions & Answers

1. **[Scope] Breaker chỉ promote từ CHoCH, có tính cả BOS không?**
   - Options: CHoCH only | CHoCH + BOS in opposite direction
   - **Answer:** CHoCH only
   - **Rationale:** ICT definition. BOS continuation không flip role;
   chỉ CHoCH mới establish trend reversal mới justify role-reversal.
   BOS event mới không "promote" breaker từ OB cũ mà tạo OB/breaker mới.

2. **[Architecture] Breaker flip gate strict `<` hay inclusive `<=`?**
   - Options: Strict `ts < flip_ts` | Inclusive `ts >= flip_ts`
   - **Answer:** Inclusive `ts >= flip_ts`
   - **Rationale:** Trader có thể vào ngay tại CHoCH bar (close bar đó là
   close của break + displacement). Match existing `is_first_test_at`
   entry-eligibility rule.

3. **[Tradeoff] `promotion_lookback_bars` default?**
   - Options: 30 bars | 50 bars | 100 bars
   - **Answer:** 50 bars
   - **Rationale:** EURUSD M15 có ~165 swing points / 8 tháng. 50 bars ≈ 12
   giờ M15. OB invalidated trong 12h mà chưa có CHoCH = đã stale. Đủ
   cover realistic setup, bound runtime.

4. **[Architecture] Body mode swap top/bottom từ high/low hay max(open,close)?**
   - Options: max(open, close) | max(open, close) only if close > open
   - **Answer:** max(open, close) regardless of direction
   - **Rationale:** Simplest semantics. Direction đã được OB direction
   field xác định. Body endpoint luôn là max/min của open↔close.

5. **[Verification] Test body mode như thế nào?**
   - Options: Compare top/bottom numeric vs full mode | Verify narrower zone
   - **Answer:** Verify narrower zone (body ≤ full)
   - **Rationale:** Direct causality check. body.top ≤ full.high and
   body.bottom ≥ full.low (and at least one strict inequality when
   wicks exist).

6. **[Scope] Adapter SMCSignals có cần phơi breakers không?**
   - Options: Yes — expose as Signal with role field | No — downstream
     computes
   - **Answer:** No — backtester consumes OrderBlockEvent directly
   - **Rationale:** SMCSignals returns Signal schema (overlay drawing).
   Breaker is a backtest concern; chart drawing uses order_blocks events
   separately. Avoid expanding legacy adapter contract.

#### Confirmed Decisions
- Breaker promotion only on CHoCH (not BOS).
- Breaker flip gate inclusive (`ts >= flip_ts`).
- `promotion_lookback_bars = 50` default.
- Body mode: `top = max(open, close)`, `bottom = min(open, close)`.
- Body test asserts narrower-or-equal zone with at least one strict.
- Adapter `SMCSignals` unchanged; backtester reads OrderBlockEvent.

#### Impact on Phases
- Phase 1 (event lifecycle): mirror role fields on `_Draft`.
- Phase 2 (breaker promotion): chronological second pass.
- Phase 3 (body mode): single if-branch in `_activate_bos`.
- Phase 4 (tests): 4 breaker + ≥2 body = ≥6 new tests.
- Phase 5 (adapter): no schema change.
- Phase 6 (smoke): count breakers, verify trade count delta.

### Whole-Plan Consistency Sweep
- **Files reread:** `plan.md`, Phase 12 `plan.md` (for contract alignment).
- **Decision deltas checked:** 6.
- **Reconciled stale references:** none.
- **Searches checked:** breaker scope, body mode semantics, causality
  invariant, promotion lookback, flip gate inclusivity, adapter
  surface, smoke SHA256 stability.
- **Unresolved contradictions:** 0.
- **Recommendation:** Plan is eligible for implementation.