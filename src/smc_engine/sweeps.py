"""Causal one-shot liquidity sweeps against activated swing levels.

Baseline rules
--------------
- Bullish (downside grab / reclaim): wick strictly takes the swing low, extends
  at least ``ATR × buffer`` beyond it (``>=``), and close reclaims above the
  level (strict ``>``).
- Bearish (upside grab / reject): symmetric on the swing high.
- Only swings activated on a *prior* bar are eligible (same-bar activation is
  deferred until the next bar).
- Each source swing emits at most one sweep; the level is then consumed until a
  newer same-side swing replaces it.
- A bar that satisfies both sides is ambiguous: no directional event, one
  diagnostic row; both source levels are consumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.events import SwingEvent, SwingResult

_OHLC_COLS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class SweepEvent:
    """One-shot liquidity grab/reclaim against an activated swing level.

    ``direction`` is the *expected setup* direction: bullish → long bias after
    a downside sweep; bearish → short bias after an upside sweep.
    ``activation_*`` refer to the sweep bar (not the source swing).
    """

    id: int
    direction: Literal["bullish", "bearish"]
    activation_pos: int
    activation_timestamp: pd.Timestamp
    source_swing_id: int
    swept_level: float
    wick_atr: float
    close_location: float
    range_expansion: bool


@dataclass(frozen=True)
class SweepDiagnostic:
    """Non-event observability for ambiguous or skipped sweep bars."""

    pos: int
    timestamp: pd.Timestamp
    code: Literal["dual_sided"]
    high_swing_id: int | None
    low_swing_id: int | None


@dataclass(frozen=True)
class SweepResult:
    """Typed sweep output: ordered events plus dual-sided diagnostics."""

    events: tuple[SweepEvent, ...]
    diagnostics: tuple[SweepDiagnostic, ...]


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _OHLC_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required OHLC columns: {missing}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def _validate_atr_buffer(atr_buffer: float) -> None:
    if isinstance(atr_buffer, bool) or not np.isfinite(atr_buffer) or atr_buffer < 0:
        raise ValueError(f"atr_buffer must be finite and >= 0, got {atr_buffer!r}")


def _validate_range_mult(mult: float) -> None:
    if isinstance(mult, bool) or not np.isfinite(mult) or mult <= 0:
        raise ValueError(f"range_expansion_mult must be finite and > 0, got {mult!r}")


def _close_location(high: float, low: float, close: float) -> float:
    span = high - low
    if not np.isfinite(span) or span <= 0:
        return float("nan")
    return float((close - low) / span)


def _bullish_sweep(
    low: float,
    close: float,
    level: float,
    atr: float,
    atr_buffer: float,
) -> bool:
    """Downside grab + reclaim. Wick uses ``>=`` buffer after strict level take."""
    if not (np.isfinite(low) and np.isfinite(close) and np.isfinite(level) and np.isfinite(atr)):
        return False
    if atr < 0:
        return False
    # Strict liquidity take of the swing low.
    if not (low < level):
        return False
    # Buffer distance with >= via float-stable form: low <= level - ATR×buffer.
    if low > (level - (atr * atr_buffer)):
        return False
    return close > level


def _bearish_sweep(
    high: float,
    close: float,
    level: float,
    atr: float,
    atr_buffer: float,
) -> bool:
    """Upside grab + reject. Symmetric to bullish."""
    if not (np.isfinite(high) and np.isfinite(close) and np.isfinite(level) and np.isfinite(atr)):
        return False
    if atr < 0:
        return False
    if not (high > level):
        return False
    # high >= level + ATR×buffer (equality at threshold counts).
    if high < (level + (atr * atr_buffer)):
        return False
    return close < level


def detect_sweeps(
    df: pd.DataFrame,
    swings: SwingResult,
    atr: pd.Series,
    atr_buffer: float = 0.05,
    range_expansion_mult: float = 1.5,
) -> SweepResult:
    """Detect one-shot liquidity sweeps on activated swing highs/lows.

    Parameters
    ----------
    df:
        OHLC frame. Index must be unique and monotonic increasing.
    swings:
        Causal swing result; only ``activation_pos`` eligibility is used
        (no extra confirmation delay).
    atr:
        Causal ATR series aligned (or reindexed) to ``df.index``. NaN bars
        never emit sweeps.
    atr_buffer:
        Minimum wick extension beyond the swing level in ATR units (``>=``).
    range_expansion_mult:
        Informational only — sets ``SweepEvent.range_expansion`` when
        ``(high - low) > mult * ATR``; does not gate emission.

    Notes
    -----
    Bar order: sweep checks run against levels activated *strictly before*
    the current bar; swing activations whose ``activation_pos == i`` become
    eligible from bar ``i + 1``.
    """
    _validate_ohlc(df)
    _validate_index(df.index)
    _validate_atr_buffer(atr_buffer)
    _validate_range_mult(range_expansion_mult)

    if not isinstance(swings, SwingResult):
        raise TypeError(f"swings must be SwingResult, got {type(swings).__name__}")
    if not isinstance(atr, pd.Series):
        raise TypeError("atr must be a pandas Series")
    if not atr.index.equals(df.index):
        atr = atr.reindex(df.index)

    n = len(df)
    index = df.index
    high = df["high"].to_numpy(dtype=float, copy=False)
    low = df["low"].to_numpy(dtype=float, copy=False)
    close = df["close"].to_numpy(dtype=float, copy=False)
    atr_arr = atr.to_numpy(dtype=float, copy=False)

    # activation_pos -> swings that become live *after* that bar closes
    by_act: dict[int, list[SwingEvent]] = {}
    for sw in swings.events:
        if sw.activation_pos < 0 or sw.activation_pos >= n:
            continue
        by_act.setdefault(sw.activation_pos, []).append(sw)

    active_high: SwingEvent | None = None
    active_low: SwingEvent | None = None

    events: list[SweepEvent] = []
    diagnostics: list[SweepDiagnostic] = []
    next_id = 0

    for i in range(n):
        h_i = float(high[i])
        l_i = float(low[i])
        c_i = float(close[i])
        a_i = float(atr_arr[i])

        bull = False
        bear = False
        if active_low is not None:
            bull = _bullish_sweep(l_i, c_i, active_low.level, a_i, atr_buffer)
        if active_high is not None:
            bear = _bearish_sweep(h_i, c_i, active_high.level, a_i, atr_buffer)

        if bull and bear:
            diagnostics.append(
                SweepDiagnostic(
                    pos=i,
                    timestamp=index[i],
                    code="dual_sided",
                    high_swing_id=active_high.id if active_high is not None else None,
                    low_swing_id=active_low.id if active_low is not None else None,
                )
            )
            # Ambiguous: no directional event. Consume both so one-shot lifecycle
            # does not spam diagnostics on later bars.
            active_high = None
            active_low = None
        elif bull and active_low is not None:
            level = float(active_low.level)
            wick_atr = (level - l_i) / a_i if np.isfinite(a_i) and a_i > 0 else float("nan")
            candle_range = h_i - l_i
            range_exp = bool(
                np.isfinite(a_i)
                and np.isfinite(candle_range)
                and candle_range > (range_expansion_mult * a_i)
            )
            events.append(
                SweepEvent(
                    id=next_id,
                    direction="bullish",
                    activation_pos=i,
                    activation_timestamp=index[i],
                    source_swing_id=active_low.id,
                    swept_level=level,
                    wick_atr=float(wick_atr),
                    close_location=_close_location(h_i, l_i, c_i),
                    range_expansion=range_exp,
                )
            )
            next_id += 1
            active_low = None  # consume source swing
        elif bear and active_high is not None:
            level = float(active_high.level)
            wick_atr = (h_i - level) / a_i if np.isfinite(a_i) and a_i > 0 else float("nan")
            candle_range = h_i - l_i
            range_exp = bool(
                np.isfinite(a_i)
                and np.isfinite(candle_range)
                and candle_range > (range_expansion_mult * a_i)
            )
            events.append(
                SweepEvent(
                    id=next_id,
                    direction="bearish",
                    activation_pos=i,
                    activation_timestamp=index[i],
                    source_swing_id=active_high.id,
                    swept_level=level,
                    wick_atr=float(wick_atr),
                    close_location=_close_location(h_i, l_i, c_i),
                    range_expansion=range_exp,
                )
            )
            next_id += 1
            active_high = None  # consume source swing

        # Register activations at this close for eligibility from the *next* bar.
        for sw in by_act.get(i, ()):
            if sw.direction == "high":
                active_high = sw
            else:
                active_low = sw

    return SweepResult(events=tuple(events), diagnostics=tuple(diagnostics))
