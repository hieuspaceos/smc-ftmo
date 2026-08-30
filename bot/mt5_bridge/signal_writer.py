"""Atomic outbox signal writer for the MQL5 EA.

Contract (per plan §Signal writer):
  1. Write JSON to <outbox>/pending/<sid>.json.tmp
  2. fsync the temp file
  3. Rename to <outbox>/pending/<sid>.json (atomic on POSIX)
  4. MQL5 EA only opens .json (never .tmp)

Idempotency: write_signal() refuses a duplicate signal_id (raises
``SignalAlreadyWrittenError``). Callers must check /done before writing.

Schema (SMC_EXECUTION_V1) — see plan §Signal JSON schema:
  {
    "schema": "SMC_EXECUTION_V1",
    "signal_id": "<16-char hex>",
    "symbol": "EURUSD",
    "side": "long" | "short",
    "entry": float,
    "sl": float,
    "tp": [float, ...],          # up to 3 take-profit levels
    "risk_pct": float,            # 0.0055 = 0.55%
    "bar_time": ISO-8601 UTC,
    "expires_at": ISO-8601 UTC,
    "ob_id": int,
    "bos_id": int,
    "approved_by": "<actor>",    # Telegram user id / "admin" / etc.
    "guard_snapshot": {            # FTMO guard at time of approval
      "trades_today": int,
      "daily_pnl": float,
      "open_position": bool,
    }
  }
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.mt5_bridge")

EXECUTION_SCHEMA_VERSION = "SMC_EXECUTION_V1"


class SignalAlreadyWrittenError(Exception):
    """Raised when write_signal() is called twice for the same signal_id."""


class SignalExpiredError(Exception):
    """Raised when expires_at is in the past at write time."""


@dataclass(frozen=True)
class SignalRecord:
    """Strongly-typed representation of a signal waiting for MT5 execution.

    ``tp`` is stored as a tuple of up to 3 floats (Phase 06 spec).
    ``guard_snapshot`` is captured at approval time so audit logs show
    what FTMO guard state permitted the trade.
    """

    signal_id: str
    symbol: str
    side: str
    entry: float
    sl: float
    tp: tuple[float, ...]
    risk_pct: float
    bar_time: str          # ISO-8601 UTC
    expires_at: str       # ISO-8601 UTC (default: bar_time + 5min)
    ob_id: int
    bos_id: int
    approved_by: str
    guard_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["schema"] = EXECUTION_SCHEMA_VERSION
        d["tp"] = list(self.tp)  # JSON-friendly list
        return d

    @classmethod
    def from_alert_payload(
        cls,
        *,
        signal_id: str,
        symbol: str,
        side: str,
        level: float,
        bar_time: datetime,
        ob_id: int = -1,
        bos_id: int = -1,
        approved_by: str,
        sl: float | None = None,
        tp_levels: tuple[float, ...] | None = None,
        risk_pct: float = 0.0055,
        guard_snapshot: dict[str, Any] | None = None,
        ttl_seconds: int = 300,
    ) -> "SignalRecord":
        """Build a SignalRecord from Phase 02/03 alert payload + decision actor."""
        # Default stop loss: 50 pips below/above entry (configurable).
        # For EURUSD with 5-digit broker: 0.0050 ≈ 50 pips.
        if sl is None:
            sl = level - 0.0050 if side == "long" else level + 0.0050
        # Default take profits: R:R 1:2, 1:3, 1:4 from entry.
        if tp_levels is None:
            risk = abs(level - sl)
            if side == "long":
                tp_levels = (level + risk * 2, level + risk * 3, level + risk * 4)
            else:
                tp_levels = (level - risk * 2, level - risk * 3, level - risk * 4)
        # ISO-8601 with 'Z' suffix (MQL5 friendly).
        bar_iso = bar_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = bar_time.astimezone(timezone.utc).timestamp() + ttl_seconds
        exp_iso = (
            datetime.fromtimestamp(expires_at, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        return cls(
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            entry=level,
            sl=sl,
            tp=tp_levels,
            risk_pct=risk_pct,
            bar_time=bar_iso,
            expires_at=exp_iso,
            ob_id=ob_id,
            bos_id=bos_id,
            approved_by=approved_by,
            guard_snapshot=guard_snapshot or {},
        )


class OutboxWriter:
    """Manages a local outbox directory tree (pending/processing/done/failed).

    The MQL5 EA (running on a Windows / VPS / VM terminal) polls ``pending/``
    via SMB / Syncthing / local mount. This class is used by the Python
    Accept path to atomically enqueue signals.
    """

    SUBDIRS = ("pending", "processing", "done", "failed")

    def __init__(self, outbox_dir: Path) -> None:
        self.outbox_dir = Path(outbox_dir)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        for sub in self.SUBDIRS:
            (self.outbox_dir / sub).mkdir(exist_ok=True)

    @property
    def pending(self) -> Path:
        return self.outbox_dir / "pending"

    @property
    def processing(self) -> Path:
        return self.outbox_dir / "processing"

    @property
    def done(self) -> Path:
        return self.outbox_dir / "done"

    @property
    def failed(self) -> Path:
        return self.outbox_dir / "failed"

    def is_pending(self, signal_id: str) -> bool:
        """True iff signal_id is in pending/ or processing/."""
        for sub in ("pending", "processing"):
            if (self.outbox_dir / sub / f"{signal_id}.json").exists():
                return True
        return False

    def is_done(self, signal_id: str) -> bool:
        return (self.done / f"{signal_id}.json").exists()

    def is_failed(self, signal_id: str) -> bool:
        return (self.failed / f"{signal_id}.json").exists()

    def write_atomic(self, signal_id: str, record: SignalRecord) -> Path:
        """Write JSON to pending/<sid>.json via tmp + fsync + rename.

        Raises ``SignalAlreadyWrittenError`` if a file already exists in
        pending/ or processing/ (idempotency contract).
        """
        if self.is_pending(signal_id):
            raise SignalAlreadyWrittenError(
                f"signal_id={signal_id} already pending or processing"
            )
        target = self.pending / f"{signal_id}.json"
        payload = json.dumps(record.to_dict(), indent=2)
        # NamedTemporaryFile + os.replace = atomic on POSIX (same filesystem).
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{signal_id}.", suffix=".json.tmp", dir=str(self.pending)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            # Clean up partial tmp on failure.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise
        logger.info("outbox: wrote %s (%d bytes)", target, target.stat().st_size)
        return target

    def read_pending(self) -> list[Path]:
        """Return sorted list of pending/*.json files (MQL5 polls oldest first)."""
        return sorted(self.pending.glob("*.json"))


def write_signal(
    outbox: OutboxWriter,
    record: SignalRecord,
) -> Path:
    """Atomic write with idempotency + expiry check.

    Raises ``SignalExpiredError`` if ``expires_at`` is already in the past.
    Raises ``SignalAlreadyWrittenError`` on duplicate signal_id.
    """
    expires_dt = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
    if expires_dt <= datetime.now(timezone.utc):
        raise SignalExpiredError(
            f"signal_id={record.signal_id} expired at {record.expires_at}"
        )
    return outbox.write_atomic(record.signal_id, record)