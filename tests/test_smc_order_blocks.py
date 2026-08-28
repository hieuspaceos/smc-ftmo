"""Golden tests for BOS-activated order block lifecycle (Phase 5)."""
from __future__ import annotations

import sys
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.displacement import ExpansionMetrics  # noqa: E402
from smc_engine.order_blocks import (  # noqa: E402
    DEFAULT_EXPIRY_BARS,
    DEFAULT_MAX_ACTIVE_PER_DIRECTION,
    OrderBlockEvent,
    OrderBlockResult,
    detect_order_blocks,
)
from smc_engine.structure import StructureEvent, StructureResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _idx(n: int, *, freq: str = "15min", tz: str | None = None) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq=freq, tz=tz)


def _ohlc(
    opens: list[float] | np.ndarray,
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
    *,
    tz: str | None = None,
) -> pd.DataFrame:
    n = len(closes)
    assert n == len(opens) == len(highs) == len(lows)
    return pd.DataFrame(
        {
            "open": np.asarray(opens, dtype=float),
            "high": np.asarray(highs, dtype=float),
            "low": np.asarray(lows, dtype=float),
            "close": np.asarray(closes, dtype=float),
        },
        index=_idx(n, tz=tz),
    )


def _qualified(df: pd.DataFrame, mask: list[bool] | np.ndarray | None = None) -> pd.Series:
    if mask is None:
        vals = np.ones(len(df), dtype=bool)
    else:
        vals = np.asarray(mask, dtype=bool)
        assert len(vals) == len(df)
    return pd.Series(vals, index=df.index, name="qualified", dtype=bool)


def _expansion(df: pd.DataFrame, mask: list[bool] | np.ndarray | None = None) -> ExpansionMetrics:
    q = _qualified(df, mask)
    nan = pd.Series(np.nan, index=df.index, dtype=float)
    direction = pd.Series("neutral", index=df.index, dtype=object)
    return ExpansionMetrics(
        range_atr=nan.rename("range_atr"),
        body_atr=nan.rename("body_atr"),
        body_ratio=nan.rename("body_ratio"),
        close_location=nan.rename("close_location"),
        direction=direction.rename("direction"),
        qualified=q,
    )


def _empty_structure(df: pd.DataFrame) -> StructureResult:
    n = len(df)
    idx = df.index
    nan_f = pd.Series(np.nan, index=idx, dtype=float)
    return StructureResult(
        events=(),
        trend=pd.Series(["neutral"] * n, index=idx, name="trend", dtype=object),
        bos=nan_f.rename("bos"),
        choch=nan_f.rename("choch"),
        broken_level=nan_f.rename("broken_level"),
        last_swing_high=nan_f.rename("last_swing_high"),
        last_swing_low=nan_f.rename("last_swing_low"),
        swing_direction=nan_f.rename("swing_direction"),
    )


def _structure_with(
    df: pd.DataFrame,
    events: list[StructureEvent],
) -> StructureResult:
    base = _empty_structure(df)
    bos = base.bos.copy()
    choch = base.choch.copy()
    broken = base.broken_level.copy()
    trend = base.trend.copy()
    for ev in events:
        sign = 1.0 if ev.direction == "bullish" else -1.0
        if ev.type == "bos":
            bos.iloc[ev.activation_pos] = sign
        else:
            choch.iloc[ev.activation_pos] = sign
        broken.iloc[ev.activation_pos] = ev.broken_level
        trend.iloc[ev.activation_pos :] = ev.next_trend
    return StructureResult(
        events=tuple(events),
        trend=trend,
        bos=bos,
        choch=choch,
        broken_level=broken,
        last_swing_high=base.last_swing_high,
        last_swing_low=base.last_swing_low,
        swing_direction=base.swing_direction,
    )


def _bos(
    id_: int,
    direction: str,
    pos: int,
    index: pd.DatetimeIndex,
    *,
    level: float = 100.0,
    prior: str = "bull",
) -> StructureEvent:
    next_trend = "bull" if direction == "bullish" else "bear"
    # prior_trend for BOS should match direction's continuation
    if direction == "bullish":
        prior_trend = "bull" if prior == "bull" else "bull"
    else:
        prior_trend = "bear" if prior == "bear" else "bear"
    return StructureEvent(
        id=id_,
        type="bos",
        direction=direction,  # type: ignore[arg-type]
        activation_pos=pos,
        activation_timestamp=index[pos],
        broken_level=float(level),
        source_swing_id=0,
        prior_trend=prior_trend,  # type: ignore[arg-type]
        next_trend=next_trend,  # type: ignore[arg-type]
    )


