"""Market regime detection — Plan 14.

Distinguishes trending vs ranging markets from OHLCV + structure data. Used
by the backtester to weight OB-classic vs Breaker overlay entries.

Plan 14 (regime-aware strategy) extends Plan 13:
- Plan 13: breakers are an opt-in flag (``enable_breakers=True``).
- Plan 14: ``regime_mode='auto'`` derives the flag from regime metrics,
  mixing OB-classic and breaker entries by weighting.

The regime metric is intentionally lightweight so it does not require an
external library (no TA-Lib, no pandas-ta). Inputs come straight from the
OHLC frame already loaded for the backtest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from smc_engine.structure import StructureResult


@dataclass(frozen=True)
class RegimeState:
    """Snapshot of market regime at one evaluation point.

    - ``trend_strength`` in [0, 1]: 0 = sideways, 1 = strong trend.
      Computed from a smoothed directional-move ratio.
    - ``choppiness`` in [0, 1]: 0 = smooth, 1 = whipsaw.
      Computed from the fraction of bars that reverse prior direction within
      a small lookback window.
    - ``regime`` label: ``"trending" | "ranging" | "mixed"``.
    - ``ob_weight`` / ``breaker_weight`` in [0, 1] summing to 1.
    """

    trend_strength: float
    choppiness: float
    regime: str
    ob_weight: float
    breaker_weight: float


def _directional_move_ratio(close: pd.Series, lookback: int = 14) -> float:
    """Smoothed |net move| / |sum of absolute moves| over ``lookback`` bars.

    Returns 0 if total absolute movement is 0; otherwise a value in [0, 1]
    where 1 = perfectly directional and 0 = perfectly mean-reverting.
    """
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
    """Fraction of bars in the recent window whose sign reversed the prior
    bar's sign. Returns value in [0, 1]; higher = more whipsaw.
    """
    if len(close) < lookback + 1:
        return 0.0
    diffs = close.diff().tail(lookback + 1).dropna()
    if len(diffs) < 2:
        return 0.0
    signs = diffs.apply(np.sign)
    reversals = (signs.diff().abs() > 0).sum()
    return float(reversals) / float(len(signs) - 1)


def _regime_label(trend_strength: float, choppiness: float) -> str:
    """Heuristic regime classification.

    - ``trending`` if trend_strength >= 0.55 AND choppiness <= 0.50
    - ``ranging`` if trend_strength <= 0.35 AND choppiness >= 0.55
    - else ``mixed``
    """
    if trend_strength >= 0.55 and choppiness <= 0.50:
        return "trending"
    if trend_strength <= 0.35 and choppiness >= 0.55:
        return "ranging"
    return "mixed"


def _weights_from_regime(regime: str) -> tuple[float, float]:
    """Map regime label to (ob_weight, breaker_weight).

    - trending: OB-classic dominates, breakers mostly noise.
    - ranging: Breakers are high-quality mean-reversion entries.
    - mixed: split 50/50.
    """
    if regime == "trending":
        return (1.0, 0.0)
    if regime == "ranging":
        return (0.0, 1.0)
    return (0.5, 0.5)


def detect_regime(
    df: pd.DataFrame,
    *,
    trend_lookback: int = 14,
    chop_lookback: int = 14,
) -> RegimeState:
    """Evaluate regime at the LAST bar of ``df``.

    This is what the backtester will call before deciding whether to apply
    breakers. Returned ``ob_weight`` / ``breaker_weight`` sum to 1.
    """
    close = df["close"].astype(float)
    trend = _directional_move_ratio(close, lookback=trend_lookback)
    chop = _choppiness(close, lookback=chop_lookback)
    label = _regime_label(trend, chop)
    ob_w, br_w = _weights_from_regime(label)
    return RegimeState(
        trend_strength=trend,
        choppiness=chop,
        regime=label,
        ob_weight=ob_w,
        breaker_weight=br_w,
    )


# Side note on the structure argument: kept for a future phase that may
# weight regime by recent CHoCH frequency (see Plan 14 deferrals).
def _unused_structure_argument(_: StructureResult) -> None:
    return None