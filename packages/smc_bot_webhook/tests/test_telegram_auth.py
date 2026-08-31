"""Tests for Phase 01 — Telegram callback secret header enforcement.

Closes audit finding C2: /telegram/callback and /telegram/command
previously accepted any caller with the webhook URL secret. They now
require the ``X-Telegram-Bot-Api-Secret-Token`` header to match
``TELEGRAM_CALLBACK_SECRET`` (or fail-closed if not configured).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_bot_webhook.security import SecurityConfig, check_telegram_secret
from smc_bot_webhook.server import AppSettings, create_app


WEBHOOK_SECRET = "test-webhook-secret-do-not-use-in-prod-x" + "x" * 8
TG_SECRET = "test-telegram-secret-do-not-use-in-prod-" + "y" * 8


def _make_app(
    tg_secret: str | None = TG_SECRET,
    db_path: Path | None = None,
) -> tuple[TestClient, Path]:
    """Build a TestClient with telegram auth configured."""
    db_path = db_path or Path(f"output/test_tg_auth_{os.urandom(4).hex()}.db")
    settings = AppSettings(
        url_secret=WEBHOOK_SECRET,
        db_path=db_path,
        security=SecurityConfig(url_secret=WEBHOOK_SECRET),
        trusted_proxy=True,
        telegram_callback_secret=tg_secret,
    )
    app = create_app(settings=settings)
    return TestClient(app), db_path
def _cleanup(path: Path) -> None:
    """Best-effort delete. Windows holds SQLite file lock after TestClient
    closes; ignore PermissionError on this platform."""
    try:
        path.unlink()
    except (FileNotFoundError, PermissionError):
        pass


# ---------------------------------------------------------------------------
# check_telegram_secret (pure function)
# ---------------------------------------------------------------------------


class TestCheckTelegramSecret:
    def test_empty_provided_returns_false(self) -> None:
        assert check_telegram_secret("", TG_SECRET) is False
        assert check_telegram_secret(None, TG_SECRET) is False

    def test_empty_expected_returns_false(self) -> None:
        # fail-closed: server with no secret cannot match any provided.
        assert check_telegram_secret(TG_SECRET, "") is False
        assert check_telegram_secret(TG_SECRET, None) is False

    def test_match_returns_true(self) -> None:
        assert check_telegram_secret(TG_SECRET, TG_SECRET) is True

    def test_mismatch_returns_false(self) -> None:
        assert check_telegram_secret("wrong", TG_SECRET) is False

    def test_constant_time_compare_uses_hmac(self) -> None:
        # hmac.compare_digest handles non-equal-length strings safely.
        assert check_telegram_secret("short", TG_SECRET) is False
        assert check_telegram_secret(TG_SECRET[:10], TG_SECRET) is False


# ---------------------------------------------------------------------------
# /telegram/callback route
# ---------------------------------------------------------------------------


class TestCallbackAuth:
    def test_rejects_missing_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post("/telegram/callback", json={"callback_data": "test"})
            assert r.status_code == 401
            assert "telegram" in r.json()["detail"].lower()
        finally:
            _cleanup(db_path)

    def test_rejects_wrong_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post(
                "/telegram/callback",
                json={"callback_data": "test"},
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            )
            assert r.status_code == 401
        finally:
            _cleanup(db_path)

    def test_rejects_empty_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post(
                "/telegram/callback",
                json={"callback_data": "test"},
                headers={"X-Telegram-Bot-Api-Secret-Token": ""},
            )
            assert r.status_code == 401
        finally:
            _cleanup(db_path)

    def test_accepts_correct_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post(
                "/telegram/callback",
                json={"callback_data": "malformed-but-auth-passes"},
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
            )
            # 200 (ignored) or 400 (malformed) — both prove auth passed.
            assert r.status_code in (200, 400, 404), f"got {r.status_code}: {r.json()}"
            assert r.status_code != 401
        finally:
            _cleanup(db_path)


# ---------------------------------------------------------------------------
# /telegram/command route
# ---------------------------------------------------------------------------


class TestCommandAuth:
    def test_rejects_missing_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post("/telegram/command", json={"text": "/ack risk_ok"})
            assert r.status_code == 401
        finally:
            _cleanup(db_path)

    def test_rejects_wrong_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post(
                "/telegram/command",
                json={"text": "/ack risk_ok"},
                headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
            )
            assert r.status_code == 401
        finally:
            _cleanup(db_path)

    def test_accepts_correct_header(self) -> None:
        client, db_path = _make_app()
        try:
            r = client.post(
                "/telegram/command",
                json={"text": "/ack risk_ok", "from_user_id": 0},
                headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
            )
            # 200 (handled=False for user 0 not in allowlist) or similar —
            # anything but 401 means auth passed.
            assert r.status_code != 401
        finally:
            _cleanup(db_path)


# ---------------------------------------------------------------------------
# Fail-closed when no secret configured
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_callback_rejects_when_no_secret(self) -> None:
        client, db_path = _make_app(tg_secret=None)
        try:
            r = client.post(
                "/telegram/callback",
                json={"callback_data": "test"},
                headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
            )
            assert r.status_code == 401
            assert "not configured" in r.json()["detail"]
        finally:
            _cleanup(db_path)

    def test_command_rejects_when_no_secret(self) -> None:
        client, db_path = _make_app(tg_secret=None)
        try:
            r = client.post(
                "/telegram/command",
                json={"text": "/ack risk_ok"},
                headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
            )
            assert r.status_code == 401
        finally:
            _cleanup(db_path)


# ---------------------------------------------------------------------------
# Runtime guard — AppSettings.from_env
# ---------------------------------------------------------------------------


class TestAppSettingsGuard:
    def test_refuses_when_bot_token_set_without_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_WEBHOOK_TOKEN", WEBHOOK_SECRET)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:bot-token")
        monkeypatch.delenv("TELEGRAM_CALLBACK_SECRET", raising=False)
        with pytest.raises(RuntimeError) as exc_info:
            AppSettings.from_env()
        assert "TELEGRAM_CALLBACK_SECRET" in str(exc_info.value)

    def test_refuses_short_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_WEBHOOK_TOKEN", WEBHOOK_SECRET)
        monkeypatch.setenv("TELEGRAM_CALLBACK_SECRET", "short")
        with pytest.raises(RuntimeError) as exc_info:
            AppSettings.from_env()
        assert "too short" in str(exc_info.value)

    def test_accepts_when_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_WEBHOOK_TOKEN", WEBHOOK_SECRET)
        monkeypatch.setenv("TELEGRAM_CALLBACK_SECRET", TG_SECRET)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        s = AppSettings.from_env()
        assert s.telegram_callback_secret == TG_SECRET

    def test_accepts_when_neither_telegram_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMC_WEBHOOK_TOKEN", WEBHOOK_SECRET)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CALLBACK_SECRET", raising=False)
        s = AppSettings.from_env()
        assert s.telegram_callback_secret is None