def _choch(
    id_: int,
    direction: str,
    pos: int,
    index: pd.DatetimeIndex,
    *,
    level: float = 100.0,
) -> StructureEvent:
    next_trend = "bull" if direction == "bullish" else "bear"
    prior_trend = "bear" if direction == "bullish" else "bull"
    return StructureEvent(
        id=id_,
        type="choch",
        direction=direction,  # type: ignore[arg-type]
        activation_pos=pos,
        activation_timestamp=index[pos],
        broken_level=float(level),
        source_swing_id=0,
        prior_trend=prior_trend,  # type: ignore[arg-type]
        next_trend=next_trend,  # type: ignore[arg-type]
    )


def _bullish_fixture(
    *,
    n: int = 12,
    origin: int = 3,
    bos_pos: int = 5,
    touch_pos: int | None = 7,
    invalidate_pos: int | None = None,
    expand_at: str = "break",
) -> tuple[pd.DataFrame, StructureResult, ExpansionMetrics]:
    """Synthetic bullish BOS with a clear bearish origin candle.

    Layout (default):
      bars 0-2: mild bullish
      bar 3: bearish origin (high=102, low=98)
      bar 4: bullish continuation
      bar 5: BOS impulse (expansion)
      later bars: optional touch / invalidation
    """
    opens = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.5] * n

    # Origin bearish candle
    opens[origin] = 101.0
    closes[origin] = 99.0
    highs[origin] = 102.0
    lows[origin] = 98.0

    # Bars between origin and BOS stay above zone (no premature touch after act)
    for j in range(origin + 1, bos_pos + 1):
        opens[j] = 100.0
        closes[j] = 103.0 if j == bos_pos else 101.0
        highs[j] = 104.0 if j == bos_pos else 102.0
        lows[j] = 100.0  # above origin top=102? wait top is 102, low must be > 102 to avoid touch
        # Actually lifecycle starts after activation, so bars <= bos_pos don't touch.
        lows[j] = 99.5

    # Post-activation default: stay away from zone
    for j in range(bos_pos + 1, n):
        opens[j] = 103.0
        closes[j] = 104.0
        highs[j] = 105.0
        lows[j] = 103.0  # above top=102 → no touch

    if touch_pos is not None and 0 <= touch_pos < n:
        # Wick into zone: low <= top (102), close still above bottom (98)
        opens[touch_pos] = 103.0
        closes[touch_pos] = 103.0
        highs[touch_pos] = 104.0
        lows[touch_pos] = 101.5  # <= 102

    if invalidate_pos is not None and 0 <= invalidate_pos < n:
        opens[invalidate_pos] = 99.0
        closes[invalidate_pos] = 97.0  # close < bottom 98
        highs[invalidate_pos] = 100.0
        lows[invalidate_pos] = 96.5

    df = _ohlc(opens, highs, lows, closes)
    mask = [False] * n
    if expand_at == "break":
        mask[bos_pos] = True
    elif expand_at == "prev":
        if bos_pos > 0:
            mask[bos_pos - 1] = True
    elif expand_at == "none":
        pass
    else:
        raise ValueError(expand_at)

    structure = _structure_with(df, [_bos(0, "bullish", bos_pos, df.index, level=101.0)])
    return df, structure, _expansion(df, mask)


