"""Tests for Phase 04 — Telegram MarkdownV2 formatting + rate limits.

Closes audit finding C4 (Telegram parse_mode unsafe), H5 (Telegram retry
blocks loop), M6 (Discord no rate limit), M8 (body cap too small).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from smc_bot_webhook.notify.formatting import (
    _md2_escape,
    format_telegram_message,
)
from smc_bot_webhook.payload import parse_payload
from smc_bot_webhook.security import SecurityConfig, body_within_cap


VALID_PIPE = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


# ---------------------------------------------------------------------------
# _md2_escape
# ---------------------------------------------------------------------------


class TestMd2Escape:
    def test_escapes_reserved_chars(self) -> None:
        assert _md2_escape("hello. (world) _test_!") == "hello\\. \\(world\\) \\_test\\_\\!"

    def test_escapes_each_reserved_char(self) -> None:
        reserved = "_*[]()~`>#+-=|{}.!"
        for ch in reserved:
            assert _md2_escape(f"a{ch}b") == f"a\\{ch}b", f"failed for {ch!r}"

    def test_passthrough_for_plain_text(self) -> None:
        assert _md2_escape("hello world") == "hello world"

    def test_passthrough_for_empty_string(self) -> None:
        assert _md2_escape("") == ""

    def test_does_not_double_escape(self) -> None:
        # Caller passes already-escaped text → leave it alone.
        assert _md2_escape("already\\.escaped") == "already\\.escaped"

    def test_preserves_unicode(self) -> None:
        assert _md2_escape("EURUSD 🚀") == "EURUSD 🚀"


# ---------------------------------------------------------------------------
# format_telegram_message — MarkdownV2 + escaping
# ---------------------------------------------------------------------------


class TestFormatTelegramMd2:
    def test_escapes_reason_with_special_chars(self) -> None:
        # reason is the only Pine payload field where we cannot predict
        # the contents — Pine rulebook code can emit strings like
        # "Sweep_/_test" or "no_displacement.at_H4".
        body = VALID_PIPE.replace(
            "reason=ok",
            "reason=has_special.chars_*[]()",
        )
        p = parse_payload(body)
        text = format_telegram_message(p)
        # Free-text "reason" must be escaped inside its inline code block.
        assert "has\\_special\\.chars\\_\\*\\[\\]\\(\\)" in text

    def test_structured_fields_remain_in_inline_code(self) -> None:
        p = parse_payload(VALID_PIPE)
        text = format_telegram_message(p)
        # signal_id wrapped in inline code.
        assert f"`{p.signal_id}`" in text

    def test_dir_long_renders_green_emoji(self) -> None:
        p = parse_payload(VALID_PIPE)
        text = format_telegram_message(p)
        assert "🟢 LONG" in text

    def test_dir_short_renders_red_emoji(self) -> None:
        body = VALID_PIPE.replace("dir=long", "dir=short")
        p = parse_payload(body)
        text = format_telegram_message(p)
        assert "🔴 SHORT" in text

    def test_state_with_hyphen_escaped_inside_inline_code(self) -> None:
        # MarkdownV2 requires escaping "-" inside inline code. The
        # formatter passes text through _md2_escape, so the hyphen in
        # "chart-qualified" becomes "\-".
        p = parse_payload(VALID_PIPE)
        text = format_telegram_message(p)
        assert "chart\\-qualified" in text

    def test_state_watch_renders_eye_emoji(self) -> None:
        body = VALID_PIPE.replace("state=chart-qualified", "state=watch")
        p = parse_payload(body)
        text = format_telegram_message(p)
        assert "👀" in text


# ---------------------------------------------------------------------------
# SecurityConfig — body cap 8 KB
# ---------------------------------------------------------------------------


class TestBodyCap:
    def test_default_body_max_bytes_is_8kb(self) -> None:
        # Phase 04: bumped from 4 KB.
        cfg = SecurityConfig(url_secret="x" * 16)
        assert cfg.body_max_bytes == 8192

    def test_5kb_body_under_cap(self) -> None:
        assert body_within_cap(b"X" * 5000, cap_bytes=8192) is True

    def test_10kb_body_over_cap(self) -> None:
        assert body_within_cap(b"X" * 10000, cap_bytes=8192) is False


# ---------------------------------------------------------------------------
# TelegramDispatcher — semaphore bounds concurrency
# ---------------------------------------------------------------------------


class TestTelegramSemaphore:
    def test_default_concurrency_is_5(self) -> None:
        from smc_bot_webhook.notify.telegram import (
            FakeTelegramTransport,
            TelegramDispatcher,
        )
        tg = FakeTelegramTransport()
        d = TelegramDispatcher(tg, chat_id=1, allowed_user_ids={1})
        # The semaphore is private; verify it exists and can be acquired.
        async def runner() -> None:
            for _ in range(5):
                assert d._send_sem.locked() is False
                await d._send_sem.acquire()
            # After 5 acquires, one more must block.
            assert d._send_sem.locked()
        asyncio.run(runner())

    def test_concurrent_sends_bounded(self) -> None:
        """With concurrency=2, at most 2 send_message calls run
        concurrently even when 5 are dispatched at once."""
        from smc_bot_webhook.notify.telegram import (
            FakeTelegramTransport,
            TelegramDispatcher,
        )

        class SlowTransport(FakeTelegramTransport):
            def __init__(self) -> None:
                super().__init__()
                self._in_flight = 0
                self._lock = asyncio.Lock()
                self.peak = 0

            async def send_message(self, **kwargs):
                async with self._lock:
                    self._in_flight += 1
                    if self._in_flight > self.peak:
                        self.peak = self._in_flight
                try:
                    await asyncio.sleep(0.02)
                finally:
                    async with self._lock:
                        self._in_flight -= 1
                return await super().send_message(**kwargs)

        async def runner() -> None:
            tg = SlowTransport()
            d = TelegramDispatcher(
                tg, chat_id=1, allowed_user_ids={1},
                max_retries=1, backoff_base_seconds=0.001,
                send_concurrency=2,
            )
            p = parse_payload(VALID_PIPE)
            await asyncio.gather(*[d.send_signal(p) for _ in range(5)])
            return tg.peak

        peak = asyncio.run(runner())
        assert peak <= 2, f"peak concurrency {peak} exceeded limit 2"


# ---------------------------------------------------------------------------
# DiscordMirror — client-side rate limit
# ---------------------------------------------------------------------------


class TestDiscordRateLimit:
    def test_rate_limit_waits_when_window_full(self) -> None:
        """With rate_limit_per_10s=2, the 3rd send should wait for
        the window to slide."""
        from smc_bot_webhook.notify.discord import DiscordMirror

        class FakeTransport:
            def __init__(self) -> None:
                self.calls: list[float] = []

            async def post_webhook(self, *, url, content, timeout_seconds):
                self.calls.append(time.monotonic())
                return 204

        async def runner() -> None:
            tg = FakeTransport()
            m = DiscordMirror(
                tg, webhook_url="http://x",
                max_retries=1, backoff_base_seconds=0.001,
                rate_limit_per_10s=2,
            )
            p = parse_payload(VALID_PIPE)
            t0 = time.monotonic()
            await m.send_signal(p)
            await m.send_signal(p)
            # 3rd: should wait (the window has 2 entries; oldest is
            # within the last 10s).
            await m.send_signal(p)
            elapsed = time.monotonic() - t0
            return len(tg.calls), elapsed

        n, elapsed = asyncio.run(runner())
        assert n == 3
        # Window is 10s; 3rd call should have slept until the first
        # call's entry is > 10s old. Assert at least 0.5s of waiting
        # happened (allows slack for asyncio scheduling).
        assert elapsed >= 0.5, f"3rd send didn't wait: {elapsed:.2f}s"
