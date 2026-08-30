"""Integration tests for webhook -> background dispatch -> signal_events audit."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_bot_webhook.notify.discord import FakeDiscordTransport
from smc_bot_webhook.notify.telegram import FakeTelegramTransport
from smc_bot_core.db import BotDB
from smc_bot_webhook.security import SecurityConfig
from smc_bot_webhook.server import AppSettings, create_app

TV_IP = "52.89.214.238"
VALID = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)
URL = "/webhooks/tradingview?token=test-secret-do-not-use-in-prod"


def _cleanup(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _client_with_dispatch(
    *,
    tg_fail_n: int = 0,
    dc_fail_n: int = 0,
) -> tuple[TestClient, BotDB, FakeTelegramTransport, FakeDiscordTransport, Path]:
    tg_tx = FakeTelegramTransport()
    dc_tx = FakeDiscordTransport()
    tg_tx.fail_n_times = tg_fail_n
    dc_tx.fail_n_times = dc_fail_n

    db_path = Path(f"output/test_dispatch_{int(time.time() * 1000000)}.db")
    db = BotDB(db_path)
    settings = AppSettings(
        url_secret="test-secret-do-not-use-in-prod",
        db_path=db_path,
        security=SecurityConfig(
            url_secret="test-secret-do-not-use-in-prod",
            rate_limit_per_min=1000,
        ),
        trusted_proxy=True,
    )
    # Build REAL dispatchers wrapping our fakes.
    from smc_bot_webhook.notify.telegram import TelegramDispatcher
    from smc_bot_webhook.notify.discord import DiscordMirror
    real_dispatcher = TelegramDispatcher(
        tg_tx, chat_id=12345, allowed_user_ids={456},
        max_retries=3, backoff_base_seconds=0.001,
    )
    real_mirror = DiscordMirror(
        dc_tx, webhook_url="http://discord.test/x",
        max_retries=3, backoff_base_seconds=0.001,
    )
    app = create_app(
        settings=settings,
        db=db,
        dispatcher=real_dispatcher,
        mirror=real_mirror,
    )
    return TestClient(app), db, tg_tx, dc_tx, db_path



class TestDispatchHappyPath:
    def test_new_alert_records_received_and_notified(self) -> None:
        client, db, tg, dc, db_path = _client_with_dispatch()
        try:
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            signal_id = resp.json()["signal_id"]
            # TestClient runs BackgroundTasks before returning from .post();
            # events should already be persisted by the time we query here.
            events = db.list_recent_events(limit=10)
            types = [e["event_type"] for e in events if e["signal_id"] == signal_id]
            assert "received" in types
            assert "notified" in types
            assert len(tg.sent) == 1
            assert len(dc.posts) == 1
        finally:
            _cleanup(db_path)

    def test_healthz_reports_dispatcher_state(self) -> None:
        client, _db, _tg, _dc, db_path = _client_with_dispatch()
        try:
            resp = client.get("/healthz")
            assert resp.status_code == 200
            body = resp.json()
            assert body["telegram"] is True
            assert body["discord"] is True
        finally:
            _cleanup(db_path)

    def test_duplicate_alert_does_not_re_dispatch(self) -> None:
        client, db, tg, dc, db_path = _client_with_dispatch()
        try:
            r1 = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert r1.status_code == 202
            r2 = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert r2.status_code == 200
            # Only ONE Telegram send (the first one — duplicate doesn't re-dispatch).
            assert len(tg.sent) == 1
            assert len(dc.posts) == 1
        finally:
            _cleanup(db_path)


class TestDispatchFailure:
    def test_telegram_failure_records_notified_failed(self) -> None:
        client, db, _tg, _dc, db_path = _client_with_dispatch(tg_fail_n=99)
        try:
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            signal_id = resp.json()["signal_id"]
            events = db.list_recent_events(limit=20)
            types = [e["event_type"] for e in events if e["signal_id"] == signal_id]
            assert "received" in types
            assert "notified_failed" in types
            # Discord still succeeded.
            assert db.count_failed_notifications() >= 1
        finally:
            _cleanup(db_path)

    def test_discord_failure_records_mirror_failed(self) -> None:
        client, db, _tg, _dc, db_path = _client_with_dispatch(dc_fail_n=99)
        try:
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            signal_id = resp.json()["signal_id"]
            events = db.list_recent_events(limit=20)
            types = [e["event_type"] for e in events if e["signal_id"] == signal_id]
            assert "mirror_failed" in types
        finally:
            _cleanup(db_path)

    def test_both_failures_recorded_independently(self) -> None:
        client, db, _tg, _dc, db_path = _client_with_dispatch(tg_fail_n=99, dc_fail_n=99)
        try:
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            signal_id = resp.json()["signal_id"]
            events = db.list_recent_events(limit=20)
            types = [e["event_type"] for e in events if e["signal_id"] == signal_id]
            assert "notified_failed" in types
            assert "mirror_failed" in types
        finally:
            _cleanup(db_path)

    def test_db_failure_does_not_break_webhook(self) -> None:
        """If recording 'received' fails, the alert is still persisted and 202 returned."""
        client, db, tg, dc, db_path = _client_with_dispatch()
        try:
            original_record = db.record_event

            def broken_record(*args, **kwargs):
                raise RuntimeError("simulated DB failure")

            db.record_event = broken_record  # type: ignore[method-assign]
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            assert len(tg.sent) == 1
            assert len(dc.posts) == 1
            db.record_event = original_record  # type: ignore[method-assign]
        finally:
            _cleanup(db_path)


class TestDispatchDisabled:
    def test_telegram_disabled_records_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        # Build app WITHOUT injecting dispatcher/mirror — factory from env kicks in.
        db_path = Path(f"output/test_dispatch_disabled_{int(time.time() * 1000000)}.db")
        db = BotDB(db_path)
        try:
            settings = AppSettings(
                url_secret="test-secret-do-not-use-in-prod",
                db_path=db_path,
                security=SecurityConfig(
                    url_secret="test-secret-do-not-use-in-prod",
                    rate_limit_per_min=1000,
                ),
                trusted_proxy=True,
            )
            app = create_app(settings=settings, db=db)
            client = TestClient(app)
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            signal_id = resp.json()["signal_id"]
            events = db.list_recent_events(limit=20)
            types = [e["event_type"] for e in events if e["signal_id"] == signal_id]
            assert "received" in types
            assert "notified_skipped" in types
            # healthz reports disabled
            h = client.get("/healthz")
            assert h.json()["telegram"] is False
            assert h.json()["discord"] is False
        finally:
            _cleanup(db_path)


class TestDispatchLatency:
    def test_webhook_returns_quickly_with_background_dispatch(self) -> None:
        client, _db, _tg, _dc, db_path = _client_with_dispatch()
        try:
            t0 = time.perf_counter()
            resp = client.post(
                URL, content=VALID,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 202
            # Background dispatch should not block. Even with retries the
            # webhook itself returns fast.
            assert elapsed_ms < 1000, f"webhook took {elapsed_ms:.0f}ms"
        finally:
            _cleanup(db_path)