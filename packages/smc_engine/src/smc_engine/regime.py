"""Structure-aware market regime detection.

Used by the backtester and app to decide whether breaker overlays should stay
off (`off` baseline), stay on, or be auto-selected from recent SMC structure.
The baseline-safe default is conservative: only a clearly ranging regime turns
breakers on automatically.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.displacement import calculate_atr
from smc_engine.liquidity_pools import LiquidityPoolResult, detect_liquidity_pools
from smc_engine.structure import StructureResult, detect_structure
from smc_engine.sweeps import SweepResult, detect_sweeps
from smc_engine.swings import detect_swings

RegimeLabel = Literal["trending", "ranging", "mixed"]
RegimeDirection = Literal["bullish", "bearish", "neutral"]

_STRUCTURE_LOOKBACK_BARS = 600
_MIN_RECENT_STRUCTURE_EVENTS = 12
_MIN_RECENT_BOS_EVENTS = 4


@dataclass(frozen=True)
class RegimeState:
    """Snapshot of market regime at one evaluation point.

    `trend_strength` and `choppiness` stay in [0, 1] for compatibility with
    the earlier lightweight heuristic, but now they represent structure-aware
    continuation and ranging pressure.
    """

    trend_strength: float
    choppiness: float
    regime: RegimeLabel
    ob_weight: float
    breaker_weight: float
    dominant_direction: RegimeDirection = "neutral"
    bos_density: float = 0.0
    choch_density: float = 0.0
    sweep_density: float = 0.0
    liquidity_pool_density: float = 0.0
    explanation: str = ""


def _directional_move_ratio(close: pd.Series, lookback: int = 14) -> float:
    """Smoothed |net move| / |sum of absolute moves| over `lookback` bars."""
    if len(close) < lookback + 1:
        return 0.0
    diffs = close.diff().tail(lookback + 1).dropna()
    if len(diffs) == 0:
        return 0.0
    net = float(abs(diffs.sum()))
    total = float(diffs.abs().sum())
    if total == 0:
        return 0.0
    return min(net / total, 1.0)


def _choppiness(close: pd.Series, lookback: int = 14) -> float:
    """Fraction of sign reversals in the recent window."""
    if len(close) < lookback + 1:
        return 0.0
    diffs = close.diff().tail(lookback + 1).dropna()
    if len(diffs) < 2:
        return 0.0
    signs = diffs.apply(np.sign)
    reversals = (signs.diff().abs() > 0).sum()
    return float(reversals) / float(len(signs) - 1)


def _regime_label(trend_strength: float, choppiness: float) -> RegimeLabel:
    """Conservative structure-aware label.

    - trending: strong continuation, contained ranging pressure
    - ranging: heavy reversal pressure, weak directional persistence
    - mixed: everything else
    """
    if trend_strength >= 0.62 and choppiness <= 0.50:
        return "trending"
    if trend_strength <= 0.56 and choppiness >= 0.58:
        return "ranging"
    return "mixed"


def _weights_from_regime(regime: str) -> tuple[float, float]:
    """Map regime label to (ob_weight, breaker_weight).

    Mixed stays conservative because the shipped baseline OB path is already
    profitable and breaker edge is only proven in clean ranging conditions.
    """
    if regime == "trending":
        return (1.0, 0.0)
    if regime == "ranging":
        return (0.0, 1.0)
    return (1.0, 0.0)


def _recent_window(df: pd.DataFrame) -> int:
    return min(len(df), _STRUCTURE_LOOKBACK_BARS)


def _dominant_bos_direction(events) -> RegimeDirection:
    bull_bos = sum(ev.type == "bos" and ev.direction == "bullish" for ev in events)
    bear_bos = sum(ev.type == "bos" and ev.direction == "bearish" for ev in events)
    if bull_bos > bear_bos:
        return "bullish"
    if bear_bos > bull_bos:
        return "bearish"
    return "neutral"


def _fallback_state(close: pd.Series) -> RegimeState:
    trend = _directional_move_ratio(close, lookback=14)
    chop = _choppiness(close, lookback=14)
    label: RegimeLabel = "trending" if trend >= 0.70 and chop <= 0.25 else "mixed"
    ob_w, br_w = _weights_from_regime(label)
    explanation = (
        f"{label}: sparse recent structure, so auto stays conservative "
        f"(trend={trend:.2f}, range={chop:.2f})."
    )
    return RegimeState(
        trend_strength=trend,
        choppiness=chop,
        regime=label,
        ob_weight=ob_w,
        breaker_weight=br_w,
        explanation=explanation,
    )


def detect_regime(
    df: pd.DataFrame,
    *,
    structure: StructureResult | None = None,
    sweeps: SweepResult | None = None,
    liquidity_pools: LiquidityPoolResult | None = None,
    swing_left: int = 5,
    swing_right: int = 5,
    sweep_atr_buffer: float = 0.05,
    displacement_atr_mult: float = 1.5,
) -> RegimeState:
    """Evaluate regime from recent structure and sweeps.

    When the recent window does not contain enough confirmed structure to make a
    clean call, the function falls back to the earlier price-path heuristic
    instead of inventing certainty.
    """
    if df.empty or "close" not in df.columns:
        return RegimeState(0.0, 0.0, "mixed", 1.0, 0.0, explanation="mixed: empty input.")

    close = df["close"].astype(float)
    if structure is None or sweeps is None or liquidity_pools is None:
        atr = calculate_atr(df)
        swings = detect_swings(df, left=swing_left, right=swing_right)
        if structure is None:
            structure = detect_structure(df, swings, atr=atr)
        if sweeps is None:
            sweeps = detect_sweeps(
                df,
                swings,
                atr,
                atr_buffer=sweep_atr_buffer,
                range_expansion_mult=displacement_atr_mult,
            )
        if liquidity_pools is None:
            liquidity_pools = detect_liquidity_pools(df, swings, atr)

    window = _recent_window(df)
    start_pos = max(0, len(df) - window)
    recent_structure = [
        ev for ev in structure.events if ev.activation_pos >= start_pos
    ]
    recent_bos = [ev for ev in recent_structure if ev.type == "bos"]
    recent_choch = [ev for ev in recent_structure if ev.type == "choch"]
    recent_sweeps = [
        ev for ev in sweeps.events if ev.activation_pos >= start_pos
    ]
    recent_pools = []
    if liquidity_pools is not None:
        recent_pools = [
            ev for ev in liquidity_pools.events if ev.activation_pos >= start_pos
        ]
    if (
        len(recent_structure) < _MIN_RECENT_STRUCTURE_EVENTS
        or len(recent_bos) < _MIN_RECENT_BOS_EVENTS
    ):
        return _fallback_state(close)

    trend_slice = structure.trend.iloc[start_pos:]
    dominant_trend_bars = Counter(str(v) for v in trend_slice if str(v) in ("bull", "bear"))
    dominant_trend_fraction = (
        dominant_trend_bars.most_common(1)[0][1] / max(len(trend_slice), 1)
        if dominant_trend_bars
        else 0.0
    )

    dominant_direction = _dominant_bos_direction(recent_structure)
    dominant_bos_count = sum(ev.direction == dominant_direction for ev in recent_bos)
    bos_directional_share = dominant_bos_count / max(len(recent_bos), 1)
    continuation = min(
        1.0,
        max(0.0, 0.55 * dominant_trend_fraction + 0.45 * bos_directional_share),
    )

    choch_fraction = len(recent_choch) / max(len(recent_structure), 1)
    sweep_fraction = len(recent_sweeps) / max(len(recent_structure) + len(recent_sweeps), 1)
    pool_fraction = len(recent_pools) / max(len(recent_structure), 1)
    ranging_pressure = min(
        1.0,
        max(0.0, 0.50 * choch_fraction + 0.35 * sweep_fraction + 0.15 * pool_fraction),
    )

    label = _regime_label(continuation, ranging_pressure)
    ob_w, br_w = _weights_from_regime(label)
    bars_per_100 = max(window / 100.0, 1e-9)
    explanation = (
        f"{label}: BOS {len(recent_bos) / bars_per_100:.1f}/100, "
        f"CHoCH {len(recent_choch) / bars_per_100:.1f}/100, "
        f"sweeps {len(recent_sweeps) / bars_per_100:.1f}/100, "
        f"EQH/EQL pools {len(recent_pools) / bars_per_100:.1f}/100, "
        f"dominant BOS {dominant_direction}, continuation {continuation:.2f}, "
        f"range pressure {ranging_pressure:.2f}."
    )
    return RegimeState(
        trend_strength=continuation,
        choppiness=ranging_pressure,
        regime=label,
        ob_weight=ob_w,
        breaker_weight=br_w,
        dominant_direction=dominant_direction,
        bos_density=len(recent_bos) / bars_per_100,
        choch_density=len(recent_choch) / bars_per_100,
        sweep_density=len(recent_sweeps) / bars_per_100,
        liquidity_pool_density=len(recent_pools) / bars_per_100,
        explanation=explanation,
    )