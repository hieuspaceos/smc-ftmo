"""Golden tests for FVG lifecycle, bias, and dealing-range context (Phase 6)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.context import (  # noqa: E402
    ZONE_DISCOUNT,
    ZONE_NEUTRAL,
    ZONE_PREMIUM,
    ContextResult,
    compute_bias_series,
    compute_dealing_range_context,
    context_snapshot,
    is_in_pd_zone,
)
from smc_engine.events import SwingEvent, SwingResult  # noqa: E402
from smc_engine.fvg import FairValueGapEvent, FVGResult, detect_fvgs  # noqa: E402
from smc_engine.structure import StructureResult, detect_structure  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _idx(n: int, *, tz: str | None = None, freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq=freq, tz=tz)


def _ohlc(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray | None = None,
    *,
    opens: list[float] | np.ndarray | None = None,
    tz: str | None = None,
) -> pd.DataFrame:
    n = len(highs)
    assert n == len(lows)
    if closes is None:
        closes = [(float(h) + float(lo)) * 0.5 for h, lo in zip(highs, lows)]
    assert n == len(closes)
    if opens is None:
        opens = closes
    return pd.DataFrame(
        {
            "open": np.asarray(opens, dtype=float),
            "high": np.asarray(highs, dtype=float),
            "low": np.asarray(lows, dtype=float),
            "close": np.asarray(closes, dtype=float),
        },
        index=_idx(n, tz=tz),
    )


def _empty_structure(df: pd.DataFrame, trend: str = "neutral") -> StructureResult:
    n = len(df)
    nan = pd.Series(np.nan, index=df.index, dtype=float)
    return StructureResult(
        events=(),
        trend=pd.Series(trend, index=df.index, name="trend", dtype=object),
        bos=nan.rename("bos"),
        choch=nan.rename("choch"),
        broken_level=nan.rename("broken_level"),
        last_swing_high=nan.rename("last_swing_high"),
        last_swing_low=nan.rename("last_swing_low"),
        swing_direction=nan.rename("swing_direction"),
    )


def _structure_with_range(
    df: pd.DataFrame,
    *,
    high: float | None,
    low: float | None,
    trend: str = "bull",
    from_bar: int = 0,
) -> StructureResult:
    """Build structure series with a constant dealing range from ``from_bar``."""
    base = _empty_structure(df, trend="neutral")
    sh = base.last_swing_high.copy()
    sl = base.last_swing_low.copy()
    tr = base.trend.copy()
    if high is not None:
        sh.iloc[from_bar:] = float(high)
    if low is not None:
        sl.iloc[from_bar:] = float(low)
    tr.iloc[from_bar:] = trend
    return StructureResult(
        events=base.events,
        trend=tr,
        bos=base.bos,
        choch=base.choch,
        broken_level=base.broken_level,
        last_swing_high=sh,
        last_swing_low=sl,
        swing_direction=base.swing_direction,
    )


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestFVGContracts:
    def test_event_frozen_and_ordered_bounds(self):
        df = _ohlc(
            highs=[10, 12, 11, 13],
            lows=[9, 11, 10.5, 12.5],
        )
        # No gap yet — craft explicit bullish gap: high[0]=10 < low[2]=12
        df = _ohlc(
            highs=[10.0, 11.0, 13.0],
            lows=[9.0, 10.5, 12.0],
            closes=[9.5, 11.0, 12.5],
        )
        r = detect_fvgs(df)
        assert isinstance(r, FVGResult)
        assert len(r.events) == 1
        e = r.events[0]
        assert isinstance(e, FairValueGapEvent)
        with pytest.raises(Exception):
            e.top = 99.0  # type: ignore[misc]
        assert e.bottom < e.top
        assert e.direction == "bullish"
        assert e.price == pytest.approx((e.top + e.bottom) * 0.5)

    def test_empty_frame(self):
        df = _ohlc([], [])
        # empty lists → 0-length frame
        df = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": []},
            index=pd.DatetimeIndex([], dtype="datetime64[ns]"),
        )
        r = detect_fvgs(df)
        assert r.events == ()
        assert r.diagnostics == ()


# ---------------------------------------------------------------------------
# Activation / equality / boundaries
# ---------------------------------------------------------------------------


class TestFVGActivation:
    def test_bullish_gap_activates_on_third_close(self):
        # i-2=0 high=10, i=2 low=12 → gap [10, 12]
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 15.0],
            lows=[8.0, 12.5, 12.0, 13.0],
            closes=[9.0, 13.0, 14.0, 14.0],
        )
        r = detect_fvgs(df)
        assert len(r.events) == 1
        e = r.events[0]
        assert e.direction == "bullish"
        assert e.bottom == pytest.approx(10.0)
        assert e.top == pytest.approx(12.0)
        assert e.activation_pos == 2
        assert e.activation_timestamp == df.index[2]
        assert e.origin_pos == 1
        assert e.origin_timestamp == df.index[1]
        assert e.is_active_at(df.index[1]) is False
        assert e.is_active_at(df.index[2]) is True

    def test_bearish_gap_activates_on_third_close(self):
        # i-2=0 low=12, i=2 high=10 → gap [10, 12]
        df = _ohlc(
            highs=[13.0, 11.0, 10.0, 9.5],
            lows=[12.0, 9.0, 8.0, 8.0],
            closes=[12.5, 10.0, 9.0, 9.0],
        )
        r = detect_fvgs(df)
        assert len(r.events) == 1
        e = r.events[0]
        assert e.direction == "bearish"
        assert e.bottom == pytest.approx(10.0)
        assert e.top == pytest.approx(12.0)
        assert e.activation_pos == 2
        assert e.is_active_at(df.index[2] - pd.Timedelta(minutes=1)) is False
        assert e.is_active_at(df.index[2]) is True

    def test_equality_does_not_create_gap(self):
        # high[i-2] == low[i]
        df = _ohlc(
            highs=[10.0, 11.0, 12.0],
            lows=[9.0, 10.0, 10.0],
            closes=[9.5, 10.5, 11.0],
        )
        r = detect_fvgs(df)
        assert r.events == ()

        # low[i-2] == high[i]
        df2 = _ohlc(
            highs=[12.0, 11.0, 10.0],
            lows=[10.0, 9.0, 8.0],
            closes=[11.0, 10.0, 9.0],
        )
        assert detect_fvgs(df2).events == ()

    def test_no_fvg_before_third_bar(self):
        df = _ohlc(highs=[10.0, 11.0], lows=[9.0, 10.0], closes=[9.5, 10.5])
        assert detect_fvgs(df).events == ()

    def test_bottom_strictly_less_than_top(self):
        df = _ohlc(
            highs=[10.0, 20.0, 21.0],
            lows=[1.0, 15.0, 12.0],
            closes=[5.0, 18.0, 16.0],
        )
        e = detect_fvgs(df).events[0]
        assert e.bottom < e.top


# ---------------------------------------------------------------------------
# Lifecycle: first touch / fill / no same-bar fill
# ---------------------------------------------------------------------------


class TestFVGLifecycle:
    def test_activation_bar_cannot_touch_own_gap(self):
        # Bullish gap top == low[activation], so same-bar lifecycle would always
        # first-touch. Lifecycle must start next bar.
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 15.0],
            lows=[8.0, 12.5, 12.0, 13.0],
            closes=[9.0, 13.0, 14.0, 14.0],
        )
        e = detect_fvgs(df).events[0]
        assert e.activation_pos == 2
        assert e.top == pytest.approx(12.0)
        assert e.bottom == pytest.approx(10.0)
        assert e.first_touch_timestamp is None
        assert e.fill_timestamp is None
        assert e.is_active_at(df.index[2]) is True
        assert e.is_active_at(df.index[3]) is True

    def test_first_touch_and_fill_next_bars_bullish(self):
        # Gap activates at 2: [10, 12]. Bar 3 touches top only. Bar 4 fills.
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 13.0, 11.0],
            lows=[8.0, 12.5, 12.0, 11.5, 9.5],
            closes=[9.0, 13.0, 14.0, 12.0, 10.0],
        )
        e = detect_fvgs(df).events[0]
        assert e.first_touch_timestamp == df.index[3]
        assert e.fill_timestamp == df.index[4]
        assert e.is_first_test_at(df.index[2]) is True
        assert e.is_first_test_at(df.index[3]) is True  # inclusive first-touch bar
        assert e.is_first_test_at(df.index[4]) is False
        # Exclusive end: inactive at fill timestamp (aligned with order blocks).
        assert e.is_active_at(df.index[3]) is True
        assert e.is_active_at(df.index[4]) is False

    def test_bearish_touch_and_full_fill(self):
        # Gap [10, 12] bearish at bar 2. Bar 3 high=11 touches. Bar 4 high=12.5 fills.
        df = _ohlc(
            highs=[13.0, 11.0, 10.0, 11.0, 12.5],
            lows=[12.0, 9.0, 8.0, 9.0, 10.0],
            closes=[12.5, 10.0, 9.0, 10.5, 11.5],
        )
        e = detect_fvgs(df).events[0]
        assert e.direction == "bearish"
        assert e.first_touch_timestamp == df.index[3]
        assert e.fill_timestamp == df.index[4]

    def test_through_fill_sets_touch_and_fill_same_bar(self):
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 11.0],
            lows=[8.0, 12.5, 12.0, 9.0],
            closes=[9.0, 13.0, 14.0, 10.0],
        )
        e = detect_fvgs(df).events[0]
        assert e.first_touch_timestamp == df.index[3]
        assert e.fill_timestamp == df.index[3]
        # Same-bar through-fill: inactive at fill ts; first-test follows is_active.
        assert e.is_active_at(df.index[3]) is False
        assert e.is_first_test_at(df.index[3]) is False

    def test_age_expiry(self):
        # Activate bullish at bar 2; never touch; expire after 3 bars → bar 5.
        highs = [10.0, 14.0, 15.0] + [15.0] * 5
        lows = [8.0, 12.5, 12.0] + [13.0] * 5
        closes = [9.0, 13.0, 14.0] + [14.0] * 5
        df = _ohlc(highs=highs, lows=lows, closes=closes)
        r = detect_fvgs(df, expiry_bars=3)
        e = r.events[0]
        assert e.fill_timestamp is None
        assert e.expiry_timestamp == df.index[5]  # 2 + 3
        # Exclusive expiry boundary.
        assert e.is_active_at(df.index[4]) is True
        assert e.is_active_at(df.index[5]) is False

    def test_cap_expires_oldest(self):
        # Monotonic impulse: every i>=2 forms an unfilled bullish FVG, so the
        # active-per-direction cap is forced without accidental fills.
        n = 10
        lows = [float(i * 2) for i in range(n)]
        highs = [float(i * 2 + 1) for i in range(n)]
        closes = [float(i * 2 + 0.5) for i in range(n)]
        df = _ohlc(highs=highs, lows=lows, closes=closes)
        r = detect_fvgs(df, expiry_bars=200, max_active_per_direction=2)
        bulls = [e for e in r.events if e.direction == "bullish"]
        assert len(bulls) == n - 2
        assert all(e.fill_timestamp is None for e in bulls)
        assert any("fvg_cap_expiry" in d for d in r.diagnostics)
        # Historical as-of active count never exceeds the cap.
        for ts in df.index:
            active = sum(1 for e in bulls if e.is_active_at(ts))
            assert active <= 2
        # Oldest of the first three is expired when the third activates.
        first_three = sorted(bulls, key=lambda e: e.activation_pos)[:3]
        assert first_three[0].expiry_timestamp == first_three[2].activation_timestamp
        assert first_three[2].is_active_at(first_three[2].activation_timestamp)


# ---------------------------------------------------------------------------
# Prefix / scale / translation / index
# ---------------------------------------------------------------------------


class TestFVGInvariance:
    def test_prefix_invariance(self):
        highs = [10.0, 14.0, 15.0, 13.0, 11.0, 16.0, 17.0, 12.0]
        lows = [8.0, 12.5, 12.0, 11.5, 9.5, 13.0, 14.0, 10.0]
        closes = [9.0, 13.0, 14.0, 12.0, 10.0, 15.0, 16.0, 11.0]
        full = _ohlc(highs=highs, lows=lows, closes=closes)
        full_events = detect_fvgs(full).events

        for end in range(3, len(full) + 1):
            prefix = full.iloc[:end]
            pref_events = detect_fvgs(prefix).events
            # Events fully determined within prefix must match full head.
            expected = [e for e in full_events if e.activation_pos < end]
            # Lifecycle timestamps only resolved with bars present in prefix.
            assert len(pref_events) == len(expected)
            for a, b in zip(pref_events, expected):
                assert a.id == b.id
                assert a.direction == b.direction
                assert a.activation_pos == b.activation_pos
                assert a.top == pytest.approx(b.top)
                assert a.bottom == pytest.approx(b.bottom)
                # Touch/fill only if their bars are inside the prefix.
                if b.first_touch_timestamp is not None and b.first_touch_timestamp <= prefix.index[-1]:
                    assert a.first_touch_timestamp == b.first_touch_timestamp
                else:
                    assert a.first_touch_timestamp is None or a.first_touch_timestamp <= prefix.index[-1]
                if b.fill_timestamp is not None and b.fill_timestamp <= prefix.index[-1]:
                    assert a.fill_timestamp == b.fill_timestamp
                else:
                    assert a.fill_timestamp is None or a.fill_timestamp <= prefix.index[-1]

    def test_price_translation(self):
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 13.0, 9.0],
            lows=[8.0, 12.5, 12.0, 11.5, 8.0],
            closes=[9.0, 13.0, 14.0, 12.0, 8.5],
        )
        shift = 100.0
        shifted = df.copy()
        for col in ("open", "high", "low", "close"):
            shifted[col] = shifted[col] + shift
        a = detect_fvgs(df).events
        b = detect_fvgs(shifted).events
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert x.direction == y.direction
            assert y.top == pytest.approx(x.top + shift)
            assert y.bottom == pytest.approx(x.bottom + shift)
            assert (x.first_touch_timestamp is None) == (y.first_touch_timestamp is None)
            assert (x.fill_timestamp is None) == (y.fill_timestamp is None)
            if x.first_touch_timestamp is not None:
                assert x.first_touch_timestamp == y.first_touch_timestamp
            if x.fill_timestamp is not None:
                assert x.fill_timestamp == y.fill_timestamp

    def test_price_scale(self):
        df = _ohlc(
            highs=[10.0, 14.0, 15.0, 13.0, 9.0],
            lows=[8.0, 12.5, 12.0, 11.5, 8.0],
            closes=[9.0, 13.0, 14.0, 12.0, 8.5],
        )
        scale = 2.5
        scaled = df.copy()
        for col in ("open", "high", "low", "close"):
            scaled[col] = scaled[col] * scale
        a = detect_fvgs(df).events
        b = detect_fvgs(scaled).events
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert y.top == pytest.approx(x.top * scale)
            assert y.bottom == pytest.approx(x.bottom * scale)

    def test_timezone_preserved(self):
        df = _ohlc(
            highs=[10.0, 14.0, 15.0],
            lows=[8.0, 12.5, 12.0],
            closes=[9.0, 13.0, 14.0],
            tz="UTC",
        )
        e = detect_fvgs(df).events[0]
        assert e.activation_timestamp.tzinfo is not None
        assert str(e.activation_timestamp.tz) == "UTC"


class TestFVGValidation:
    def test_missing_columns(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=_idx(3))
        with pytest.raises(ValueError, match="missing"):
            detect_fvgs(df)

    def test_bad_expiry(self):
        df = _ohlc(highs=[1, 2, 3], lows=[0, 1, 2])
        with pytest.raises(ValueError):
            detect_fvgs(df, expiry_bars=0)
        with pytest.raises(TypeError):
            detect_fvgs(df, expiry_bars=1.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Bias
# ---------------------------------------------------------------------------


class TestBias:
    def test_bias_mirrors_structure_trend_exactly(self):
        df = _ohlc(highs=[1, 2, 3, 4, 5], lows=[0, 1, 2, 3, 4], closes=[0.5, 1.5, 2.5, 3.5, 4.5])
        trend = pd.Series(
            ["neutral", "neutral", "bull", "bull", "bear"],
            index=df.index,
            dtype=object,
            name="trend",
        )
        structure = _empty_structure(df)
        structure = StructureResult(
            events=structure.events,
            trend=trend,
            bos=structure.bos,
            choch=structure.choch,
            broken_level=structure.broken_level,
            last_swing_high=structure.last_swing_high,
            last_swing_low=structure.last_swing_low,
            swing_direction=structure.swing_direction,
        )
        bias = compute_bias_series(structure)
        assert list(bias) == ["neutral", "neutral", "bull", "bull", "bear"]
        assert bias.name == "bias"
        assert bias.index.equals(df.index)
        assert set(bias.unique()) <= {"bull", "bear", "neutral"}

    def test_neutral_not_replaced_by_prior(self):
        df = _ohlc(highs=[1, 2, 3], lows=[0, 1, 2], closes=[0.5, 1.5, 2.5])
        trend = pd.Series(["bull", "neutral", "bear"], index=df.index, dtype=object)
        structure = StructureResult(
            events=(),
            trend=trend,
            bos=pd.Series(np.nan, index=df.index),
            choch=pd.Series(np.nan, index=df.index),
            broken_level=pd.Series(np.nan, index=df.index),
            last_swing_high=pd.Series(np.nan, index=df.index),
            last_swing_low=pd.Series(np.nan, index=df.index),
            swing_direction=pd.Series(np.nan, index=df.index),
        )
        bias = compute_bias_series(structure)
        assert bias.iloc[1] == "neutral"

    def test_bias_from_live_structure_detect(self):
        # Minimal path: swings + structure produce trend series; bias equals it.
        n = 30
        closes = np.linspace(100, 110, n)
        highs = closes + 1.0
        lows = closes - 1.0
        # Plant a clear swing high/low pattern
        highs = highs.copy()
        lows = lows.copy()
        highs[5] = 120.0
        lows[10] = 90.0
        closes[5] = 119.0
        closes[10] = 91.0
        df = _ohlc(highs=highs.tolist(), lows=lows.tolist(), closes=closes.tolist())
        # Build synthetic activated swings for structure
        idx = df.index
        swings = SwingResult(
            events=(
                SwingEvent(
                    id=0,
                    direction="high",
                    level=120.0,
                    pivot_pos=5,
                    pivot_timestamp=idx[5],
                    activation_pos=7,
                    activation_timestamp=idx[7],
                ),
                SwingEvent(
                    id=1,
                    direction="low",
                    level=90.0,
                    pivot_pos=10,
                    pivot_timestamp=idx[10],
                    activation_pos=12,
                    activation_timestamp=idx[12],
                ),
            ),
            high_at_activation=pd.Series(np.nan, index=idx),
            low_at_activation=pd.Series(np.nan, index=idx),
        )
        # Force a bullish break of high after activation
        df.loc[idx[15], "close"] = 121.0
        structure = detect_structure(df, swings)
        bias = compute_bias_series(structure)
        assert bias.equals(structure.trend.rename("bias")) or list(bias) == list(structure.trend)


# ---------------------------------------------------------------------------
# Premium / discount context
# ---------------------------------------------------------------------------


class TestDealingRangeContext:
    def test_neutral_without_valid_range(self):
        df = _ohlc(
            highs=[10, 11, 12, 13],
            lows=[9, 10, 11, 12],
            closes=[9.5, 10.5, 11.5, 12.5],
        )
        structure = _empty_structure(df)
        ctx = compute_dealing_range_context(df, structure)
        assert isinstance(ctx, ContextResult)
        assert (ctx.zone == ZONE_NEUTRAL).all()
        assert ctx.equilibrium.isna().all()
        assert ctx.range_high.isna().all()
        assert ctx.range_low.isna().all()

    def test_neutral_when_only_one_side(self):
        df = _ohlc(highs=[10, 11, 12], lows=[9, 10, 11], closes=[9.5, 10.5, 11.5])
        structure = _structure_with_range(df, high=20.0, low=None, trend="bull")
        ctx = compute_dealing_range_context(df, structure)
        assert (ctx.zone == ZONE_NEUTRAL).all()

    def test_neutral_when_unordered_pair(self):
        df = _ohlc(highs=[10, 11, 12], lows=[9, 10, 11], closes=[9.5, 10.5, 11.5])
        structure = _structure_with_range(df, high=10.0, low=20.0, trend="bear")
        ctx = compute_dealing_range_context(df, structure)
        assert (ctx.zone == ZONE_NEUTRAL).all()

    def test_premium_discount_classification(self):
        # Range [100, 200], eq=150
        closes = [120.0, 150.0, 180.0]
        df = _ohlc(highs=[121, 151, 181], lows=[119, 149, 179], closes=closes)
        structure = _structure_with_range(df, high=200.0, low=100.0, trend="bull")
        ctx = compute_dealing_range_context(df, structure)
        assert ctx.zone.iloc[0] == ZONE_DISCOUNT
        assert ctx.zone.iloc[1] == ZONE_NEUTRAL
        assert ctx.zone.iloc[2] == ZONE_PREMIUM
        assert ctx.equilibrium.iloc[0] == pytest.approx(150.0)
        assert ctx.range_high.iloc[0] == pytest.approx(200.0)
        assert ctx.range_low.iloc[0] == pytest.approx(100.0)
        assert ctx.bias.iloc[0] == "bull"

    def test_snapshot_keys_for_compatibility(self):
        df = _ohlc(highs=[121, 151], lows=[119, 149], closes=[120.0, 180.0])
        structure = _structure_with_range(df, high=200.0, low=100.0, trend="bear")
        ctx = compute_dealing_range_context(df, structure)
        snap = context_snapshot(ctx, lookback=None)
        assert set(snap.keys()) == {
            "zone",
            "equilibrium",
            "range_high",
            "range_low",
            "current_price",
            "lookback",
        }
        assert snap["zone"] == ZONE_PREMIUM
        assert snap["current_price"] == pytest.approx(180.0)

    def test_is_in_pd_zone_direction(self):
        assert is_in_pd_zone(ZONE_DISCOUNT, "long") is True
        assert is_in_pd_zone(ZONE_PREMIUM, "short") is True
        assert is_in_pd_zone(ZONE_PREMIUM, "long") is False
        assert is_in_pd_zone(ZONE_NEUTRAL, "long") is False

    def test_context_prefix_invariance(self):
        closes = [120.0, 140.0, 160.0, 180.0, 130.0]
        df = _ohlc(
            highs=[c + 1 for c in closes],
            lows=[c - 1 for c in closes],
            closes=closes,
        )
        structure = _structure_with_range(df, high=200.0, low=100.0, trend="bull", from_bar=1)
        full = compute_dealing_range_context(df, structure)
        for end in range(1, len(df) + 1):
            sub_df = df.iloc[:end]
            sub_st = StructureResult(
                events=(),
                trend=structure.trend.iloc[:end],
                bos=structure.bos.iloc[:end],
                choch=structure.choch.iloc[:end],
                broken_level=structure.broken_level.iloc[:end],
                last_swing_high=structure.last_swing_high.iloc[:end],
                last_swing_low=structure.last_swing_low.iloc[:end],
                swing_direction=structure.swing_direction.iloc[:end],
            )
            sub = compute_dealing_range_context(sub_df, sub_st)
            assert list(sub.zone) == list(full.zone.iloc[:end])

    def test_context_translation_scale(self):
        closes = [120.0, 180.0]
        df = _ohlc(highs=[121, 181], lows=[119, 179], closes=closes)
        structure = _structure_with_range(df, high=200.0, low=100.0, trend="bull")
        base = compute_dealing_range_context(df, structure)

        shift = 50.0
        df_t = df.copy()
        for col in ("open", "high", "low", "close"):
            df_t[col] = df_t[col] + shift
        st_t = _structure_with_range(df_t, high=200.0 + shift, low=100.0 + shift, trend="bull")
        tr = compute_dealing_range_context(df_t, st_t)
        assert list(tr.zone) == list(base.zone)
        assert tr.equilibrium.iloc[0] == pytest.approx(base.equilibrium.iloc[0] + shift)

        scale = 3.0
        df_s = df.copy()
        for col in ("open", "high", "low", "close"):
            df_s[col] = df_s[col] * scale
        st_s = _structure_with_range(df_s, high=200.0 * scale, low=100.0 * scale, trend="bull")
        sc = compute_dealing_range_context(df_s, st_s)
        assert list(sc.zone) == list(base.zone)
        assert sc.equilibrium.iloc[0] == pytest.approx(base.equilibrium.iloc[0] * scale)

    def test_index_timezone_alignment(self):
        df = _ohlc(
            highs=[121, 181],
            lows=[119, 179],
            closes=[120.0, 180.0],
            tz="US/Eastern",
        )
        structure = _structure_with_range(df, high=200.0, low=100.0, trend="bull")
        ctx = compute_dealing_range_context(df, structure)
        assert ctx.zone.index.equals(df.index)
        assert ctx.bias.index.equals(df.index)
        assert str(ctx.zone.index.tz) == "US/Eastern"


class TestContextValidation:
    def test_mismatched_index_raises(self):
        df = _ohlc(highs=[1, 2, 3], lows=[0, 1, 2], closes=[0.5, 1.5, 2.5])
        other = df.iloc[:2]
        structure = _empty_structure(other)
        with pytest.raises(ValueError, match="index"):
            compute_dealing_range_context(df, structure)

    def test_bias_requires_structure_result(self):
        with pytest.raises(TypeError):
            compute_bias_series("nope")  # type: ignore[arg-type]
