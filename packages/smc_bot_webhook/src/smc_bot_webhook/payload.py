"""SMC|v1 alert payload parser.

Wire format from Pine:

    SMC|v1|event=<e>|symbol=<ticker>|tf=<interval>|dir=<dir>|level=<price>|bar_time=<epoch>|ob_id=<id>|bos_id=<id>|state=<state>|reason=<code>

Notes
-----
- ``tf`` arrives as TradingView ``timeframe.period`` numeric string ("15", "60", "240", "D").
  Normalize to canonical tokens: M15, H1, H4, D.
- ``bar_time`` is TradingView ``time`` in epoch SECONDS.
- ``ob_id`` and ``bos_id`` use ``-1`` when not applicable.
- ``symbol`` arrives as Pine ``syminfo.ticker`` (e.g. ``"EURUSD"``, ``"OANDA:EURUSD"``).
  Strip ``"<BROKER>:"`` prefix and uppercase.
- ``dir`` is one of ``long``, ``short``, ``bullish``, ``bearish``, ``none``.
- ``state`` is one of ``chart-qualified``, ``watch``, ``blocked``, ``no-signal``.
  Phase 01 accepts ``chart-qualified``, ``watch``, ``blocked``.
- ``event`` is one of ``bos``, ``choch``, ``ob_activated``, ``sweep``, ``pool``,
  ``chart_qualified``, ``watch``, ``blocked``.

Idempotency
-----------
``signal_id`` = first 16 hex chars of SHA-256 over the canonical tuple::

    event + "|" + symbol + "|" + tf + "|" + dir + "|" + str(level) + "|"
    + str(bar_time) + "|" + str(ob_id) + "|" + str(bos_id)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Accepted Pine tf values → canonical tokens.
TF_CANONICAL = ("M15", "H1", "H4", "D")
TF_PINE_TO_CANONICAL = {
    "1": "M1",
    "3": "M3",
    "5": "M5",
    "15": "M15",
    "30": "M30",
    "45": "M45",
    "60": "H1",
    "120": "H2",
    "180": "H3",
    "240": "H4",
    "360": "H6",
    "720": "H12",
    "D": "D",
    "W": "W",
    "M": "M",
}

EVENT_VALUES = (
    "bos",
    "choch",
    "ob_activated",
    "sweep",
    "pool",
    "chart_qualified",
    "watch",
    "blocked",
)

STATE_VALUES = ("chart-qualified", "watch", "blocked", "no-signal")
# Phase 01 (per plan) accepts all four; downstream phases gate on the value.
STATE_PHASE01_ACCEPTED = STATE_VALUES

DIR_VALUES = ("long", "short", "bullish", "bearish", "none")

SYMBOL_ALLOWLIST = ("EURUSD",)  # P0 single-symbol scope

PREFIX = "SMC"
VERSION = "v1"


def normalize_symbol(raw: str) -> str:
    """Strip broker prefix (``OANDA:``) and uppercase."""
    if not raw:
        return ""
    return raw.split(":", 1)[-1].strip().upper()


def normalize_tf(raw: str) -> str:
    """Map TradingView timeframe.period string to canonical token."""
    if not raw:
        return ""
    s = raw.strip().upper()
    if s in TF_CANONICAL:
        return s
    return TF_PINE_TO_CANONICAL.get(s, s)


def normalize_dir(raw: str) -> Literal["long", "short", "none"]:
    """Map bullish/bearish → long/short. Anything else → none."""
    s = (raw or "").strip().lower()
    if s in ("long", "bullish"):
        return "long"
    if s in ("short", "bearish"):
        return "short"
    return "none"


def normalize_state(raw: str) -> str:
    """Lowercase, hyphenated canonical. Pine emits ``chart-qualified`` etc."""
    return (raw or "").strip().lower()


def compute_signal_id(
    event: str,
    symbol: str,
    tf: str,
    dir_: str,
    level: float,
    bar_time: int,
    ob_id: int,
    bos_id: int,
) -> str:
    """Deterministic 16-char hex idempotency key."""
    h = hashlib.sha256()
    h.update(event.encode("utf-8"))
    h.update(b"|")
    h.update(symbol.encode("utf-8"))
    h.update(b"|")
    h.update(tf.encode("utf-8"))
    h.update(b"|")
    h.update(dir_.encode("utf-8"))
    h.update(b"|")
    # Phase 05 (audit fix): round level to broker tick (5-digit EURUSD
    # = 0.00001) so that two Pine runs emitting the same OB at
    # 1.10000 vs 1.10000001 produce the same signal_id. Without
    # rounding, a re-alert for the same setup gets a new id, bypasses
    # dedupe, and the trader sees a duplicate Accept.
    h.update(f"{round(level, 5):.5f}".encode("utf-8"))
    h.update(b"|")
    h.update(str(bar_time).encode("utf-8"))
    h.update(b"|")
    h.update(str(ob_id).encode("utf-8"))
    h.update(b"|")
    h.update(str(bos_id).encode("utf-8"))
    return h.hexdigest()[:16]


class AlertPayload(BaseModel):
    """Validated SMC|v1 alert payload."""

    # Phase 05 (audit fix): frozen=True prevents accidental mutation
    # after validation. Any field change should go through model_copy.
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> "AlertPayload":  # type: ignore[override]
        """Override ``model_construct`` so re-hydrating from the DB without
        ``signal_id`` still produces the canonical hash.

        Pydantic's ``model_construct`` deliberately skips all validators
        (including ``@model_validator`` that fills ``signal_id``). Callers
        that re-build an AlertPayload from a stored row would otherwise
        get ``signal_id=''`` — which silently breaks audit-row lookups by
        signal_id (every audit row stores ``''``).

        This override re-computes ``signal_id`` when it's empty or missing,
        matching what ``@model_validator`` does during normal validation.
        """
        obj = super().model_construct(_fields_set=_fields_set, **values)
        if not obj.signal_id:
            # frozen=True blocks direct setattr; use object.__setattr__
            # to backfill the canonical hash. Pydantic v2 frozen models
            # still allow this escape hatch (model_copy is the public
            # path, but here we're inside model_construct which runs
            # before the model is fully formed).
            object.__setattr__(
                obj,
                "signal_id",
                compute_signal_id(
                    event=obj.event,
                    symbol=obj.symbol,
                    tf=obj.tf,
                    dir_=obj.dir,
                    level=obj.level,
                    bar_time=obj.bar_time,
                    ob_id=obj.ob_id,
                    bos_id=obj.bos_id,
                ),
            )
        return obj

    prefix: Literal["SMC"]
    version: Literal["v1"]
    event: str
    symbol: str
    tf: str
    dir: str  # normalized to long|short|none by validator
    level: float
    bar_time: int
    ob_id: int = -1
    bos_id: int = -1
    state: str
    reason: str = ""

    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: str = ""
    signal_id: str = ""

    @field_validator("event")
    @classmethod
    def _event_allowed(cls, v: str) -> str:
        if v not in EVENT_VALUES:
            raise ValueError(f"event must be one of {EVENT_VALUES}, got {v!r}")
        return v

    @field_validator("symbol")
    @classmethod
    def _symbol_allowed(cls, v: str) -> str:
        if v not in SYMBOL_ALLOWLIST:
            raise ValueError(f"symbol must be in {SYMBOL_ALLOWLIST}, got {v!r}")
        return v

    @field_validator("tf")
    @classmethod
    def _tf_allowed(cls, v: str) -> str:
        if v not in TF_CANONICAL:
            raise ValueError(f"tf must be one of {TF_CANONICAL}, got {v!r}")
        return v

    @field_validator("dir")
    @classmethod
    def _dir_allowed(cls, v: str) -> str:
        if v not in ("long", "short", "none"):
            raise ValueError(f"dir must be one of ('long','short','none'), got {v!r}")
        return v

    @field_validator("state")
    @classmethod
    def _state_allowed(cls, v: str) -> str:
        if v not in STATE_PHASE01_ACCEPTED:
            raise ValueError(f"state must be one of {STATE_PHASE01_ACCEPTED}, got {v!r}")
        return v

    @field_validator("bar_time")
    @classmethod
    def _bar_time_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("bar_time must be > 0")
        return v

    @field_validator("ob_id", "bos_id")
    @classmethod
    def _ids_non_negative_or_minus_one(cls, v: int) -> int:
        if v < -1:
            raise ValueError("ob_id/bos_id must be >= -1 (-1 = N/A)")
        return v

    @model_validator(mode="after")
    def _fill_signal_id(self) -> "AlertPayload":
        if not self.signal_id:
            # frozen=True blocks self.signal_id =; use object.__setattr__
            # so the backfill doesn't violate the immutability contract.
            object.__setattr__(
                self,
                "signal_id",
                compute_signal_id(
                    event=self.event,
                    symbol=self.symbol,
                    tf=self.tf,
                    dir_=self.dir,
                    level=self.level,
                    bar_time=self.bar_time,
                    ob_id=self.ob_id,
                    bos_id=self.bos_id,
                ),
            )
        return self


# ---------------------------------------------------------------------------
# Wire-format parsing
# ---------------------------------------------------------------------------


class PayloadParseError(ValueError):
    """Raised when a raw wire payload cannot be parsed into AlertPayload."""


def _kv_from_pipe_string(body: str) -> dict[str, str]:
    """Parse ``SMC|v1|event=...|symbol=...|...`` into a dict.

    The first two positional fields (``prefix``, ``version``) become their own keys.
    """
    parts = body.split("|")
    if len(parts) < 2:
        raise PayloadParseError("payload must contain at least prefix|version")
    prefix = parts[0].strip()
    version = parts[1].strip()
    if prefix != PREFIX:
        raise PayloadParseError(f"prefix must be {PREFIX!r}, got {prefix!r}")
    if version != VERSION:
        raise PayloadParseError(f"version must be {VERSION!r}, got {version!r}")
    fields: dict[str, str] = {"prefix": prefix, "version": version}
    for raw in parts[2:]:
        if "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def _coerce_from_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw dict (from JSON body or pipe string) into typed fields."""
    required = ("prefix", "version", "event", "symbol", "tf", "dir", "level", "bar_time", "state")
    missing = [k for k in required if k not in d]
    if missing:
        raise PayloadParseError(f"missing required fields: {missing}")
    return {
        "prefix": d["prefix"],
        "version": d["version"],
        "event": d["event"],
        "symbol": normalize_symbol(d["symbol"]),
        "tf": normalize_tf(d["tf"]),
        "dir": normalize_dir(d["dir"]),
        "level": float(d["level"]),
        "bar_time": int(d["bar_time"]),
        "ob_id": int(d.get("ob_id", -1)),
        "bos_id": int(d.get("bos_id", -1)),
        "state": normalize_state(d["state"]),
        "reason": str(d.get("reason", "") or ""),
    }


