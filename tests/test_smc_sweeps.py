"""Golden tests for one-shot liquidity sweeps (Phase 4)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.events import SwingEvent, SwingResult  # noqa: E402
from smc_engine.sweeps import (  # noqa: E402
    SweepDiagnostic,
    SweepEvent,
    SweepResult,
    detect_sweeps,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _idx(n: int, *, tz: str | None = None, freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq=freq, tz=tz)


def _ohlc(
    highs: list[float] | np.ndarray,
    lows: list[float] | np.ndarray,
    closes: list[float] | np.ndarray,
    *,
    opens: list[float] | np.ndarray | None = None,
    tz: str | None = None,
) -> pd.DataFrame:
    n = len(highs)
    assert n == len(lows) == len(closes)
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


def _const_atr(df: pd.DataFrame, value: float = 1.0) -> pd.Series:
    return pd.Series(value, index=df.index, name="atr", dtype=float)


def _swing(
    id_: int,
    direction: str,
    level: float,
    pivot_pos: int,
    activation_pos: int,
    index: pd.DatetimeIndex,
) -> SwingEvent:
    return SwingEvent(
        id=id_,
        direction=direction,  # type: ignore[arg-type]
        level=float(level),
        pivot_pos=pivot_pos,
        pivot_timestamp=index[pivot_pos],
        activation_pos=activation_pos,
        activation_timestamp=index[activation_pos],
    )


def _empty_swings(df: pd.DataFrame) -> SwingResult:
    nan = pd.Series(np.nan, index=df.index, dtype=float)
    return SwingResult(
        events=(),
        high_at_activation=nan.rename("high_at_activation"),
        low_at_activation=nan.rename("low_at_activation"),
    )


def _result_from_events(df: pd.DataFrame, events: list[SwingEvent]) -> SwingResult:
    high_at = pd.Series(np.nan, index=df.index, dtype=float, name="high_at_activation")
    low_at = pd.Series(np.nan, index=df.index, dtype=float, name="low_at_activation")
    for e in events:
        if e.direction == "high":
            high_at.iloc[e.activation_pos] = e.level
        else:
            low_at.iloc[e.activation_pos] = e.level
    return SwingResult(events=tuple(events), high_at_activation=high_at, low_at_activation=low_at)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class TestContracts:
    def test_sweep_event_frozen(self):
        idx = _idx(3)
        ev = SweepEvent(
            id=0,
            direction="bullish",
            activation_pos=1,
            activation_timestamp=idx[1],
            source_swing_id=0,
            swept_level=100.0,
            wick_atr=0.5,
            close_location=0.8,
            range_expansion=False,
        )
        with pytest.raises(Exception):
            ev.direction = "bearish"  # type: ignore[misc]

    def test_result_types(self):
        df = _ohlc([1, 1, 1], [0, 0, 0], [0.5, 0.5, 0.5])
        out = detect_sweeps(df, _empty_swings(df), _const_atr(df))
        assert isinstance(out, SweepResult)
        assert out.events == ()
        assert out.diagnostics == ()


# ---------------------------------------------------------------------------
# Bullish / bearish paths
# ---------------------------------------------------------------------------


class TestBullishDownsideGrab:
    def test_emits_one_bullish_sweep(self):
        # Swing low activates at bar 2 (level=100). Bar 3 grabs below and reclaims.
        n = 6
        df = _ohlc(
            highs=[101, 101, 101, 101, 101, 101],
            lows=[99, 99, 99, 99.0, 99, 99],
            closes=[100, 100, 100, 100.5, 100, 100],
        )
        # Force the sweep bar geometry: low takes 100 by buffer, close above 100.
        df.iloc[3, df.columns.get_loc("low")] = 99.9  # level 100, atr=1, buf=0.05 → need low <= 99.95
        df.iloc[3, df.columns.get_loc("high")] = 100.8
        df.iloc[3, df.columns.get_loc("close")] = 100.2
        df.iloc[3, df.columns.get_loc("open")] = 100.0

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        e = out.events[0]
        assert e.direction == "bullish"
        assert e.source_swing_id == 0
        assert e.swept_level == pytest.approx(100.0)
        assert e.activation_pos == 3
        assert e.activation_timestamp == df.index[3]
        assert e.wick_atr == pytest.approx((100.0 - 99.9) / 1.0)
        assert 0.0 <= e.close_location <= 1.0
        assert out.diagnostics == ()


class TestBearishUpsideGrab:
    def test_emits_one_bearish_sweep(self):
        n = 6
        df = _ohlc(
            highs=[101, 101, 101, 101, 101, 101],
            lows=[99, 99, 99, 99, 99, 99],
            closes=[100, 100, 100, 100, 100, 100],
        )
        df.iloc[3, df.columns.get_loc("high")] = 100.1  # level 100, need high >= 100.05
        df.iloc[3, df.columns.get_loc("low")] = 99.2
        df.iloc[3, df.columns.get_loc("close")] = 99.8
        df.iloc[3, df.columns.get_loc("open")] = 100.0

        sw = _swing(0, "high", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        e = out.events[0]
        assert e.direction == "bearish"
        assert e.source_swing_id == 0
        assert e.swept_level == pytest.approx(100.0)
        assert e.activation_pos == 3
        assert e.wick_atr == pytest.approx((100.1 - 100.0) / 1.0)


# ---------------------------------------------------------------------------
# Same-bar activation ordering
# ---------------------------------------------------------------------------


class TestActivationOrdering:
    def test_same_close_activation_not_eligible_until_next_bar(self):
        """Swing activates at bar i; sweep geometry on bar i must not fire."""
        df = _ohlc(
            highs=[101, 101, 102, 101, 101],
            lows=[99, 99, 98.0, 99, 99],
            closes=[100, 100, 100.5, 100, 100],
        )
        # Bar 2 would be a perfect bullish sweep of level 100, but activation is also bar 2.
        df.iloc[2, df.columns.get_loc("low")] = 99.9
        df.iloc[2, df.columns.get_loc("close")] = 100.2
        df.iloc[2, df.columns.get_loc("high")] = 100.8

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert out.events == (), "must not sweep on the activation bar itself"

        # Same geometry on the *next* bar should fire.
        df2 = df.copy()
        df2.iloc[3, df2.columns.get_loc("low")] = 99.9
        df2.iloc[3, df2.columns.get_loc("close")] = 100.2
        df2.iloc[3, df2.columns.get_loc("high")] = 100.8
        out2 = detect_sweeps(df2, swings, atr, atr_buffer=0.05)
        assert len(out2.events) == 1
        assert out2.events[0].activation_pos == 3


# ---------------------------------------------------------------------------
# One-shot / repeated wick
# ---------------------------------------------------------------------------


class TestRepeatedWickOneShot:
    def test_repeated_wicks_do_not_duplicate(self):
        df = _ohlc(
            highs=[101] * 8,
            lows=[99] * 8,
            closes=[100] * 8,
        )
        for i in (3, 4, 5):
            df.iloc[i, df.columns.get_loc("low")] = 99.9
            df.iloc[i, df.columns.get_loc("close")] = 100.2
            df.iloc[i, df.columns.get_loc("high")] = 100.8

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        assert out.events[0].activation_pos == 3
        assert out.events[0].source_swing_id == 0


# ---------------------------------------------------------------------------
# Replacement level
# ---------------------------------------------------------------------------


class TestReplacementSwing:
    def test_new_swing_enables_new_sweep(self):
        df = _ohlc(
            highs=[101] * 10,
            lows=[99] * 10,
            closes=[100] * 10,
        )
        # First sweep of level 100 at bar 3
        df.iloc[3, df.columns.get_loc("low")] = 99.9
        df.iloc[3, df.columns.get_loc("close")] = 100.2
        df.iloc[3, df.columns.get_loc("high")] = 100.8
        # Replacement low activates at bar 5 (level 98)
        # Sweep of 98 at bar 7
        df.iloc[7, df.columns.get_loc("low")] = 97.9
        df.iloc[7, df.columns.get_loc("close")] = 98.2
        df.iloc[7, df.columns.get_loc("high")] = 98.8

        sw0 = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        sw1 = _swing(1, "low", 98.0, pivot_pos=3, activation_pos=5, index=df.index)
        swings = _result_from_events(df, [sw0, sw1])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 2
        assert out.events[0].source_swing_id == 0
        assert out.events[0].swept_level == pytest.approx(100.0)
        assert out.events[1].source_swing_id == 1
        assert out.events[1].swept_level == pytest.approx(98.0)
        assert out.events[1].activation_pos == 7

    def test_replacement_without_prior_sweep_still_tracks_latest(self):
        """Newer swing replaces an unswept level; old level is no longer eligible."""
        df = _ohlc(
            highs=[101] * 8,
            lows=[99] * 8,
            closes=[100] * 8,
        )
        # Would-be sweep of old level 100 at bar 6 — should NOT fire after replacement.
        df.iloc[6, df.columns.get_loc("low")] = 99.9
        df.iloc[6, df.columns.get_loc("close")] = 100.2
        df.iloc[6, df.columns.get_loc("high")] = 100.8
        # Sweep of new level 95 at bar 6 instead (geometry for 95)
        df.iloc[6, df.columns.get_loc("low")] = 94.9
        df.iloc[6, df.columns.get_loc("close")] = 95.2
        df.iloc[6, df.columns.get_loc("high")] = 95.8

        sw0 = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        sw1 = _swing(1, "low", 95.0, pivot_pos=2, activation_pos=4, index=df.index)
        swings = _result_from_events(df, [sw0, sw1])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        assert out.events[0].source_swing_id == 1
        assert out.events[0].swept_level == pytest.approx(95.0)


# ---------------------------------------------------------------------------
# Dual-sided ambiguous bar
# ---------------------------------------------------------------------------


class TestDualSided:
    def test_dual_sided_emits_diagnostic_not_event(self):
        df = _ohlc(
            highs=[110] * 6,
            lows=[90] * 6,
            closes=[100] * 6,
        )
        # Bar 3 takes both sides of 100-high and 100-low with reclaim/reject.
        # active high=105, active low=95 for a clearer dual case.
        df.iloc[3, df.columns.get_loc("high")] = 105.2
        df.iloc[3, df.columns.get_loc("low")] = 94.8
        df.iloc[3, df.columns.get_loc("close")] = 100.0  # above low 95, below high 105
        df.iloc[3, df.columns.get_loc("open")] = 100.0

        hi = _swing(0, "high", 105.0, pivot_pos=0, activation_pos=2, index=df.index)
        lo = _swing(1, "low", 95.0, pivot_pos=1, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [hi, lo])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert out.events == ()
        assert len(out.diagnostics) == 1
        d = out.diagnostics[0]
        assert isinstance(d, SweepDiagnostic)
        assert d.code == "dual_sided"
        assert d.pos == 3
        assert d.high_swing_id == 0
        assert d.low_swing_id == 1


# ---------------------------------------------------------------------------
# Exact threshold / equality
# ---------------------------------------------------------------------------


class TestExactThreshold:
    def test_wick_exact_buffer_distance_counts(self):
        """Wick extension == ATR×buffer must fire (threshold uses >=)."""
        level = 100.0
        atr_v = 2.0
        buf = 0.05
        threshold = atr_v * buf  # identical float path as detector
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
        )
        df.iloc[3, df.columns.get_loc("low")] = level - threshold
        df.iloc[3, df.columns.get_loc("close")] = level + 0.1
        df.iloc[3, df.columns.get_loc("high")] = level + 0.5

        sw = _swing(0, "low", level, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, atr_v)

        out = detect_sweeps(df, swings, atr, atr_buffer=buf)
        assert len(out.events) == 1
        assert out.events[0].wick_atr == pytest.approx(buf)

    def test_wick_just_short_of_buffer_does_not_count(self):
        level = 100.0
        atr_v = 2.0
        buf = 0.05
        threshold = atr_v * buf
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
        )
        # Half the required extension — clearly short of threshold.
        df.iloc[3, df.columns.get_loc("low")] = level - (threshold * 0.5)
        df.iloc[3, df.columns.get_loc("close")] = level + 0.1
        df.iloc[3, df.columns.get_loc("high")] = level + 0.5

        sw = _swing(0, "low", level, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, atr_v)

        out = detect_sweeps(df, swings, atr, atr_buffer=buf)
        assert out.events == ()

    def test_close_equal_level_does_not_reclaim(self):
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
        )
        df.iloc[3, df.columns.get_loc("low")] = 99.8
        df.iloc[3, df.columns.get_loc("close")] = 100.0  # equality — not a reclaim
        df.iloc[3, df.columns.get_loc("high")] = 100.5

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert out.events == ()

    def test_zero_buffer_requires_strict_level_take_only(self):
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
        )
        df.iloc[3, df.columns.get_loc("low")] = 99.999
        df.iloc[3, df.columns.get_loc("close")] = 100.001
        df.iloc[3, df.columns.get_loc("high")] = 100.5

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.0)
        assert len(out.events) == 1


# ---------------------------------------------------------------------------
# NaN ATR / OHLC
# ---------------------------------------------------------------------------


class TestNaNHandling:
    def test_nan_atr_skips_sweep(self):
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
        )
        df.iloc[3, df.columns.get_loc("low")] = 99.8
        df.iloc[3, df.columns.get_loc("close")] = 100.2
        df.iloc[3, df.columns.get_loc("high")] = 100.8

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)
        atr.iloc[3] = np.nan

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert out.events == ()

    def test_nan_ohlc_bar_skips_without_consuming(self):
        df = _ohlc(
            highs=[101] * 6,
            lows=[99] * 6,
            closes=[100] * 6,
        )
        # Bar 3 is NaN (gap); bar 4 is a clean sweep — must still fire.
        df.iloc[3] = np.nan
        df.iloc[4, df.columns.get_loc("low")] = 99.8
        df.iloc[4, df.columns.get_loc("close")] = 100.2
        df.iloc[4, df.columns.get_loc("high")] = 100.8
        df.iloc[4, df.columns.get_loc("open")] = 100.0

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        assert out.events[0].activation_pos == 4


# ---------------------------------------------------------------------------
# Timezone / index preservation
# ---------------------------------------------------------------------------


class TestTimezone:
    def test_timezone_aware_timestamps_preserved(self):
        df = _ohlc(
            highs=[101] * 5,
            lows=[99] * 5,
            closes=[100] * 5,
            tz="UTC",
        )
        df.iloc[3, df.columns.get_loc("low")] = 99.8
        df.iloc[3, df.columns.get_loc("close")] = 100.2
        df.iloc[3, df.columns.get_loc("high")] = 100.8

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)

        out = detect_sweeps(df, swings, atr, atr_buffer=0.05)
        assert len(out.events) == 1
        ts = out.events[0].activation_timestamp
        assert ts.tzinfo is not None
        assert str(ts.tzinfo) in ("UTC", "UTC+00:00") or ts.tz is not None


# ---------------------------------------------------------------------------
# Prefix invariance
# ---------------------------------------------------------------------------


class TestPrefixInvariance:
    def test_prefix_matches_full_history(self):
        rng = np.random.default_rng(7)
        n = 60
        # Synthetic path with planted swings + occasional deep wicks
        close = 100 + np.cumsum(rng.normal(0, 0.3, size=n))
        high = close + rng.uniform(0.2, 1.5, size=n)
        low = close - rng.uniform(0.2, 1.5, size=n)
        open_ = close + rng.normal(0, 0.1, size=n)
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close},
            index=_idx(n),
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)

        # Hand-craft alternating activated swings every few bars
        events: list[SwingEvent] = []
        sid = 0
        for act in range(2, n - 1, 5):
            direction = "low" if sid % 2 == 0 else "high"
            level = float(low[act - 2] if direction == "low" else high[act - 2])
            events.append(
                _swing(sid, direction, level, pivot_pos=act - 2, activation_pos=act, index=df.index)
            )
            sid += 1
        swings = _result_from_events(df, events)

        full = detect_sweeps(df, swings, atr, atr_buffer=0.05)

        for cut in (20, 35, 50, n):
            pref_df = df.iloc[:cut]
            pref_events = [e for e in events if e.activation_pos < cut]
            # Rebuild swing result on prefix index
            pref_swings = _result_from_events(pref_df, [
                SwingEvent(
                    id=e.id,
                    direction=e.direction,
                    level=e.level,
                    pivot_pos=e.pivot_pos,
                    pivot_timestamp=pref_df.index[e.pivot_pos],
                    activation_pos=e.activation_pos,
                    activation_timestamp=pref_df.index[e.activation_pos],
                )
                for e in pref_events
                if e.pivot_pos < cut
            ])
            pref_atr = atr.iloc[:cut]
            pref = detect_sweeps(pref_df, pref_swings, pref_atr, atr_buffer=0.05)

            full_keys = {
                (e.direction, e.activation_pos, e.source_swing_id, e.swept_level)
                for e in full.events
                if e.activation_pos < cut
            }
            pref_keys = {
                (e.direction, e.activation_pos, e.source_swing_id, e.swept_level)
                for e in pref.events
            }
            assert pref_keys == full_keys

            full_diag = {
                (d.pos, d.code, d.high_swing_id, d.low_swing_id)
                for d in full.diagnostics
                if d.pos < cut
            }
            pref_diag = {
                (d.pos, d.code, d.high_swing_id, d.low_swing_id)
                for d in pref.diagnostics
            }
            assert pref_diag == full_diag

    def test_appending_bars_does_not_change_prior_events(self):
        df = _ohlc(
            highs=[101] * 6,
            lows=[99] * 6,
            closes=[100] * 6,
        )
        df.iloc[3, df.columns.get_loc("low")] = 99.8
        df.iloc[3, df.columns.get_loc("close")] = 100.2
        df.iloc[3, df.columns.get_loc("high")] = 100.8

        sw = _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=df.index)
        swings = _result_from_events(df, [sw])
        atr = _const_atr(df, 1.0)
        first = detect_sweeps(df, swings, atr, atr_buffer=0.05)

        extra = _ohlc(
            highs=[102, 103],
            lows=[98, 97],
            closes=[100, 99],
        )
        # Shift extra index to continue after df
        extra.index = pd.date_range(
            df.index[-1] + pd.Timedelta(minutes=15), periods=2, freq="15min"
        )
        extended = pd.concat([df, extra])
        # Same swing still only activates inside original range
        sw_ext = _result_from_events(extended, [
            _swing(0, "low", 100.0, pivot_pos=0, activation_pos=2, index=extended.index)
        ])
        atr_ext = _const_atr(extended, 1.0)
        second = detect_sweeps(extended, sw_ext, atr_ext, atr_buffer=0.05)

        prior = [
            (e.direction, e.activation_pos, e.source_swing_id, e.swept_level)
            for e in second.events
            if e.activation_pos < len(df)
        ]
        original = [
            (e.direction, e.activation_pos, e.source_swing_id, e.swept_level)
            for e in first.events
        ]
        assert prior == original


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_ohlc_raises(self):
        df = pd.DataFrame({"open": [1], "high": [2], "close": [1.5]}, index=_idx(1))
        with pytest.raises(ValueError, match="OHLC"):
            detect_sweeps(df, _empty_swings(df), _const_atr(df))

    def test_negative_buffer_raises(self):
        df = _ohlc([1], [0], [0.5])
        with pytest.raises(ValueError, match="atr_buffer"):
            detect_sweeps(df, _empty_swings(df), _const_atr(df), atr_buffer=-0.1)

    def test_bool_buffer_raises(self):
        df = _ohlc([1], [0], [0.5])
        with pytest.raises(ValueError, match="atr_buffer"):
            detect_sweeps(df, _empty_swings(df), _const_atr(df), atr_buffer=True)  # type: ignore[arg-type]

    def test_non_series_atr_raises(self):
        df = _ohlc([1], [0], [0.5])
        with pytest.raises(TypeError, match="atr"):
            detect_sweeps(df, _empty_swings(df), [1.0])  # type: ignore[arg-type]

    def test_bad_swings_type_raises(self):
        df = _ohlc([1], [0], [0.5])
        with pytest.raises(TypeError, match="SwingResult"):
            detect_sweeps(df, [], _const_atr(df))  # type: ignore[arg-type]
