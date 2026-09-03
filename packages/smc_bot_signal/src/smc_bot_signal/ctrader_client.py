"""cTrader Open API session + trendbar feed (optional deps)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import pandas as pd

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.data_feed import normalize_ohlc

logger = logging.getLogger("smc_bot_signal.ctrader")

# Spotware ProtoOATrendbarPeriod enum values (common subset).
_PERIOD_MAP = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M10": 6,
    "M15": 7,
    "M30": 8,
    "H1": 9,
    "H4": 10,
    "H12": 11,
    "D1": 12,
    "D": 12,
    "W1": 13,
    "MN1": 14,
}


class TrendbarTransport(Protocol):
    """Testable transport: returns raw trendbar-like dicts."""

    def fetch_trendbars(
        self,
        *,
        symbol: str,
        period: str,
        bars: int,
    ) -> list[dict[str, Any]]:
        """Each item: time (ms or sec), open, high, low, close (and optional delta)."""


def trendbars_to_ohlc(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert transport rows to normalized OHLC DataFrame."""
    if not rows:
        return normalize_ohlc(pd.DataFrame(columns=["open", "high", "low", "close"]))

    records: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("time") or row.get("timestamp") or row.get("utcTimestampInMinutes")
        if ts is None:
            continue
        ts_f = float(ts)
        # Spotware often uses minutes since epoch for trendbars.
        if ts_f < 10_000_000_000:  # seconds
            if ts_f < 50_000_000:  # minutes
                ts_f = ts_f * 60.0
            dt = datetime.fromtimestamp(ts_f, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(ts_f / 1000.0, tz=timezone.utc)

        # OpenApi trendbars sometimes encode open as absolute and others as delta.
        o = float(row.get("open", row.get("low") or 0))
        h = float(row.get("high", o))
        l = float(row.get("low", o))
        c = float(row.get("close", o))
        # If high/low/close look like deltas from open (common in proto scaled ints
        # already decoded by caller), leave as provided absolute prices.
        records.append({"time": dt, "open": o, "high": h, "low": l, "close": c})

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return normalize_ohlc(pd.DataFrame(columns=["open", "high", "low", "close"]))
    frame = frame.set_index("time")
    return normalize_ohlc(frame)


@dataclass
class StaticTrendbarTransport:
    """In-test transport returning preloaded rows per symbol."""

    data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def fetch_trendbars(
        self,
        *,
        symbol: str,
        period: str,
        bars: int,
    ) -> list[dict[str, Any]]:
        _ = period
        rows = list(self.data.get(symbol.upper(), []))
        if bars > 0:
            rows = rows[-bars:]
        return rows


def _require_open_api() -> None:
    try:
        import ctrader_open_api  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "ctrader-open-api not installed. "
            "pip install 'smc_bot_signal[ctrader]' or pip install ctrader-open-api twisted protobuf"
        ) from exc


@dataclass
class LiveOpenApiTransport:
    """
    Thin live transport.

    Full Twisted reactor loop is deferred to process lifetime; this class
    exposes a callable hook so production can inject a connected session
    fetcher without hard-wiring reactor in unit tests.
    """

    fetch_fn: Callable[..., list[dict[str, Any]]]

    def fetch_trendbars(
        self,
        *,
        symbol: str,
        period: str,
        bars: int,
    ) -> list[dict[str, Any]]:
        return self.fetch_fn(symbol=symbol, period=period, bars=bars)


class CTraderFeed:
    """MarketDataFeed backed by a TrendbarTransport."""

    def __init__(
        self,
        cfg: SignalBotConfig,
        *,
        transport: TrendbarTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self._transport = transport
        self._symbol_cache: dict[str, int] = {}

    @property
    def transport(self) -> TrendbarTransport:
        if self._transport is None:
            raise RuntimeError(
                "No cTrader transport configured. "
                "Pass transport=... for tests, or wire LiveOpenApiTransport after Open API connect."
            )
        return self._transport

    def get_ohlc(
        self,
        symbol: str,
        *,
        timeframe: str = "M15",
        bars: int = 500,
    ) -> pd.DataFrame:
        period = (timeframe or self.cfg.timeframe or "M15").upper()
        if period not in _PERIOD_MAP and period not in ("M15",):
            logger.warning("unknown period %s; using M15", period)
            period = "M15"
        rows = self.transport.fetch_trendbars(
            symbol=symbol.upper(),
            period=period,
            bars=bars or self.cfg.history_bars,
        )
        return trendbars_to_ohlc(rows)


def period_to_proto(period: str) -> int:
    key = period.upper()
    if key not in _PERIOD_MAP:
        raise ValueError(f"unsupported timeframe {period!r}")
    return _PERIOD_MAP[key]


def build_live_transport_placeholder(cfg: SignalBotConfig) -> TrendbarTransport:
    """
    Validate optional deps + credentials; return a transport that fails until
    a real fetch_fn is attached post-connect.

    Production wiring (Mac mini) should replace fetch_fn after OpenApiPy auth.
    """
    _require_open_api()
    if not (cfg.ctrader_client_id and cfg.ctrader_client_secret and cfg.ctrader_access_token):
        raise RuntimeError("cTrader credentials incomplete")
    if not cfg.ctrader_account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID required")

    def _not_connected(**kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError(
            "Live Open API session not connected yet. "
            "Use docs/deploy-mac-mini-ctrader.md to wire OpenApiPy ConsoleSample flow, "
            f"then inject fetch_fn (host={cfg.ctrader_host}:{cfg.ctrader_port}). "
            f"kwargs={kwargs}"
        )

    return LiveOpenApiTransport(fetch_fn=_not_connected)


def sleep_poll(seconds: float) -> None:
    """Test seam for watcher sleep."""
    time.sleep(seconds)
