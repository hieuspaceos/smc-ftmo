"""Executor transport dispatcher.

Feature flag: ``EXECUTOR_TRANSPORT=disabled|file|metaapi`` (default ``disabled``).

  - ``disabled``: Phase 06 default. Webhook accepts signals and persists
    them to ``execution_log`` with ``transport_state='blocked'`` but does
    NOT write to outbox / call any broker API.
  - ``file``: Phase 06 primary. Writes ``OutboxWriter`` JSON for MQL5 EA
    pickup. Same-row recorded as ``transport_state='queued'``.
  - ``metaapi``: reserved stub. Not implemented — raises if used.

Used by ``bot/webhook/server.py`` in the Telegram Accept callback (when
admin approves a signal) and in the webhook ``/api/execution`` endpoint
to read the ``execution_log`` table.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol

from smc_bot_webhook.mt5_bridge.signal_writer import (
    OutboxWriter,
    SignalRecord,
    SignalAlreadyWrittenError,
    SignalExpiredError,
    write_signal,
)

logger = logging.getLogger("bot.mt5_bridge")

# Outbox default location (relative to repo root).
DEFAULT_OUTBOX_DIR = Path("output/mt5_outbox")


def _validate_outbox_dir(path: Path) -> Path:
    """Validate MT5_OUTBOX_DIR is safe to use.

    Phase 06 (audit fix H1): reject paths that:
    - are symlinks (potential symlink-attack redirect)
    - point to a regular file (not a directory)
    - are not writable by the current process

    Returns the resolved (real) path. Raises ``ValueError`` with a
    clear message on any failure so the trader can fix the env var.
    """
    if path.is_symlink():
        raise ValueError(
            f"MT5_OUTBOX_DIR is a symlink: {path!s}. Refusing to write "
            "to symlinked directories for security (symlink-attack risk)."
        )
    if path.exists() and not path.is_dir():
        raise ValueError(
            f"MT5_OUTBOX_DIR exists but is not a directory: {path!s}"
        )
    # Try to create the directory; this also surfaces permission
    # errors early. resolve(strict=False) so the path doesn't need
    # to exist yet.
    resolved = path.resolve()
    if not resolved.exists():
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            raise ValueError(
                f"MT5_OUTBOX_DIR cannot be created: {path!s} ({exc})"
            ) from exc
    if not os.access(resolved, os.W_OK):
        raise ValueError(
            f"MT5_OUTBOX_DIR is not writable: {resolved!s}"
        )
    return resolved

class Executor(Protocol):
    """Minimal contract every executor backend implements."""

    name: str
    enabled: bool

    def execute(self, record: SignalRecord) -> tuple[bool, str]:
        """Send the signal to the broker.

        Returns ``(True, ticket_or_msg)`` on success, ``(False, reason)``
        on failure. The result is recorded in ``execution_log`` by the
        caller.
        """
        ...


class DisabledExecutor:
    """Default executor. Persists execution_log row as 'blocked' but does
    nothing else. Safe for production until trader proves the full flow."""

    name = "disabled"
    enabled = False

    def execute(self, record: SignalRecord) -> tuple[bool, str]:
        logger.info("executor=disabled: signal %s would have gone to MT5", record.signal_id)
        return True, "disabled: signal accepted, transport not configured"


class FileBridgeExecutor:
    """Atomic outbox writer (Phase 06 primary transport).

    Writes ``OutboxWriter`` JSON, records ``execution_log`` as
    ``transport='file', transport_state='queued'``.
    """

    name = "file"
    enabled = True

    def __init__(self, outbox: OutboxWriter) -> None:
        self.outbox = outbox

    def execute(self, record: SignalRecord) -> tuple[bool, str]:
        try:
            path = write_signal(self.outbox, record)
        except SignalAlreadyWrittenError as e:
            return False, f"duplicate: {e}"
        except SignalExpiredError as e:
            return False, f"expired: {e}"
        except Exception as e:  # noqa: BLE001
            return False, f"outbox write failed: {e}"
        return True, str(path)


def build_executor(
    *,
    outbox_dir: Path | None = None,
    db: Any | None = None,
) -> Executor:
    """Construct the executor specified by ``EXECUTOR_TRANSPORT`` env var.

    Defaults to ``DisabledExecutor`` (safe). Raises ``ValueError`` if the
    configured transport is unknown or the outbox dir can't be created.
    """
    transport = os.environ.get("EXECUTOR_TRANSPORT", "disabled").strip().lower()
    if transport == "disabled":
        return DisabledExecutor()
    if transport == "file":
        out_dir = outbox_dir or Path(os.environ.get("MT5_OUTBOX_DIR", str(DEFAULT_OUTBOX_DIR)))
        # Phase 06 (audit fix H1): validate path is real directory, not
        # a symlink, and is writable. Raises ValueError on misconfig.
        validated = _validate_outbox_dir(out_dir)
        return FileBridgeExecutor(OutboxWriter(validated))
    if transport == "metaapi":
        raise NotImplementedError(
            "MetaAPI executor is a future stub; not implemented in Phase 06. "
            "Use EXECUTOR_TRANSPORT=file (local outbox) until Phase 06.5 ships."
        )
    raise ValueError(
        f"unknown EXECUTOR_TRANSPORT={transport!r}; expected disabled|file|metaapi"
    )