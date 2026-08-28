---
title: "Custom SMC Engine Rewrite"
description: "Replace the broken external SMC dependency with a causal, timestamp-aligned, deterministic engine and verified adapter cutover."
status: pending
priority: P1
branch: "master"
tags: [smc, backtest, causality, python]
blockedBy: []
blocks: []
created: "2026-08-27T16:53:49.199Z"
createdBy: "ck:plan"
source: skill
---

# Custom SMC Engine Rewrite

## Overview
Replace `smartmoneyconcepts==0.0.27` with an in-project engine for confirmed swings, ATR/range expansion, BOS/CHoCH, liquidity sweeps, order blocks, FVGs, premium/discount context, and multi-timeframe bias.

The objective is correctness and observability—not improving profitability. Economic metrics are characterization outputs, not pass/fail oracles.

## Why This Rewrite Is Required
- Library output uses `NaN` for no-signal rows and integer indexes instead of source timestamps.
- Current bias parsing previously collapsed `NaN` to bearish behavior, producing one-sided trades.
- `SMCSignals` currently returns empty BOS/CHoCH/FVG arrays and derives OBs from raw swings rather than structure breaks.
- Current backtester compares bias vocabulary `bull`/`bear` against `bullish`/`bearish` when alignment is disabled.
- Current daily/H4 bias mapping can expose completed day-end state to earlier M15 bars from the same day.
- Current mitigation state is terminal/full-history state, unsafe for historical `as_of` queries without explicit timestamps.

## Architectural Decisions
1. **DIY baseline**. No maintained Python library provides the full causal ICT/SMC stack with stable timestamp-aligned APIs.
2. **Typed events**. Every event carries origin and activation timestamps. Consumers never reconstruct confirmation timing.
3. **Completed-bar causality**. At timestamp `t`, use only events activated at or before `t`; HTF state uses the latest completed HTF bar with close timestamp `<= t`.
4. **Lifecycle timestamps**. OB/FVG records store first-touch, invalidation/fill, and optional expiry timestamps; state is queried with `is_active_at(t)` / `is_first_test_at(t)`.
5. **MVP boundary**. Breakers, volume confirmation, body-quality filters, alternative ZigZag engines, and optimization are optional post-cutover upgrades.
6. **Exact adapter compatibility**. Preserve the current `Signal` schema, exact `SMCSignals.get_signals(df, tf="M15", skip_mitigation=False)` signature, and `get_smc_overlays()` function until all callers are deliberately migrated.
7. **Oracle-based verification**. Synthetic/golden/property tests prove semantics. Real EURUSD counts and PF/winrate only characterize changes.

## MVP Scope
- Confirmed Williams/fractal swing events.
- Causal ATR and baseline range expansion (`range > multiplier × ATR`).
- Exhaustive BOS/CHoCH state machine.
- One-shot liquidity sweeps per confirmed level.
- BOS-activated OB zones with first-touch and invalidation lifecycle.
- Three-candle FVG zones with activation and fill lifecycle.
- Structure-derived bias and structure-leg premium/discount context.
- Adapter and caller cutover with no-lookahead verification.

## Optional Post-Cutover Upgrades
- ATR/deviation ZigZag or directional-change swing engine.
- Body ratio, close-location, and volume-qualified displacement.
- Breaker block classification.
- Sweep quality score combining rejection, displacement, and close location.
- Configurable OB body/full-candle zones and FVG midpoint/full-fill policies.
- Threshold tuning or profitability optimization.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Causal Swing Events](./phase-01-causal-swing-events.md) | Pending |
| 2 | [ATR and Range Expansion](./phase-02-atr-and-range-expansion.md) | Pending |
| 3 | [Structure State Machine](./phase-03-structure-state-machine.md) | Pending |
| 4 | [Liquidity Sweeps](./phase-04-liquidity-sweeps.md) | Pending |
| 5 | [Order Block Lifecycle](./phase-05-order-block-lifecycle.md) | Pending |
| 6 | [FVG Bias and Context](./phase-06-fvg-bias-and-context.md) | Pending |
| 7 | [Adapter Cutover](./phase-07-adapter-cutover.md) | Pending |
| 8 | [Migration and Verification](./phase-08-migration-and-verification.md) | Pending |
| 9 | [Acceptance Cleanup](./phase-09-acceptance-cleanup.md) | Pending |