def _bearish_fixture(
    *,
    n: int = 12,
    origin: int = 3,
    bos_pos: int = 5,
    touch_pos: int | None = 7,
    invalidate_pos: int | None = None,
) -> tuple[pd.DataFrame, StructureResult, ExpansionMetrics]:
    opens = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [99.5] * n

    # Origin bullish candle
    opens[origin] = 99.0
    closes[origin] = 101.0
    highs[origin] = 102.0
    lows[origin] = 98.0

    for j in range(origin + 1, bos_pos + 1):
        opens[j] = 100.0
        closes[j] = 97.0 if j == bos_pos else 99.0
        highs[j] = 100.5
        lows[j] = 96.0 if j == bos_pos else 98.5

    for j in range(bos_pos + 1, n):
        opens[j] = 97.0
        closes[j] = 96.0
        highs[j] = 97.5  # below bottom=98 → no touch
        lows[j] = 95.0

    if touch_pos is not None and 0 <= touch_pos < n:
        opens[touch_pos] = 97.0
        closes[touch_pos] = 97.0
        highs[touch_pos] = 98.5  # >= bottom 98
        lows[touch_pos] = 96.0

    if invalidate_pos is not None and 0 <= invalidate_pos < n:
        opens[invalidate_pos] = 101.0
        closes[invalidate_pos] = 103.0  # close > top 102
        highs[invalidate_pos] = 104.0
        lows[invalidate_pos] = 100.0

    df = _ohlc(opens, highs, lows, closes)
    mask = [False] * n
    mask[bos_pos] = True
    structure = _structure_with(df, [_bos(0, "bearish", bos_pos, df.index, level=99.0)])
    return df, structure, _expansion(df, mask)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_event_frozen_and_price_midpoint(self):
        idx = _idx(3)
        ev = OrderBlockEvent(
            id=0,
            direction="bullish",
            origin_pos=0,
            origin_timestamp=idx[0],
            activation_pos=1,
            activation_timestamp=idx[1],
            top=110.0,
            bottom=100.0,
            first_touch_timestamp=None,
            invalidation_timestamp=None,
            expiry_timestamp=None,
            structure_event_id=7,
        )
        with pytest.raises((FrozenInstanceError, Exception)):
            ev.direction = "bearish"  # type: ignore[misc]
        assert ev.price == pytest.approx(105.0)

    def test_result_types_empty(self):
        df = _ohlc([1, 1], [1, 1], [0, 0], [0.5, 0.5])
        out = detect_order_blocks(df, _empty_structure(df), _expansion(df))
        assert isinstance(out, OrderBlockResult)
        assert out.events == ()
        assert isinstance(out.diagnostics, tuple)


# ---------------------------------------------------------------------------
# Activation / origin / BOS-only / expansion gate
# ---------------------------------------------------------------------------


class TestActivationAndOrigin:
    def test_unavailable_before_activation(self):
        df, structure, expansion = _bullish_fixture(touch_pos=None)
        out = detect_order_blocks(df, structure, expansion, candidate_lookback=10)
        assert len(out.events) == 1
        ob = out.events[0]
        assert ob.origin_pos == 3
        assert ob.activation_pos == 5
        assert ob.origin_timestamp == df.index[3]
        assert ob.activation_timestamp == df.index[5]
        assert ob.top == pytest.approx(102.0)
        assert ob.bottom == pytest.approx(98.0)
        assert ob.structure_event_id == 0

        # Strictly before activation → not active, not first-test
        assert ob.is_active_at(df.index[4]) is False
        assert ob.is_first_test_at(df.index[4]) is False
        # Origin bar itself is not tradeable as OB
        assert ob.is_active_at(df.index[3]) is False

        # Activation bar is available
        assert ob.is_active_at(df.index[5]) is True
        assert ob.is_first_test_at(df.index[5]) is True

    def test_choch_does_not_create_ob(self):
        n = 10
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.5] * n
        opens[2] = 101.0
        closes[2] = 99.0
        highs[2] = 102.0
        lows[2] = 98.0
        df = _ohlc(opens, highs, lows, closes)
        ev = _choch(0, "bullish", 5, df.index)
        structure = _structure_with(df, [ev])
        mask = [False] * n
        mask[5] = True
        out = detect_order_blocks(df, structure, _expansion(df, mask))
        assert out.events == ()

    def test_requires_expansion_at_break_or_prev(self):
        df, structure, _ = _bullish_fixture(expand_at="none", touch_pos=None)
        out = detect_order_blocks(df, structure, _expansion(df, [False] * len(df)))
        assert out.events == ()
        assert any("skip_no_expansion" in d for d in out.diagnostics)

        df2, structure2, exp2 = _bullish_fixture(expand_at="prev", touch_pos=None)
        out2 = detect_order_blocks(df2, structure2, exp2)
        assert len(out2.events) == 1

    def test_last_opposite_candle_within_lookback(self):
        # Two bearish candles; last one before BOS wins
        n = 10
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.5] * n
        # older bearish
        opens[1] = 101.0
        closes[1] = 99.0
        highs[1] = 110.0
        lows[1] = 90.0
        # nearer bearish
        opens[3] = 102.0
        closes[3] = 100.0
        highs[3] = 103.0
        lows[3] = 99.0
        bos_pos = 6
        opens[bos_pos] = 100.0
        closes[bos_pos] = 105.0
        highs[bos_pos] = 106.0
        lows[bos_pos] = 100.0
        df = _ohlc(opens, highs, lows, closes)
        structure = _structure_with(df, [_bos(0, "bullish", bos_pos, df.index)])
        mask = [False] * n
        mask[bos_pos] = True
        out = detect_order_blocks(df, structure, _expansion(df, mask), candidate_lookback=10)
        assert len(out.events) == 1
        assert out.events[0].origin_pos == 3
        assert out.events[0].top == pytest.approx(103.0)
        assert out.events[0].bottom == pytest.approx(99.0)


