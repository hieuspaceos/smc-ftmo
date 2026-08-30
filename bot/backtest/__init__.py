"""Phase 04: Python replay engine + signal CSV capture.

The replay engine walks a frozen OHLC bundle bar-by-bar and emits
``AlertPayload``-equivalent signal decisions — same shape as live
``/webhooks/tradingview`` would receive. Determinism: same OHLC + same
config → byte-for-byte identical output.

Capture.py writes a unified CSV from 3 sources:
- live webhook (joined from alert_log + signal_events)
- Python replay output
- manual Pine Logs paste (regex-parsed)
"""

from bot.backtest.replay_engine import (
    ReplayEngine,
    ReplayRun,
    replay_from_ohlc,
)
from bot.backtest.capture import (
    CSV_COLUMNS,
    capture_from_live,
    capture_from_pine_logs,
    capture_from_replay,
)

__all__ = [
    # replay
    "ReplayEngine",
    "ReplayRun",
    "replay_from_ohlc",
    # capture
    "CSV_COLUMNS",
    "capture_from_live",
    "capture_from_replay",
    "capture_from_pine_logs",
]