## Dependencies
- Phase 1 and Phase 2 can execute independently.
- Phase 3 depends on 1–2.
- Phase 4 depends on 1–2.
- Phase 5 depends on 2–3.
- Phase 6 depends on 1–3.
- Phase 7 depends on 1–6.
- Phase 8 depends on 7.
- Phase 9 depends on 8.

## Planned Files
### Create
- `src/smc_engine/__init__.py`
- `src/smc_engine/events.py`
- `src/smc_engine/swings.py`
- `src/smc_engine/displacement.py`
- `src/smc_engine/structure.py`
- `src/smc_engine/sweeps.py`
- `src/smc_engine/order_blocks.py`
- `src/smc_engine/fvg.py`
- `src/smc_engine/context.py`
- `tests/test_smc_swings.py`
- `tests/test_smc_displacement.py`
- `tests/test_smc_structure.py`
- `tests/test_smc_sweeps.py`
- `tests/test_smc_order_blocks.py`
- `tests/test_smc_fvg_context.py`
- `tests/test_smc_adapter_contract.py`
- `tests/fixtures/smc-golden-events.json`
- `scripts/smoke-phase12.py`

### Modify
- `src/smc_signals.py`
- `src/bias_detector.py`
- `src/backtester.py`
- `src/premium_discount.py`
- `app.py`
- `tests/test_backtest.py`
- `requirements.txt`
- `README.md`
- `docs/system-architecture.md` (create `docs/` if still missing)

## Staged Go/No-Go Gates
### Gate 1 — Engine Semantics
Pass exact decision-table tests, golden fixtures, prefix invariance, event-time ordering, legal enums, zone ordering, translation invariance, and scale invariance for Phases 1–6.

**Stop/rollback**: any event appears before activation; prefix results change after appending future bars; lifecycle state differs between full-history and prefix evaluation.

### Gate 2 — Adapter Compatibility
Pass signature inspection and golden serialization for defaults, positional `tf`, `skip_mitigation=False`, and `skip_mitigation=True`. Preserve `Signal.type`, `price`, `direction`, `timestamp`, `mitigated`, `mitigation_time`, `top`, and `bottom`.

**Stop/rollback**: any current caller or chart contract breaks outside the approved algorithm delta.

### Gate 3 — Causal Backtest + Performance
Pass completed-HTF boundary fixtures, prefix-vs-full backtest equivalence, unique equity timestamps, deterministic journal rows, cold runtime/memory benchmark, and scaling ratio target (`runtime(2N) / runtime(N) < 2.5`).

**Stop/rollback**: lookahead, superlinear lifecycle scans, unexplained golden drift, or runtime/memory regression beyond the recorded legacy budget.

### Gate 4 — Actual UI Behavior
Run Streamlit, exercise Run Backtest, verify chart overlays and fresh journal state, capture screenshot and smoke JSON.

**Stop/rollback**: app exception, empty overlay caused by schema break, stale journal run, or missing long/short events on deterministic synthetic fixture.

Only after Gate 4 passes: remove `smartmoneyconcepts` from `requirements.txt`.

## Acceptance Criteria
- [ ] No `smartmoneyconcepts` imports remain after cutover.
- [ ] Every event has explicit causal activation time.
- [ ] OB/FVG/sweep state is correct as-of any historical timestamp.
- [ ] HTF bias uses only completed bars.
- [ ] Exact adapter contract and `get_smc_overlays()` remain available.
- [ ] Deterministic fixtures prove both bullish and bearish paths.
- [ ] Full test suite passes after economic-threshold tests are converted into characterization where necessary.
- [ ] Smoke and UI reports are stored under `reports/`.

## Research Sources
- `https://github.com/rafalsza/smartmoneyconcepts/blob/master/smartmoneyconcepts/smc.py`
- `https://github.com/jaydai81/smartmoneyconcepts/blob/master/smartmoneyconcepts/SMC.py`
- Existing source contracts: `src/smc_signals.py`, `src/bias_detector.py`, `src/backtester.py`, `src/premium_discount.py`, `app.py`.

## Unresolved Questions
None. MVP defaults are locked in phase files. Optional enhancements remain explicitly post-cutover.

## Validation Log

### Session 1 — 2026-08-28
**Trigger:** User requested `/ck:plan validate` after deep research and red-team review.
**Questions asked:** 7

