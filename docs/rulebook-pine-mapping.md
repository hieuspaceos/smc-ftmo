---
status: active
title: "Rule Book → Pine Mapping"
created: "2026-08-29"
updated: "2026-08-31"
version: "v1.3"

# Rule Book → Pine Mapping

Every load-bearing rule in `journal/rule-book.md` must map to a concrete
gate in the Rulebook 8W selector. This file records the current mapping
and is the source of truth for the `TestRulebookGaps` suite.

## Setup Freeze (§0)

| Rule | Pine code | Test |
|---|---|---|
| `bias_mode = strict` (D + H4) | `Gate 2` of candidate pipeline: `htfDTrend`/`htfH4Trend` aligned, no neutral | `test_bias_strict_requires_d_and_h4_alignment` |
| `regime_mode = off` | no breaker / body-mode code path in `Rulebook` profile | (no test) |
| OB zone = `full` (high–low) | `OrderBlockZone.top`/`bottom` from origin candle high/low | parity with `tests/test_smc_order_blocks.py` |
| Displacement `1.5× ATR` | `displacementMult` input default = 1.5 | (input default) |
| SL buffer `0.2× ATR` | `rulebookSlEdgeAtr` input default = 0.2 | (input default) |
| EURUSD only | `config.yaml` symbol list, not Pine-side | (out of scope) |
| No slider additions | `inputs` block frozen for Rulebook profile | (visual) |

## Account & Risk (§1)

| Rule | Pine code |
|---|---|
| Risk per trade `0.55%` | manual gate `manualRiskOk` |
| Max 3 trades/day | manual gate `manualTradesLeft` |
| Daily loss limit `2R` | manual gate `manualDailyROk` |
| Max 1 open position | manual gate `manualPosOk` |
| SL outside OB edge + `0.2× ATR` buffer | `slEdge = obBottom - atr * rulebookSlEdgeAtr` (long) / mirror short |
| Partial TP 40/30/30 at 2R/3R/4R | out of scope for the Pine indicator (manual) |

## Reading Order (§2)

The Rulebook selector enforces the strict reading order via gates, not
chart annotations:

1. D bias → Gate 2 (htfDTrend)
2. H4 bias → Gate 2 (htfH4Trend)
3. H1 = context (not in Pine, manual)
4. M15 structure → Gate 2 (structureTrend) + Gate 4 (no later CHoCH)
5. Sweep / FVG → score bonuses
6. EQH / EQL → Gate 7 (HTF wall)
7. Breaker = `regime_mode=on` → not in Rulebook profile

## Setup Mandatory (§3)

| Layer | Rule | Pine code |
|---|---|---|
| Bias | D + H4 cùng hướng | `Gate 2` |
| Displacement | `(high-low) > 1.5× ATR(14)` tại/near BOS | `expansionQualified` + `Gate 8` |
| BOS | Close phá swing, wick không tính | `obLookback` + `Gate 1` linkedBosId |
| OB active | Zone còn sống, chưa invalidated, first-test | `Gate 3` + `OrderBlockZone.dead`/`touched` |
| Score ≥ 4 | disp + bias + first-test = 3, điểm 4 từ sweep hoặc P/D | `Gate 8` threshold + score formula |

## Bias (§4) — §4 strict

- **Pine:** `Gate 2` requires `htfDTrend == htfH4Trend == structureTrend != 0`
  when both HTF inputs are enabled.
- **Test:** `test_bias_strict_requires_d_and_h4_alignment` asserts the
  disagree scenario is no more permissive than the aligned scenario.

## Structure (§5)

- BOS via close, wick không tính → `f_make_structure_label` only fires
  on confirmed close, structure evaluation requires `close > level +
  structureBufferAtr * atr`.
- CHoCH không tạo OB → OB activation gated by `bosSignal != 0`, not
  `chochSignal`.
- "Đứng ngoài OB cũ sau CHoCH" → `Gate 4` rejects OBs whose linked BOS
  id is older than the latest CHoCH id on that side.

## Order Block (§6)

| Rule | Pine code |
|---|---|
| OB = nến ngược chiều cuối trước BOS | `f_find_ob_origin` scans lookback window for last opposite candle |
| Full zone = `[low, high]` nến origin | `zoneTop = high[originOffset]`, `zoneBottom = low[originOffset]` |
| BOS + displacement | `expansionNearBreak` check before OB activation |
| First-test = 1 lần | `zone.touched` set once, `Gate 3` requires `not zone.touched` |
| Bullish OB chết khi `close < bottom` | OB lifecycle block |
| Bearish OB chết khi `close > top` | OB lifecycle block |
| Entry = `ob_top` (long) / `ob_bottom` (short) | `entryPrice` in pipeline |
| SL = `± 0.2× ATR` ngoài edge | `slPrice` in pipeline |
| Proximity ≤ 1.5× ATR | `Gate 5` |
| Freeze `SL > 1.2× ATR` | `Gate 6` |
| 2R tường HTF gần nhất | `Gate 7` |

## Displacement (§7)

