"""Message formatting + callback parsing — pure functions, no I/O.

These helpers are unit-tested directly without any network or DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

from smc_bot_webhook.payload import AlertPayload

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

# Telegram MarkdownV2 reserved characters that must be escaped in
# free-text portions of a message. Reference:
# https://core.telegram.org/bots/api#markdownv2-style
_MD2_RESERVED = set("_*[]()~`>#+-=|{}.!" )


def _md2_escape(text: str) -> str:
    """Escape a string for use in a Telegram MarkdownV2 message body.

    Each reserved character is prefixed with a backslash. Pre-escaped
    sequences (e.g. ``\\.``) are left alone so callers that pre-escape
    their own content keep working.
    """
    if not text:
        return text
    out: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in _MD2_RESERVED:
            # already escaped — keep both chars
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c in _MD2_RESERVED:
            out.append("\\")
        out.append(c)
        i += 1
    return "".join(out)


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
    # signal_id must be exactly the canonical length (compute_signal_id returns 16 hex).
    # Reject anything else — this also blocks DoS via huge signal_id strings.
    if len(signal_id) != 16:
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
    """Render MarkdownV2 message body for Telegram.

    Free-text fields (``symbol``, ``tf``, ``dir``, ``state``, ``reason``)
    are escaped with ``_md2_escape`` to prevent 400 errors from
    Telegram when the payload contains reserved characters like
    ``_*[]()``. Numeric / structured fields are wrapped in inline
    code (``...``) which doesn't require escaping.
    """
    bar_time_iso = (
        datetime.fromtimestamp(payload.bar_time, tz=timezone.utc).isoformat()
        if payload.bar_time > 0
        else "n/a"
    )
    dir_text = DIR_EMOJI.get(payload.dir, payload.dir)

    lines = [
        f"*SMC Alert* — {_md2_escape(payload.symbol)} {_md2_escape(payload.tf)}",
        f"{STATE_EMOJI.get(payload.state, '·')} State: `{_md2_escape(payload.state)}`"
        f"  •  {_md2_escape(dir_text)}",
        f"Event: `{_md2_escape(payload.event)}`  •  Reason: `{_md2_escape(payload.reason or '—')}`",
        f"Level: `{payload.level:.5f}`  •  Bar: `{bar_time_iso}`",
        f"OB id: `{payload.ob_id}`  •  BOS id: `{payload.bos_id}`",
        "",
        "*Manual gates*",
        render_gate_checklist(gate_states),
        "",
        f"signal\\_id: `{payload.signal_id}`",
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

def build_ack_keyboard(signal_id: str, missing_gates: list[str]) -> dict[str, Any]:
    """Build a keyboard with one row per missing manual gate + Accept/Reject row.

    Each ack button carries ``callback_data = "ack:<gate_name>:<signal_id>"`` so
    the dispatcher can route the press to the right gate. The Accept/Reject row
    is ALWAYS present (so the trader can reject even without acking gates);
    Accept is enabled only when ``missing_gates`` is empty (the dispatcher
    ignores Accept presses when validator says otherwise).
    """
    rows: list[list[dict[str, str]]] = []
    # Two ack buttons per row (Telegram inline keyboards: max ~8 columns).
    for i in range(0, len(missing_gates), 2):
        chunk = missing_gates[i:i + 2]
        rows.append(
            [
                {"text": f"✓ Ack {name}", "callback_data": f"ack:{name}:{signal_id}"}
                for name in chunk
            ]
        )
    rows.append(
        [
            {"text": "✅ Accept", "callback_data": f"accept:{signal_id}:nonce"},
            {"text": "❌ Reject", "callback_data": f"reject:{signal_id}:nonce"},
        ]
    )
    return {"inline_keyboard": rows}


# Callback data formats (kept here so dispatcher + parser share constants).
ACK_PREFIX = "ack:"
ACCEPT_PREFIX = "accept:"
REJECT_PREFIX = "reject:"


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