### Verification Results
- **Tier:** Full (9 phases; fact checker, flow tracer, scope auditor, contract verifier)
- **Claims checked:** 135
- **Verified:** 130 | **Failed:** 0 | **Unverified:** 5
- **Verified contracts:** current `Signal` fields; exact `SMCSignals.get_signals(df, tf=\"M15\", skip_mitigation=False)` signature; `get_smc_overlays()`; app/backtester signal field usage; bias enum mismatch; current P/D API; Streamlit/backtester call flow.
- **Unverified until implementation:** cold runtime, peak memory, 2N scaling ratio, post-cutover real-data distributions, post-cutover UI overlay behavior.
- **Rejected audit claims:** equity timestamps are not duplicated on the same execution path; `iloc[:searchsorted(day_end, side=\"left\")]` does not include the next day's first bar. The actual HTF leak is same-day completed state applied to earlier M15 bars.

#### Questions & Answers

1. **[Architecture] Phase 2 — ATR warmup: xử lý 13 bar đầu trước khi ATR(14) đủ dữ liệu thế nào?**
   - Options: NaN causal | Legacy backfill | Expanding ATR
   - **Answer:** NaN causal
   - **Rationale:** Loại future leakage; warmup bar không được tạo displacement/sweep.

2. **[Tradeoff] Phase 5/6 — OB/FVG tồn tại bao lâu nếu chưa invalidated/filled?**
   - Options: 200 bars + cap 128 | Không expiry | 50 bars + cap 64
   - **Answer:** 200 bars + cap 128
   - **Rationale:** Bound runtime/memory với lifecycle deterministic.

3. **[Architecture] Phase 6 — Premium/Discount dùng dealing range theo structure hay rolling high/low 50 bars?**
   - Options: Structure dealing range | Giữ rolling 50 | Chạy song song
   - **Answer:** Structure dealing range
   - **Rationale:** Context bám activated structure leg; rolling API chỉ còn compatibility wrapper.

4. **[Scope] Phase 5 — Breaker Block có nằm trong MVP rewrite này không?**
   - Options: Để post-cutover | Thêm vào MVP
   - **Answer:** Để post-cutover
   - **Rationale:** Breaker cần contract/test riêng; không chặn dependency replacement.

5. **[Verification] Phase 8 — tests hiện tại ép winrate/PF/trade-count theo engine cũ. Khi engine đúng làm metrics thay đổi, xử lý thế nào?**
   - Options: Chuyển thành characterization | Giữ hard thresholds | Chỉ giữ risk thresholds
   - **Answer:** Chuyển thành characterization
   - **Rationale:** Correctness dùng deterministic/causal oracles; economic metrics chỉ để review.

6. **[Causality] Phase 3 — swing được confirm tại close bar i. Có cho chính close i phá level vừa confirm không?**
   - Options: Dùng từ bar kế tiếp | Cho dùng cùng close
   - **Answer:** Dùng từ bar kế tiếp
   - **Rationale:** Tránh confirm-and-break cùng một close; ordering dễ audit.

7. **[Entry timing] Phase 5/6 — bar hiện tại chạm OB/FVG lần đầu có được entry không?**
   - Options: Cho entry tại first-touch bar | Chỉ entry bar sau
   - **Answer:** Cho entry tại first-touch bar
   - **Rationale:** `is_first_test_at(t)` true tại touch timestamp; entry dùng close bar touch.

#### Confirmed Decisions
- Causal NaN ATR warmup.
- OB/FVG expiry 200 bars; cap 128 active zones per direction.
- Structure-dealing-range P/D.
- Breakers deferred.
- Economic metrics are characterization only.
- Confirmed swings become break-eligible from the next bar.
- First-touch bar is entry-eligible.

#### Impact on Phases
- Phase 2: lock causal NaN warmup.
- Phase 3: lock next-bar break eligibility.
- Phase 5/6: lock expiry/cap and first-touch entry semantics.
- Phase 6: lock structure dealing range.
- Phase 8: convert economic thresholds to characterization.

### Whole-Plan Consistency Sweep
- **Files reread:** `plan.md`, phases 01–09, `research/algorithm-review.md`.
- **Decision deltas checked:** 7.
- **Reconciled stale references:** 9 superseded phase files removed; CK numeric phase links are authoritative.
- **Searches checked:** ATR warmup, zone expiry/cap, breaker scope, structure dealing range, economic gates, swing activation order, first-touch timing, adapter signature, lifecycle as-of semantics.
- **Unresolved contradictions:** 0.
- **Recommendation:** Plan is eligible for implementation; five implementation outcomes remain intentionally unverified until their gates run.
