"""Shared core for SMC bot packages.

Exposes:
- BotDB: SQLite helper with thread-safe per-call connections (Phase 01 fix)
- Settings: typed config dataclass + env loading
- Re-export AlertPayload / compute_signal_id / parse_payload for convenience

Other bot packages depend on this — keep the surface minimal.
"""

from smc_bot_core.config import AppSettings, get_settings, _env, _env_bool, _env_int
from smc_bot_core.db import BotDB, DEFAULT_DB_PATH, init_db
from smc_bot_core.models import AlertPayload, compute_signal_id, parse_payload

__all__ = [
    "AppSettings",
    "get_settings",
    "_env",
    "_env_bool",
    "_env_int",
    "BotDB",
    "DEFAULT_DB_PATH",
    "init_db",
    "AlertPayload",
    "compute_signal_id",
    "parse_payload",
]