"""Causal Williams/fractal swing detection.

Baseline rules (earliest-equal tie policy):
- Swing high at ``i``: ``high[i] > max(left bars)`` and ``high[i] >= max(right bars)``.
- Swing low at ``i``: ``low[i] < min(left bars)`` and ``low[i] <= min(right bars)``.

A pivot at ``i`` activates at ``i + right``. The first ``left`` and last
``right`` positions cannot emit confirmed events.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from smc_engine.events import SwingEvent, SwingResult

_REQUIRED_COLUMNS = ("high", "low")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


def _validate_windows(left: int, right: int) -> None:
    if not isinstance(left, (int, np.integer)) or isinstance(left, bool):
        raise TypeError(f"left must be a positive int, got {type(left).__name__}")
    if not isinstance(right, (int, np.integer)) or isinstance(right, bool):
        raise TypeError(f"right must be a positive int, got {type(right).__name__}")
    if left <= 0:
        raise ValueError(f"left must be > 0, got {left}")
    if right <= 0:
        raise ValueError(f"right must be > 0, got {right}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def detect_swings(
    df: pd.DataFrame,
    left: int = 2,
    right: int = 2,
) -> SwingResult:
    """Detect confirmed left/right fractal swing highs and lows.

    Parameters
    ----------
    df:
        OHLC frame with at least ``high`` and ``low`` columns. Index must be
        unique and monotonic increasing (timezone-aware indexes are preserved).
    left:
        Number of bars strictly to the left of the candidate pivot.
    right:
        Number of bars to the right required for confirmation. Activation is
        always ``pivot_pos + right``.

    Returns
    -------
    SwingResult
        Immutable events ordered by ascending ``pivot_pos`` (equivalently
        activation order) plus activation-aligned level series.

    Notes
    -----
    Equal-level ties select the **earliest** pivot via ``>=`` / ``<=`` on the
    right window and strict inequality on the left window.
    """
    _validate_ohlc(df)
    _validate_windows(left, right)
    _validate_index(df.index)

    n = len(df)
    high = df["high"].to_numpy(dtype=float, copy=False)
    low = df["low"].to_numpy(dtype=float, copy=False)
    index = df.index

    high_at = np.full(n, np.nan, dtype=float)
    low_at = np.full(n, np.nan, dtype=float)
    events: list[SwingEvent] = []
    next_id = 0

    # Confirmed pivots only exist in [left, n - right - 1].
    end = n - right
    for i in range(left, end):
        left_slice_h = high[i - left : i]
        right_slice_h = high[i + 1 : i + 1 + right]
        left_slice_l = low[i - left : i]
        right_slice_l = low[i + 1 : i + 1 + right]

        is_high = high[i] > left_slice_h.max() and high[i] >= right_slice_h.max()
        is_low = low[i] < left_slice_l.min() and low[i] <= right_slice_l.min()

        if not is_high and not is_low:
            continue

        act = i + right
        pivot_ts = index[i]
        act_ts = index[act]

        if is_high:
            level = float(high[i])
            high_at[act] = level
            events.append(
                SwingEvent(
                    id=next_id,
                    direction="high",
                    level=level,
                    pivot_pos=i,
                    pivot_timestamp=pivot_ts,
                    activation_pos=act,
                    activation_timestamp=act_ts,
                )
            )
            next_id += 1

        if is_low:
            level = float(low[i])
            low_at[act] = level
            events.append(
                SwingEvent(
                    id=next_id,
                    direction="low",
                    level=level,
                    pivot_pos=i,
                    pivot_timestamp=pivot_ts,
                    activation_pos=act,
                    activation_timestamp=act_ts,
                )
            )
            next_id += 1

    high_series = pd.Series(high_at, index=index, name="high_at_activation", dtype=float)
    low_series = pd.Series(low_at, index=index, name="low_at_activation", dtype=float)

    return SwingResult(
        events=tuple(events),
        high_at_activation=high_series,
        low_at_activation=low_series,
    )


def detect_swings_symmetric(
    df: pd.DataFrame,
    swing_length: int = 2,
) -> SwingResult:
    """Convenience wrapper with equal left/right windows."""
    return detect_swings(df, left=swing_length, right=swing_length)
