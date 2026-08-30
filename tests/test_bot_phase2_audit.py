"""Edge-case + concurrency audit tests for Phase 02 dispatchers + audit hooks."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from bot.notify.formatting import (
    build_inline_keyboard,
    parse_callback_data,
)
from bot.notify.telegram import (
    FakeTelegramTransport,
    TelegramDispatcher,
)
from bot.storage.db import BotDB, init_db
from bot.webhook.payload import parse_payload

VALID = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def _db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_p2_audit_{int(time.time() * 1000000)}.db")
    init_db(p)
    return BotDB(p), p


class TestConcurrentSignalEvents:
    def test_50_threads_writing_distinct_signal_ids(self) -> None:
        """50 threads each insert 5 events for distinct signal_ids — no loss."""
        db, path = _db()
        try:
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    for j in range(5):
                        db.record_event(
                            f"sig-{i}-{j}", "notified",
                            payload='{"k":"v"}', actor=f"user-{i}",
                        )
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"unexpected errors: {errors[:3]}"
            recent = db.list_recent_events(limit=1000)
            assert len(recent) == 250  # 50 * 5
        finally:
            _cleanup(path)

    def test_record_event_appends_each_call(self) -> None:
        """signal_events has no UNIQUE — repeated calls append (audit semantics)."""
        db, path = _db()
        try:
            db.record_event("sig-1", "notified", actor="x")
            db.record_event("sig-1", "notified", actor="x")
            db.record_event("sig-1", "notified", actor="x")
            events = [e for e in db.list_recent_events() if e["signal_id"] == "sig-1"]
            assert len(events) == 3
        finally:
            _cleanup(path)


class TestRecordDecisionPayloadInjection:
    """Bug1 fix: record_decision uses json.dumps, so actor/nonce with embedded
    quote/brace/etc parse cleanly via json.loads."""

    def test_actor_with_quote_parses_as_valid_json(self) -> None:
        db, path = _db()
        try:
            TelegramDispatcher.record_decision(
                db, "sig", decision="accept",
                actor='evil"}INJECTED{"', nonce="nonce1234",
            )
            event = db.latest_event("sig")
            assert event is not None
            parsed = json.loads(event["payload"])
            assert parsed["decision"] == "accept"
            assert parsed["actor"] == 'evil"}INJECTED{"'
            assert parsed["nonce"] == "nonce1234"
        finally:
            _cleanup(path)

    def test_nonce_with_quote_parses_as_valid_json(self) -> None:
        db, path = _db()
        try:
            TelegramDispatcher.record_decision(
                db, "sig", decision="reject",
                actor="u1", nonce='nonce"INJECT',
            )
            event = db.latest_event("sig")
            assert event is not None
            parsed = json.loads(event["payload"])
            assert parsed["nonce"] == 'nonce"INJECT'
        finally:
            _cleanup(path)

    def test_payload_uses_json_dumps_not_fstring(self) -> None:
        """Direct check: payload must be exactly what json.dumps produces."""
        db, path = _db()
        try:
            TelegramDispatcher.record_decision(
                db, "sig", decision="accept",
                actor="u1", nonce="n1234",
            )
            event = db.latest_event("sig")
            expected = json.dumps(
                {"decision": "accept", "actor": "u1", "nonce": "n1234"},
                sort_keys=True,
            )
            assert event["payload"] == expected
        finally:
            _cleanup(path)


class TestParseCallbackNormalization:
    def test_uppercase_hex_normalized_to_lowercase(self) -> None:
        """compute_signal_id returns lowercase hex; callback must match."""
        cb = parse_callback_data("accept:DEADBEEF12345678:nonce1234")
        assert cb is not None
        assert cb.signal_id == "deadbeef12345678"

    def test_mixed_case_normalized_to_lowercase(self) -> None:
        cb = parse_callback_data("accept:AbCdEf1234567890:nonce1234")
        assert cb is not None
        assert cb.signal_id == "abcdef1234567890"

    def test_non_hex_alphabetic_rejected(self) -> None:
        cb = parse_callback_data("accept:ggg1234567890ab:nonce1234")
        assert cb is None

    def test_nonce_length_capped_4_to_64(self) -> None:
        """Telegram limits callback_data to 64 bytes; nonce must fit."""
        # Too short (3 chars)
        assert parse_callback_data("accept:abc1234567890abc:abc") is None
        # Too long (65+ chars)
        long_nonce = "n" * 65
        assert parse_callback_data(f"accept:abc1234567890abc:{long_nonce}") is None
        # Exactly 64
        ok_nonce = "n" * 64
        cb = parse_callback_data(f"accept:abc1234567890abc:{ok_nonce}")
        assert cb is not None
        assert len(cb.nonce) == 64


class TestKeyboardPayloadSize:
    def test_default_keyboard_within_telegram_64_byte_limit(self) -> None:
        """Default 16-char hex signal_id + 16-char nonce -> 39 bytes, fits."""
        kb = build_inline_keyboard("a" * 16, "n" * 16)
        for row in kb["inline_keyboard"]:
            for btn in row:
                assert len(btn["callback_data"]) <= 64

    def test_extreme_keyboard_exceeds_limit(self) -> None:
        """Documents current limitation: a long nonce would exceed Telegram's
        64-byte cap and Telegram would reject the button."""
        kb = build_inline_keyboard("a" * 16, "n" * 100)
        cb = kb["inline_keyboard"][0][0]["callback_data"]
        assert len(cb) > 64


class TestMessageIdCacheThreadSafety:
    def test_concurrent_send_records_message_ids(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )

            async def send_one(i: int) -> None:
                body = (
                    "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
                    f"|level=1.10000|bar_time={1700000000 + i}"
                    "|state=chart-qualified|reason=ok"
                )
                p = parse_payload(body)
                msg_id = await d.send_signal(p)
                assert d.get_message_id(p.signal_id) == msg_id

            await asyncio.gather(*[send_one(i) for i in range(20)])

        asyncio.run(run())


class TestHttpxDiscordClientLifecycle:
    def test_httpx_transport_has_aclose(self) -> None:
        from bot.notify.discord import _HttpxDiscordTransport
        tx = _HttpxDiscordTransport()
        assert hasattr(tx, "aclose")
        assert callable(tx.aclose)

    def test_disabled_mirror_has_no_aclose(self) -> None:
        """_DisabledMirror is the no-op singleton — must NOT have aclose."""
        from bot.notify.discord import _DisabledMirror
        m = _DisabledMirror()
        assert m.enabled is False
        assert not hasattr(m, "aclose")

    def test_live_mirror_exposes_aclose(self) -> None:
        """Live DiscordMirror must expose aclose so app shutdown can close httpx."""
        from bot.notify.discord import DiscordMirror, FakeDiscordTransport
        m = DiscordMirror(
            FakeDiscordTransport(),
            webhook_url="http://x", max_retries=1, backoff_base_seconds=0.001,
        )
        assert hasattr(m, "aclose")
        assert callable(m.aclose)


class TestPayloadLength:
    def test_payload_capped_at_32kb(self) -> None:
        """Bug2 fix: oversized payload truncated with 'replace' on UTF-8 boundary."""
        db, path = _db()
        try:
            huge = "x" * 100_000
            db.record_event("sig", "notified", payload=huge, actor="u")
            event = db.latest_event("sig")
            assert event is not None
            assert len(event["payload"]) == 32 * 1024
        finally:
            _cleanup(path)

    def test_payload_under_limit_unchanged(self) -> None:
        db, path = _db()
        try:
            payload = "small payload"
            db.record_event("sig", "notified", payload=payload, actor="u")
            event = db.latest_event("sig")
            assert event is not None
            assert event["payload"] == "small payload"
        finally:
            _cleanup(path)