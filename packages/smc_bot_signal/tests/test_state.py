"""SignalStateStore dedup tests."""

from __future__ import annotations

from pathlib import Path

from smc_bot_signal.state import SignalStateStore


def test_should_notify_and_dedup(tmp_path: Path) -> None:
    store = SignalStateStore(tmp_path / "s.db", dedup_window_minutes=60)
    assert store.should_notify("abc", now=1_000.0) is True
    store.record_alert("abc", symbol="EURUSD", bar_time=1, now=1_000.0)
    assert store.should_notify("abc", now=1_000.0 + 10) is False
    assert store.should_notify("abc", now=1_000.0 + 60 * 60) is True


def test_empty_signal_id(tmp_path: Path) -> None:
    store = SignalStateStore(tmp_path / "s.db")
    assert store.should_notify("") is False
    store.record_alert("")  # no-op