def parse_payload(body: str | bytes, content_type: str | None = None) -> AlertPayload:
    """Parse a raw TradingView webhook body into a validated ``AlertPayload``.

    Accepts both:
      - ``text/plain`` pipe-delimited (default TradingView alert message)
      - ``application/json`` (forward-compatible wrapper)

    The original raw payload is preserved on ``AlertPayload.raw_payload``.
    """
    if isinstance(body, (bytes, bytearray)):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PayloadParseError("body is not valid UTF-8") from exc
    else:
        text = body

    text = (text or "").strip()
    if not text:
        raise PayloadParseError("empty body")

    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct == "application/json":
        import json

        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PayloadParseError(f"invalid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise PayloadParseError("JSON body must be an object")
        coerced = _coerce_from_dict(obj)
    else:
        # text/plain pipe-delimited OR JSON-as-text (TradingView lets user pick).
        if text.startswith("{"):
            import json

            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                coerced = _coerce_from_dict(obj)
            else:
                coerced = _coerce_from_dict(_kv_from_pipe_string(text))
        else:
            coerced = _coerce_from_dict(_kv_from_pipe_string(text))

    coerced["raw_payload"] = text
    try:
        return AlertPayload(**coerced)
    except Exception as exc:  # pydantic ValidationError or coercion ValueError
        raise PayloadParseError(str(exc)) from exc