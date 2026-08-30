"""Typed configuration loaded from environment variables.

Used by `smc_bot_webhook`, `smc_bot_dashboard`, etc. Each consumer reads
the relevant subset; defaults match the prior in-webhook `_env` helpers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


MIN_SECRET_LENGTH = 16


@dataclass(frozen=True)
class AppSettings:
    """Generic bot settings — webhook URL secret, DB path, rate limit, trust proxy."""

    url_secret: str
    db_path: Path
    security: "SecurityConfig"  # forward-ref to avoid cycle
    trusted_proxy: bool

    @classmethod
    def from_env(cls) -> "AppSettings":
        from smc_bot_core.security import SecurityConfig

        secret = _env("SMC_WEBHOOK_TOKEN", "") or ""
        if not secret:
            raise RuntimeError(
                "SMC_WEBHOOK_TOKEN env var is required. "
                "Set it to a long random string shared with the TradingView alert URL."
            )
        if len(secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"SMC_WEBHOOK_TOKEN is too short ({len(secret)} chars). "
                f"Use at least {MIN_SECRET_LENGTH} chars."
            )
        db = Path(
            _env("SMC_BOT_DB_PATH", "output/bot.db")
            or "output/bot.db"
        )
        return cls(
            url_secret=secret,
            db_path=db,
            security=SecurityConfig(
                url_secret=secret,
                rate_limit_per_min=_env_int("SMC_RATE_LIMIT_PER_MIN", 60),
            ),
            trusted_proxy=_env_bool("SMC_TRUSTED_PROXY", False),
        )


def get_settings() -> AppSettings:
    """Cached loader — call AppSettings.from_env() directly for fresh instance."""
    return AppSettings.from_env()
