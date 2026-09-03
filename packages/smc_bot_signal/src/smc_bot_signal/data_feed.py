"""Market data feed protocol + offline implementations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from smc_bot_signal.config import SignalBotConfig

logger = logging.getLogger("smc_bot_signal.feed")

_OHLC = ("open", "high", "low", "close")


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Return OHLC frame with UTC DatetimeIndex, sorted unique bars."""
    if df is None or df.empty:
        out = pd.DataFrame(columns=list(_OHLC))
        out.index = pd.DatetimeIndex([], tz="UTC", name="time")
        return out

    frame = df.copy()
    cols = {c.lower(): c for c in frame.columns}
    rename = {}
    for need in _OHLC:
        if need in frame.columns:
            continue
        if need in cols:
            rename[cols[need]] = need
        else:
            raise ValueError(f"OHLC missing column {need!r}; got {list(frame.columns)}")
    if rename:
        frame = frame.rename(columns=rename)

    if not isinstance(frame.index, pd.DatetimeIndex):
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"], utc=True)
            frame = frame.set_index("time")
        else:
            frame.index = pd.to_datetime(frame.index, utc=True)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    else:
        frame.index = frame.index.tz_convert("UTC")

    frame = frame.loc[:, list(_OHLC)].astype(float)
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.sort_index()
    frame.index.name = "time"
    return frame


@runtime_checkable
class MarketDataFeed(Protocol):
    def get_ohlc(
        self,
        symbol: str,
        *,
        timeframe: str = "M15",
        bars: int = 500,
    ) -> pd.DataFrame:
        """Return normalized OHLC for ``symbol`` (most recent ``bars``)."""


class InMemoryFeed:
    """Dict-backed feed for tests."""

    def __init__(self, frames: dict[str, pd.DataFrame] | None = None) -> None:
        self._frames: dict[str, pd.DataFrame] = {
            k.upper(): normalize_ohlc(v) for k, v in (frames or {}).items()
        }

    def set_frame(self, symbol: str, df: pd.DataFrame) -> None:
        self._frames[symbol.upper()] = normalize_ohlc(df)

    def get_ohlc(
        self,
        symbol: str,
        *,
        timeframe: str = "M15",
        bars: int = 500,
    ) -> pd.DataFrame:
        _ = timeframe
        frame = self._frames.get(symbol.upper())
        if frame is None or frame.empty:
            return normalize_ohlc(pd.DataFrame(columns=list(_OHLC)))
        if bars > 0 and len(frame) > bars:
            return frame.iloc[-bars:].copy()
        return frame.copy()


class CsvFeed:
    """Load OHLC from a CSV path (optional symbol column filter)."""

    def __init__(self, path: str | Path, *, symbol_column: str | None = "symbol") -> None:
        self.path = Path(path)
        self.symbol_column = symbol_column
        self._cache: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache
        raw = pd.read_csv(self.path)
        self._cache = raw
        return raw

    def get_ohlc(
        self,
        symbol: str,
        *,
        timeframe: str = "M15",
        bars: int = 500,
    ) -> pd.DataFrame:
        _ = timeframe
        raw = self._load()
        frame = raw
        if self.symbol_column and self.symbol_column in raw.columns:
            frame = raw[raw[self.symbol_column].astype(str).str.upper() == symbol.upper()]
        out = normalize_ohlc(frame)
        if bars > 0 and len(out) > bars:
            return out.iloc[-bars:].copy()
        return out


def feed_from_config(
    cfg: SignalBotConfig,
    *,
    frames: dict[str, pd.DataFrame] | None = None,
    transport: Any | None = None,
) -> MarketDataFeed:
    """Build a feed from config.

    ``auto``: csv path → CSV; else explicit ``transport`` → cTrader; else memory.
    Credentials alone never create a live feed (Open API session must inject transport).
    """
    mode = (cfg.feed_mode or "auto").lower()
    if mode == "memory":
        return InMemoryFeed(frames)
    if mode == "csv" or (mode == "auto" and cfg.csv_path):
        if not cfg.csv_path:
            raise RuntimeError("SMC_SIGNAL_CSV_PATH required for csv feed")
        return CsvFeed(cfg.csv_path)
    if mode == "ctrader":
        from smc_bot_signal.ctrader_client import CTraderFeed

        if transport is None:
            raise RuntimeError(
                "feed_mode=ctrader requires an Open API transport "
                "(wire LiveOpenApiTransport after connect; see docs/deploy-mac-mini-ctrader.md)"
            )
        return CTraderFeed(cfg, transport=transport)
    if mode == "auto" and transport is not None:
        from smc_bot_signal.ctrader_client import CTraderFeed

        return CTraderFeed(cfg, transport=transport)
    if mode == "auto" and (
        cfg.ctrader_client_id and cfg.ctrader_access_token and cfg.ctrader_account_id
    ):
        logger.warning(
            "cTrader credentials present but no transport injected; "
            "falling back to InMemoryFeed (idle until CSV/transport wired)"
        )
    return InMemoryFeed(frames)