# ---------------------------------------------------------------------------
# First touch (inclusive) / invalidation
# ---------------------------------------------------------------------------


class TestFirstTouchAndInvalidation:
    def test_first_touch_inclusive_bullish(self):
        df, structure, expansion = _bullish_fixture(touch_pos=7, invalidate_pos=None)
        out = detect_order_blocks(df, structure, expansion)
        ob = out.events[0]
        assert ob.first_touch_timestamp == df.index[7]
        assert ob.invalidation_timestamp is None

        # Inclusive: first-touch bar is still first-test eligible
        assert ob.is_active_at(df.index[7]) is True
        assert ob.is_first_test_at(df.index[7]) is True

        # After first touch → active but not first-test
        assert ob.is_active_at(df.index[8]) is True
        assert ob.is_first_test_at(df.index[8]) is False

        # Before first touch, still first-test
        assert ob.is_first_test_at(df.index[6]) is True

    def test_invalidation_bullish_close_below_bottom(self):
        df, structure, expansion = _bullish_fixture(
            touch_pos=7, invalidate_pos=9, n=12
        )
        out = detect_order_blocks(df, structure, expansion)
        ob = out.events[0]
        assert ob.first_touch_timestamp == df.index[7]
        assert ob.invalidation_timestamp == df.index[9]

        assert ob.is_active_at(df.index[8]) is True
        # On invalidation bar: not active
        assert ob.is_active_at(df.index[9]) is False
        assert ob.is_first_test_at(df.index[9]) is False
        assert ob.is_active_at(df.index[10]) is False

    def test_bearish_touch_and_invalidation(self):
        df, structure, expansion = _bearish_fixture(touch_pos=7, invalidate_pos=9)
        out = detect_order_blocks(df, structure, expansion)
        assert len(out.events) == 1
        ob = out.events[0]
        assert ob.direction == "bearish"
        assert ob.origin_pos == 3
        assert ob.top == pytest.approx(102.0)
        assert ob.bottom == pytest.approx(98.0)
        assert ob.first_touch_timestamp == df.index[7]
        assert ob.invalidation_timestamp == df.index[9]
        assert ob.is_first_test_at(df.index[7]) is True
        assert ob.is_active_at(df.index[9]) is False

    def test_activation_bar_cannot_self_touch(self):
        """Impulse BOS bar must not set first_touch even if wick overlaps zone."""
        n = 10
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.5] * n
        origin = 2
        bos_pos = 4
        opens[origin] = 101.0
        closes[origin] = 99.0
        highs[origin] = 102.0
        lows[origin] = 98.0
        # BOS bar wicks into zone
        opens[bos_pos] = 100.0
        closes[bos_pos] = 105.0
        highs[bos_pos] = 106.0
        lows[bos_pos] = 101.0  # <= top 102
        # Stay clear after
        for j in range(bos_pos + 1, n):
            opens[j] = 105.0
            closes[j] = 106.0
            highs[j] = 107.0
            lows[j] = 104.0
        df = _ohlc(opens, highs, lows, closes)
        structure = _structure_with(df, [_bos(0, "bullish", bos_pos, df.index)])
        mask = [False] * n
        mask[bos_pos] = True
        out = detect_order_blocks(df, structure, _expansion(df, mask))
        ob = out.events[0]
        assert ob.first_touch_timestamp is None
        assert ob.is_first_test_at(df.index[bos_pos]) is True


# ---------------------------------------------------------------------------
# Expiry / cap
# ---------------------------------------------------------------------------


