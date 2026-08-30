"""Phase 06: MT5 file-based bridge for demo execution."""

from bot.mt5_bridge.executor import (
    DisabledExecutor,
    FileBridgeExecutor,
    build_executor,
)
from bot.mt5_bridge.ftmo_guard import FtmoGuard, FtmoGuardResult, GuardState
from bot.mt5_bridge.signal_writer import (
    EXECUTION_SCHEMA_VERSION,
    OutboxWriter,
    SignalAlreadyWrittenError,
    SignalExpiredError,
    SignalRecord,
    write_signal,
)

__all__ = [
    "EXECUTION_SCHEMA_VERSION",
    "OutboxWriter",
    "SignalAlreadyWrittenError",
    "SignalExpiredError",
    "SignalRecord",
    "write_signal",
    "FtmoGuard",
    "FtmoGuardResult",
    "GuardState",
    "DisabledExecutor",
    "FileBridgeExecutor",
    "build_executor",
]