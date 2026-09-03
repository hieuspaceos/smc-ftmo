"""Telegram dispatcher — sends signals, handles accept/reject/ack callbacks.

Production transport: ``python-telegram-bot`` v21+ async client. Tests inject
``FakeTelegramTransport`` to capture sent messages and edit attempts without
any network I/O.

Public surface
--------------
- ``TelegramDispatcher(transport, allowed_users, ...)`` — main entry point.
- ``send_signal(payload)`` → ``Optional[int]``
- ``send_with_gates(payload, gate_states, missing_gates)`` → ``Optional[int]``
- ``edit_signal(message_id, payload, decision, actor)`` → bool
- ``handle_callback(callback_data, from_user_id)`` → ``Optional[CallbackDecision]``
- ``parse_ack_callback(callback_data)`` → ``Optional[(gate_name, signal_id)]``
- ``record_decision / record_edit_failure`` audit hooks
- ``disabled_dispatcher`` — no-op singleton when TELEGRAM_BOT_TOKEN unset.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from json import dumps as json_dumps
from typing import Any, Protocol

from smc_bot_webhook.notify.formatting import (
    build_inline_keyboard,
    format_telegram_message,
    parse_callback_data,
)
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("bot.notify.telegram")


# ---------------------------------------------------------------------------
# Transport abstraction
# ---------------------------------------------------------------------------


class TelegramTransport(Protocol):
    async def send_message(
        self,
        *,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]: ...

    async def edit_message_text(
        self,
        *,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]: ...


class FakeTelegramTransport:
    """In-memory transport for tests."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []
        self.fail_n_times: int = 0
        self._send_seq = 0

    async def send_message(
        self,
        *,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]:
        if self.fail_n_times > 0:
            self.fail_n_times -= 1
            raise RuntimeError("simulated transient failure")
        self._send_seq += 1
        msg_id = self._send_seq
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
                "message_id": msg_id,
            }
        )
        return {"message_id": msg_id}

    async def edit_message_text(
        self,
        *,
        chat_id: int | str,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]:
        # Phase 03 (audit fix): honor fail_n_times for edits so retry logic
        # in _edit_with_retry can be tested.
        if self.fail_n_times > 0:
            self.fail_n_times -= 1
            raise RuntimeError("simulated transient failure")
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return {"message_id": message_id}


def make_live_transport(token: str) -> TelegramTransport:
    """Build a real python-telegram-bot client (lazy import)."""
    from telegram import Bot  # type: ignore[import-untyped]
    from telegram.constants import ParseMode  # type: ignore[import-untyped]

    bot = Bot(token=token)

    class _Live:
        async def send_message(
            self,
            *,
            chat_id: int | str,
            text: str,
            reply_markup: dict[str, Any] | None = None,
            parse_mode: str | None = "Markdown",
        ) -> dict[str, Any]:
            from telegram import InlineKeyboardMarkup  # type: ignore[import-untyped]

            markup = (
                InlineKeyboardMarkup.de_json(reply_markup) if reply_markup else None
            )
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN if parse_mode == "Markdown" else None,
            )
            return {"message_id": msg.message_id}

        async def edit_message_text(
            self,
            *,
            chat_id: int | str,
            message_id: int,
            text: str,
            reply_markup: dict[str, Any] | None = None,
            parse_mode: str | None = "Markdown",
        ) -> dict[str, Any]:
            from telegram import InlineKeyboardMarkup  # type: ignore[import-untyped]

            markup = (
                InlineKeyboardMarkup.de_json(reply_markup) if reply_markup else None
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.MARKDOWN if parse_mode == "Markdown" else None,
            )
            return {"message_id": message_id}

    return _Live()


# ---------------------------------------------------------------------------
# Callback decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CallbackDecision:
    action: str  # 'accept' | 'reject'
    signal_id: str
    nonce: str
    accepted: bool
    reason: str
    actor: str


# ---------------------------------------------------------------------------
# Disabled dispatcher
# ---------------------------------------------------------------------------


class _DisabledDispatcher:
    """No-op dispatcher used when TELEGRAM_BOT_TOKEN is unset."""

    async def send_signal(
        self, payload: AlertPayload, *, gate_states: dict[str, bool | None] | None = None
    ) -> int | None:  # noqa: ARG002
        return None

    async def send_with_gates(
        self,
        payload: AlertPayload,
        *,
        gate_states: dict[str, bool | None],
        missing_gates: list[str],
    ) -> int | None:  # noqa: ARG002
        return None

    async def edit_signal(
        self, message_id: int, payload: AlertPayload, decision: str, actor: str  # noqa: ARG002
    ) -> bool:
        return False

    async def handle_callback(
        self,
        callback_data: str,
        from_user_id: int,
    ) -> CallbackDecision | None:
        return None

    @staticmethod
    def parse_ack_callback(callback_data: str) -> tuple[str, str] | None:
        return None

    @staticmethod
    def record_decision(
        db: Any, signal_id: str, *, decision: str, actor: str, nonce: str
    ) -> None:
        return None

    @staticmethod
    def record_edit_failure(
        db: Any, signal_id: str, *, actor: str, exc: Exception
    ) -> None:
        return None

    @property
    def enabled(self) -> bool:
        return False


