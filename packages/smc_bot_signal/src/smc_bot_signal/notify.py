"""Signal notifiers — dry-run log + Telegram via smc_bot_webhook."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from smc_bot_signal.config import SignalBotConfig
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("smc_bot_signal.notify")


@runtime_checkable
class SignalNotifier(Protocol):
    def send(
        self,
        payload: AlertPayload,
        *,
        m15_data: pd.DataFrame | None = None,
    ) -> int | None:
        """Send alert; return transport message id or None."""


@dataclass
class LoggingNotifier:
    """Dry-run / disabled notifier — logs only."""

    sent: list[AlertPayload] = field(default_factory=list)

    def send(
        self,
        payload: AlertPayload,
        *,
        m15_data: pd.DataFrame | None = None,
    ) -> int | None:
        _ = m15_data
        self.sent.append(payload)
        logger.info(
            "dry-run signal symbol=%s dir=%s entry=%s sl=%s signal_id=%s",
            payload.symbol,
            payload.dir,
            payload.entry,
            payload.sl,
            payload.signal_id,
        )
        return 0


@dataclass
class TelegramSignalNotifier:
    """Wrap TelegramDispatcher (async) for sync watcher calls."""

    dispatcher: Any
    validate: bool = True

    def send(
        self,
        payload: AlertPayload,
        *,
        m15_data: pd.DataFrame | None = None,
    ) -> int | None:
        validation = None
        if self.validate and m15_data is not None:
            try:
                from smc_bot_webhook.smc_validator import validate_pine_signal

                validation = validate_pine_signal(payload, m15_data)
            except Exception:
                logger.exception("validation annotation failed")

        async def _go() -> int | None:
            return await self.dispatcher.send_signal(
                payload, validation=validation
            )

        try:
            return asyncio.run(_go())
        except RuntimeError as exc:
            # Nested event loop (e.g. pytest-asyncio) — best-effort new loop.
            if "asyncio.run()" not in str(exc) and "running event loop" not in str(exc):
                raise
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_go())
            finally:
                loop.close()


def notifier_from_config(cfg: SignalBotConfig, *, transport: Any | None = None) -> SignalNotifier:
    if cfg.dry_run or not cfg.telegram_bot_token:
        if not cfg.telegram_bot_token and not cfg.dry_run:
            logger.warning("TELEGRAM_BOT_TOKEN unset; using LoggingNotifier")
        return LoggingNotifier()

    from smc_bot_webhook.notify.telegram import (
        TelegramDispatcher,
        make_live_transport,
    )

    chat_raw = cfg.telegram_chat_id
    try:
        chat_id: int | str = int(chat_raw)
    except (TypeError, ValueError):
        chat_id = chat_raw or ""

    disp = TelegramDispatcher(
        transport=transport or make_live_transport(cfg.telegram_bot_token),
        chat_id=chat_id,
        allowed_user_ids=set(),
    )
    return TelegramSignalNotifier(dispatcher=disp, validate=True)
