"""Golden tests for causal BOS/CHoCH structure state machine (Phase 3)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.events import SwingEvent, SwingResult  # noqa: E402
from smc_engine.structure import (  # noqa: E402
    StructureEvent,
    StructureResult,
    detect_structure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _index(n: int, *, freq: str = "15min", start: str = "2024-01-01 00:00:00", tz: str | None = None) -> pd.DatetimeIndex:
    return pd.date_range(start=start, periods=n, freq=freq, tz=tz)


def _ohlc(
    closes: list[float] | np.ndarray,
    *,
    highs: list[float] | np.ndarray | None = None,
    lows: list[float] | np.ndarray | None = None,
    index: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    n = len(c)
    if index is None:
        index = _index(n)
    if highs is None:
        h = c + 1.0
    else:
        h = np.asarray(highs, dtype=float)
    if lows is None:
        l = c - 1.0
    else:
        l = np.asarray(lows, dtype=float)
    return pd.DataFrame(
        {"open": c.copy(), "high": h, "low": l, "close": c},
        index=index,
    )


def _swing(
    sid: int,
    direction: str,
    level: float,
    pivot_pos: int,
    activation_pos: int,
    index: pd.DatetimeIndex,
) -> SwingEvent:
    return SwingEvent(
        id=sid,
        direction=direction,  # type: ignore[arg-type]
        level=float(level),
        pivot_pos=pivot_pos,
        pivot_timestamp=index[pivot_pos],
        activation_pos=activation_pos,
        activation_timestamp=index[activation_pos],
    )


def _swings_result(
    specs: list[tuple[int, str, float, int, int]],
    index: pd.DatetimeIndex,
) -> SwingResult:
    """Build SwingResult from (id, direction, level, pivot_pos, act_pos)."""
    events: list[SwingEvent] = []
    high_at = np.full(len(index), np.nan, dtype=float)
    low_at = np.full(len(index), np.nan, dtype=float)
    for sid, direction, level, pivot_pos, act_pos in specs:
        ev = _swing(sid, direction, level, pivot_pos, act_pos, index)
        events.append(ev)
        if direction == "high":
            high_at[act_pos] = level
        else:
            low_at[act_pos] = level
    return SwingResult(
        events=tuple(events),
        high_at_activation=pd.Series(high_at, index=index, name="high_at_activation"),
        low_at_activation=pd.Series(low_at, index=index, name="low_at_activation"),
    )


def _event_map(result: StructureResult) -> dict[int, StructureEvent]:
    return {e.activation_pos: e for e in result.events}


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_structure_event_frozen(self):
        idx = _index(3)
        ev = StructureEvent(
            id=0,
            type="bos",
            direction="bullish",
            activation_pos=1,
            activation_timestamp=idx[1],
            broken_level=10.0,
            source_swing_id=0,
            prior_trend="neutral",
            next_trend="bull",
        )
        with pytest.raises(Exception):
            ev.id = 1  # type: ignore[misc]

    def test_result_series_aligned(self):
        df = _ohlc([10.0, 11.0, 12.0, 13.0, 14.0])
        swings = _swings_result([(0, "high", 12.0, 0, 1)], df.index)
        result = detect_structure(df, swings)
        assert isinstance(result, StructureResult)
        for s in (
            result.trend,
            result.bos,
            result.choch,
            result.broken_level,
            result.last_swing_high,
            result.last_swing_low,
            result.swing_direction,
        ):
            assert s.index.equals(df.index)
            assert len(s) == len(df)


# ---------------------------------------------------------------------------
# Decision table — every row
# ---------------------------------------------------------------------------


class TestDecisionTable:
    """Exhaustive prior_trend × break direction fixtures."""

    def _run(
        self,
        *,
        prior_setup: str,
        break_side: str,
    ) -> StructureResult:
        """
        prior_setup:
          - 'neutral': only the break level is activated, no prior break
          - 'bull': establish bull via prior upper BOS, then set opposite/continuation level
          - 'bear': establish bear via prior lower BOS
        break_side: 'upper' | 'lower'
        """
        # Bar layout (n=12):
        # 0: dummy
        # 1: activate initial levels (for non-neutral, seed a first break path)
        # ...
        n = 14
        closes = np.full(n, 100.0, dtype=float)
        idx = _index(n)
        specs: list[tuple[int, str, float, int, int]] = []

        if prior_setup == "neutral":
            # Activate high@1 level 105, low@1 level 95; break later
            specs = [
                (0, "high", 105.0, 0, 1),
                (1, "low", 95.0, 0, 1),
            ]
            if break_side == "upper":
                closes[3] = 106.0  # close break high
            else:
                closes[3] = 94.0
            return detect_structure(_ohlc(closes, index=idx), _swings_result(specs, idx))

        if prior_setup == "bull":
            # Activate high 105 / low 95 at bar 1
            # Break upper at bar 3 → bull BOS
            # New high 110 activates at bar 5; new low 98 at bar 5
            # Then break upper or lower at bar 8
            specs = [
                (0, "high", 105.0, 0, 1),
                (1, "low", 95.0, 0, 1),
                (2, "high", 110.0, 3, 5),
                (3, "low", 98.0, 3, 5),
            ]
            closes[3] = 106.0  # first bull BOS
            if break_side == "upper":
                closes[8] = 111.0  # bull BOS continuation
            else:
                closes[8] = 97.0  # bear CHoCH
            return detect_structure(_ohlc(closes, index=idx), _swings_result(specs, idx))

        if prior_setup == "bear":
            specs = [
                (0, "high", 105.0, 0, 1),
                (1, "low", 95.0, 0, 1),
                (2, "high", 102.0, 3, 5),
                (3, "low", 90.0, 3, 5),
            ]
            closes[3] = 94.0  # first bear BOS
            if break_side == "upper":
                closes[8] = 103.0  # bull CHoCH
            else:
                closes[8] = 89.0  # bear BOS continuation
            return detect_structure(_ohlc(closes, index=idx), _swings_result(specs, idx))

        raise AssertionError(prior_setup)

    def test_neutral_upper_bull_bos(self):
        r = self._run(prior_setup="neutral", break_side="upper")
        assert len(r.events) == 1
        e = r.events[0]
        assert e.type == "bos"
        assert e.direction == "bullish"
        assert e.prior_trend == "neutral"
        assert e.next_trend == "bull"
        assert e.broken_level == pytest.approx(105.0)
        assert e.source_swing_id == 0
        assert r.trend.iloc[e.activation_pos] == "bull"
        assert r.bos.iloc[e.activation_pos] == 1.0
        assert np.isnan(r.choch.iloc[e.activation_pos])

    def test_neutral_lower_bear_bos(self):
        r = self._run(prior_setup="neutral", break_side="lower")
        assert len(r.events) == 1
        e = r.events[0]
        assert e.type == "bos"
        assert e.direction == "bearish"
        assert e.prior_trend == "neutral"
        assert e.next_trend == "bear"
        assert e.broken_level == pytest.approx(95.0)
        assert r.bos.iloc[e.activation_pos] == -1.0
        assert np.isnan(r.choch.iloc[e.activation_pos])

    def test_bull_upper_bull_bos(self):
        r = self._run(prior_setup="bull", break_side="upper")
        assert len(r.events) == 2
        e = r.events[1]
        assert e.type == "bos"
        assert e.direction == "bullish"
        assert e.prior_trend == "bull"
        assert e.next_trend == "bull"
        assert e.broken_level == pytest.approx(110.0)
        assert np.isnan(r.choch.iloc[e.activation_pos])
        assert r.bos.iloc[e.activation_pos] == 1.0

    def test_bull_lower_bear_choch(self):
        r = self._run(prior_setup="bull", break_side="lower")
        assert len(r.events) == 2
        e = r.events[1]
        assert e.type == "choch"
        assert e.direction == "bearish"
        assert e.prior_trend == "bull"
        assert e.next_trend == "bear"
        assert e.broken_level == pytest.approx(98.0)
        assert r.choch.iloc[e.activation_pos] == -1.0
        assert np.isnan(r.bos.iloc[e.activation_pos])

    def test_bear_upper_bull_choch(self):
        r = self._run(prior_setup="bear", break_side="upper")
        assert len(r.events) == 2
        e = r.events[1]
        assert e.type == "choch"
        assert e.direction == "bullish"
        assert e.prior_trend == "bear"
        assert e.next_trend == "bull"
        assert e.broken_level == pytest.approx(102.0)
        assert r.choch.iloc[e.activation_pos] == 1.0
        assert np.isnan(r.bos.iloc[e.activation_pos])

    def test_bear_lower_bear_bos(self):
        r = self._run(prior_setup="bear", break_side="lower")
        assert len(r.events) == 2
        e = r.events[1]
        assert e.type == "bos"
        assert e.direction == "bearish"
        assert e.prior_trend == "bear"
        assert e.next_trend == "bear"
        assert e.broken_level == pytest.approx(90.0)
        assert r.bos.iloc[e.activation_pos] == -1.0
        assert np.isnan(r.choch.iloc[e.activation_pos])

    def test_no_break_unchanged(self):
        n = 6
        closes = np.full(n, 100.0)
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert r.events == ()
        assert (r.trend == "neutral").all()
        assert r.bos.isna().all()
        assert r.choch.isna().all()


# ---------------------------------------------------------------------------
# Mutual exclusion / dual-break / invariant
# ---------------------------------------------------------------------------


class TestMutualExclusionAndMalformed:
    def test_bos_and_choch_never_same_bar(self):
        n = 14
        closes = np.full(n, 100.0)
        closes[3] = 106.0
        closes[8] = 97.0
        idx = _index(n)
        swings = _swings_result(
            [
                (0, "high", 105.0, 0, 1),
                (1, "low", 95.0, 0, 1),
                (2, "high", 110.0, 3, 5),
                (3, "low", 98.0, 3, 5),
            ],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        both = r.bos.notna() & r.choch.notna()
        assert not both.any()
        for e in r.events:
            if e.type == "bos":
                assert np.isnan(r.choch.iloc[e.activation_pos])
            else:
                assert np.isnan(r.bos.iloc[e.activation_pos])

    def test_dual_close_break_emits_none_and_diagnostic(self):
        # Single bar closes above high and below low (malformed levels or huge range)
        n = 5
        closes = np.array([100.0, 100.0, 100.0, 200.0, 100.0])
        # Force dual by making low > high? Actually dual needs close > high AND close < low
        # which requires low > high (invariant). With invariant check first, dual from
        # crossed levels is caught as invariant. Test true dual with valid levels
        # is impossible for a single close. Crossed levels:
        idx = _index(n)
        swings = _swings_result(
            [
                (0, "high", 90.0, 0, 1),  # high below low → invariant fail
                (1, "low", 110.0, 0, 1),
            ],
            idx,
        )
        # close 100 is > 90 and < 110 → would be dual if invariant not checked
        closes[3] = 100.0
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert r.events == ()
        assert any("invariant" in d for d in r.diagnostics)

    def test_dual_break_same_level_gap_via_buffer_zero_wide_close(self):
        """If somehow both flags fire with valid levels, suppress and diagnose.

        Valid low < high cannot have one close break both without buffer tricks.
        We inject via levels that are valid but we still cover the branch by
        using a close that only breaks one — this documents impossibility.
        For the dual_break diagnostic path, use equal levels almost and
        force by setting last_low slightly below last_high with close outside both
        is impossible. Instead construct high=100, low=99, close would need
        >100 and <99. Skip — invariant/dual covered above and below.
        """
        n = 4
        idx = _index(n)
        # high and low equal → invariant (not strict <)
        swings = _swings_result(
            [(0, "high", 100.0, 0, 1), (1, "low", 100.0, 0, 1)],
            idx,
        )
        closes = np.array([100.0, 100.0, 100.0, 101.0])
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert r.events == ()
        assert len(r.diagnostics) >= 1


# ---------------------------------------------------------------------------
# Consumed level / repeated breaks
# ---------------------------------------------------------------------------


class TestConsumedLevels:
    def test_repeated_closes_beyond_level_emit_one_event(self):
        n = 8
        closes = np.array([100.0, 100.0, 100.0, 106.0, 107.0, 108.0, 109.0, 110.0])
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert len(r.events) == 1
        assert r.events[0].activation_pos == 3
        assert r.events[0].broken_level == pytest.approx(105.0)
        # Later bars still bull trend, no extra bos
        assert r.bos.notna().sum() == 1

    def test_new_swing_replaces_consumed_level(self):
        n = 12
        closes = np.full(n, 100.0)
        closes[3] = 106.0  # break high 105
        closes[8] = 112.0  # break new high 110
        idx = _index(n)
        swings = _swings_result(
            [
                (0, "high", 105.0, 0, 1),
                (1, "low", 95.0, 0, 1),
                (2, "high", 110.0, 4, 5),  # new high after first break
            ],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert len(r.events) == 2
        assert r.events[0].source_swing_id == 0
        assert r.events[1].source_swing_id == 2
        assert r.events[1].type == "bos"
        assert r.events[1].broken_level == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# Equality / wick-only / buffer
# ---------------------------------------------------------------------------


class TestBreakRules:
    def test_equality_does_not_break(self):
        n = 5
        closes = np.array([100.0, 100.0, 100.0, 105.0, 100.0])  # equal to high
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert r.events == ()

    def test_wick_only_does_not_break(self):
        n = 5
        closes = np.array([100.0, 100.0, 100.0, 104.0, 100.0])
        highs = closes + 1.0
        highs[3] = 110.0  # wick above 105, close below
        lows = closes - 1.0
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        r = detect_structure(_ohlc(closes, highs=highs, lows=lows, index=idx), swings)
        assert r.events == ()

    def test_atr_buffer_requires_extra_margin(self):
        n = 5
        closes = np.array([100.0, 100.0, 100.0, 105.5, 100.0])  # >105 but not >105+1
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        atr = pd.Series(np.ones(n), index=idx, dtype=float)
        r0 = detect_structure(_ohlc(closes, index=idx), swings, atr=atr, close_break_buffer_atr=0.0)
        assert len(r0.events) == 1
        r1 = detect_structure(_ohlc(closes, index=idx), swings, atr=atr, close_break_buffer_atr=1.0)
        assert r1.events == ()
        # Now clear the buffer
        closes2 = closes.copy()
        closes2[3] = 106.1
        r2 = detect_structure(_ohlc(closes2, index=idx), swings, atr=atr, close_break_buffer_atr=1.0)
        assert len(r2.events) == 1

    def test_buffer_requires_atr(self):
        df = _ohlc([1.0, 2.0, 3.0])
        swings = _swings_result([], df.index)
        with pytest.raises(ValueError, match="atr is required"):
            detect_structure(df, swings, atr=None, close_break_buffer_atr=0.5)

    def test_nan_atr_with_buffer_skips_break(self):
        n = 5
        closes = np.array([100.0, 100.0, 100.0, 120.0, 100.0])
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        atr = pd.Series([np.nan, np.nan, np.nan, np.nan, np.nan], index=idx)
        r = detect_structure(_ohlc(closes, index=idx), swings, atr=atr, close_break_buffer_atr=0.1)
        assert r.events == ()


# ---------------------------------------------------------------------------
# Activation timing — next bar only
# ---------------------------------------------------------------------------


class TestActivationTiming:
    def test_same_bar_activation_not_breakable(self):
        """Swing activates at i; close at i cannot break it."""
        n = 6
        closes = np.array([100.0, 106.0, 100.0, 100.0, 100.0, 100.0])
        idx = _index(n)
        # high activates at bar 1 same time as close 106
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 1)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert r.events == ()
        # Eligible from next bar
        closes2 = closes.copy()
        closes2[2] = 106.0
        r2 = detect_structure(_ohlc(closes2, index=idx), swings)
        assert len(r2.events) == 1
        assert r2.events[0].activation_pos == 2

    def test_last_swing_series_updates_on_activation_bar(self):
        n = 4
        closes = np.full(n, 100.0)
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 1), (1, "low", 95.0, 0, 2)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert np.isnan(r.last_swing_high.iloc[0])
        assert r.last_swing_high.iloc[1] == pytest.approx(105.0)
        assert r.last_swing_low.iloc[2] == pytest.approx(95.0)
        assert r.swing_direction.iloc[1] == pytest.approx(1.0)
        assert r.swing_direction.iloc[2] == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Prefix / translation / scale / index
# ---------------------------------------------------------------------------


class TestPrefixInvariance:
    def test_prefix_events_stable(self):
        n = 16
        closes = np.full(n, 100.0)
        closes[4] = 106.0
        closes[10] = 97.0
        idx = _index(n)
        specs = [
            (0, "high", 105.0, 0, 2),
            (1, "low", 95.0, 0, 2),
            (2, "high", 110.0, 5, 7),
            (3, "low", 98.0, 5, 7),
        ]
        full_df = _ohlc(closes, index=idx)
        full_sw = _swings_result(specs, idx)
        full = detect_structure(full_df, full_sw)

        for end in range(3, n + 1):
            sub_idx = idx[:end]
            sub_df = full_df.iloc[:end]
            sub_specs = [s for s in specs if s[4] < end]
            # Remap nothing — activation_pos still valid within prefix
            sub_sw = _swings_result(sub_specs, sub_idx)
            sub = detect_structure(sub_df, sub_sw)
            full_prefix_events = tuple(
                e for e in full.events if e.activation_pos < end
            )
            assert len(sub.events) == len(full_prefix_events)
            for a, b in zip(sub.events, full_prefix_events, strict=True):
                assert a.type == b.type
                assert a.direction == b.direction
                assert a.activation_pos == b.activation_pos
                assert a.broken_level == pytest.approx(b.broken_level)
                assert a.prior_trend == b.prior_trend
                assert a.next_trend == b.next_trend
                assert a.source_swing_id == b.source_swing_id


class TestTranslationScaleInvariance:
    def test_price_translation(self):
        n = 10
        closes = np.full(n, 100.0)
        closes[4] = 106.0
        idx = _index(n)
        specs = [
            (0, "high", 105.0, 0, 2),
            (1, "low", 95.0, 0, 2),
        ]
        base = detect_structure(_ohlc(closes, index=idx), _swings_result(specs, idx))
        shift = 1000.0
        closes_t = closes + shift
        specs_t = [(s[0], s[1], s[2] + shift, s[3], s[4]) for s in specs]
        moved = detect_structure(_ohlc(closes_t, index=idx), _swings_result(specs_t, idx))
        assert len(moved.events) == len(base.events)
        for a, b in zip(base.events, moved.events, strict=True):
            assert a.activation_pos == b.activation_pos
            assert a.type == b.type
            assert a.direction == b.direction
            assert b.broken_level == pytest.approx(a.broken_level + shift)

    def test_price_scale(self):
        n = 10
        closes = np.full(n, 100.0)
        closes[4] = 106.0
        idx = _index(n)
        specs = [
            (0, "high", 105.0, 0, 2),
            (1, "low", 95.0, 0, 2),
        ]
        base = detect_structure(_ohlc(closes, index=idx), _swings_result(specs, idx))
        scale = 2.5
        closes_s = closes * scale
        specs_s = [(s[0], s[1], s[2] * scale, s[3], s[4]) for s in specs]
        scaled = detect_structure(_ohlc(closes_s, index=idx), _swings_result(specs_s, idx))
        assert len(scaled.events) == len(base.events)
        for a, b in zip(base.events, scaled.events, strict=True):
            assert a.activation_pos == b.activation_pos
            assert b.broken_level == pytest.approx(a.broken_level * scale)


class TestIndexAndTimezone:
    def test_timezone_preserved(self):
        n = 8
        idx = _index(n, tz="UTC")
        closes = np.full(n, 100.0)
        closes[4] = 106.0
        swings = _swings_result(
            [(0, "high", 105.0, 0, 2), (1, "low", 95.0, 0, 2)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        assert str(r.trend.index.tz) == "UTC"
        assert r.events[0].activation_timestamp.tzinfo is not None
        assert r.bos.index.equals(idx)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_close(self):
        df = pd.DataFrame({"high": [1.0], "low": [0.5]}, index=_index(1))
        swings = _swings_result([], df.index)
        with pytest.raises(ValueError, match="close"):
            detect_structure(df, swings)

    def test_non_monotonic_index(self):
        idx = pd.DatetimeIndex(
            ["2024-01-01 01:00", "2024-01-01 00:00", "2024-01-01 02:00"]
        )
        df = _ohlc([1.0, 2.0, 3.0], index=idx)
        with pytest.raises(ValueError, match="monotonic"):
            detect_structure(df, _swings_result([], idx))

    def test_bad_buffer(self):
        df = _ohlc([1.0, 2.0])
        with pytest.raises(ValueError):
            detect_structure(df, _swings_result([], df.index), close_break_buffer_atr=-1.0)

    def test_swing_activation_out_of_range(self):
        df = _ohlc([1.0, 2.0, 3.0])
        bad = SwingResult(
            events=(
                SwingEvent(
                    id=0,
                    direction="high",
                    level=1.0,
                    pivot_pos=0,
                    pivot_timestamp=df.index[0],
                    activation_pos=99,
                    activation_timestamp=df.index[0],
                ),
            ),
            high_at_activation=pd.Series(np.nan, index=df.index),
            low_at_activation=pd.Series(np.nan, index=df.index),
        )
        with pytest.raises(ValueError, match="out of range"):
            detect_structure(df, bad)


# ---------------------------------------------------------------------------
# broken_level series alignment
# ---------------------------------------------------------------------------


class TestBrokenLevelSeries:
    def test_broken_level_matches_event(self):
        n = 8
        closes = np.full(n, 100.0)
        closes[4] = 106.0
        idx = _index(n)
        swings = _swings_result(
            [(0, "high", 105.0, 0, 2), (1, "low", 95.0, 0, 2)],
            idx,
        )
        r = detect_structure(_ohlc(closes, index=idx), swings)
        e = r.events[0]
        assert r.broken_level.iloc[e.activation_pos] == pytest.approx(e.broken_level)
        assert r.broken_level.isna().sum() == n - 1
