"""Compatibility adapter over the in-project SMC engine.

The class and function signatures are preserved so existing callers (app.py,
backtester.py) continue to work. Internally this delegates to:

    src.smc_engine.swings, structure, sweeps, order_blocks, fvg, displacement,
    context.

The generic ``Signal`` dataclass remains the serialization shape for chart
overlay, journal rows, and backtest entry selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

from smc_engine.context import (
    compute_bias_series,
    compute_dealing_range_context,
    is_in_pd_zone,
)
from smc_engine.displacement import (
    ExpansionMetrics,
    calculate_atr,
    detect_range_expansion,
)
from smc_engine.fvg import FairValueGapEvent, FVGResult, detect_fvgs
from smc_engine.order_blocks import (
    OrderBlockEvent,
    OrderBlockResult,
    detect_order_blocks,
)
from smc_engine.structure import detect_structure
from smc_engine.sweeps import SweepEvent, SweepResult, detect_sweeps
from smc_engine.swings import SwingResult, detect_swings


SignalType = Literal["bos", "choch", "fvg", "ob", "sweep", "displacement"]
SignalDirection = Literal["bullish", "bearish"]


@dataclass
class Signal:
    """Generic SMC overlay signal. Field names match the legacy contract."""

    timestamp: datetime
    type: str
    price: float
    direction: str
    mitigated: bool = False
    mitigation_time: Optional[datetime] = None
    confluence: int = 0
    top: Optional[float] = None
    bottom: Optional[float] = None


EMPTY_SIGNAL_DICT: Dict[str, List[Signal]] = {
    "bos": [],
    "choch": [],
    "fvg": [],
    "ob": [],
    "sweep": [],
    "displacement": [],
}


def _to_datetime(ts: pd.Timestamp) -> datetime:
    return pd.Timestamp(ts).to_pydatetime()


def _to_pd_timestamp(ts: datetime | pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(ts)


def _signals_from_sweeps(result: SweepResult) -> List[Signal]:
    out: List[Signal] = []
    for event in result.events:
        out.append(Signal(
            timestamp=_to_datetime(event.activation_timestamp),
            type="sweep",
            price=float(event.swept_level),
            direction=event.direction,
            confluence=0,
            mitigated=False,
        ))
    return out


def _signals_from_displacement(metrics: ExpansionMetrics) -> List[Signal]:
    out: List[Signal] = []
    direction = metrics.direction
    close = metrics.range_atr  # placeholder; replaced below with close series
    qualified = metrics.qualified
    if not qualified.any():
        return out
    valid_dir = direction[direction != "neutral"]
    valid_dir = valid_dir.reindex(qualified.index)
    valid_qualified = qualified & (valid_dir != "neutral")
    for ts, is_qual in valid_qualified.items():
        if not bool(is_qual):
            continue
        d = str(direction.loc[ts])
        out.append(Signal(
            timestamp=_to_datetime(ts),
            type="displacement",
            price=0.0,
            direction=d,
            confluence=0,
            mitigated=False,
        ))
    return out


def _signals_from_ob(result: OrderBlockResult) -> List[Signal]:
    out: List[Signal] = []
    for ob in result.events:
        out.append(Signal(
            timestamp=_to_datetime(ob.activation_timestamp),
            type="ob",
            price=ob.price,
            direction=ob.direction,
            mitigated=ob.invalidation_timestamp is not None,
            mitigation_time=_to_datetime(ob.invalidation_timestamp) if ob.invalidation_timestamp is not None else None,
            confluence=0,
            top=float(ob.top),
            bottom=float(ob.bottom),
        ))
    return out


def _signals_from_fvg(result: FVGResult) -> List[Signal]:
    out: List[Signal] = []
    for fvg in result.events:
        out.append(Signal(
            timestamp=_to_datetime(fvg.activation_timestamp),
            type="fvg",
            price=fvg.price,
            direction=fvg.direction,
            mitigated=fvg.fill_timestamp is not None,
            mitigation_time=_to_datetime(fvg.fill_timestamp) if fvg.fill_timestamp is not None else None,
            confluence=0,
            top=float(fvg.top),
            bottom=float(fvg.bottom),
        ))
    return out


def _signals_from_structure(result) -> tuple[List[Signal], List[Signal]]:
    bos: List[Signal] = []
    choch: List[Signal] = []
    for ev in result.events:
        sig = Signal(
            timestamp=_to_datetime(ev.activation_timestamp),
            type="bos" if ev.type == "bos" else "choch",
            price=float(ev.broken_level),
            direction=ev.direction,
            confluence=0,
        )
        if ev.type == "bos":
            bos.append(sig)
        else:
            choch.append(sig)
    return bos, choch


def compute_overlays(
    df: pd.DataFrame,
    *,
    swing_left: int = 5,
    swing_right: int = 5,
    displacement_atr_mult: float = 1.5,
    sweep_atr_buffer: float = 0.05,
) -> Dict[str, pd.Series | SwingResult | object]:
    """Return the raw engine outputs (used by tests/backtester)."""
    if df.empty or len(df) < (swing_left + swing_right + 1):
        return {"swings": SwingResult((), pd.Series(dtype=float), pd.Series(dtype=float))}

    swings = detect_swings(df, left=swing_left, right=swing_right)
    atr = calculate_atr(df)
    expansion = detect_range_expansion(df, atr, multiplier=displacement_atr_mult)
    structure = detect_structure(df, swings, atr=atr)
    sweeps = detect_sweeps(
        df,
        swings,
        atr,
        atr_buffer=sweep_atr_buffer,
        range_expansion_mult=displacement_atr_mult,
    )
    order_blocks = detect_order_blocks(df, structure, expansion)
    fvgs = detect_fvgs(df)
    context = compute_dealing_range_context(df, structure)
    bias = compute_bias_series(structure)
    return {
        "swings": swings,
        "atr": atr,
        "expansion": expansion,
        "structure": structure,
        "sweeps": sweeps,
        "order_blocks": order_blocks,
        "fvgs": fvgs,
        "context": context,
        "bias": bias,
    }


class SMCSignals:
    """Compatibility wrapper that exposes generic Signal dicts."""

    def __init__(
        self,
        swing_length: int = 20,
        displacement_atr_mult: float = 1.5,
        sweep_atr_buffer: float = 0.05,
    ):
        self.swing_length = swing_length
        self.displacement_atr_mult = displacement_atr_mult
        self.sweep_atr_buffer = sweep_atr_buffer
        # Map user-facing swing_length to (left, right) symmetric window.
        self._left = self._right = max(2, self.swing_length // 2)

    def get_signals(
        self,
        df: pd.DataFrame,
        tf: str = "M15",
        skip_mitigation: bool = False,
    ) -> Dict[str, List[Signal]]:
        empty = {key: [] for key in EMPTY_SIGNAL_DICT}
        if df.empty or len(df) < (self._left + self._right + 1):
            return empty

        overlays = compute_overlays(
            df,
            swing_left=self._left,
            swing_right=self._right,
            displacement_atr_mult=self.displacement_atr_mult,
            sweep_atr_buffer=self.sweep_atr_buffer,
        )

        bos, choch = _signals_from_structure(overlays["structure"])
        signals: Dict[str, List[Signal]] = {
            "bos": bos,
            "choch": choch,
            "fvg": _signals_from_fvg(overlays["fvgs"]),
            "ob": _signals_from_ob(overlays["order_blocks"]),
            "sweep": _signals_from_sweeps(overlays["sweeps"]),
            "displacement": _signals_from_displacement(overlays["expansion"]),
        }

        if not skip_mitigation:
            return signals
        # Backwards-compatible skip_mitigation: drop zones already known to be
        # mitigated/invalidated/filled at the timestamp of their event.
        signals["ob"] = [s for s in signals["ob"] if not s.mitigated]
        signals["fvg"] = [s for s in signals["fvg"] if not s.mitigated]
        return signals


def get_smc_overlays(
    df: pd.DataFrame,
    params: Dict[str, Any] | None = None,
) -> Dict[str, List[Signal]]:
    """Functional wrapper kept for backward compatibility with app.py."""
    if params is None:
        params = {}
    kw = {
        "swing_length": params.get("swing_length", 20),
        "displacement_atr_mult": params.get("displacement_atr_mult", 1.5),
        "sweep_atr_buffer": params.get("sweep_atr_buffer", 0.05),
    }
    return SMCSignals(**kw).get_signals(df)


__all__ = ["Signal", "SMCSignals", "get_smc_overlays", "calculate_atr"]
