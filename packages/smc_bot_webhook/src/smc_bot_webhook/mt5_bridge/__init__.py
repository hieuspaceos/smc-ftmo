"""Phase 06: MT5 file-based bridge for demo execution."""

from smc_bot_webhook.mt5_bridge.executor import (
    DisabledExecutor,
    FileBridgeExecutor,
    build_executor,
)
from smc_bot_webhook.mt5_bridge.ftmo_guard import FtmoGuard, FtmoGuardResult, GuardState
from smc_bot_webhook.mt5_bridge.signal_writer import (
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