disabled_dispatcher: Any = _DisabledDispatcher()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TelegramDispatcher:
    def __init__(
        self,
        transport: TelegramTransport,
        *,
        chat_id: int | str,
        allowed_user_ids: set[int],
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        send_concurrency: int = 5,
    ) -> None:
        self._transport = transport
        self._chat_id = chat_id
        self._allowed_user_ids = frozenset(allowed_user_ids)
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._message_ids: dict[str, int] = {}
        # Phase 04 (audit fix): bound concurrent Telegram sends so a
        # burst of alerts cannot stall the event loop or exceed
        # Telegram's per-chat limits. Default 5 leaves headroom for
        # other in-flight tasks.
        self._send_sem = asyncio.Semaphore(send_concurrency)

    @property
    def enabled(self) -> bool:
        return True

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        return self._allowed_user_ids

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_signal(
        self,
        payload: AlertPayload,
        *,
        gate_states: dict[str, bool | None] | None = None,
        validation: Any | None = None,
    ) -> int | None:
        """Send signal to Telegram. Optional ``validation`` (Phase 1.5) is
        passed through to ``format_telegram_message`` for inline annotation.
        """
        nonce = secrets.token_hex(8)
        text = format_telegram_message(payload, gate_states=gate_states,
                                      validation=validation)
        keyboard = build_inline_keyboard(payload.signal_id, nonce)
        return await self._do_send(payload, text, keyboard)

    async def send_with_gates(
        self,
        payload: AlertPayload,
        *,
        gate_states: dict[str, bool | None],
        missing_gates: list[str],
        validation: Any | None = None,
    ) -> int | None:
        """Send alert + keyboard that includes per-gate ack rows when needed.
        Optional ``validation`` (Phase 1.5) is passed through for inline annotation.
        """
        nonce = secrets.token_hex(8)
        text = format_telegram_message(payload, gate_states=gate_states,
                                      validation=validation)
        if missing_gates:
            from smc_bot_webhook.notify.formatting import build_ack_keyboard

            keyboard = build_ack_keyboard(payload.signal_id, missing_gates)
        else:
            keyboard = build_inline_keyboard(payload.signal_id, nonce)
        return await self._do_send(payload, text, keyboard)

    async def _do_send(
        self,
        payload: AlertPayload,
        text: str,
        keyboard: dict[str, Any],
    ) -> int | None:
        last_exc: Exception | None = None
        async with self._send_sem:
            for attempt in range(self._max_retries):
                try:
                    result = await asyncio.wait_for(
                        self._transport.send_message(
                            chat_id=self._chat_id,
                            text=text,
                            reply_markup=keyboard,
                            parse_mode="MarkdownV2",
                        ),
                        timeout=10.0,
                    )
                    msg_id = int(result["message_id"])
                    self._message_ids[payload.signal_id] = msg_id
                    logger.info(
                        "telegram send ok: signal_id=%s message_id=%s attempt=%d",
                        payload.signal_id, msg_id, attempt + 1,
                    )
                    return msg_id
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    backoff = self._backoff_base * (2 ** attempt)
                    logger.warning(
                        "telegram send failed: signal_id=%s attempt=%d/%d exc=%s; sleeping %.1fs",
                        payload.signal_id, attempt + 1, self._max_retries, exc, backoff,
                    )
                    if attempt + 1 < self._max_retries:
                        await asyncio.sleep(backoff)
        logger.error(
            "telegram send exhausted retries: signal_id=%s last_exc=%s",
            payload.signal_id, last_exc,
        )
        return None

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------

    async def edit_signal(
        self,
        message_id: int,
        payload: AlertPayload,
        *,
        decision: str,
        actor: str,
    ) -> bool:
        if decision not in ("accept", "reject"):
            raise ValueError(f"decision must be 'accept' or 'reject', got {decision!r}")
        new_text = (
            f"{format_telegram_message(payload)}\n\n"
            f"— *Decision*: `{decision.upper()}` by `{actor}` — buttons disabled."
        )
        try:
            await self._transport.edit_message_text(
                chat_id=self._chat_id,
                message_id=message_id,
                text=new_text,
                reply_markup=None,
                parse_mode="Markdown",
            )
            self._message_ids.pop(payload.signal_id, None)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telegram edit failed: signal_id=%s message_id=%s exc=%s",
                payload.signal_id, message_id, exc,
            )
            return False

    # ------------------------------------------------------------------
    # Callback parsing + authorization
    # ------------------------------------------------------------------

    async def handle_callback(
        self,
        callback_data: str,
        from_user_id: int,
    ) -> CallbackDecision | None:
        parsed = parse_callback_data(callback_data)
        if parsed is None:
            logger.info("rejecting malformed callback: %r", callback_data)
            return CallbackDecision(
                action="reject", signal_id="", nonce="", accepted=False,
                reason="malformed callback_data", actor=str(from_user_id),
            )
        actor = str(from_user_id)
        if from_user_id not in self._allowed_user_ids:
            logger.warning(
                "rejecting callback from user=%s not in allowlist", from_user_id,
            )
            return CallbackDecision(
                action=parsed.action, signal_id=parsed.signal_id,
                nonce=parsed.nonce, accepted=False, reason="user not allowed",
                actor=actor,
            )
        return CallbackDecision(
            action=parsed.action, signal_id=parsed.signal_id,
            nonce=parsed.nonce, accepted=True, reason="authorized", actor=actor,
        )

    @staticmethod
    def parse_ack_callback(callback_data: str) -> tuple[str, str] | None:
        """Parse ``ack:<gate_name>:<signal_id>``. Returns (gate_name, signal_id) or None."""
        from smc_bot_webhook.notify.formatting import ACK_PREFIX
        from smc_bot_webhook.gates.state import MANUAL_GATE_NAMES

        if not callback_data or not callback_data.startswith(ACK_PREFIX):
            return None
        body = callback_data[len(ACK_PREFIX):]
        parts = body.split(":", 1)
        if len(parts) != 2:
            return None
        gate_name, signal_id = parts
        if gate_name not in MANUAL_GATE_NAMES:
            return None
        if any(c not in "0123456789abcdef" for c in signal_id.lower()):
            return None
        # Phase 05 (audit fix): length must be exactly 16 hex chars
        # (matches compute_signal_id output length). Empty or wrong-
        # length ids previously passed the hex check, leading to
        # gate_ack rows with garbage signal_id.
        if len(signal_id) != 16:
            return None
        return gate_name, signal_id.lower()

    # ------------------------------------------------------------------
    # Audit hooks (Phase 03 wires these into Accept revalidation)
    # ------------------------------------------------------------------

    @staticmethod
    def record_decision(
        db: Any,
        signal_id: str,
        *,
        decision: str,
        actor: str,
        nonce: str,
    ) -> None:
        if decision not in ("accept", "reject"):
            raise ValueError(f"decision must be 'accept' or 'reject', got {decision!r}")
        db.record_event(
            signal_id,
            decision,
            payload=json_dumps(
                {"decision": decision, "actor": actor, "nonce": nonce},
                sort_keys=True,
            ),
            actor=actor,
        )

    @staticmethod
    def record_edit_failure(db: Any, signal_id: str, *, actor: str, exc: Exception) -> None:
        db.record_event(
            signal_id, "edit_failed",
            payload=str(exc), actor=actor,
        )

    def get_message_id(self, signal_id: str) -> int | None:
        return self._message_ids.get(signal_id)


# ---------------------------------------------------------------------------
# Factory from env
# ---------------------------------------------------------------------------


def dispatcher_from_env(
    *,
    transport: TelegramTransport | None = None,
) -> Any:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or ""
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN unset; telegram dispatcher disabled")
        return disabled_dispatcher
    chat_id_env = os.environ.get("TELEGRAM_CHAT_ID", "") or ""
    try:
        chat_id: int | str = int(chat_id_env)
    except ValueError:
        chat_id = chat_id_env
    allowed_str = os.environ.get("TELEGRAM_ALLOWED_USERS", "") or ""
    allowed_user_ids: set[int] = set()
    for chunk in allowed_str.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            allowed_user_ids.add(int(chunk))
        except ValueError:
            logger.warning("ignoring non-int TELEGRAM_ALLOWED_USERS entry: %r", chunk)
    max_retries = _env_int("TELEGRAM_MAX_RETRIES", 3)
    backoff = float(os.environ.get("TELEGRAM_BACKOFF_BASE_SECONDS", "1.0") or "1.0")
    return TelegramDispatcher(
        transport=transport or make_live_transport(token),
        chat_id=chat_id,
        allowed_user_ids=allowed_user_ids,
        max_retries=max_retries,
        backoff_base_seconds=backoff,
    )