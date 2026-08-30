"""Causal ATR and baseline range-expansion metrics."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_OHLC_COLS = ("open", "high", "low", "close")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _OHLC_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required OHLC columns: {missing}")


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True-range ATR with causal NaN warmup (no backfill).

    ATR is defined only after ``period`` true-range observations exist in the
    rolling window. Early bars stay NaN so consumers cannot trade warmup.
    """
    _validate_ohlc(df)
    if not isinstance(period, (int, np.integer)) or isinstance(period, bool) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period, min_periods=period).mean()
    atr.name = "atr"
    return atr


@dataclass(frozen=True)
class ExpansionMetrics:
    """Per-bar range-expansion quality metrics (MVP qualifies on range only)."""

    range_atr: pd.Series
    body_atr: pd.Series
    body_ratio: pd.Series
    close_location: pd.Series  # 0 = low, 1 = high
    direction: pd.Series  # bullish | bearish | neutral
    qualified: pd.Series  # range_atr > multiplier (strict)


def detect_range_expansion(
    df: pd.DataFrame,
    atr: pd.Series,
    multiplier: float = 1.5,
) -> ExpansionMetrics:
    """Baseline range expansion: ``(high - low) > multiplier * ATR``.

    Optional quality series (body_ratio, close_location) are exposed but do not
    gate ``qualified`` in MVP.
    """
    _validate_ohlc(df)
    if not np.isfinite(multiplier) or multiplier <= 0:
        raise ValueError(f"multiplier must be finite and > 0, got {multiplier!r}")
    if not isinstance(atr, pd.Series):
        raise TypeError("atr must be a pandas Series")
    if not atr.index.equals(df.index):
        atr = atr.reindex(df.index)

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)
    close = df["close"].astype(float)
    atr_f = atr.astype(float)

    candle_range = high - low
    body = (close - open_).abs()

    range_atr = candle_range / atr_f
    body_atr = body / atr_f

    # Zero-range bars → undefined ratio/location
    with np.errstate(divide="ignore", invalid="ignore"):
        body_ratio = body / candle_range
        close_location = (close - low) / candle_range
    body_ratio = body_ratio.where(candle_range > 0)
    close_location = close_location.where(candle_range > 0)

    direction = pd.Series(
        np.where(close > open_, "bullish", np.where(close < open_, "bearish", "neutral")),
        index=df.index,
        dtype=object,
    )
    # NaN OHLC → neutral direction
    invalid_ohlc = open_.isna() | close.isna()
    direction = direction.where(~invalid_ohlc, other="neutral")

    # Strict >; NaN ATR or range → not qualified (warmup / gaps)
    qualified = (candle_range > (multiplier * atr_f)).fillna(False).astype(bool)

    return ExpansionMetrics(
        range_atr=range_atr.rename("range_atr"),
        body_atr=body_atr.rename("body_atr"),
        body_ratio=body_ratio.rename("body_ratio"),
        close_location=close_location.rename("close_location"),
        direction=direction.rename("direction"),
        qualified=qualified.rename("qualified"),
    )
