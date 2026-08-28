"""Unit tests for causal Williams/fractal swing detection (Phase 1)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine import SwingEvent, SwingResult, detect_swings  # noqa: E402
from smc_engine.swings import detect_swings_symmetric  # noqa: E402


def _ohlc_from_high_low(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray | None = None,
    *,
    freq: str = "15min",
    start: str = "2024-01-01 00:00:00",
    tz: str | None = None,
) -> pd.DataFrame:
    """Build a minimal OHLC frame from high (and optional low) series."""
    highs_arr = np.asarray(highs, dtype=float)
    if lows is None:
        lows_arr = highs_arr - 1.0
    else:
        lows_arr = np.asarray(lows, dtype=float)
    n = len(highs_arr)
    idx = pd.date_range(start=start, periods=n, freq=freq, tz=tz)
    close = (highs_arr + lows_arr) / 2.0
    open_ = close.copy()
    return pd.DataFrame(
        {"open": open_, "high": highs_arr, "low": lows_arr, "close": close},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Fixtures — golden shapes
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_pivots() -> pd.DataFrame:
    """Clear isolated swing high and low with left=right=2.

    Positions (0-based):
      high: [1, 2, 5, 3, 2, 1, 2, 3, 2]
      low:  [0, 1, 2, 1, 0,-1, 0, 1, 0]

    Expected:
      - swing high at pivot 2 (level 5), activation 4
      - swing low  at pivot 5 (level -1), activation 7
    """
    highs = [1.0, 2.0, 5.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0]
    lows = [0.0, 1.0, 2.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0]
    return _ohlc_from_high_low(highs, lows)


@pytest.fixture
def equal_highs() -> pd.DataFrame:
    """Two equal candidate highs; earliest-equal policy keeps the first.

    highs: plateau twin peaks of 10 at positions 2 and 3, with right=2.
    At i=2: left max=2, right max=max(10,4)=10 → 10>2 and 10>=10 → high.
    At i=3: left max=max(2,10)=10 → 10>10 is False → not a high.
    """
    highs = [1.0, 2.0, 10.0, 10.0, 4.0, 3.0, 2.0]
    lows = [0.0, 1.0, 5.0, 5.0, 2.0, 1.0, 0.0]
    return _ohlc_from_high_low(highs, lows)


@pytest.fixture
def equal_lows() -> pd.DataFrame:
    """Two equal candidate lows; earliest-equal policy keeps the first."""
    highs = [5.0, 4.0, 3.0, 3.0, 4.0, 5.0, 6.0]
    lows = [4.0, 3.0, 0.0, 0.0, 2.0, 3.0, 4.0]
    return _ohlc_from_high_low(highs, lows)


@pytest.fixture
def asymmetric_windows() -> pd.DataFrame:
    """left=1, right=3 — activation lag differs from left lookback."""
    # Need enough bars: pivot range [1, n-3-1] = [1, n-4]
    highs = [1.0, 2.0, 8.0, 3.0, 2.0, 1.0, 1.5, 2.0]
    lows = [0.0, 1.0, 4.0, 2.0, 1.0, 0.5, 0.8, 1.0]
    return _ohlc_from_high_low(highs, lows)


# ---------------------------------------------------------------------------
# Contract / import surface
# ---------------------------------------------------------------------------


class TestContracts:
    def test_swing_event_frozen(self):
        ev = SwingEvent(
            id=0,
            direction="high",
            level=1.5,
            pivot_pos=2,
            pivot_timestamp=pd.Timestamp("2024-01-01"),
            activation_pos=4,
            activation_timestamp=pd.Timestamp("2024-01-01 00:30"),
        )
        with pytest.raises(Exception):
            ev.level = 9.0  # type: ignore[misc]

    def test_swing_result_frozen(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        assert isinstance(result, SwingResult)
        with pytest.raises(Exception):
            result.events = ()  # type: ignore[misc]

    def test_events_are_swing_event_instances(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        assert all(isinstance(e, SwingEvent) for e in result.events)


# ---------------------------------------------------------------------------
# Isolated pivots
# ---------------------------------------------------------------------------


class TestIsolatedPivots:
    def test_detects_high_and_low(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        directions = [e.direction for e in result.events]
        assert "high" in directions
        assert "low" in directions

    def test_high_pivot_and_activation(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        highs = [e for e in result.events if e.direction == "high"]
        assert len(highs) == 1
        h = highs[0]
        assert h.pivot_pos == 2
        assert h.level == 5.0
        assert h.activation_pos == 4
        assert h.activation_pos == h.pivot_pos + 2

    def test_low_pivot_and_activation(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        lows = [e for e in result.events if e.direction == "low"]
        assert len(lows) == 1
        lo = lows[0]
        assert lo.pivot_pos == 5
        assert lo.level == -1.0
        assert lo.activation_pos == 7
        assert lo.activation_pos == lo.pivot_pos + 2

    def test_activation_aligned_series(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        assert result.high_at_activation.iloc[4] == 5.0
        assert result.low_at_activation.iloc[7] == -1.0
        # Sparse elsewhere
        assert result.high_at_activation.isna().sum() == len(isolated_pivots) - 1
        assert result.low_at_activation.isna().sum() == len(isolated_pivots) - 1

    def test_timestamps_match_index(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        for e in result.events:
            assert e.pivot_timestamp == isolated_pivots.index[e.pivot_pos]
            assert e.activation_timestamp == isolated_pivots.index[e.activation_pos]

    def test_ids_are_unique_sequential(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        ids = [e.id for e in result.events]
        assert ids == list(range(len(ids)))


# ---------------------------------------------------------------------------
# Equal-level (earliest) tie policy
# ---------------------------------------------------------------------------


class TestEqualLevelTies:
    def test_earliest_equal_high(self, equal_highs):
        result = detect_swings(equal_highs, left=2, right=2)
        highs = [e for e in result.events if e.direction == "high"]
        assert len(highs) == 1
        assert highs[0].pivot_pos == 2
        assert highs[0].level == 10.0
        # Later equal peak must not emit
        assert all(e.pivot_pos != 3 for e in highs)

    def test_earliest_equal_low(self, equal_lows):
        result = detect_swings(equal_lows, left=2, right=2)
        lows = [e for e in result.events if e.direction == "low"]
        assert len(lows) == 1
        assert lows[0].pivot_pos == 2
        assert lows[0].level == 0.0
        assert all(e.pivot_pos != 3 for e in lows)

    def test_flat_series_no_pivots(self):
        df = _ohlc_from_high_low([5.0] * 12, [4.0] * 12)
        result = detect_swings(df, left=2, right=2)
        assert result.events == ()
        assert result.high_at_activation.isna().all()
        assert result.low_at_activation.isna().all()


# ---------------------------------------------------------------------------
# Asymmetric windows
# ---------------------------------------------------------------------------


class TestAsymmetricWindows:
    def test_activation_uses_right_only(self, asymmetric_windows):
        left, right = 1, 3
        result = detect_swings(asymmetric_windows, left=left, right=right)
        assert len(result.events) >= 1
        for e in result.events:
            assert e.activation_pos == e.pivot_pos + right
            assert e.activation_pos != e.pivot_pos + left or left == right

    def test_high_confirmed_with_asymmetric(self, asymmetric_windows):
        result = detect_swings(asymmetric_windows, left=1, right=3)
        highs = [e for e in result.events if e.direction == "high"]
        assert any(e.pivot_pos == 2 and e.level == 8.0 for e in highs)
        h = next(e for e in highs if e.pivot_pos == 2)
        assert h.activation_pos == 5


# ---------------------------------------------------------------------------
# Edge cases: short / boundary data
# ---------------------------------------------------------------------------


class TestShortAndBoundary:
    def test_too_short_for_windows_returns_empty(self):
        df = _ohlc_from_high_low([1, 3, 2, 1], [0, 1, 0, 0])
        # left=2,right=2 needs at least left+right+1 = 5 bars
        result = detect_swings(df, left=2, right=2)
        assert result.events == ()

    def test_exact_minimum_length_can_emit(self):
        # left=2,right=2 → candidate only at i=2 for n=5
        highs = [1.0, 2.0, 9.0, 3.0, 2.0]
        lows = [0.0, 1.0, 4.0, 2.0, 1.0]
        df = _ohlc_from_high_low(highs, lows)
        result = detect_swings(df, left=2, right=2)
        highs_ev = [e for e in result.events if e.direction == "high"]
        assert len(highs_ev) == 1
        assert highs_ev[0].pivot_pos == 2
        assert highs_ev[0].activation_pos == 4

    def test_boundary_positions_never_emit(self):
        # Peak at index 0 and at last bar must never confirm
        highs = [10.0, 1.0, 2.0, 3.0, 4.0, 10.0]
        lows = [9.0, 0.0, 1.0, 2.0, 3.0, 9.0]
        df = _ohlc_from_high_low(highs, lows)
        result = detect_swings(df, left=2, right=2)
        for e in result.events:
            assert e.pivot_pos >= 2
            assert e.pivot_pos <= len(df) - 2 - 1


# ---------------------------------------------------------------------------
# Prefix invariance (no repainting)
# ---------------------------------------------------------------------------


class TestPrefixInvariance:
    def test_prefix_matches_full_history_activated_events(self):
        rng = np.random.default_rng(42)
        n = 80
        noise = rng.normal(0, 1, size=n).cumsum()
        highs = noise + 2.0
        lows = noise - 2.0
        df = _ohlc_from_high_low(highs, lows)
        left = right = 3
        full = detect_swings(df, left=left, right=right)

        for cut in (30, 45, 60, n):
            prefix = detect_swings(df.iloc[:cut], left=left, right=right)
            # Every prefix event must appear identically in the full result
            # (same pivot, activation, level, direction).
            full_by_key = {
                (e.direction, e.pivot_pos, e.activation_pos, e.level): e
                for e in full.events
                if e.activation_pos < cut
            }
            prefix_keys = {
                (e.direction, e.pivot_pos, e.activation_pos, e.level)
                for e in prefix.events
            }
            assert prefix_keys == set(full_by_key.keys())

            # Series values up to cut-1 must match for already-activated slots
            assert np.allclose(
                prefix.high_at_activation.to_numpy(),
                full.high_at_activation.iloc[:cut].to_numpy(),
                equal_nan=True,
            )
            assert np.allclose(
                prefix.low_at_activation.to_numpy(),
                full.low_at_activation.iloc[:cut].to_numpy(),
                equal_nan=True,
            )

    def test_appending_bars_does_not_change_prior_activations(self):
        base = _ohlc_from_high_low(
            [1, 2, 5, 3, 2, 1, 2, 3, 2],
            [0, 1, 2, 1, 0, -1, 0, 1, 0],
        )
        first = detect_swings(base, left=2, right=2)
        extended = pd.concat(
            [
                base,
                _ohlc_from_high_low(
                    [4, 6, 3],
                    [1, 2, 0],
                    start=str(base.index[-1] + pd.Timedelta(minutes=15)),
                ),
            ]
        )
        second = detect_swings(extended, left=2, right=2)
        prior = [
            (e.direction, e.pivot_pos, e.activation_pos, e.level)
            for e in second.events
            if e.activation_pos < len(base)
        ]
        original = [
            (e.direction, e.pivot_pos, e.activation_pos, e.level)
            for e in first.events
        ]
        assert prior == original


# ---------------------------------------------------------------------------
# Index / timezone preservation
# ---------------------------------------------------------------------------


class TestIndexAndTimezone:
    def test_timezone_preserved(self):
        df = _ohlc_from_high_low(
            [1, 2, 5, 3, 2, 1, 2, 3, 2],
            [0, 1, 2, 1, 0, -1, 0, 1, 0],
            tz="UTC",
        )
        result = detect_swings(df, left=2, right=2)
        assert result.high_at_activation.index.tz is not None
        assert str(result.high_at_activation.index.tz) == "UTC"
        assert result.low_at_activation.index.equals(df.index)
        for e in result.events:
            assert e.pivot_timestamp.tzinfo is not None
            assert e.activation_timestamp.tzinfo is not None

    def test_index_identity_preserved(self, isolated_pivots):
        result = detect_swings(isolated_pivots, left=2, right=2)
        assert result.high_at_activation.index.equals(isolated_pivots.index)
        assert result.low_at_activation.index.equals(isolated_pivots.index)


# ---------------------------------------------------------------------------
# Translation / scale invariance
# ---------------------------------------------------------------------------


class TestTranslationScaleInvariance:
    def test_price_translation_preserves_positions(self, isolated_pivots):
        shift = 1000.0
        translated = isolated_pivots.copy()
        for col in ("open", "high", "low", "close"):
            translated[col] = translated[col] + shift
        base = detect_swings(isolated_pivots, left=2, right=2)
        moved = detect_swings(translated, left=2, right=2)
        assert [(e.direction, e.pivot_pos, e.activation_pos) for e in base.events] == [
            (e.direction, e.pivot_pos, e.activation_pos) for e in moved.events
        ]
        for a, b in zip(base.events, moved.events):
            assert b.level == pytest.approx(a.level + shift)

    def test_positive_scale_preserves_positions(self, isolated_pivots):
        scale = 3.5
        scaled = isolated_pivots.copy()
        for col in ("open", "high", "low", "close"):
            scaled[col] = scaled[col] * scale
        base = detect_swings(isolated_pivots, left=2, right=2)
        scaled_res = detect_swings(scaled, left=2, right=2)
        assert [(e.direction, e.pivot_pos, e.activation_pos) for e in base.events] == [
            (e.direction, e.pivot_pos, e.activation_pos) for e in scaled_res.events
        ]
        for a, b in zip(base.events, scaled_res.events):
            assert b.level == pytest.approx(a.level * scale)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_columns(self):
        df = pd.DataFrame({"open": [1.0], "close": [1.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            detect_swings(df)

    def test_non_positive_left(self, isolated_pivots):
        with pytest.raises(ValueError, match="left"):
            detect_swings(isolated_pivots, left=0, right=2)
        with pytest.raises(ValueError, match="left"):
            detect_swings(isolated_pivots, left=-1, right=2)

    def test_non_positive_right(self, isolated_pivots):
        with pytest.raises(ValueError, match="right"):
            detect_swings(isolated_pivots, left=2, right=0)

    def test_duplicate_index(self):
        df = _ohlc_from_high_low([1, 2, 5, 3, 2, 1, 2])
        idx = list(df.index)
        idx[3] = idx[2]
        df = df.copy()
        df.index = pd.DatetimeIndex(idx)
        with pytest.raises(ValueError, match="unique"):
            detect_swings(df, left=2, right=2)

    def test_non_monotonic_index(self):
        df = _ohlc_from_high_low([1, 2, 5, 3, 2, 1, 2, 3, 2])
        df = df.iloc[::-1]
        with pytest.raises(ValueError, match="monotonic"):
            detect_swings(df, left=2, right=2)

    def test_symmetric_wrapper(self, isolated_pivots):
        a = detect_swings(isolated_pivots, left=2, right=2)
        b = detect_swings_symmetric(isolated_pivots, swing_length=2)
        assert [
            (e.direction, e.pivot_pos, e.activation_pos, e.level) for e in a.events
        ] == [
            (e.direction, e.pivot_pos, e.activation_pos, e.level) for e in b.events
        ]


# ---------------------------------------------------------------------------
# Activation invariant for every event
# ---------------------------------------------------------------------------


class TestActivationInvariant:
    def test_activation_pos_equals_pivot_plus_right(self):
        rng = np.random.default_rng(7)
        noise = rng.normal(0, 1, size=100).cumsum()
        df = _ohlc_from_high_low(noise + 1.5, noise - 1.5)
        for left, right in ((1, 1), (2, 2), (1, 4), (3, 2)):
            result = detect_swings(df, left=left, right=right)
            for e in result.events:
                assert e.activation_pos == e.pivot_pos + right
                assert result.high_at_activation.index[e.activation_pos] == e.activation_timestamp
                if e.direction == "high":
                    assert result.high_at_activation.iloc[e.activation_pos] == e.level
                else:
                    assert result.low_at_activation.iloc[e.activation_pos] == e.level
