"""Causal BOS/CHoCH structure state machine.

Break eligibility uses activated swing levels strictly from the bar after
activation. Close-only breaks; equality and wick-only crosses do not break.
CHoCH and BOS are mutually exclusive. Broken levels are consumed until a
newer activated swing of the same side replaces them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.events import SwingEvent, SwingResult

Trend = Literal["bull", "bear", "neutral"]
StructureType = Literal["bos", "choch"]
StructureDirection = Literal["bullish", "bearish"]

_REQUIRED_COLUMNS = ("close",)


@dataclass(frozen=True)
class StructureEvent:
    """A single BOS or CHoCH break of an activated swing level."""

    id: int
    type: StructureType
    direction: StructureDirection
    activation_pos: int
    activation_timestamp: pd.Timestamp
    broken_level: float
    source_swing_id: int
    prior_trend: Trend
    next_trend: Literal["bull", "bear"]


@dataclass(frozen=True)
class StructureResult:
    """Typed structure output: events plus index-aligned adapter series."""

    events: tuple[StructureEvent, ...]
    trend: pd.Series
    bos: pd.Series
    choch: pd.Series
    broken_level: pd.Series
    last_swing_high: pd.Series
    last_swing_low: pd.Series
    swing_direction: pd.Series
    diagnostics: tuple[str, ...] = ()


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def _transition(
    prior: Trend,
    upper_break: bool,
    lower_break: bool,
) -> tuple[StructureType, StructureDirection, Literal["bull", "bear"]] | None:
    """Pure decision table. Returns (type, direction, next_trend) or None."""
    if upper_break and lower_break:
        return None
    if not upper_break and not lower_break:
        return None
    if upper_break:
        if prior == "bear":
            return ("choch", "bullish", "bull")
        # neutral or bull → bull BOS
        return ("bos", "bullish", "bull")
    # lower_break
    if prior == "bull":
        return ("choch", "bearish", "bear")
    # neutral or bear → bear BOS
    return ("bos", "bearish", "bear")


def detect_structure(
    df: pd.DataFrame,
    swings: SwingResult,
    atr: pd.Series | None = None,
    close_break_buffer_atr: float = 0.0,
) -> StructureResult:
    """Detect BOS/CHoCH from activated swing levels (one causal pass).

    Parameters
    ----------
    df:
        OHLC frame; ``close`` is required. Index must match swing series and
        be unique + monotonic increasing.
    swings:
        Confirmed swing events from ``detect_swings``. Activation timing is
        consumed as-is (no extra confirmation lag).
    atr:
        Optional ATR series aligned to ``df`` (reindexed if needed). Required
        only when ``close_break_buffer_atr > 0``.
    close_break_buffer_atr:
        Bullish break requires ``close > level + ATR * buffer``; bearish is
        symmetric. Default ``0.0`` is a strict close-through level.

    Notes
    -----
    At bar ``i``: evaluate the close against levels activated strictly before
    ``i``; then register swings whose ``activation_pos == i`` for use from
    bar ``i + 1``.
    """
    _validate_ohlc(df)
    _validate_index(df.index)

    if not isinstance(swings, SwingResult):
        raise TypeError("swings must be a SwingResult")
    if not np.isfinite(close_break_buffer_atr) or close_break_buffer_atr < 0:
        raise ValueError(
            f"close_break_buffer_atr must be finite and >= 0, got {close_break_buffer_atr!r}"
        )

    n = len(df)
    index = df.index
    close = df["close"].to_numpy(dtype=float, copy=False)

    use_buffer = close_break_buffer_atr > 0.0
    atr_arr: np.ndarray | None = None
    if use_buffer:
        if atr is None:
            raise ValueError("atr is required when close_break_buffer_atr > 0")
        if not isinstance(atr, pd.Series):
            raise TypeError("atr must be a pandas Series")
        if not atr.index.equals(index):
            atr = atr.reindex(index)
        atr_arr = atr.to_numpy(dtype=float, copy=False)
    elif atr is not None:
        if not isinstance(atr, pd.Series):
            raise TypeError("atr must be a pandas Series")
        if not atr.index.equals(index):
            atr = atr.reindex(index)
        atr_arr = atr.to_numpy(dtype=float, copy=False)

    # Group swing activations by bar for O(n + m) registration.
    by_act: dict[int, list[SwingEvent]] = {}
    for ev in swings.events:
        if ev.activation_pos < 0 or ev.activation_pos >= n:
            raise ValueError(
                f"swing id={ev.id} activation_pos={ev.activation_pos} out of range for n={n}"
            )
        by_act.setdefault(ev.activation_pos, []).append(ev)

    trend_state: Trend = "neutral"
    last_high: SwingEvent | None = None
    last_low: SwingEvent | None = None
    high_consumed = False
    low_consumed = False

    events: list[StructureEvent] = []
    diagnostics: list[str] = []
    next_id = 0

    trend_out = np.empty(n, dtype=object)
    bos_out = np.full(n, np.nan, dtype=float)
    choch_out = np.full(n, np.nan, dtype=float)
    broken_out = np.full(n, np.nan, dtype=float)
    last_high_out = np.full(n, np.nan, dtype=float)
    last_low_out = np.full(n, np.nan, dtype=float)
    swing_dir_out = np.full(n, np.nan, dtype=float)

    # Running display state for series (updated after same-bar activations).
    disp_high = np.nan
    disp_low = np.nan
    disp_dir = np.nan

    for i in range(n):
        c = close[i]
        upper_break = False
        lower_break = False

        buf = 0.0
        atr_ok = True
        if use_buffer:
            assert atr_arr is not None
            a = atr_arr[i]
            if not np.isfinite(a):
                atr_ok = False
            else:
                buf = float(a) * close_break_buffer_atr

        if atr_ok and np.isfinite(c):
            if last_high is not None and not high_consumed:
                if c > last_high.level + buf:
                    upper_break = True
            if last_low is not None and not low_consumed:
                if c < last_low.level - buf:
                    lower_break = True

        # Level invariant: last_swing_low < last_swing_high when both exist.
        invariant_ok = True
        if last_high is not None and last_low is not None:
            if not (last_low.level < last_high.level):
                invariant_ok = False
                if upper_break or lower_break:
                    diagnostics.append(
                        f"invariant_violation@i={i}: low={last_low.level} high={last_high.level}"
                    )
                upper_break = False
                lower_break = False

        if invariant_ok and upper_break and lower_break:
            diagnostics.append(f"dual_break@i={i}")
            upper_break = False
            lower_break = False

        decision = _transition(trend_state, upper_break, lower_break)
        if decision is not None:
            etype, direction, next_trend = decision
            if direction == "bullish":
                assert last_high is not None
                src = last_high
                high_consumed = True
            else:
                assert last_low is not None
                src = last_low
                low_consumed = True

            prior = trend_state
            trend_state = next_trend
            sign = 1.0 if direction == "bullish" else -1.0
            if etype == "bos":
                bos_out[i] = sign
            else:
                choch_out[i] = sign
            broken_out[i] = float(src.level)

            events.append(
                StructureEvent(
                    id=next_id,
                    type=etype,
                    direction=direction,
                    activation_pos=i,
                    activation_timestamp=index[i],
                    broken_level=float(src.level),
                    source_swing_id=src.id,
                    prior_trend=prior,
                    next_trend=next_trend,
                )
            )
            next_id += 1

        trend_out[i] = trend_state

        # Register swings activating on this bar for next-bar eligibility.
        for sw in by_act.get(i, ()):
            if sw.direction == "high":
                last_high = sw
                high_consumed = False
                disp_high = float(sw.level)
                disp_dir = 1.0
            elif sw.direction == "low":
                last_low = sw
                low_consumed = False
                disp_low = float(sw.level)
                disp_dir = -1.0
            else:  # pragma: no cover - contract guard
                diagnostics.append(f"unknown_swing_direction@i={i}:id={sw.id}")

        last_high_out[i] = disp_high
        last_low_out[i] = disp_low
        swing_dir_out[i] = disp_dir

    return StructureResult(
        events=tuple(events),
        trend=pd.Series(trend_out, index=index, name="trend", dtype=object),
        bos=pd.Series(bos_out, index=index, name="bos", dtype=float),
        choch=pd.Series(choch_out, index=index, name="choch", dtype=float),
        broken_level=pd.Series(broken_out, index=index, name="broken_level", dtype=float),
        last_swing_high=pd.Series(
            last_high_out, index=index, name="last_swing_high", dtype=float
        ),
        last_swing_low=pd.Series(
            last_low_out, index=index, name="last_swing_low", dtype=float
        ),
        swing_direction=pd.Series(
            swing_dir_out, index=index, name="swing_direction", dtype=float
        ),
        diagnostics=tuple(diagnostics),
    )
