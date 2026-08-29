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
    RegimeState,
    _choppiness,
    _directional_move_ratio,
    _regime_label,
    _weights_from_regime,
    detect_regime,
)
from smc_engine.liquidity_pools import LiquidityPoolEvent, LiquidityPoolResult  # noqa: E402
from smc_engine.structure import StructureEvent, StructureResult  # noqa: E402
from smc_engine.sweeps import SweepEvent, SweepResult  # noqa: E402


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


def _structure_result(
    n: int,
    trend: list[str],
    events: list[StructureEvent],
) -> StructureResult:
    index = _idx(n)
    return StructureResult(
        events=tuple(events),
        trend=pd.Series(trend, index=index, dtype=object),
        bos=pd.Series(np.nan, index=index, dtype=float),
        choch=pd.Series(np.nan, index=index, dtype=float),
        broken_level=pd.Series(np.nan, index=index, dtype=float),
        last_swing_high=pd.Series(np.nan, index=index, dtype=float),
        last_swing_low=pd.Series(np.nan, index=index, dtype=float),
        swing_direction=pd.Series(np.nan, index=index, dtype=float),
        diagnostics=(),
    )


def _sweep_result(events: list[SweepEvent]) -> SweepResult:
    return SweepResult(events=tuple(events), diagnostics=())