- `range > 1.5× ATR` → `expansionQualified` in core math.
- Required for score and OB activation.

## Sweep (§8) — §8 clean threshold

- Engine overlay wick ≥ `0.05× ATR` + reclaim → `sweepBufferAtr` input.
- **Rulebook clean** wick ≥ `0.25× ATR` + reclaim → `rulebookCleanSweepAtr`
  input default 0.25.
- Pine tracks `lastCleanSweepBar` / `lastCleanSweepDir` separately so
  the score gate can use the strict threshold.
- **Test:** `test_clean_sweep_threshold_is_0_25_atr` asserts the constant
  is 0.25 and the reference script respects it.

## FVG (§9)

- Không phải entry zone — chỉ vẽ overlay khi `effectiveShowFvgs` true.
- Pine gate không cộng điểm FVG.

## Premium / Discount (§10)

- Long ưu tiên discount (rẻ hơn equilibrium), short ưu tiên premium.
- P/D theo H4 khi `Use H4 HTF` on, chart-timeframe fallback otherwise.
- Score cộng 1 nếu đúng phía.

## Liquidity Pools (§11)

- Tolerance `0.15× ATR`, 2-member activation → `poolToleranceAtr` and
  `poolMinMembers` inputs.
- EQH/EQL activation logic matches Python `_PoolDraft` semantics.

## Breaker (§12)

- `regime_mode=off` cho 8 tuần → Rulebook profile không có breaker code.
- (ngoài scope Rulebook v1)

## Confluence Score (§13)

Score formula trong Pine hiện tại:

```
score = 0
+ 1.0 if expansionQualified                    # displacement (mandatory)
+ 1.0 if dirSign == structureTrend            # bias (mandatory)
+ 1.0 if not zone.touched                     # first-test (mandatory)
+ 1.0 if lastCleanSweepDir == dirSign         # sweep clean (optional)
+ 1.0 if pdZone == "discount"/"premium" right side  # P/D (optional)
threshold = 4.0
```

Rule book §13 demands exactly this — 3 mandatory (disp, bias, first-test)
+ at least one of (sweep_clean, P/D) to clear 4. **Test:**
`test_score_includes_clean_sweep_and_pd_bonuses` confirms the score
column never exceeds 5 and any `ok` row is non-zero.

## Session Filter (§14) — §14 EST windows

- Pine uses `hour(time, "America/New_York")` so the session windows are
  computed in NY local time, not exchange time.
- Asia 19:00–02:00 EST ✗
- London **02:00–05:00 EST** (narrow, cố ý) ✓
- NY 07:00–10:00 EST ✓
- Overlap 08:00–10:00 EST ✓
- First 15 minutes of London (02:00–02:15) blocked → `londonFirst15Blocked`
- **Test:** `test_session_helper_matches_rule_book_windows` exhaustively
  pins the boundary cases.

## Pairs & Timeframes (§15)

- Pine cố định M15 chart-timeframe cho Rulebook profile.
- D + H4 qua `request.security` (confirmed-bar semantics).
- Cặp lock: config-side, Pine không enforce.

## Confirmed Events

- HTF values dùng `barmerge.lookahead_on` + `[1]` offset để không repaint.

## Scale-in Exit Mode (§1 addendum, opt-in)

Scale-in is **not** part of the 8-week manual trade protocol (ladder 40/30/30
vẫn là mặc định cho manual). Pine hỗ trợ nó như một **visual layer** để
validate vị trí 2R/4R khi đọc chart và đối chiếu với bot config.

| Pine input | Maps to | Test |
|---|---|---|
| `useScaleInMode = false` (default) | `config.strategy.exit_mode == "ladder"` | (no test — toggle is user-driven) |
| `useScaleInMode = true` | `config.strategy.exit_mode == "scale_in"` | (no test) |
| `scaleInLeg2Tp1R = 3.0` (default) | `config.strategy.leg2_tp1_r == 3.0` (Design B) | `test_design_b_long_tp1_then_tp4r` |
| `scaleInLeg2Tp1R` left at default with `useScaleInMode = false` | Design A (no leg2 TP1) | `test_design_b_default_unchanged` |

**Pine visual → Python math invariants (Design A):**

| Pine line | Math invariant | Python equivalent |
|---|---|---|
| Teal: `rulebookScaleInTrigger` | `entry + 2.0 * slDistance` | `ScaleInExit.scale_in_r = 2.0` |
| Fuchsia: `rulebookFinalTp` | `entry + 4.0 * slDistance` | `ScaleInExit.final_tp_r = 4.0` |
| Orange: `rulebookLeg2Tp1` | `entry + scaleInLeg2Tp1R * slDistance` | `ScaleInExit.leg2_tp1_r` |

**Out of scope (Pine v1.3):**

- Pine không track leg1/leg2 lots runtime. Chỉ vẽ levels.
- Cascade / SL hit scenarios không có chart marker (chỉ có line cho kịch bản running).
- Pine không emit alert cho scale-in events (chỉ chart_qualified/watch/blocked cho entry OB).

