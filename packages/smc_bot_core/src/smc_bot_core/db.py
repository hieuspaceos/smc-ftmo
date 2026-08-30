"""SQLite helper used by all bot packages.

Re-exports BotDB, DEFAULT_DB_PATH, init_db, get_default_db_path from
db_impl (formerly bot/storage/db.py).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_DB_PATH = Path("output/bot.db")

from smc_bot_core.db_impl import (  # noqa: F401  (re-export)
    BotDB,
    DEFAULT_DB_PATH as _DEFAULT_DB_PATH,
    init_db,
    get_default_db_path,
)

# Re-export at module level for `from smc_bot_core.db import get_default_db_path`.
get_default_db_path = get_default_db_path

__all__ = ["BotDB", "DEFAULT_DB_PATH", "init_db", "get_default_db_path"]
