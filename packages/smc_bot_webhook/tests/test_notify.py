"""Unit tests for notification dispatchers + formatters (Phase 02)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from smc_bot_webhook.notify.discord import (
    DiscordMirror,
    FakeDiscordTransport,
    disabled_discord,
    mirror_from_env,
)
from smc_bot_webhook.notify.formatting import (
    MANUAL_GATE_NAMES,
    build_inline_keyboard,
    format_discord_message,
    format_telegram_message,
    parse_callback_data,
    render_gate_checklist,
)
from smc_bot_webhook.notify.telegram import (
    FakeTelegramTransport,
    TelegramDispatcher,
    dispatcher_from_env,
)
from smc_bot_webhook.payload import parse_payload

VALID = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


# ---------------------------------------------------------------------------
# Format / parse — pure functions
# ---------------------------------------------------------------------------


class TestFormatTelegram:
    def test_includes_symbol_and_tf(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert "EURUSD" in text
        assert "M15" in text

    def test_includes_state_with_emoji(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert "chart-qualified" in text
        assert "✅" in text

    def test_long_dir_renders_green(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert "🟢 LONG" in text

    def test_short_dir_renders_red(self) -> None:
        body = VALID.replace("dir=long", "dir=short")
        p = parse_payload(body)
        text = format_telegram_message(p)
        assert "🔴 SHORT" in text

    def test_watch_state_renders_eye_emoji(self) -> None:
        body = VALID.replace("state=chart-qualified", "state=watch")
        p = parse_payload(body)
        text = format_telegram_message(p)
        assert "👀" in text

    def test_blocked_state_renders_ban_emoji(self) -> None:
        body = VALID.replace("state=chart-qualified", "state=blocked")
        p = parse_payload(body)
        text = format_telegram_message(p)
        assert "🚫" in text

    def test_bar_time_rendered_iso(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert "2023-11-14" in text

    def test_includes_signal_id(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert p.signal_id in text

    def test_includes_ob_and_bos_ids(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        assert "42" in text  # ob_id
        assert "7" in text   # bos_id

    def test_gate_checklist_placeholder_when_no_states(self) -> None:
        p = parse_payload(VALID)
        text = format_telegram_message(p)
        for name in MANUAL_GATE_NAMES:
            assert name in text

    def test_gate_checklist_marks_true(self) -> None:
        p = parse_payload(VALID)
        states = {"risk_ok": True, "trades_left": False}
        text = format_telegram_message(p, gate_states=states)
        assert "✅ risk_ok" in text
        assert "❌ trades_left" in text


class TestFormatDiscord:
    def test_no_markdown(self) -> None:
        p = parse_payload(VALID)
        text = format_discord_message(p)
        # No markdown bold/italic
        assert "*" not in text
        assert "`" not in text

    def test_mentions_telegram_is_sole_authority(self) -> None:
        p = parse_payload(VALID)
        text = format_discord_message(p)
        assert "Telegram" in text
        assert "read-only" in text.lower()

    def test_includes_all_fields(self) -> None:
        p = parse_payload(VALID)
        text = format_discord_message(p)
        assert p.signal_id in text
        assert "EURUSD" in text


class TestParseCallback:
    def test_accept(self) -> None:
        cb = parse_callback_data("accept:1c54f6c631e1fc3d:abcd1234")
        assert cb is not None
        assert cb.action == "accept"
        assert cb.signal_id == "1c54f6c631e1fc3d"
        assert cb.nonce == "abcd1234"
        assert cb.key == "accept:1c54f6c631e1fc3d:abcd1234"

    def test_reject(self) -> None:
        cb = parse_callback_data("reject:deadbeef00000000:12345678")
        assert cb is not None
        assert cb.action == "reject"

    def test_rejects_unknown_action(self) -> None:
        assert parse_callback_data("delete:abc12345:nonce1234") is None

    def test_rejects_too_few_parts(self) -> None:
        assert parse_callback_data("accept:abc12345") is None

    def test_rejects_non_hex_signal_id(self) -> None:
        assert parse_callback_data("accept:NOTHEX!!!:nonce1234") is None

    def test_rejects_short_nonce(self) -> None:
        assert parse_callback_data("accept:abc1234567890123:ab") is None

    def test_rejects_empty_signal_id(self) -> None:
        assert parse_callback_data("accept::nonce1234") is None

    def test_rejects_empty_data(self) -> None:
        assert parse_callback_data("") is None


class TestGateChecklist:
    def test_default_uses_question_marks(self) -> None:
        text = render_gate_checklist()
        for name in MANUAL_GATE_NAMES:
            assert "❔" in text
            assert name in text

    def test_mixed_states(self) -> None:
        states = {n: True for n in MANUAL_GATE_NAMES[:3]}
        text = render_gate_checklist(states)
        for n in MANUAL_GATE_NAMES[:3]:
            assert f"✅ {n}" in text
        for n in MANUAL_GATE_NAMES[3:]:
            assert f"❔ {n}" in text


class TestInlineKeyboard:
    def test_shape(self) -> None:
        kb = build_inline_keyboard("abc12345", "nonce1234")
        assert "inline_keyboard" in kb
        assert len(kb["inline_keyboard"]) == 1
        buttons = kb["inline_keyboard"][0]
        assert len(buttons) == 2
        assert buttons[0]["text"] == "✅ Accept"
        assert buttons[0]["callback_data"] == "accept:abc12345:nonce1234"
        assert buttons[1]["text"] == "❌ Reject"


# ---------------------------------------------------------------------------
# Telegram dispatcher
# ---------------------------------------------------------------------------


class TestTelegramDispatcherSend:
    def test_send_returns_message_id(self) -> None:
        async def run() -> int | None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            return await d.send_signal(parse_payload(VALID))
        msg_id = asyncio.run(run())
        assert msg_id == 1

    def test_send_retries_on_transient_failure(self) -> None:
        async def run() -> tuple[int, int]:
            tx = FakeTelegramTransport()
            tx.fail_n_times = 2  # fail twice, succeed on 3rd attempt
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=3, backoff_base_seconds=0.001,
            )
            msg_id = await d.send_signal(parse_payload(VALID))
            return msg_id, len(tx.sent)
        msg_id, sent_count = asyncio.run(run())
        assert msg_id == 1  # eventually succeeds
        assert sent_count == 1  # only the successful one recorded

    def test_send_exhausts_retries_and_returns_none(self) -> None:
        async def run() -> int | None:
            tx = FakeTelegramTransport()
            tx.fail_n_times = 99
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=3, backoff_base_seconds=0.001,
            )
            return await d.send_signal(parse_payload(VALID))
        msg_id = asyncio.run(run())
        assert msg_id is None

    def test_send_records_message_id_for_callback(self) -> None:
        async def run() -> int | None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            p = parse_payload(VALID)
            msg_id = await d.send_signal(p)
            assert d.get_message_id(p.signal_id) == msg_id
            return msg_id
        asyncio.run(run())

    def test_send_passes_inline_keyboard(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            await d.send_signal(parse_payload(VALID))
            sent = tx.sent[0]
            assert "reply_markup" in sent
            assert sent["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Accept"
        asyncio.run(run())


class TestTelegramDispatcherEdit:
    def test_edit_disables_buttons(self) -> None:
        async def run() -> bool:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            p = parse_payload(VALID)
            msg_id = await d.send_signal(p)
            ok = await d.edit_signal(msg_id, p, decision="accept", actor="456")
            assert ok is True
            assert len(tx.edits) == 1
            assert tx.edits[0]["reply_markup"] is None
            assert "ACCEPT" in tx.edits[0]["text"]
            return ok
        asyncio.run(run())

    def test_edit_invalid_decision_raises(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            with pytest.raises(ValueError, match="decision"):
                await d.edit_signal(1, parse_payload(VALID), decision="what", actor="x")
        asyncio.run(run())

    def test_edit_clears_message_id_cache(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            p = parse_payload(VALID)
            msg_id = await d.send_signal(p)
            assert d.get_message_id(p.signal_id) == msg_id
            await d.edit_signal(msg_id, p, decision="reject", actor="456")
            assert d.get_message_id(p.signal_id) is None
        asyncio.run(run())


class TestTelegramDispatcherCallback:
    def test_authorized_user_accepted(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456, 789},
                max_retries=2, backoff_base_seconds=0.001,
            )
            dec = await d.handle_callback("accept:1c54f6c631e1fc3d:nonce1234", 456)
            assert dec is not None
            assert dec.accepted is True
            assert dec.action == "accept"
            assert dec.actor == "456"
        asyncio.run(run())

    def test_unauthorized_user_rejected(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            dec = await d.handle_callback("accept:1c54f6c631e1fc3d:nonce1234", 999)
            assert dec is not None
            assert dec.accepted is False
            assert dec.reason == "user not allowed"
        asyncio.run(run())

    def test_malformed_callback_returns_zero_signal_id(self) -> None:
        async def run() -> None:
            tx = FakeTelegramTransport()
            d = TelegramDispatcher(
                tx, chat_id=123, allowed_user_ids={456},
                max_retries=2, backoff_base_seconds=0.001,
            )
            dec = await d.handle_callback("garbage", 456)
            assert dec is not None
            assert dec.accepted is False
            assert dec.reason == "malformed callback_data"


# ---------------------------------------------------------------------------
# Disabled / env factory
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_telegram_disabled_when_token_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        d = dispatcher_from_env()
        assert d.enabled is False

        async def run() -> None:
            msg_id = await d.send_signal(parse_payload(VALID))
            assert msg_id is None
        asyncio.run(run())

    def test_discord_disabled_when_url_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        m = mirror_from_env()
        assert m.enabled is False

        async def run() -> None:
            ok = await m.send_signal(parse_payload(VALID))
            assert ok is False
        asyncio.run(run())

    def test_telegram_enabled_when_token_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-not-real")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111,222")
        # We don't actually connect — just verify factory builds enabled dispatcher.
        d = dispatcher_from_env()
        # It builds a live transport that will fail to connect, but enabled flag is True.
        assert d.enabled is True
        assert d.allowed_user_ids == frozenset({111, 222})

    def test_telegram_factory_skips_non_int_allowlist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-not-real")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111,not-an-int,222")
        d = dispatcher_from_env()
        assert d.allowed_user_ids == frozenset({111, 222})


# ---------------------------------------------------------------------------
# Discord mirror
# ---------------------------------------------------------------------------


class TestDiscordMirror:
    def test_send_ok(self) -> None:
        async def run() -> bool:
            tx = FakeDiscordTransport()
            m = DiscordMirror(
                tx, webhook_url="http://discord.test/x",
                max_retries=2, backoff_base_seconds=0.001,
            )
            ok = await m.send_signal(parse_payload(VALID))
            assert ok is True
            assert len(tx.posts) == 1
            assert "EURUSD" in tx.posts[0]["content"]
            return ok
        asyncio.run(run())

    def test_send_retries_on_transient(self) -> None:
        async def run() -> bool:
            tx = FakeDiscordTransport()
            tx.fail_n_times = 2
            m = DiscordMirror(
                tx, webhook_url="http://discord.test/x",
                max_retries=3, backoff_base_seconds=0.001,
            )
            ok = await m.send_signal(parse_payload(VALID))
            assert ok is True
            assert len(tx.posts) == 1
            return ok
        asyncio.run(run())

    def test_send_exhausts_retries(self) -> None:
        async def run() -> bool:
            tx = FakeDiscordTransport()
            tx.fail_n_times = 99
            m = DiscordMirror(
                tx, webhook_url="http://discord.test/x",
                max_retries=3, backoff_base_seconds=0.001,
            )
            ok = await m.send_signal(parse_payload(VALID))
            assert ok is False
            return ok
        asyncio.run(run())

    def test_permanent_4xx_does_not_retry(self) -> None:
        """Permanent errors (e.g. 404) must NOT retry — they indicate config issues."""
        class _Perm4xx:
            def __init__(self) -> None:
                self.calls = 0

            async def post_webhook(self, *, url: str, content: str, timeout_seconds: float) -> int:
                self.calls += 1
                return 404

        async def run() -> int:
            tx = _Perm4xx()
            m = DiscordMirror(
                tx, webhook_url="http://discord.test/x",
                max_retries=5, backoff_base_seconds=0.001,
            )
            ok = await m.send_signal(parse_payload(VALID))
            assert ok is False
            return tx.calls
        calls = asyncio.run(run())
        assert calls == 1



    def test_429_retries(self) -> None:
        class _RateLimited:
            def __init__(self) -> None:
                self.calls = 0

            async def post_webhook(self, *, url: str, content: str, timeout_seconds: float) -> int:
                self.calls += 1
                if self.calls < 3:
                    return 429
                return 204

        async def run() -> tuple[bool, int]:
            tx = _RateLimited()
            m = DiscordMirror(
                tx, webhook_url="http://discord.test/x",
                max_retries=5, backoff_base_seconds=0.001,
            )
            ok = await m.send_signal(parse_payload(VALID))
            return ok, tx.calls
        ok, calls = asyncio.run(run())
        assert ok is True
        assert calls == 3

class TestAuditHooks:
    """Phase 02 exposes record_decision + record_edit_failure so Phase 03
    just wires a route handler. Verify they persist correct audit rows."""

    def _db_with_event_capture(self):
        from pathlib import Path
        import time
        from smc_bot_core.db import BotDB, init_db
        p = Path(f"output/test_audit_{int(time.time() * 1000000)}.db")
        init_db(p)
        return BotDB(p), p

    def _cleanup(self, p) -> None:
        try:
            p.unlink()
        except (FileNotFoundError, PermissionError):
            pass

    def test_record_decision_accept_writes_accept_row(self) -> None:
        from smc_bot_webhook.notify.telegram import TelegramDispatcher
        db, path = self._db_with_event_capture()
        try:
            TelegramDispatcher.record_decision(
                db, "1c54f6c631e1fc3d",
                decision="accept", actor="456", nonce="abcd1234",
            )
            event = db.latest_event("1c54f6c631e1fc3d")
            assert event is not None
            assert event["event_type"] == "accept"
            assert event["actor"] == "456"
            assert "accept" in event["payload"]
        finally:
            self._cleanup(path)

    def test_record_decision_reject_writes_reject_row(self) -> None:
        from smc_bot_webhook.notify.telegram import TelegramDispatcher
        db, path = self._db_with_event_capture()
        try:
            TelegramDispatcher.record_decision(
                db, "1c54f6c631e1fc3d",
                decision="reject", actor="456", nonce="abcd1234",
            )
            event = db.latest_event("1c54f6c631e1fc3d")
            assert event is not None
            assert event["event_type"] == "reject"
        finally:
            self._cleanup(path)

    def test_record_decision_invalid_decision_raises(self) -> None:
        from smc_bot_webhook.notify.telegram import TelegramDispatcher
        db, path = self._db_with_event_capture()
        try:
            with pytest.raises(ValueError, match="decision"):
                TelegramDispatcher.record_decision(
                    db, "abc",
                    decision="delete", actor="x", nonce="nonce1",
                )
        finally:
            self._cleanup(path)

    def test_record_edit_failure_writes_edit_failed_row(self) -> None:
        from smc_bot_webhook.notify.telegram import TelegramDispatcher
        db, path = self._db_with_event_capture()
        try:
            TelegramDispatcher.record_edit_failure(
                db, "1c54f6c631e1fc3d",
                actor="456", exc=RuntimeError("transport timeout"),
            )
            event = db.latest_event("1c54f6c631e1fc3d")
            assert event is not None
            assert event["event_type"] == "edit_failed"
            assert "transport timeout" in event["payload"]
            assert event["actor"] == "456"
        finally:
            self._cleanup(path)

    def test_record_decision_payload_is_json_with_actor_nonce(self) -> None:
        import json
        from smc_bot_webhook.notify.telegram import TelegramDispatcher
        db, path = self._db_with_event_capture()
        try:
            TelegramDispatcher.record_decision(
                db, "sig",
                decision="accept", actor="u1", nonce="n2",
            )
            event = db.latest_event("sig")
            assert event is not None
            parsed = json.loads(event["payload"])
            assert parsed["decision"] == "accept"
            assert parsed["actor"] == "u1"
            assert parsed["nonce"] == "n2"
        finally:
            self._cleanup(path)

