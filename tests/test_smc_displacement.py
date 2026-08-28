"""Golden tests for causal ATR and range expansion (Phase 2)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.displacement import (  # noqa: E402
    ExpansionMetrics,
    calculate_atr,
    detect_range_expansion,
)


def _ohlc_frame(
    n: int,
    *,
    start: float = 100.0,
    step: float = 0.1,
    range_: float = 1.0,
    body: float = 0.4,
    freq: str = "15min",
    tz: str | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Synthetic OHLC with controllable high-low range and body size."""
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz=tz)
    if seed is not None:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, step, size=n)
    else:
        noise = np.full(n, step, dtype=float)

    close = start + np.cumsum(noise)
    open_ = close - body
    mid_hi = np.maximum(open_, close)
    mid_lo = np.minimum(open_, close)
    candle_body = mid_hi - mid_lo
    remainder = np.maximum(range_ - candle_body, 0.0)
    high = mid_hi + remainder / 2.0
    low = mid_lo - remainder / 2.0

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=idx,
    )



class TestCalculateAtrValidation:
    def test_missing_ohlc_raises(self):
        df = pd.DataFrame({"open": [1], "high": [2], "close": [1.5]})
        with pytest.raises(ValueError, match="OHLC"):
            calculate_atr(df)

    def test_non_positive_period_raises(self):
        df = _ohlc_frame(20)
        for bad in (0, -1, -14):
            with pytest.raises(ValueError, match="period"):
                calculate_atr(df, period=bad)

    def test_bool_period_rejected(self):
        df = _ohlc_frame(20)
        with pytest.raises(ValueError, match="period"):
            calculate_atr(df, period=True)  # type: ignore[arg-type]


class TestCalculateAtrWarmup:
    def test_nan_warmup_no_backfill(self):
        period = 14
        df = _ohlc_frame(40, range_=1.0, body=0.5)
        atr = calculate_atr(df, period=period)

        assert atr.index.equals(df.index)
        # First period-1 bars must be NaN (need `period` TR observations)
        assert atr.iloc[: period - 1].isna().all()
        assert pd.notna(atr.iloc[period - 1])
        # No backfill: early values stay NaN, not filled with first valid ATR
        first_valid = atr.iloc[period - 1]
        assert atr.iloc[0] != first_valid or pd.isna(atr.iloc[0])
        assert atr.iloc[: period - 1].isna().all()

    def test_first_valid_is_mean_of_first_period_tr(self):
        period = 5
        # Flat path with constant range so TR is deterministic after bar 0
        df = _ohlc_frame(20, step=0.0, range_=2.0, body=0.0, start=100.0)
        # open=close=100, high=101, low=99 → range 2; prev close same → TR=2
        atr = calculate_atr(df, period=period)
        assert pd.isna(atr.iloc[period - 2])
        assert atr.iloc[period - 1] == pytest.approx(2.0)
        np.testing.assert_allclose(atr.iloc[period:].to_numpy(dtype=float), 2.0)

    def test_true_range_uses_prev_close_gap(self):
        """Gap beyond high-low must expand true range."""
        idx = pd.date_range("2024-01-01", periods=6, freq="h")
        df = pd.DataFrame(
            {
                "open": [10.0, 12.0, 12.0, 12.0, 12.0, 12.0],
                "high": [11.0, 12.5, 12.5, 12.5, 12.5, 12.5],
                "low": [9.0, 11.5, 11.5, 11.5, 11.5, 11.5],
                "close": [10.0, 12.0, 12.0, 12.0, 12.0, 12.0],
            },
            index=idx,
        )
        # Bar 1: H-L=1.0, |H-prevC|=2.5, |L-prevC|=1.5 → TR=2.5
        atr = calculate_atr(df, period=2)
        # rolling mean of TR[0]=2.0, TR[1]=2.5 → 2.25 at index 1
        assert atr.iloc[1] == pytest.approx(2.25)


class TestCalculateAtrNaNsAndGaps:
    def test_nan_rows_propagate_without_backfill(self):
        df = _ohlc_frame(30, range_=1.0, body=0.4)
        df.iloc[5] = np.nan
        df.iloc[6] = np.nan
        atr = calculate_atr(df, period=5)

        assert atr.index.equals(df.index)
        # Warmup still NaN
        assert atr.iloc[:4].isna().all()
        # No forward-fill: warmup stays NaN (unlike legacy backfill)
        assert pd.isna(atr.iloc[0])

    def test_insufficient_bars_all_nan(self):
        df = _ohlc_frame(5, range_=1.0)
        atr = calculate_atr(df, period=14)
        assert atr.isna().all()
        assert len(atr) == 5


class TestDetectRangeExpansionValidation:
    def test_missing_ohlc_raises(self):
        df = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5]})
        atr = pd.Series([1.0], index=df.index)
        with pytest.raises(ValueError, match="OHLC"):
            detect_range_expansion(df, atr)

    def test_non_positive_multiplier_raises(self):
        df = _ohlc_frame(20)
        atr = calculate_atr(df, period=5)
        for bad in (0.0, -1.5, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="multiplier"):
                detect_range_expansion(df, atr, multiplier=bad)


