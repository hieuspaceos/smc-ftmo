"""Tests for the regime detection layer (Plan 14)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.regime import (  # noqa: E402
    detect_regime,
    _choppiness,
    _directional_move_ratio,
    _regime_label,
    _weights_from_regime,
    RegimeState,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="15min")


def _ohlc(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": [c + 0.0001 for c in closes],
        "low": [c - 0.0001 for c in closes],
        "close": closes,
    }, index=_idx(n))


class TestRegimeMetrics:
    def test_directional_move_perfect_trend(self):
        closes = [1.10 + i * 0.001 for i in range(20)]
        ratio = _directional_move_ratio(pd.Series(closes), lookback=14)
        assert ratio >= 0.95  # near 1.0 for monotonic uptrend

    def test_directional_move_perfect_chop(self):
        closes = [1.10 + (0.001 if i % 2 else -0.001) for i in range(20)]
        ratio = _directional_move_ratio(pd.Series(closes), lookback=14)
        # Alternating produces a tiny bias from boundary effects; threshold 0.1
        # is loose enough to accommodate that without losing signal.
        assert ratio <= 0.10

    def test_choppiness_high_for_alternating(self):
        closes = [1.10 + (0.001 if i % 2 else -0.001) for i in range(20)]
        chop = _choppiness(pd.Series(closes), lookback=14)
        assert chop >= 0.95

    def test_choppiness_low_for_monotonic(self):
        closes = [1.10 + i * 0.001 for i in range(20)]
        chop = _choppiness(pd.Series(closes), lookback=14)
        assert chop <= 0.05


class TestRegimeLabels:
    def test_trending_label(self):
        assert _regime_label(0.7, 0.3) == "trending"

    def test_ranging_label(self):
        assert _regime_label(0.2, 0.7) == "ranging"

    def test_mixed_label(self):
        assert _regime_label(0.5, 0.5) == "mixed"


class TestWeightsFromRegime:
    def test_trending_weights_ob(self):
        ob_w, br_w = _weights_from_regime("trending")
        assert ob_w == 1.0 and br_w == 0.0

    def test_ranging_weights_breaker(self):
        ob_w, br_w = _weights_from_regime("ranging")
        assert ob_w == 0.0 and br_w == 1.0

    def test_mixed_split(self):
        ob_w, br_w = _weights_from_regime("mixed")
        assert ob_w == 0.5 and br_w == 0.5
        assert ob_w + br_w == 1.0


class TestDetectRegime:
    def test_returns_regime_state(self):
        closes = [1.10 + i * 0.001 for i in range(40)]  # strong uptrend
        df = _ohlc(closes)
        state = detect_regime(df)
        assert isinstance(state, RegimeState)
        assert state.regime == "trending"
        assert state.ob_weight == 1.0
        assert state.breaker_weight == 0.0
        # Trend strength should be high, choppiness low
        assert state.trend_strength >= 0.7
        assert state.choppiness <= 0.3

    def test_ranging_detected(self):
        closes = [1.10 + (0.001 if i % 2 else -0.001) for i in range(40)]
        df = _ohlc(closes)
        state = detect_regime(df)
        assert state.regime == "ranging"
        assert state.ob_weight == 0.0
        assert state.breaker_weight == 1.0

    def test_short_frame_returns_mixed(self):
        closes = [1.10] * 5  # not enough data
        df = _ohlc(closes)
        state = detect_regime(df)
        assert state.regime == "mixed"  # defaults when insufficient data

    def test_weights_sum_to_one(self):
        closes = [1.10 + (0.0001 * i if i % 3 != 0 else -0.0002) for i in range(40)]
        df = _ohlc(closes)
        state = detect_regime(df)
        assert abs(state.ob_weight + state.breaker_weight - 1.0) < 1e-9