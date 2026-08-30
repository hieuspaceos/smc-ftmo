"""Shared immutable event contracts for the SMC engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class SwingEvent:
    """A confirmed Williams/fractal pivot with causal activation timing.

    A pivot detected at ``pivot_pos`` becomes usable only at
    ``activation_pos == pivot_pos + right``. Downstream phases must consume
    activation fields directly and must not re-apply a confirmation delay.
    """

    id: int
    direction: Literal["high", "low"]
    level: float
    pivot_pos: int
    pivot_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp


@dataclass(frozen=True)
class SwingResult:
    """Typed swing output: ordered events plus activation-aligned series.

    ``high_at_activation`` / ``low_at_activation`` carry the confirmed level
    at the activation bar index (NaN elsewhere). Index/timezone match the
    input OHLC frame.
    """

    events: tuple[SwingEvent, ...]
    high_at_activation: pd.Series
    low_at_activation: pd.Series