class TestExpiryAndCap:
    def test_natural_expiry_after_expiry_bars(self):
        expiry_bars = 5
        n = 20
        origin = 2
        bos_pos = 4
        opens = [100.0] * n
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.5] * n
        opens[origin] = 101.0
        closes[origin] = 99.0
        highs[origin] = 102.0
        lows[origin] = 98.0
        opens[bos_pos] = 100.0
        closes[bos_pos] = 105.0
        highs[bos_pos] = 106.0
        lows[bos_pos] = 100.0
        for j in range(bos_pos + 1, n):
            opens[j] = 105.0
            closes[j] = 106.0
            highs[j] = 107.0
            lows[j] = 104.0  # no touch
        df = _ohlc(opens, highs, lows, closes)
        structure = _structure_with(df, [_bos(0, "bullish", bos_pos, df.index)])
        mask = [False] * n
        mask[bos_pos] = True
        out = detect_order_blocks(
            df,
            structure,
            _expansion(df, mask),
            expiry_bars=expiry_bars,
        )
        ob = out.events[0]
        exp_pos = bos_pos + expiry_bars
        assert ob.expiry_timestamp == df.index[exp_pos]
        assert any(d.startswith("expiry@") for d in out.diagnostics)

        assert ob.is_active_at(df.index[exp_pos - 1]) is True
        assert ob.is_active_at(df.index[exp_pos]) is False
        assert ob.is_active_at(df.index[exp_pos + 1]) is False

    def test_cap_expires_oldest_active(self):
        n = 40
        opens = np.full(n, 100.0)
        highs = np.full(n, 101.0)
        lows = np.full(n, 99.0)
        closes = np.full(n, 100.5)
        events: list[StructureEvent] = []
        # Create 3 bullish BOS events with distinct origins
        bos_positions = [5, 12, 20]
        for k, bos_pos in enumerate(bos_positions):
            origin = bos_pos - 2
            opens[origin] = 101.0 + k
            closes[origin] = 99.0 + k
            highs[origin] = 102.0 + k
            lows[origin] = 98.0 + k
            opens[bos_pos] = 100.0
            closes[bos_pos] = 110.0
            highs[bos_pos] = 111.0
            lows[bos_pos] = 100.0
            # Keep post-activation price away from all zones
            for j in range(bos_pos + 1, n):
                if j in bos_positions or j in [p - 2 for p in bos_positions]:
                    continue
                opens[j] = 120.0
                closes[j] = 121.0
                highs[j] = 122.0
                lows[j] = 119.0
            events.append(_bos(k, "bullish", bos_pos, _idx(n), level=105.0))

        df = _ohlc(opens, highs, lows, closes)
        # Fix index on structure events to df.index
        events = [
            _bos(k, "bullish", bos_pos, df.index, level=105.0)
            for k, bos_pos in enumerate(bos_positions)
        ]
        structure = _structure_with(df, events)
        mask = [False] * n
        for p in bos_positions:
            mask[p] = True

        out = detect_order_blocks(
            df,
            structure,
            _expansion(df, mask),
            max_active_zones_per_direction=2,
            expiry_bars=500,  # avoid natural expiry
            candidate_lookback=5,
        )
        assert len(out.events) == 3
        # Oldest should be cap-expired when the 3rd activates
        oldest = out.events[0]
        newest = out.events[2]
        assert oldest.expiry_timestamp == newest.activation_timestamp
        assert any("cap_expiry@" in d for d in out.diagnostics)
        assert oldest.is_active_at(newest.activation_timestamp) is False
        assert out.events[1].is_active_at(newest.activation_timestamp) is True
        assert newest.is_active_at(newest.activation_timestamp) is True


# ---------------------------------------------------------------------------
# Direction separation
# ---------------------------------------------------------------------------


