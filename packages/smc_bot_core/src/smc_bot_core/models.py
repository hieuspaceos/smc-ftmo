"""Re-export of payload models + parser.

The canonical implementation lives in `bot.webhook.payload` (Phase 01).
This stub keeps imports working for downstream packages while we migrate.
"""

from __future__ import annotations

# Re-export
from smc_bot_webhook.payload import (  # noqa: F401  (re-export)
    AlertPayload,
    compute_signal_id,
    parse_payload,
)

__all__ = ["AlertPayload", "compute_signal_id", "parse_payload"]
