"""Source verification for TradingView webhook.

TradingView webhooks do NOT send custom headers — only POST body over HTTPS.
Phase 0 (P0) auth is therefore URL secret query param + TradingView IP allowlist.
HMAC requires an edge proxy (out of scope for P0).
"""

from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass

# TradingView published webhook IP ranges (TradingView Help Center, 2024)
TRADINGVIEW_IPV4_ALLOWLIST: tuple[str, ...] = (
    "52.89.214.238",
    "34.212.75.30",
    "54.218.53.128",
    "52.32.178.7",
    "52.36.118.78",
)

DEFAULT_RATE_LIMIT_PER_MIN = 60
DEFAULT_BODY_MAX_BYTES = 8192  # 8 KB cap (Phase 04: bumped from 4 KB for richer payloads)

@dataclass(frozen=True)
class SecurityConfig:
    url_secret: str
    ipv4_allowlist: tuple[str, ...] = TRADINGVIEW_IPV4_ALLOWLIST
    body_max_bytes: int = DEFAULT_BODY_MAX_BYTES
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN


def check_url_secret(provided: str | None, expected: str) -> bool:
    """Constant-time compare URL secret. Empty provided → False."""
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def check_telegram_secret(provided: str | None, expected: str | None) -> bool:
    """Constant-time compare Telegram callback secret header.

    Empty provided → False. Empty expected (server not configured) → False:
    the server refuses to accept any Telegram callback when no secret is set,
    so misconfiguration fails closed rather than open.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)

def check_ip_allowlist(client_ip: str | None, allowlist: tuple[str, ...] = TRADINGVIEW_IPV4_ALLOWLIST) -> bool:
    """Return True iff client_ip is in allowlist.

    Empty/None client_ip → False (deny). Defensive: any parse error → deny.
    """
    if not client_ip:
        return False
    try:
        candidate = ipaddress.ip_address(client_ip.strip())
    except (ValueError, AttributeError):
        return False
    return str(candidate) in allowlist


def extract_client_ip(
    forwarded_for: str | None,
    direct_ip: str | None,
    trusted_proxy: bool = False,
) -> str | None:
    """Pick the right client IP.

    Cloudflare tunnel sets `CF-Connecting-IP`. FastAPI exposes it via headers.
    If behind a trusted proxy, prefer the leftmost `X-Forwarded-For` entry.
    Otherwise prefer the direct socket IP. Returns None when nothing is known.
    """
    if trusted_proxy and forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return direct_ip


def body_within_cap(body: bytes | str, cap_bytes: int = DEFAULT_BODY_MAX_BYTES) -> bool:
    """True iff body length is within cap."""
    size = len(body) if isinstance(body, (bytes, bytearray)) else len(body.encode("utf-8"))
    return size <= cap_bytes