class TestDirection:
    def test_bullish_and_bearish_independent_caps(self):
        """Bear BOS bar at 18 closes below bullish OB bottom → invalidates bullish OB (MVP rule, breakers deferred to post-cutover)."""
        n = 30
        opens = np.full(n, 100.0)
        highs = np.full(n, 101.0)
        lows = np.full(n, 99.0)
        closes = np.full(n, 100.0)
        opens[5] = 101.0; closes[5] = 99.0; highs[5] = 102.0; lows[5] = 98.0
        opens[8] = 100.0; closes[8] = 110.0; highs[8] = 111.0; lows[8] = 100.0
        opens[15] = 99.0; closes[15] = 101.0; highs[15] = 102.0; lows[15] = 98.0
        opens[18] = 100.0; closes[18] = 90.0; highs[18] = 100.0; lows[18] = 89.0
        for j in list(range(9, 15)) + list(range(19, n)):
            opens[j] = 105.0; closes[j] = 105.0; highs[j] = 106.0; lows[j] = 104.0
        df = _ohlc(opens, highs, lows, closes)
        events = [_bos(0, "bullish", 8, df.index), _bos(1, "bearish", 18, df.index)]
        structure = _structure_with(df, events)
        mask = [False] * n
        mask[8] = True; mask[18] = True
        out = detect_order_blocks(df, structure, _expansion(df, mask))
        # Both OBs are produced from the two BOS events; cap is per direction so
        # the bullish/bearish queues do not collide.
        assert len(out.events) == 2
        assert out.events[0].direction == "bullish"
        assert out.events[1].direction == "bearish"
        # Bear BOS bar at 18 invalidates bullish OB; bull follow-through at bar 19
        # invalidates bearish OB (close > bearish top). MVP has no breaker
        # role-flip — defer post-cutover.
        assert out.events[1].is_active_at(df.index[25]) is False
        assert out.events[0].is_active_at(df.index[25]) is False

# ---------------------------------------------------------------------------
# As-of / no future leak / prefix invariance
# ---------------------------------------------------------------------------


class TestAsOfAndPrefix:
    def test_as_of_ignores_future_terminal_state(self):
        df, structure, expansion = _bullish_fixture(
            touch_pos=7, invalidate_pos=9, n=12
        )
        out = detect_order_blocks(df, structure, expansion)
        ob = out.events[0]
        # Querying before invalidation must not see the future invalidation
        assert ob.invalidation_timestamp == df.index[9]
        assert ob.is_active_at(df.index[8]) is True
        assert ob.is_first_test_at(df.index[6]) is True
        # Construct a "historical view" event with future fields cleared
        historical = OrderBlockEvent(
            id=ob.id,
            direction=ob.direction,
            origin_pos=ob.origin_pos,
            origin_timestamp=ob.origin_timestamp,
            activation_pos=ob.activation_pos,
            activation_timestamp=ob.activation_timestamp,
            top=ob.top,
            bottom=ob.bottom,
            first_touch_timestamp=None,  # not yet known at ts=6
            invalidation_timestamp=None,
            expiry_timestamp=None,
            structure_event_id=ob.structure_event_id,
        )
        assert historical.is_active_at(df.index[6]) is True
        assert historical.is_first_test_at(df.index[6]) is True

    def test_prefix_invariance_of_activated_zones(self):
        df, structure, expansion = _bullish_fixture(
            touch_pos=7, invalidate_pos=9, n=14
        )
        full = detect_order_blocks(df, structure, expansion)

        # Prefix ending before touch
        cut = 7  # exclusive end → bars 0..6
        df_p = df.iloc[:cut].copy()
        # structure events fully inside prefix
        evs = [e for e in structure.events if e.activation_pos < cut]
        structure_p = _structure_with(df_p, evs)
        expansion_p = _expansion(df_p, expansion.qualified.iloc[:cut].tolist())
        prefix = detect_order_blocks(df_p, structure_p, expansion_p)

        assert len(prefix.events) == 1
        assert len(full.events) == 1
        a, b = prefix.events[0], full.events[0]
        assert a.origin_pos == b.origin_pos
        assert a.activation_pos == b.activation_pos
        assert a.top == pytest.approx(b.top)
        assert a.bottom == pytest.approx(b.bottom)
        assert a.structure_event_id == b.structure_event_id
        # Touch not yet resolved in prefix
        assert a.first_touch_timestamp is None
        assert a.invalidation_timestamp is None
        # As-of queries inside prefix agree with full event methods for pre-touch bars
        for i in range(a.activation_pos, cut):
            ts = df.index[i]
            assert a.is_active_at(ts) == b.is_active_at(ts)
            # full event may already know first_touch in the future; for first-test
            # before the touch bar both must agree when we mask future touch
            if b.first_touch_timestamp is None or ts < b.first_touch_timestamp:
                assert a.is_first_test_at(ts) is True
                assert b.is_first_test_at(ts) is True


