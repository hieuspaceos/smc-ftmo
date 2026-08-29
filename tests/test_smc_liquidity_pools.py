"""Tests for EQH/EQL liquidity pool detection."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.events import SwingEvent, SwingResult  # noqa: E402
from smc_engine.liquidity_pools import (  # noqa: E402
    LiquidityPoolEvent,
    LiquidityPoolResult,
    detect_liquidity_pools,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")


def _ohlc(
    highs: list[float],
    lows: list[float],
    closes: list[float] | None = None,
) -> pd.DataFrame:
    opens = [(h + l) * 0.5 for h, l in zip(highs, lows)]
    close_vals = closes[:] if closes is not None else opens[:]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": close_vals},
        index=_idx(len(highs)),
    )


def _swings(df: pd.DataFrame, events: list[SwingEvent]) -> SwingResult:
    return SwingResult(
        events=tuple(events),
        high_at_activation=pd.Series(np.nan, index=df.index, dtype=float),
        low_at_activation=pd.Series(np.nan, index=df.index, dtype=float),
    )


class TestLiquidityPools:
    def test_equal_highs_form_one_pool_and_later_sweep(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.8, 102.05, 101.7, 102.4],
            lows=[99.0, 100.0, 100.5, 100.8, 100.9, 100.7, 101.0],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "high", 102.05, 3, df.index[3], 4, df.index[4]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert isinstance(out, LiquidityPoolResult)
        assert len(out.events) == 1
        event = out.events[0]
        assert isinstance(event, LiquidityPoolEvent)
        assert event.side == "high"
        assert event.activation_pos == 4
        assert event.member_swing_ids == (0, 1)
        assert event.level_mean == pytest.approx(102.025)
        assert event.level_min == pytest.approx(102.0)
        assert event.level_max == pytest.approx(102.05)
        assert event.swept is True
        assert event.sweep_pos == 6
        assert event.sweep_timestamp == df.index[6]

    def test_equal_lows_form_pool(self):
        df = _ohlc(
            highs=[101.0, 101.2, 101.1, 101.0, 101.3, 101.4],
            lows=[99.0, 98.0, 98.4, 98.05, 98.2, 97.8],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "low", 98.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "low", 98.05, 2, df.index[2], 3, df.index[3]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert len(out.events) == 1
        event = out.events[0]
        assert event.side == "low"
        assert event.member_swing_ids == (0, 1)
        assert event.swept is True
        assert event.sweep_pos == 5

    def test_levels_outside_tolerance_do_not_cluster(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.5, 102.3, 101.9],
            lows=[99.0, 100.0, 100.5, 100.7, 100.8, 100.9],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "high", 102.3, 3, df.index[3], 4, df.index[4]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert out.events == ()

    def test_single_swing_never_becomes_pool(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.6],
            lows=[99.0, 100.0, 100.5, 100.8],
        )
        swings = _swings(
            df,
            [SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2])],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert out.events == ()

    def test_breakout_without_reclaim_is_not_marked_swept(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.8, 102.05, 101.7, 102.4],
            lows=[99.0, 100.0, 100.5, 100.8, 100.9, 100.7, 101.0],
            closes=[99.5, 100.5, 101.0, 101.3, 101.5, 101.2, 102.2],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "high", 102.05, 3, df.index[3], 4, df.index[4]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert len(out.events) == 1
        assert out.events[0].swept is False
        assert out.events[0].sweep_pos is None

    def test_third_member_does_not_delay_pool_activation(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.8, 102.05, 102.12, 102.04, 101.7],
            lows=[99.0, 100.0, 100.5, 100.8, 100.9, 100.95, 100.92, 100.7],
            closes=[99.5, 100.5, 101.0, 101.2, 101.5, 101.95, 101.6, 101.0],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "high", 102.05, 3, df.index[3], 4, df.index[4]),
                SwingEvent(2, "high", 102.04, 5, df.index[5], 6, df.index[6]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert len(out.events) == 1
        event = out.events[0]
        assert event.activation_pos == 4
        assert event.activation_timestamp == df.index[4]
        assert event.swept is True
        assert event.sweep_pos == 5

    def test_activation_bar_scanned_before_later_member_extends_pool(self):
        df = _ohlc(
            highs=[100.0, 101.0, 102.0, 101.8, 102.05, 101.9, 102.08, 101.7],
            lows=[99.0, 100.0, 100.5, 100.8, 100.9, 100.95, 100.92, 100.7],
            closes=[99.5, 100.5, 101.0, 101.2, 101.5, 101.8, 101.95, 101.0],
        )
        swings = _swings(
            df,
            [
                SwingEvent(0, "high", 102.0, 1, df.index[1], 2, df.index[2]),
                SwingEvent(1, "high", 102.05, 3, df.index[3], 4, df.index[4]),
                SwingEvent(2, "high", 102.08, 5, df.index[5], 6, df.index[6]),
            ],
        )
        atr = pd.Series(1.0, index=df.index, dtype=float)
        out = detect_liquidity_pools(df, swings, atr)
        assert len(out.events) == 1
        event = out.events[0]
        assert event.activation_pos == 4
        assert event.swept is True
        assert event.sweep_pos == 6
