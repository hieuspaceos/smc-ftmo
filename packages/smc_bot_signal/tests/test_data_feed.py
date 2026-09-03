"""Data feed tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.ctrader_client import (
    CTraderFeed,
    StaticTrendbarTransport,
    trendbars_to_ohlc,
)
from smc_bot_signal.data_feed import CsvFeed, InMemoryFeed, feed_from_config, normalize_ohlc


def _sample_frame(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [1.0 + i * 0.001 for i in range(n)],
            "high": [1.001 + i * 0.001 for i in range(n)],
            "low": [0.999 + i * 0.001 for i in range(n)],
            "close": [1.0005 + i * 0.001 for i in range(n)],
        },
        index=idx,
    )


def test_normalize_ohlc_basic() -> None:
    out = normalize_ohlc(_sample_frame())
    assert list(out.columns) == ["open", "high", "low", "close"]
    assert out.index.tz is not None
    assert len(out) == 5


def test_inmemory_bars_slice() -> None:
    feed = InMemoryFeed({"EURUSD": _sample_frame(10)})
    out = feed.get_ohlc("EURUSD", bars=3)
    assert len(out) == 3


def test_csv_feed(tmp_path: Path) -> None:
    df = _sample_frame(4).reset_index().rename(columns={"index": "time"})
    df["symbol"] = "EURUSD"
    path = tmp_path / "x.csv"
    df.to_csv(path, index=False)
    feed = CsvFeed(path)
    out = feed.get_ohlc("EURUSD", bars=10)
    assert len(out) == 4
    assert out["close"].notna().all()


def test_trendbars_to_ohlc_seconds() -> None:
    rows = [
        {"time": 1_700_000_000 + i * 900, "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105}
        for i in range(3)
    ]
    out = trendbars_to_ohlc(rows)
    assert len(out) == 3


def test_ctrader_feed_with_static_transport() -> None:
    ts0 = 1_700_000_000
    rows = [
        {"time": ts0 + i * 900, "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.005}
        for i in range(5)
    ]
    transport = StaticTrendbarTransport({"EURUSD": rows})
    feed = CTraderFeed(SignalBotConfig(), transport=transport)
    out = feed.get_ohlc("EURUSD", bars=3)
    assert len(out) == 3


def test_feed_from_config_memory() -> None:
    cfg = SignalBotConfig(feed_mode="memory")
    feed = feed_from_config(cfg, frames={"EURUSD": _sample_frame()})
    assert len(feed.get_ohlc("EURUSD")) == 5


def test_feed_from_config_csv_requires_path() -> None:
    cfg = SignalBotConfig(feed_mode="csv", csv_path="")
    with pytest.raises(RuntimeError, match="CSV_PATH"):
        feed_from_config(cfg)