# ---------------------------------------------------------------------------
# Validation / series expansion input
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_ohlc_raises(self):
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=_idx(2))
        with pytest.raises(ValueError, match="OHLC"):
            detect_order_blocks(df, _empty_structure(df), _qualified(df))

    def test_bad_params_raise(self):
        df = _ohlc([1, 1], [1, 1], [0, 0], [0.5, 0.5])
        structure = _empty_structure(df)
        exp = _expansion(df)
        with pytest.raises(ValueError):
            detect_order_blocks(df, structure, exp, candidate_lookback=0)
        with pytest.raises(ValueError):
            detect_order_blocks(df, structure, exp, expiry_bars=-1)
        with pytest.raises(ValueError):
            detect_order_blocks(df, structure, exp, max_active_zones_per_direction=0)

    def test_accepts_qualified_series_directly(self):
        df, structure, expansion = _bullish_fixture(touch_pos=None)
        out = detect_order_blocks(df, structure, expansion.qualified)
        assert len(out.events) == 1


# ---------------------------------------------------------------------------
# Scaling
# ---------------------------------------------------------------------------


class TestScaleBehavior:
    def test_runtime_scales_near_linear(self):
        """runtime(2N)/runtime(N) < 2.5 on synthetic multi-BOS fixture."""

        def make_frame(n: int) -> tuple[pd.DataFrame, StructureResult, pd.Series]:
            rng = np.random.default_rng(0)
            # Random-ish walk with forced opposite candles + BOS every 30 bars
            opens = np.empty(n)
            highs = np.empty(n)
            lows = np.empty(n)
            closes = np.empty(n)
            price = 100.0
            events: list[StructureEvent] = []
            qual = np.zeros(n, dtype=bool)
            eid = 0
            idx = _idx(n)
            for i in range(n):
                shock = float(rng.normal(0.0, 0.3))
                opens[i] = price
                closes[i] = price + shock
                highs[i] = max(opens[i], closes[i]) + abs(float(rng.normal(0.2, 0.1)))
                lows[i] = min(opens[i], closes[i]) - abs(float(rng.normal(0.2, 0.1)))
                price = closes[i]
                if i > 10 and i % 30 == 0:
                    # Force opposite origin two bars back
                    if eid % 2 == 0:
                        opens[i - 2] = closes[i - 2] + 1.0
                        closes[i - 2] = opens[i - 2] - 1.5
                        highs[i - 2] = opens[i - 2] + 0.2
                        lows[i - 2] = closes[i - 2] - 0.2
                        direction = "bullish"
                        closes[i] = highs[i - 2] + 2.0
                        opens[i] = closes[i] - 1.0
                        highs[i] = closes[i] + 0.5
                        lows[i] = opens[i] - 0.5
                    else:
                        opens[i - 2] = closes[i - 2] - 1.0
                        closes[i - 2] = opens[i - 2] + 1.5
                        highs[i - 2] = closes[i - 2] + 0.2
                        lows[i - 2] = opens[i - 2] - 0.2
                        direction = "bearish"
                        closes[i] = lows[i - 2] - 2.0
                        opens[i] = closes[i] + 1.0
                        highs[i] = opens[i] + 0.5
                        lows[i] = closes[i] - 0.5
                    qual[i] = True
                    events.append(_bos(eid, direction, i, idx, level=float(closes[i])))
                    eid += 1
            df = _ohlc(opens, highs, lows, closes)
            # Rebuild events with correct index timestamps
            rebuilt = [
                _bos(e.id, e.direction, e.activation_pos, df.index, level=e.broken_level)
                for e in events
            ]
            structure = _structure_with(df, rebuilt)
            return df, structure, pd.Series(qual, index=df.index, dtype=bool)

        def run_once(n: int) -> float:
            df, structure, qual = make_frame(n)
            t0 = time.perf_counter()
            detect_order_blocks(
                df,
                structure,
                qual,
                expiry_bars=DEFAULT_EXPIRY_BARS,
                max_active_zones_per_direction=DEFAULT_MAX_ACTIVE_PER_DIRECTION,
            )
            return time.perf_counter() - t0

        run_once(2_000)
        n = 8_000
        t_n = min(run_once(n) for _ in range(3))
        t_2n = min(run_once(2 * n) for _ in range(3))
        if t_n < 1e-4:
            pytest.skip("timing resolution too coarse")
        ratio = t_2n / t_n
        assert ratio < 2.5, f"runtime(2N)/runtime(N) = {ratio:.3f} >= 2.5"
