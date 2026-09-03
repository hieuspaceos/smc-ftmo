"""Notifier tests."""

from __future__ import annotations

import pytest

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.notify import LoggingNotifier, TelegramSignalNotifier, notifier_from_config
from smc_bot_webhook.notify.telegram import FakeTelegramTransport, TelegramDispatcher
from smc_bot_webhook.payload import AlertPayload


def _payload() -> AlertPayload:
    return AlertPayload(
        prefix="SMC",
        version="v1",
        event="chart_qualified",
        symbol="EURUSD",
        tf="M15",
        dir="long",
        level=1.1,
        bar_time=1_700_000_000,
        ob_id=1,
        bos_id=2,
        state="chart-qualified",
        reason="test",
        entry=1.10000,
        sl=1.09500,
        tp1=1.11000,
        tp2=1.11500,
        tp3=1.12000,
    )


def test_logging_notifier() -> None:
    n = LoggingNotifier()
    assert n.send(_payload()) == 0
    assert len(n.sent) == 1


def test_telegram_notifier_fake_transport() -> None:
    transport = FakeTelegramTransport()
    disp = TelegramDispatcher(
        transport=transport,
        chat_id=1,
        allowed_user_ids=set(),
    )
    n = TelegramSignalNotifier(dispatcher=disp, validate=False)
    msg_id = n.send(_payload())
    assert msg_id is not None
    assert transport.sent


def test_notifier_from_config_dry_run() -> None:
    n = notifier_from_config(SignalBotConfig(dry_run=True, telegram_bot_token="x"))
    assert isinstance(n, LoggingNotifier)


def test_notifier_from_config_no_token() -> None:
    n = notifier_from_config(SignalBotConfig(dry_run=False, telegram_bot_token=""))
    assert isinstance(n, LoggingNotifier)