class TestDetectRangeExpansionQualified:
    def test_exact_threshold_not_qualified_strict_gt(self):
        """qualified uses strict >; equality is not expansion."""
        n = 20
        period = 5
        mult = 1.5
        idx = pd.date_range("2024-06-01", periods=n, freq="h")
        # Constant TR=2.0 → ATR=2.0 after warmup
        atr_val = 2.0
        exact_range = mult * atr_val  # 3.0
        opens = np.full(n, 100.0)
        closes = opens + 0.5
        highs = np.maximum(opens, closes) + (exact_range - 0.5) / 2
        lows = np.minimum(opens, closes) - (exact_range - 0.5) / 2
        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes},
            index=idx,
        )
        # Force exact high-low
        df["high"] = df[["open", "close"]].max(axis=1) + (exact_range - 0.5) / 2
        df["low"] = df[["open", "close"]].min(axis=1) - (exact_range - 0.5) / 2
        # Verify range
        assert np.allclose((df["high"] - df["low"]).iloc[period:], exact_range)

        atr = pd.Series(atr_val, index=idx, dtype=float)
        atr.iloc[: period - 1] = np.nan
        metrics = detect_range_expansion(df, atr, multiplier=mult)

        # Exact equality → False
        assert not metrics.qualified.iloc[period:].any()

        # Slightly above → True
        df2 = df.copy()
        df2["high"] = df2["high"] + 1e-9
        metrics2 = detect_range_expansion(df2, atr, multiplier=mult)
        assert metrics2.qualified.iloc[period:].all()

    def test_warmup_never_qualified(self):
        df = _ohlc_frame(30, range_=10.0, body=2.0)  # large range
        atr = calculate_atr(df, period=14)
        metrics = detect_range_expansion(df, atr, multiplier=1.5)
        # Bars where ATR is NaN must not qualify
        assert not metrics.qualified[atr.isna()].any()

    def test_zero_range_not_qualified(self):
        idx = pd.date_range("2024-01-01", periods=20, freq="h")
        px = 50.0
        df = pd.DataFrame(
            {"open": px, "high": px, "low": px, "close": px},
            index=idx,
        )
        atr = pd.Series(1.0, index=idx)
        metrics = detect_range_expansion(df, atr, multiplier=1.5)
        assert not metrics.qualified.any()
        assert metrics.body_ratio.isna().all()
        assert metrics.close_location.isna().all()
        assert (metrics.direction == "neutral").all()


class TestDetectRangeExpansionMetrics:
    def test_direction_bullish_bearish_neutral(self):
        idx = pd.date_range("2024-01-01", periods=3, freq="h")
        df = pd.DataFrame(
            {
                "open": [10.0, 10.0, 10.0],
                "high": [12.0, 12.0, 11.0],
                "low": [9.0, 8.0, 9.0],
                "close": [11.0, 9.0, 10.0],  # up, down, flat
            },
            index=idx,
        )
        atr = pd.Series([1.0, 1.0, 1.0], index=idx)
        m = detect_range_expansion(df, atr, multiplier=1.5)
        assert list(m.direction) == ["bullish", "bearish", "neutral"]

    def test_close_location_and_body_ratio(self):
        idx = pd.date_range("2024-01-01", periods=1, freq="h")
        # open=10, close=18, high=20, low=0 → range=20, body=8
        # close_location = (18-0)/20 = 0.9; body_ratio = 8/20 = 0.4
        df = pd.DataFrame(
            {"open": [10.0], "high": [20.0], "low": [0.0], "close": [18.0]},
            index=idx,
        )
        atr = pd.Series([4.0], index=idx)
        m = detect_range_expansion(df, atr, multiplier=1.5)
        assert m.close_location.iloc[0] == pytest.approx(0.9)
        assert m.body_ratio.iloc[0] == pytest.approx(0.4)
        assert m.range_atr.iloc[0] == pytest.approx(20.0 / 4.0)
        assert m.body_atr.iloc[0] == pytest.approx(8.0 / 4.0)
        assert bool(m.qualified.iloc[0]) is True  # 20 > 1.5*4

    def test_index_and_timezone_preserved(self):
        df = _ohlc_frame(40, tz="UTC", range_=2.0, body=0.5)
        atr = calculate_atr(df, period=10)
        m = detect_range_expansion(df, atr, multiplier=1.5)

        assert isinstance(m, ExpansionMetrics)
        for series in (
            m.range_atr,
            m.body_atr,
            m.body_ratio,
            m.close_location,
            m.direction,
            m.qualified,
        ):
            assert series.index.equals(df.index)
            assert series.index.tz is not None
            assert str(series.index.tz) == "UTC"

    def test_metrics_align_with_nan_atr(self):
        df = _ohlc_frame(25, range_=3.0, body=1.0)
        atr = calculate_atr(df, period=14)
        m = detect_range_expansion(df, atr)
        # range_atr NaN wherever atr NaN
        assert m.range_atr.iloc[:13].isna().all()
        assert m.qualified.dtype == bool or m.qualified.dtype == np.bool_


class TestScaleBehavior:
    def test_runtime_scales_near_linear(self):
        """runtime(2N)/runtime(N) < 2.5 on synthetic fixture."""

        def run_once(n: int) -> float:
            df = _ohlc_frame(n, seed=0, range_=1.5, body=0.6)
            t0 = time.perf_counter()
            atr = calculate_atr(df, period=14)
            detect_range_expansion(df, atr, multiplier=1.5)
            return time.perf_counter() - t0

        # Warm JIT/caches
        run_once(2_000)
        n = 8_000
        t_n = min(run_once(n) for _ in range(3))
        t_2n = min(run_once(2 * n) for _ in range(3))
        # Avoid flaky zero division on ultra-fast runs
        if t_n < 1e-4:
            pytest.skip("timing resolution too coarse")
        ratio = t_2n / t_n
        assert ratio < 2.5, f"runtime(2N)/runtime(N) = {ratio:.3f} >= 2.5"
