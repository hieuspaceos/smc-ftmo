"""Watcher run_once + dedup tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.data_feed import InMemoryFeed
from smc_bot_signal.notify import LoggingNotifier
from smc_bot_signal.signal_engine import SignalEngine
from smc_bot_signal.state import SignalStateStore
from smc_bot_signal.watcher import Watcher
from smc_bot_webhook.payload import AlertPayload


class _FakeEngine:
    def __init__(self, payloads: list[AlertPayload]) -> None:
        self.payloads = payloads
        self.calls = 0

    def scan(self, df, symbol, *, timeframe=None):  # noqa: ANN001
        self.calls += 1
        return list(self.payloads)


def _payload(bar_time: int = 1_700_000_000) -> AlertPayload:
    return AlertPayload(
        prefix="SMC",
        version="v1",
        event="chart_qualified",
        symbol="EURUSD",
        tf="M15",
        dir="long",
        level=1.1,
        bar_time=bar_time,
        ob_id=1,
        bos_id=2,
        state="chart-qualified",
        reason="test",
        entry=1.1,
        sl=1.09,
        tp1=1.12,
        tp2=1.13,
        tp3=1.14,
    )


def _frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=40, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": 1.1,
            "high": 1.11,
            "low": 1.09,
            "close": 1.105,
        },
        index=idx,
    )


def test_run_once_sends_and_dedups(tmp_path: Path) -> None:
    cfg = SignalBotConfig(
        symbols=("EURUSD",),
        state_db_path=tmp_path / "w.db",
        dry_run=True,
        dedup_window_minutes=60,
    )
    p = _payload()
    notifier = LoggingNotifier()
    w = Watcher(
        cfg=cfg,
        feed=InMemoryFeed({"EURUSD": _frame()}),
        engine=_FakeEngine([p]),  # type: ignore[arg-type]
        state=SignalStateStore(cfg.state_db_path, cfg.dedup_window_minutes),
        notifier=notifier,
    )
    sent1 = w.run_once()
    assert sent1 == [p.signal_id]
    assert len(notifier.sent) == 1

    # same bar → skip entirely
    sent2 = w.run_once()
    assert sent2 == []

    # new bar, same signal_id → dedup
    frame2 = _frame()
    frame2.index = frame2.index + pd.Timedelta(minutes=15)
    w.feed = InMemoryFeed({"EURUSD": frame2})
    sent3 = w.run_once()
    assert sent3 == []
    assert len(notifier.sent) == 1


def test_build_watcher_memory(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("SMC_SIGNAL_FEED_MODE", "memory")
    monkeypatch.setenv("SMC_SIGNAL_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("SMC_SIGNAL_DRY_RUN", "1")
    from smc_bot_signal.watcher import build_watcher

    w = build_watcher(frames={"EURUSD": _frame()})
    assert w.run_once() == []  # real engine, may be empty
