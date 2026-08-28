"""Causal three-candle Fair Value Gap detection with touch/fill lifecycle.

MVP rules:
- Bullish gap at bar ``i``: ``high[i-2] < low[i]`` → zone ``[high[i-2], low[i]]``.
- Bearish gap at bar ``i``: ``low[i-2] > high[i]`` → zone ``[high[i], low[i-2]]``.
- Equality does not form a gap.
- Event activates at the third candle close (bar ``i``) and is unavailable before.
- Lifecycle (first-touch / full-fill / expiry) starts at bar ``i + 1``.
- First touch: bullish ``low <= top``; bearish ``high >= bottom``.
- Full fill: bullish ``low <= bottom``; bearish ``high >= top``.
- Expiry: ``expiry_bars`` (default 200) after activation; at most
  ``max_active_per_direction`` (default 128) concurrent active gaps per side;
  oldest is expired at the cap with a diagnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

FVGDirection = Literal["bullish", "bearish"]

_REQUIRED_COLUMNS = ("high", "low")
_DEFAULT_EXPIRY_BARS = 200
_DEFAULT_MAX_ACTIVE = 128


@dataclass(frozen=True)
class FairValueGapEvent:
    """Immutable FVG zone with origin/activation and lifecycle timestamps."""

    id: int
    direction: FVGDirection
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None
    fill_timestamp: pd.Timestamp | None
    expiry_timestamp: pd.Timestamp | None

    @property
    def price(self) -> float:
        """Compatibility midpoint between zone bounds."""
        return (self.top + self.bottom) * 0.5

    def is_active_at(self, ts: pd.Timestamp) -> bool:
        """True when activated and strictly before fill/expiry.

        Matches order-block lifecycle: ``activation <= ts < fill/expiry``.
        First-touch bar remains active when fill occurs on a later bar.
        """
        t = pd.Timestamp(ts)
        if t < self.activation_timestamp:
            return False
        if self.fill_timestamp is not None and t >= self.fill_timestamp:
            return False
        if self.expiry_timestamp is not None and t >= self.expiry_timestamp:
            return False
        return True

    def is_first_test_at(self, ts: pd.Timestamp) -> bool:
        """True while active and at or before the first touch (or never touched)."""
        if not self.is_active_at(ts):
            return False
        if self.first_touch_timestamp is None:
            return True
        return pd.Timestamp(ts) <= self.first_touch_timestamp


@dataclass(frozen=True)
class FVGResult:
    """Typed FVG output: chronological events plus cap/expiry diagnostics."""

    events: tuple[FairValueGapEvent, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass
class _LiveFVG:
    """Mutable builder used only during the single chronological pass."""

    id: int
    direction: FVGDirection
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None = None
    fill_timestamp: pd.Timestamp | None = None
    expiry_timestamp: pd.Timestamp | None = None
    closed: bool = False

    def freeze(self) -> FairValueGapEvent:
        return FairValueGapEvent(
            id=self.id,
            direction=self.direction,
            origin_pos=self.origin_pos,
            origin_timestamp=self.origin_timestamp,
            activation_pos=self.activation_pos,
            activation_timestamp=self.activation_timestamp,
            top=self.top,
            bottom=self.bottom,
            first_touch_timestamp=self.first_touch_timestamp,
            fill_timestamp=self.fill_timestamp,
            expiry_timestamp=self.expiry_timestamp,
        )


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def _validate_positive_int(name: str, value: int) -> int:
    if not isinstance(value, (int, np.integer)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a positive int, got {type(value).__name__}")
    ivalue = int(value)
    if ivalue <= 0:
        raise ValueError(f"{name} must be > 0, got {ivalue}")
    return ivalue


def _expire(
    live: _LiveFVG,
    ts: pd.Timestamp,
    diagnostics: list[str],
    reason: str,
    bar_i: int,
) -> None:
    if live.closed:
        return
    live.expiry_timestamp = ts
    live.closed = True
    diagnostics.append(f"{reason}@i={bar_i}:id={live.id}:dir={live.direction}")


def _apply_touch_fill(live: _LiveFVG, high: float, low: float, ts: pd.Timestamp) -> None:
    if live.closed:
        return
    if live.direction == "bullish":
        if live.first_touch_timestamp is None and low <= live.top:
            live.first_touch_timestamp = ts
        if live.fill_timestamp is None and low <= live.bottom:
            live.fill_timestamp = ts
            live.closed = True
    else:
        if live.first_touch_timestamp is None and high >= live.bottom:
            live.first_touch_timestamp = ts
        if live.fill_timestamp is None and high >= live.top:
            live.fill_timestamp = ts
            live.closed = True


def detect_fvgs(
    df: pd.DataFrame,
    *,
    expiry_bars: int = _DEFAULT_EXPIRY_BARS,
    max_active_per_direction: int = _DEFAULT_MAX_ACTIVE,
) -> FVGResult:
    """Detect FVGs and resolve touch/fill/expiry in one chronological pass.

    Parameters
    ----------
    df:
        OHLC frame; ``high`` and ``low`` required. Index must be unique and
        monotonic increasing.
    expiry_bars:
        Bars after ``activation_pos`` at which an unfilled gap expires.
    max_active_per_direction:
        Maximum concurrently active (unfilled, unexpired) gaps per direction.
        When a new gap would exceed the cap, the oldest active gap is expired.
    """
    _validate_ohlc(df)
    _validate_index(df.index)
    expiry_bars = _validate_positive_int("expiry_bars", expiry_bars)
    max_active = _validate_positive_int("max_active_per_direction", max_active_per_direction)

    n = len(df)
    if n == 0:
        return FVGResult(events=())

    index = df.index
    high = df["high"].to_numpy(dtype=float, copy=False)
    low = df["low"].to_numpy(dtype=float, copy=False)

    lives: list[_LiveFVG] = []
    active_bull: list[int] = []
    active_bear: list[int] = []
    diagnostics: list[str] = []
    next_id = 0

    def _prune(active: list[int]) -> None:
        # Drop closed refs; order preserved for oldest-first cap expiry.
        keep = [idx for idx in active if not lives[idx].closed]
        active[:] = keep

    def _age_expire(active: list[int], i: int, ts: pd.Timestamp) -> None:
        changed = False
        for idx in active:
            live = lives[idx]
            if live.closed:
                changed = True
                continue
            if i - live.activation_pos >= expiry_bars:
                _expire(live, ts, diagnostics, "fvg_age_expiry", i)
                changed = True
        if changed:
            _prune(active)

    def _cap_expire(active: list[int], i: int, ts: pd.Timestamp) -> None:
        _prune(active)
        while len(active) >= max_active:
            oldest_idx = active.pop(0)
            live = lives[oldest_idx]
            if not live.closed:
                _expire(live, ts, diagnostics, "fvg_cap_expiry", i)

    for i in range(n):
        ts = index[i]
        h = high[i]
        lo = low[i]

        # Lifecycle for gaps activated strictly before this bar.
        for idx in active_bull:
            _apply_touch_fill(lives[idx], h, lo, ts)
        for idx in active_bear:
            _apply_touch_fill(lives[idx], h, lo, ts)

        _age_expire(active_bull, i, ts)
        _age_expire(active_bear, i, ts)

        if i < 2:
            continue
        if not (np.isfinite(high[i - 2]) and np.isfinite(low[i - 2]) and np.isfinite(h) and np.isfinite(lo)):
            continue

        new_live: _LiveFVG | None = None
        if high[i - 2] < lo:
            bottom = float(high[i - 2])
            top = float(lo)
            if bottom < top:
                new_live = _LiveFVG(
                    id=next_id,
                    direction="bullish",
                    origin_pos=i - 1,
                    origin_timestamp=index[i - 1],
                    activation_pos=i,
                    activation_timestamp=ts,
                    top=top,
                    bottom=bottom,
                )
        elif low[i - 2] > h:
            bottom = float(h)
            top = float(low[i - 2])
            if bottom < top:
                new_live = _LiveFVG(
                    id=next_id,
                    direction="bearish",
                    origin_pos=i - 1,
                    origin_timestamp=index[i - 1],
                    activation_pos=i,
                    activation_timestamp=ts,
                    top=top,
                    bottom=bottom,
                )

        if new_live is None:
            continue

        lives.append(new_live)
        next_id += 1
        if new_live.direction == "bullish":
            _cap_expire(active_bull, i, ts)
            active_bull.append(len(lives) - 1)
        else:
            _cap_expire(active_bear, i, ts)
            active_bear.append(len(lives) - 1)

    return FVGResult(
        events=tuple(live.freeze() for live in lives),
        diagnostics=tuple(diagnostics),
    )
