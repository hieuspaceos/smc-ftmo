"""Re-export of `bot.webhook.security.SecurityConfig` for backward compat.

The actual implementation stays in smc_bot_webhook (where the rate limiter
lives). This stub keeps imports from working without circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityConfig:
    """Subset used by all packages (token + rate limit).

    The rate limiter itself lives in smc_bot_webhook. Other packages only
    need to read the config (e.g. to display the configured limit).
    """

    url_secret: str
    rate_limit_per_min: int = 60
