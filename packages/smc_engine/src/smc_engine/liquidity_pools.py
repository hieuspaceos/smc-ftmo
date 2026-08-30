"""Equal-high/equal-low liquidity pool detection.

Pure enrichment layer over confirmed swings. A pool becomes confirmed when at
least two same-side swings activate close enough in price under a fixed internal
ATR-relative tolerance. Sweep detection is causal: bars are evaluated with the
pool boundary available at that time, and a sweep requires a reclaim close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.events import SwingEvent, SwingResult

PoolSide = Literal["high", "low"]

_TOLERANCE_ATR = 0.15
_MIN_MEMBERS = 2


@dataclass(frozen=True)
class LiquidityPoolEvent:
    id: int
    side: PoolSide
    activation_pos: int
    activation_timestamp: pd.Timestamp
    level_mean: float
    level_min: float
    level_max: float
    member_swing_ids: tuple[int, ...]
    member_levels: tuple[float, ...]
    swept: bool
    sweep_pos: int | None
    sweep_timestamp: pd.Timestamp | None


@dataclass(frozen=True)
class LiquidityPoolResult:
    events: tuple[LiquidityPoolEvent, ...]


@dataclass
class _PoolDraft:
    side: PoolSide
    member_swing_ids: list[int]
    member_levels: list[float]
    activation_pos: int | None = None
    activation_timestamp: pd.Timestamp | None = None
    sweep_pos: int | None = None
    sweep_timestamp: pd.Timestamp | None = None
    last_scanned_pos: int = -1

    @property
    def level_mean(self) -> float:
        return float(sum(self.member_levels) / len(self.member_levels))

    @property
    def level_min(self) -> float:
        return float(min(self.member_levels))

    @property
    def level_max(self) -> float:
        return float(max(self.member_levels))

    @property
    def is_confirmed(self) -> bool:
        return self.activation_pos is not None and self.activation_timestamp is not None


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def _match_pool(drafts: list[_PoolDraft], swing: SwingEvent, atr_now: float) -> _PoolDraft | None:
    tolerance = float(atr_now) * _TOLERANCE_ATR
    best: _PoolDraft | None = None
    best_distance = float("inf")
    for draft in drafts:
        if draft.sweep_pos is not None:
            continue
        distance = abs(float(swing.level) - draft.level_mean)
        if distance > tolerance:
            continue
        if distance < best_distance:
            best = draft
            best_distance = distance
    return best


def _scan_until(
    df: pd.DataFrame,
    draft: _PoolDraft,
    *,
    stop_pos: int,
) -> None:
    if not draft.is_confirmed or draft.sweep_pos is not None:
        return
    assert draft.activation_pos is not None
    start = max(draft.last_scanned_pos + 1, draft.activation_pos + 1)
    stop = min(stop_pos, len(df))
    if start >= stop:
        draft.last_scanned_pos = max(draft.last_scanned_pos, stop - 1)
        return

    high = df["high"].to_numpy(dtype=float, copy=False)
    low = df["low"].to_numpy(dtype=float, copy=False)
    close = df["close"].to_numpy(dtype=float, copy=False)
    level_high = draft.level_max
    level_low = draft.level_min

    for pos in range(start, stop):
        c = close[pos]
        if not np.isfinite(c):
            continue
        if draft.side == "high":
            if np.isfinite(high[pos]) and high[pos] > level_high and c < level_high:
                draft.sweep_pos = pos
                draft.sweep_timestamp = df.index[pos]
                draft.last_scanned_pos = pos
                return
        else:
            if np.isfinite(low[pos]) and low[pos] < level_low and c > level_low:
                draft.sweep_pos = pos
                draft.sweep_timestamp = df.index[pos]
                draft.last_scanned_pos = pos
                return
    draft.last_scanned_pos = stop - 1


def detect_liquidity_pools(
    df: pd.DataFrame,
    swings: SwingResult,
    atr: pd.Series,
) -> LiquidityPoolResult:
    """Detect EQH/EQL-style liquidity pools from confirmed swings.

    High-side pools cluster nearby swing highs. Low-side pools cluster nearby
    swing lows. A pool is confirmed when the second matching swing activates;
    later members extend the pool only from that bar forward.
    """
    _validate_index(df.index)
    if not isinstance(swings, SwingResult):
        raise TypeError("swings must be a SwingResult")
    if not isinstance(atr, pd.Series):
        raise TypeError("atr must be a pandas Series")
    if not atr.index.equals(df.index):
        atr = atr.reindex(df.index)

    high_drafts: list[_PoolDraft] = []
    low_drafts: list[_PoolDraft] = []
    all_drafts: list[_PoolDraft] = []
    by_activation: dict[int, list[SwingEvent]] = {}

    for swing in swings.events:
        if swing.activation_pos < 0 or swing.activation_pos >= len(df):
            raise ValueError(
                f"swing id={swing.id} activation_pos={swing.activation_pos} out of range for n={len(df)}"
            )
        by_activation.setdefault(swing.activation_pos, []).append(swing)

    for activation_pos in sorted(by_activation):
        for draft in all_drafts:
            _scan_until(df, draft, stop_pos=activation_pos + 1)

        for swing in by_activation[activation_pos]:
            atr_now = atr.iloc[swing.activation_pos]
            if not np.isfinite(atr_now) or float(atr_now) <= 0.0:
                continue

            drafts = high_drafts if swing.direction == "high" else low_drafts
            side: PoolSide = "high" if swing.direction == "high" else "low"
            match = _match_pool(drafts, swing, float(atr_now))
            if match is None:
                draft = _PoolDraft(
                    side=side,
                    member_swing_ids=[swing.id],
                    member_levels=[float(swing.level)],
                )
                drafts.append(draft)
                all_drafts.append(draft)
                continue

            match.member_swing_ids.append(swing.id)
            match.member_levels.append(float(swing.level))
            if len(match.member_swing_ids) == _MIN_MEMBERS:
                match.activation_pos = swing.activation_pos
                match.activation_timestamp = swing.activation_timestamp
                match.last_scanned_pos = swing.activation_pos
    for draft in all_drafts:
        _scan_until(df, draft, stop_pos=len(df))

    events: list[LiquidityPoolEvent] = []
    next_id = 0
    for draft in all_drafts:
        if not draft.is_confirmed:
            continue
        assert draft.activation_pos is not None
        assert draft.activation_timestamp is not None
        events.append(
            LiquidityPoolEvent(
                id=next_id,
                side=draft.side,
                activation_pos=draft.activation_pos,
                activation_timestamp=draft.activation_timestamp,
                level_mean=draft.level_mean,
                level_min=draft.level_min,
                level_max=draft.level_max,
                member_swing_ids=tuple(draft.member_swing_ids),
                member_levels=tuple(draft.member_levels),
                swept=draft.sweep_pos is not None,
                sweep_pos=draft.sweep_pos,
                sweep_timestamp=draft.sweep_timestamp,
            )
        )
        next_id += 1
    events.sort(key=lambda event: (event.activation_pos, event.id))
    return LiquidityPoolResult(events=tuple(events))