def _pool_result(events: list[LiquidityPoolEvent]) -> LiquidityPoolResult:
    return LiquidityPoolResult(events=tuple(events))


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

    def test_mixed_weights_stay_baseline_safe(self):
        ob_w, br_w = _weights_from_regime("mixed")
        assert ob_w == 1.0 and br_w == 0.0
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
        assert state.trend_strength >= 0.7
        assert state.choppiness <= 0.3
        assert "trending" in state.explanation

    def test_sparse_ranging_signal_stays_mixed(self):
        closes = [1.10 + (0.001 if i % 2 else -0.001) for i in range(40)]
        df = _ohlc(closes)
        state = detect_regime(df)
        assert state.regime == "mixed"
        assert state.ob_weight == 1.0
        assert state.breaker_weight == 0.0
        assert "sparse recent structure" in state.explanation

    def test_short_frame_returns_mixed(self):
        closes = [1.10] * 5  # not enough data
        df = _ohlc(closes)
        state = detect_regime(df)
        assert state.regime == "mixed"
        assert state.ob_weight == 1.0
        assert state.breaker_weight == 0.0

    def test_weights_sum_to_one(self):
        closes = [1.10 + (0.0001 * i if i % 3 != 0 else -0.0002) for i in range(40)]
        df = _ohlc(closes)
        state = detect_regime(df)
        assert abs(state.ob_weight + state.breaker_weight - 1.0) < 1e-9

    def test_borderline_signal_stays_mixed(self):
        assert _regime_label(0.60, 0.57) == "mixed"


    def test_dense_ranging_structure_enables_breakers(self):
        n = 40
        index = _idx(n)
        trend = ["bull", "bear"] * 20
        structure = _structure_result(
            n,
            trend,
            [
                StructureEvent(0, "bos", "bullish", 10, index[10], 1.0, 1, "neutral", "bull"),
                StructureEvent(1, "choch", "bearish", 11, index[11], 1.0, 2, "bull", "bear"),
                StructureEvent(2, "choch", "bullish", 12, index[12], 1.0, 3, "bear", "bull"),
                StructureEvent(3, "bos", "bearish", 13, index[13], 1.0, 4, "bull", "bear"),
                StructureEvent(4, "choch", "bullish", 14, index[14], 1.0, 5, "bear", "bull"),
                StructureEvent(5, "choch", "bearish", 15, index[15], 1.0, 6, "bull", "bear"),
                StructureEvent(6, "bos", "bullish", 16, index[16], 1.0, 7, "bear", "bull"),
                StructureEvent(7, "choch", "bearish", 17, index[17], 1.0, 8, "bull", "bear"),
                StructureEvent(8, "choch", "bullish", 18, index[18], 1.0, 9, "bear", "bull"),
                StructureEvent(9, "bos", "bearish", 19, index[19], 1.0, 10, "bull", "bear"),
                StructureEvent(10, "choch", "bullish", 20, index[20], 1.0, 11, "bear", "bull"),
                StructureEvent(11, "choch", "bearish", 21, index[21], 1.0, 12, "bull", "bear"),
            ],
        )
        sweeps = _sweep_result(
            [
                SweepEvent(0, "bullish", 11, index[11], 1, 1.0, 0.3, 0.7, False),
                SweepEvent(1, "bearish", 13, index[13], 2, 1.0, 0.3, 0.2, False),
                SweepEvent(2, "bullish", 15, index[15], 3, 1.0, 0.3, 0.8, False),
                SweepEvent(3, "bearish", 17, index[17], 4, 1.0, 0.3, 0.1, False),
                SweepEvent(4, "bullish", 19, index[19], 5, 1.0, 0.3, 0.8, False),
                SweepEvent(5, "bearish", 21, index[21], 6, 1.0, 0.3, 0.2, False),
                SweepEvent(6, "bullish", 23, index[23], 7, 1.0, 0.3, 0.7, False),
                SweepEvent(7, "bearish", 25, index[25], 8, 1.0, 0.3, 0.2, False),
                SweepEvent(8, "bullish", 27, index[27], 9, 1.0, 0.3, 0.7, False),
                SweepEvent(9, "bearish", 29, index[29], 10, 1.0, 0.3, 0.2, False),
                SweepEvent(10, "bullish", 31, index[31], 11, 1.0, 0.3, 0.7, False),
                SweepEvent(11, "bearish", 33, index[33], 12, 1.0, 0.3, 0.2, False),
            ]
        )
        pools = _pool_result(
            [
                LiquidityPoolEvent(0, "high", 18, index[18], 1.0, 0.99, 1.01, (1, 2), (1.0, 1.01), False, None, None),
                LiquidityPoolEvent(1, "low", 20, index[20], 1.0, 0.99, 1.01, (3, 4), (1.0, 0.99), False, None, None),
                LiquidityPoolEvent(2, "high", 22, index[22], 1.0, 0.99, 1.01, (5, 6), (1.0, 1.01), False, None, None),
                LiquidityPoolEvent(3, "low", 24, index[24], 1.0, 0.99, 1.01, (7, 8), (1.0, 0.99), False, None, None),
                LiquidityPoolEvent(4, "high", 26, index[26], 1.0, 0.99, 1.01, (9, 10), (1.0, 1.01), False, None, None),
                LiquidityPoolEvent(5, "low", 30, index[30], 1.0, 0.99, 1.01, (11, 12), (1.0, 0.99), True, 34, index[34]),
            ]
        )
        state = detect_regime(
            _ohlc([1.10] * n),
            structure=structure,
            sweeps=sweeps,
            liquidity_pools=pools,
        )
        assert state.regime == "ranging"
        assert state.breaker_weight == 1.0
        assert state.ob_weight == 0.0
        assert "ranging" in state.explanation

    def test_dense_trending_structure_stays_ob_only(self):
        n = 40
        index = _idx(n)
        structure = _structure_result(
            n,
            ["bull"] * n,
            [
                StructureEvent(0, "bos", "bullish", 10, index[10], 1.0, 1, "neutral", "bull"),
                StructureEvent(1, "bos", "bullish", 12, index[12], 1.0, 2, "bull", "bull"),
                StructureEvent(2, "bos", "bullish", 14, index[14], 1.0, 3, "bull", "bull"),
                StructureEvent(3, "bos", "bullish", 16, index[16], 1.0, 4, "bull", "bull"),
                StructureEvent(4, "bos", "bullish", 18, index[18], 1.0, 5, "bull", "bull"),
                StructureEvent(5, "bos", "bullish", 20, index[20], 1.0, 6, "bull", "bull"),
                StructureEvent(6, "choch", "bearish", 22, index[22], 1.0, 7, "bull", "bear"),
                StructureEvent(7, "bos", "bullish", 24, index[24], 1.0, 8, "bear", "bull"),
                StructureEvent(8, "bos", "bullish", 26, index[26], 1.0, 9, "bull", "bull"),
                StructureEvent(9, "bos", "bullish", 28, index[28], 1.0, 10, "bull", "bull"),
                StructureEvent(10, "bos", "bullish", 30, index[30], 1.0, 11, "bull", "bull"),
                StructureEvent(11, "bos", "bullish", 32, index[32], 1.0, 12, "bull", "bull"),
            ],
        )
        sweeps = _sweep_result(
            [
                SweepEvent(0, "bullish", 13, index[13], 1, 1.0, 0.2, 0.9, False),
                SweepEvent(1, "bullish", 21, index[21], 2, 1.0, 0.2, 0.8, False),
                SweepEvent(2, "bullish", 29, index[29], 3, 1.0, 0.2, 0.7, False),
            ]
        )
        state = detect_regime(
            _ohlc([1.10 + i * 0.001 for i in range(n)]),
            structure=structure,
            sweeps=sweeps,
        )
        assert state.regime == "trending"
        assert state.breaker_weight == 0.0
        assert state.ob_weight == 1.0
        assert state.dominant_direction == "bullish"

    def test_liquidity_pools_raise_range_pressure_in_explanation(self):
        n = 40
        index = _idx(n)
        structure = _structure_result(
            n,
            ["bull", "bear"] * 20,
            [
                StructureEvent(0, "bos", "bullish", 10, index[10], 1.0, 1, "neutral", "bull"),
                StructureEvent(1, "choch", "bearish", 12, index[12], 1.0, 2, "bull", "bear"),
                StructureEvent(2, "bos", "bearish", 14, index[14], 1.0, 3, "bear", "bear"),
                StructureEvent(3, "choch", "bullish", 16, index[16], 1.0, 4, "bear", "bull"),
                StructureEvent(4, "bos", "bullish", 18, index[18], 1.0, 5, "bull", "bull"),
                StructureEvent(5, "choch", "bearish", 20, index[20], 1.0, 6, "bull", "bear"),
                StructureEvent(6, "bos", "bearish", 22, index[22], 1.0, 7, "bear", "bear"),
                StructureEvent(7, "choch", "bullish", 24, index[24], 1.0, 8, "bear", "bull"),
                StructureEvent(8, "bos", "bullish", 26, index[26], 1.0, 9, "bull", "bull"),
                StructureEvent(9, "choch", "bearish", 28, index[28], 1.0, 10, "bull", "bear"),
                StructureEvent(10, "bos", "bearish", 30, index[30], 1.0, 11, "bear", "bear"),
                StructureEvent(11, "choch", "bullish", 32, index[32], 1.0, 12, "bear", "bull"),
            ],
        )
        sweeps = _sweep_result(
            [
                SweepEvent(0, "bullish", 11, index[11], 1, 1.0, 0.3, 0.7, False),
                SweepEvent(1, "bearish", 15, index[15], 2, 1.0, 0.3, 0.2, False),
                SweepEvent(2, "bullish", 19, index[19], 3, 1.0, 0.3, 0.8, False),
                SweepEvent(3, "bearish", 23, index[23], 4, 1.0, 0.3, 0.1, False),
                SweepEvent(4, "bullish", 27, index[27], 5, 1.0, 0.3, 0.8, False),
                SweepEvent(5, "bearish", 31, index[31], 6, 1.0, 0.3, 0.2, False),
            ]
        )
        pools = _pool_result(
            [
                LiquidityPoolEvent(0, "high", 18, index[18], 1.0, 0.99, 1.01, (1, 2), (1.0, 1.01), False, None, None),
                LiquidityPoolEvent(1, "low", 26, index[26], 1.0, 0.99, 1.01, (3, 4), (1.0, 0.99), True, 30, index[30]),
            ]
        )
        state = detect_regime(
            _ohlc([1.10] * n),
            structure=structure,
            sweeps=sweeps,
            liquidity_pools=pools,
        )
        assert state.liquidity_pool_density > 0.0
        assert "EQH/EQL pools" in state.explanation