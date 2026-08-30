"""Integration tests for the FastAPI webhook (Phase 01 acceptance)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# TradingView IP we use to simulate the source.
TV_IP = "52.89.214.238"


def _client() -> TestClient:
    """Build a TestClient with a temp DB and a known URL secret."""
    tmp_dir = Path("output")
    tmp_dir.mkdir(exist_ok=True)
    # Per-test override: isolate DB by patching settings.
    os.environ["SMC_WEBHOOK_TOKEN"] = "test-secret-do-not-use-in-prod"
    from smc_bot_core.db import BotDB
    from smc_bot_webhook.security import SecurityConfig
    from smc_bot_webhook.server import AppSettings, create_app

    db_path = Path(f"output/test_bot_{int(time.time() * 1000000)}.db")
    db = BotDB(db_path)
    settings = AppSettings(
        url_secret="test-secret-do-not-use-in-prod",
        db_path=db_path,
        security=SecurityConfig(
            url_secret="test-secret-do-not-use-in-prod",
            rate_limit_per_min=1000,  # generous for tests
        ),
        # TestClient uses "testclient" as request.client.host; treat X-Forwarded-For as trusted.
        trusted_proxy=True,
    )
    app = create_app(settings=settings, db=db)
    return TestClient(app), db, db_path
VALID_BODY = (
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


class TestHealthz:
    def test_healthz_returns_ok(self) -> None:
        client, _db, db_path = _client()
        try:
            resp = client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        finally:
            _cleanup(db_path)


class TestAuth:
    def test_rejects_missing_token(self) -> None:
        client, _db, db_path = _client()
        try:
            resp = client.post(
                "/webhooks/tradingview",
                content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 401
        finally:
            _cleanup(db_path)

    def test_rejects_bad_token(self) -> None:
        client, _db, db_path = _client()
        try:
            resp = client.post(
                "/webhooks/tradingview?token=wrong",
                content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 401
        finally:
            _cleanup(db_path)

    def test_rejects_disallowed_ip(self) -> None:
        client, _db, db_path = _client()
        try:
            resp = client.post(
                URL,
                content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": "1.2.3.4"},
            )
            assert resp.status_code == 401
        finally:
            _cleanup(db_path)


class TestValidation:
    def test_rejects_malformed_body(self) -> None:
        client, _db, db_path = _client()
        try:
            resp = client.post(
                URL,
                content="not a valid payload",
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 400
        finally:
            _cleanup(db_path)

    def test_rejects_oversized_body(self) -> None:
        client, _db, db_path = _client()
        try:
            huge = "X" * 5000  # > 4 KB cap
            resp = client.post(
                URL,
                content=huge,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 413
        finally:
            _cleanup(db_path)


class TestPersistenceAndIdempotency:
    def test_first_valid_returns_202_and_persists(self) -> None:
        client, db, db_path = _client()
        try:
            resp = client.post(
                URL,
                content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            body = resp.json()
            assert body["is_new"] is True
            assert len(body["signal_id"]) == 16
            assert db.count_alerts() == 1
            stored = db.get_alert_by_signal_id(body["signal_id"])
            assert stored is not None
            assert stored["symbol"] == "EURUSD"
            assert stored["tf"] == "M15"
            assert stored["state"] == "chart-qualified"
            assert stored["dedupe_count"] == 1
        finally:
            _cleanup(db_path)

    def test_duplicate_signal_id_returns_200_no_new_row(self) -> None:
        client, db, db_path = _client()
        try:
            r1 = client.post(
                URL, content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert r1.status_code == 202
            r2 = client.post(
                URL, content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert r2.status_code == 200
            assert r2.json()["is_new"] is False
            assert db.count_alerts() == 1
            stored = db.get_alert_by_signal_id(r1.json()["signal_id"])
            assert stored["dedupe_count"] == 2
        finally:
            _cleanup(db_path)

    def test_distinct_bar_times_create_distinct_rows(self) -> None:
        client, db, db_path = _client()
        try:
            for bt in (1700000000, 1700000900, 1700001800):
                body = (
                    "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
                    f"|level=1.10000|bar_time={bt}|ob_id=42"
                    "|state=chart-qualified|reason=ok"
                )
                resp = client.post(
                    URL, content=body,
                    headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
                )
                assert resp.status_code == 202
            assert db.count_alerts() == 3
        finally:
            _cleanup(db_path)

    def test_json_payload_accepted(self) -> None:
        client, db, db_path = _client()
        try:
            obj = (
                '{"prefix":"SMC","version":"v1","event":"watch",'
                '"symbol":"EURUSD","tf":"15","dir":"long",'
                '"level":1.1,"bar_time":1700000000,'
                '"ob_id":-1,"bos_id":-1,'
                '"state":"watch","reason":"spread_too_wide"}'
            )
            resp = client.post(
                URL, content=obj,
                headers={"content-type": "application/json", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 202
            assert db.count_alerts() == 1
        finally:
            _cleanup(db_path)

    def test_latency_under_500ms_local(self) -> None:
        client, _db, db_path = _client()
        try:
            t0 = time.perf_counter()
            resp = client.post(
                URL, content=VALID_BODY,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code in (200, 202)
            # Plan acceptance: <500ms local.
            assert elapsed_ms < 500, f"webhook too slow: {elapsed_ms:.1f}ms"
        finally:
            _cleanup(db_path)


class TestRateLimit:
    def test_rate_limit_returns_429(self) -> None:
        # Override settings to a very small limit just for this test.
        os.environ["SMC_WEBHOOK_TOKEN"] = "test-secret-do-not-use-in-prod"
        from smc_bot_core.db import BotDB
        from smc_bot_webhook.security import SecurityConfig
        from smc_bot_webhook.server import AppSettings, create_app

        db_path = Path(f"output/test_bot_rl_{int(time.time() * 1000000)}.db")
        db = BotDB(db_path)
        settings = AppSettings(
            url_secret="test-secret-do-not-use-in-prod",
            db_path=db_path,
            security=SecurityConfig(
                url_secret="test-secret-do-not-use-in-prod",
                rate_limit_per_min=2,
            ),
            trusted_proxy=True,
        )
        app = create_app(settings=settings, db=db)
        client = TestClient(app)
        try:
            for i in range(2):
                body = (
                    "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
                    f"|level=1.10000|bar_time={1700000000 + i}"
                    "|state=chart-qualified|reason=ok"
                )
                resp = client.post(
                    URL, content=body,
                    headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
                )
                assert resp.status_code == 202, f"req {i} unexpected {resp.status_code}"
            body = (
                "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
                "|level=1.10000|bar_time=1700000999"
                "|state=chart-qualified|reason=ok"
            )
            resp = client.post(
                URL, content=body,
                headers={"content-type": "text/plain", "x-forwarded-for": TV_IP},
            )
            assert resp.status_code == 429
        finally:
            _cleanup(db_path)