"""Telegram + Discord notification dispatchers."""

from bot.notify.formatting import (
    format_discord_message,
    format_telegram_message,
    parse_callback_data,
    render_gate_checklist,
)
from bot.notify.telegram import (
    FakeTelegramTransport,
    TelegramDispatcher,
    TelegramTransport,
    build_inline_keyboard,
    disabled_dispatcher,
)
from bot.notify.discord import (
    DiscordMirror,
    DiscordTransport,
    FakeDiscordTransport,
    disabled_discord,
)

__all__ = [
    # formatting
    "format_telegram_message",
    "format_discord_message",
    "parse_callback_data",
    "render_gate_checklist",
    "build_inline_keyboard",
    # telegram
    "TelegramDispatcher",
    "TelegramTransport",
    "FakeTelegramTransport",
    "disabled_dispatcher",
    # discord
    "DiscordMirror",
    "DiscordTransport",
    "FakeDiscordTransport",
    "disabled_discord",
]