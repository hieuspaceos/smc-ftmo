"""Structure-derived bias and dealing-range premium/discount context.

Bias is the structure trend state machine output exactly
(``bull`` / ``bear`` / ``neutral``) — never a silent hold of a prior bias.

Premium/discount uses the latest activated external swing high/low pair from
structure (``last_swing_high`` / ``last_swing_low``). Equilibrium is the
midpoint; close above → premium, below → discount, else neutral. Without a
valid ordered pair (``low < high``), context is neutral.

Series outputs are index-aligned for adapter/backtester consumption. Rolling
lookback helpers remain in ``premium_discount.py`` until Phase 8 migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.structure import StructureResult

Bias = Literal["bull", "bear", "neutral"]
PDZone = Literal["premium", "discount", "neutral"]

ZONE_PREMIUM: PDZone = "premium"
ZONE_DISCOUNT: PDZone = "discount"
ZONE_NEUTRAL: PDZone = "neutral"

_VALID_BIAS = frozenset({"bull", "bear", "neutral"})
_REQUIRED_COLUMNS = ("close",)


@dataclass(frozen=True)
class ContextResult:
    """Index-aligned structure dealing-range premium/discount context.

    Keys mirror the rolling ``premium_discount`` snapshot contract so a later
    compatibility wrapper can re-expose ``zone`` / ``equilibrium`` /
    ``range_high`` / ``range_low`` / ``current_price`` without reshaping.
    """

    zone: pd.Series
    equilibrium: pd.Series
    range_high: pd.Series
    range_low: pd.Series
    current_price: pd.Series
    bias: pd.Series


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def compute_bias_series(structure: StructureResult) -> pd.Series:
    """Return structure trend as bias: ``bull`` / ``bear`` / ``neutral``.

    Neutral remains neutral until the structure state machine transitions.
    No carry-forward of a prior directional bias outside that machine.
    """
    if not isinstance(structure, StructureResult):
        raise TypeError("structure must be a StructureResult")
    trend = structure.trend
    if not isinstance(trend, pd.Series):
        raise TypeError("structure.trend must be a pandas Series")

    out = trend.astype(object).copy()
    out.name = "bias"
    # Guard unexpected values without inventing directional bias.
    invalid = ~out.isin(_VALID_BIAS)
    if invalid.any():
        out.loc[invalid] = "neutral"
    return out


def compute_dealing_range_context(
    df: pd.DataFrame,
    structure: StructureResult,
) -> ContextResult:
    """Classify each bar against the latest activated structure dealing range.

    A dealing range is valid only when both ``last_swing_low`` and
    ``last_swing_high`` are finite and strictly ordered ``low < high``.
    Otherwise the bar is ``neutral`` with NaN range fields.
    """
    _validate_ohlc(df)
    _validate_index(df.index)
    if not isinstance(structure, StructureResult):
        raise TypeError("structure must be a StructureResult")

    index = df.index
    n = len(df)
    if n == 0:
        empty = pd.Series(dtype=object, name="zone")
        nan = pd.Series(dtype=float)
        return ContextResult(
            zone=empty,
            equilibrium=nan.rename("equilibrium"),
            range_high=nan.rename("range_high"),
            range_low=nan.rename("range_low"),
            current_price=nan.rename("current_price"),
            bias=pd.Series(dtype=object, name="bias"),
        )

    if len(structure.trend) != n or not structure.trend.index.equals(index):
        raise ValueError("structure series index must match df.index")
    if not structure.last_swing_high.index.equals(index):
        raise ValueError("structure.last_swing_high index must match df.index")
    if not structure.last_swing_low.index.equals(index):
        raise ValueError("structure.last_swing_low index must match df.index")

    close = df["close"].to_numpy(dtype=float, copy=False)
    sh = structure.last_swing_high.to_numpy(dtype=float, copy=False)
    sl = structure.last_swing_low.to_numpy(dtype=float, copy=False)

    zone = np.empty(n, dtype=object)
    eq = np.full(n, np.nan, dtype=float)
    rh = np.full(n, np.nan, dtype=float)
    rl = np.full(n, np.nan, dtype=float)

    for i in range(n):
        hi = sh[i]
        lo = sl[i]
        c = close[i]
        if not (np.isfinite(hi) and np.isfinite(lo) and lo < hi):
            zone[i] = ZONE_NEUTRAL
            continue
        mid = (hi + lo) * 0.5
        rh[i] = hi
        rl[i] = lo
        eq[i] = mid
        if not np.isfinite(c):
            zone[i] = ZONE_NEUTRAL
        elif c > mid:
            zone[i] = ZONE_PREMIUM
        elif c < mid:
            zone[i] = ZONE_DISCOUNT
        else:
            zone[i] = ZONE_NEUTRAL

    bias = compute_bias_series(structure)
    return ContextResult(
        zone=pd.Series(zone, index=index, name="zone", dtype=object),
        equilibrium=pd.Series(eq, index=index, name="equilibrium", dtype=float),
        range_high=pd.Series(rh, index=index, name="range_high", dtype=float),
        range_low=pd.Series(rl, index=index, name="range_low", dtype=float),
        current_price=pd.Series(close, index=index, name="current_price", dtype=float),
        bias=bias,
    )


def context_snapshot(result: ContextResult, *, lookback: int | None = None) -> dict:
    """Last-bar dict compatible with ``detect_premium_discount`` keys.

    ``lookback`` is retained for wrapper parity; structure context does not use
    a rolling window, so the value is stored as provided (default ``None``).
    """
    if not isinstance(result, ContextResult):
        raise TypeError("result must be a ContextResult")
    if len(result.zone) == 0:
        return {
            "zone": ZONE_NEUTRAL,
            "equilibrium": 0.0,
            "range_high": 0.0,
            "range_low": 0.0,
            "current_price": 0.0,
            "lookback": lookback,
        }

    eq = result.equilibrium.iloc[-1]
    rh = result.range_high.iloc[-1]
    rl = result.range_low.iloc[-1]
    px = result.current_price.iloc[-1]
    return {
        "zone": str(result.zone.iloc[-1]),
        "equilibrium": float(eq) if np.isfinite(eq) else 0.0,
        "range_high": float(rh) if np.isfinite(rh) else 0.0,
        "range_low": float(rl) if np.isfinite(rl) else 0.0,
        "current_price": float(px) if np.isfinite(px) else 0.0,
        "lookback": lookback,
    }


def is_in_pd_zone(
    zone: str,
    direction: str,
    *,
    long_in_discount: bool = True,
    short_in_premium: bool = True,
) -> bool:
    """Direction-aware P/D check (long→discount, short→premium)."""
    if zone == ZONE_NEUTRAL:
        return False
    if direction == "long" and zone == ZONE_DISCOUNT and long_in_discount:
        return True
    if direction == "short" and zone == ZONE_PREMIUM and short_in_premium:
        return True
    return False
