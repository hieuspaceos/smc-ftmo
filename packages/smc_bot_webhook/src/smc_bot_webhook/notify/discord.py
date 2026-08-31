"""Discord webhook mirror.

Plain-text HTTP POST to a Discord webhook URL. NO buttons, NO approval
authority — Discord is read-only. Telegram remains the sole approval channel.

Mirrors the same retry semantics as the Telegram dispatcher: 3 attempts with
exponential backoff (1s, 2s, 4s) on transient failures. Permanent errors
(4xx other than 429) raise immediately.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol

import httpx

from smc_bot_webhook.notify.formatting import format_discord_message
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("bot.notify.discord")


class DiscordTransport(Protocol):
    """Minimal async POST interface — tests inject a fake."""

    async def post_webhook(
        self,
        *,
        url: str,
        content: str,
        timeout_seconds: float,
    ) -> int:
        """Return HTTP status code; raise on transport errors."""


class FakeDiscordTransport:
    """In-memory transport for tests."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.fail_n_times: int = 0

    async def post_webhook(
        self,
        *,
        url: str,
        content: str,
        timeout_seconds: float,
    ) -> int:
        if self.fail_n_times > 0:
            self.fail_n_times -= 1
            raise RuntimeError("simulated discord transport failure")
        self.posts.append({"url": url, "content": content, "timeout": timeout_seconds})
        return 204  # Discord webhook success


class _HttpxDiscordTransport:
    def __init__(self) -> None:
        # Shared client across all post_webhook calls.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    async def post_webhook(
        self,
        *,
        url: str,
        content: str,
        timeout_seconds: float,
    ) -> int:
        resp = await self._client.post(
            url,
            content=content,
            headers={"content-type": "text/plain; charset=utf-8"},
            timeout=timeout_seconds,
        )
        return int(resp.status_code)

    async def aclose(self) -> None:
        await self._client.aclose()


class _DisabledMirror:
    async def send_signal(self, payload: AlertPayload) -> bool:  # noqa: ARG002
        logger.debug("discord disabled; skipping send_signal for %s", payload.signal_id)
        return False

    @property
    def enabled(self) -> bool:
        return False


disabled_discord: Any = _DisabledMirror()


class DiscordMirror:
    """Mirror alerts to a Discord webhook (text-only)."""

    def __init__(
        self,
        transport: DiscordTransport,
        *,
        webhook_url: str,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        timeout_seconds: float = 10.0,
        rate_limit_per_10s: int = 5,
    ) -> None:
        self._transport = transport
        self._webhook_url = webhook_url
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._timeout_seconds = timeout_seconds
        # Phase 04 (audit fix): client-side rate limit to avoid
        # Discord 429 storm on burst. Tracks wall-clock timestamps
        # of recent sends and sleeps until the 10s window has space.
        self._rate_limit = rate_limit_per_10s
        self._recent_sends: list[float] = []
        self._rate_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return True

    async def aclose(self) -> None:
        close = getattr(self._transport, "aclose", None)
        if callable(close):
            await close()


    async def send_signal(
        self,
        payload: AlertPayload,
        *,
        gate_states: dict[str, bool | None] | None = None,
    ) -> bool:
        text = format_discord_message(payload, gate_states=gate_states)
        # Phase 04: client-side rate limit. Wait until under the
        # per-10s cap before calling the transport.
        import time as _time
        async with self._rate_lock:
            now = _time.monotonic()
            self._recent_sends = [t for t in self._recent_sends if now - t < 10.0]
            if len(self._recent_sends) >= self._rate_limit:
                wait = 10.0 - (now - self._recent_sends[0])
                if wait > 0:
                    logger.warning(
                        "discord client rate-limit hit, sleeping %.2fs", wait,
                    )
                    await asyncio.sleep(wait)
            self._recent_sends.append(_time.monotonic())
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                status = await self._transport.post_webhook(
                    url=self._webhook_url,
                    content=text,
                    timeout_seconds=self._timeout_seconds,
                )
                # Discord returns 204 on success; 429 is rate-limit (retry).
                if status == 429 or status >= 500:
                    raise RuntimeError(f"discord returned status={status}")
                if status >= 400:
                    # Permanent client error — don't retry.
                    logger.warning(
                        "discord permanent failure: signal_id=%s status=%d",
                        payload.signal_id, status,
                    )
                    return False
                logger.info(
                    "discord mirror ok: signal_id=%s status=%d attempt=%d",
                    payload.signal_id, status, attempt + 1,
                )
                return True
            except Exception as exc:  # noqa: BLE001 — retry transient
                last_exc = exc
                backoff = self._backoff_base * (2 ** attempt)
                logger.warning(
                    "discord mirror failed: signal_id=%s attempt=%d/%d exc=%s; sleeping %.1fs",
                    payload.signal_id, attempt + 1, self._max_retries, exc, backoff,
                )
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(backoff)
        logger.error(
            "discord mirror exhausted retries: signal_id=%s last_exc=%s",
            payload.signal_id, last_exc,
        )
        return False


def mirror_from_env(
    *,
    transport: DiscordTransport | None = None,
) -> Any:
    """Build a mirror from environment, or ``disabled_discord`` if unset."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "") or ""
    if not url:
        logger.info("DISCORD_WEBHOOK_URL unset; discord mirror disabled")
        return disabled_discord
    return DiscordMirror(
        transport=transport or _HttpxDiscordTransport(),
        webhook_url=url,
    )