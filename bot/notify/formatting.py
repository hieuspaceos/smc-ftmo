"""Message formatting + callback parsing — pure functions, no I/O.

These helpers are unit-tested directly without any network or DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

from bot.webhook.payload import AlertPayload

# Six manual gates that Phase 03 will validate. We render placeholder
# states here so the message layout is stable across phases.
MANUAL_GATE_NAMES: Final[tuple[str, ...]] = (
    "risk_ok",
    "trades_left",
    "daily_loss_ok",
    "no_position",
    "spread_news_clean",
    "judgment_clear",
)

STATE_EMOJI: Final[dict[str, str]] = {
    "chart-qualified": "✅",
    "watch": "👀",
    "blocked": "🚫",
    "no-signal": "·",
}

DIR_EMOJI: Final[dict[str, str]] = {
    "long": "🟢 LONG",
    "short": "🔴 SHORT",
    "none": "·",
}


@dataclass(frozen=True)
class CallbackAction:
    """Result of parsing a Telegram callback_data payload."""

    action: str  # 'accept' | 'reject'
    signal_id: str
    nonce: str

    @property
    def key(self) -> str:
        return f"{self.action}:{self.signal_id}:{self.nonce}"


def parse_callback_data(data: str) -> "CallbackAction | None":
    """Parse ``accept:<signal_id>:<nonce>`` or ``reject:<signal_id>:<nonce>``.

    Returns ``None`` if data is malformed. ``nonce`` is opaque — Phase 03 will
    bind it to ``signal_events.created_at`` for freshness checks.
    """
    if not data:
        return None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    action, signal_id, nonce = parts
    if action not in ("accept", "reject"):
        return None
    if not signal_id or not nonce:
        return None
    # Normalize signal_id to lowercase — compute_signal_id always returns
    # lowercase hex; an uppercase callback would never match a real signal.
    signal_id = signal_id.lower()
    if any(c not in "0123456789abcdef" for c in signal_id):
        return None
    if len(nonce) < 4 or len(nonce) > 64:
        return None
    return CallbackAction(action=action, signal_id=signal_id, nonce=nonce)

def render_gate_checklist(states: dict[str, bool | None] | None = None) -> str:
    """Render the 6 manual gates as a checklist.

    Pass ``None`` for all gates to render Phase 02 placeholders (Phase 03 will
    fill them in). Pass a dict with any subset of gate names.
    """
    states = states or {}
    lines: list[str] = []
    for name in MANUAL_GATE_NAMES:
        v = states.get(name)
        if v is True:
            mark = "✅"
        elif v is False:
            mark = "❌"
        else:
            mark = "❔"
        lines.append(f"  {mark} {name}")
    return "\n".join(lines)


def format_telegram_message(
    payload: AlertPayload,
    *,
    gate_states: dict[str, bool | None] | None = None,
) -> str:
    """Render Markdown message body for Telegram."""
    bar_time_iso = (
        datetime.fromtimestamp(payload.bar_time, tz=timezone.utc).isoformat()
        if payload.bar_time > 0
        else "n/a"
    )
    state_emoji = STATE_EMOJI.get(payload.state, "·")
    dir_text = DIR_EMOJI.get(payload.dir, payload.dir)

    lines = [
        f"*SMC Alert* — {payload.symbol} {payload.tf}",
        f"{state_emoji} State: `{payload.state}`  •  {dir_text}",
        f"Event: `{payload.event}`  •  Reason: `{payload.reason or '—'}`",
        f"Level: `{payload.level:.5f}`  •  Bar: `{bar_time_iso}`",
        f"OB id: `{payload.ob_id}`  •  BOS id: `{payload.bos_id}`",
        "",
        "*Manual gates*",
        render_gate_checklist(gate_states),
        "",
        f"signal_id: `{payload.signal_id}`",
    ]
    return "\n".join(lines)


def format_discord_message(
    payload: AlertPayload,
    *,
    gate_states: dict[str, bool | None] | None = None,
) -> str:
    """Render plain-text body for Discord (mirror-only, no buttons)."""
    bar_time_iso = (
        datetime.fromtimestamp(payload.bar_time, tz=timezone.utc).isoformat()
        if payload.bar_time > 0
        else "n/a"
    )
    state_emoji = STATE_EMOJI.get(payload.state, "·")
    return (
        f"📡 SMC Alert {payload.symbol} {payload.tf}\n"
        f"{state_emoji} {payload.state} • {payload.event} • {payload.reason or '—'}\n"
        f"dir={payload.dir} | level={payload.level:.5f} | bar={bar_time_iso}\n"
        f"ob_id={payload.ob_id} bos_id={payload.bos_id}\n"
        f"signal_id={payload.signal_id}\n\n"
        f"Manual gates:\n{render_gate_checklist(gate_states)}\n\n"
        f"Approval via Telegram only — Discord is read-only."
    )


def build_inline_keyboard(signal_id: str, nonce: str) -> dict[str, Any]:
    """Build an ``InlineKeyboardMarkup``-shaped dict.

    Returns a dict compatible with python-telegram-bot's
    ``InlineKeyboardMarkup`` model (so tests can assert structure without
    importing the SDK types).
    """
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Accept", "callback_data": f"accept:{signal_id}:{nonce}"},
                {"text": "❌ Reject", "callback_data": f"reject:{signal_id}:{nonce}"},
            ]
        ]
    }


def callback_payload_json(payload: AlertPayload) -> str:
    """Serialize minimal payload for storage in signal_events.payload."""
    return json.dumps(
        {
            "event": payload.event,
            "symbol": payload.symbol,
            "tf": payload.tf,
            "dir": payload.dir,
            "level": payload.level,
            "bar_time": payload.bar_time,
            "ob_id": payload.ob_id,
            "bos_id": payload.bos_id,
            "state": payload.state,
            "reason": payload.reason,
            "signal_id": payload.signal_id,
        },
        sort_keys=True,
    )