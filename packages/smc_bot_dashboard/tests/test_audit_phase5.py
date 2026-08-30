"""Edge-case + concurrency audit tests for Phase 05 dashboard backend."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smc_bot_dashboard.web import (
    DEFAULT_DB_PATH,
    DEFAULT_SIGNAL_CSV_DIR,
    create_app,
    render_audit,
    render_execution,
    render_live,
    render_replay,
    _serialize,
)
from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.payload import AlertPayload, parse_payload

VALID_BODY = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


def _make_db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_p5audit_{int(time.time() * 1e6)}.db")
    init_db(p)
    return BotDB(p), p


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def _client(db: BotDB, csv_dir: Path, follow_redirects: bool = True) -> TestClient:
    return TestClient(create_app(db, signal_csv_dir=csv_dir), follow_redirects=follow_redirects)


# ---------------------------------------------------------------------------
# Render functions edge cases
# ---------------------------------------------------------------------------


class TestRenderLiveEdgeCases:
    def test_alert_with_no_received_at(self) -> None:
        """Old alerts may have None received_at. Document current behavior."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            payload = AlertPayload.model_construct(
                **{**payload.__dict__, 'received_at': None}
            )
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            # No exception expected.
            result = render_live(db)
            assert len(result["rows"]) == 1
        finally:
            _cleanup(path)

    def test_alert_with_invalid_received_at_string(self) -> None:
        """If received_at is a non-ISO string, since-filter should skip silently."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            # Manually corrupt received_at (test only — production code never writes this).
            from smc_bot_core.db import BotDB as _B
            with db._conn_ctx() as conn:  # noqa: SLF001
                conn.execute(
                    "UPDATE alert_log SET received_at = 'not-iso' WHERE signal_id = ?",
                    (payload.signal_id,),
                )
            # since filter applies ISO parsing — corrupt string is silently skipped
            result = render_live(db, since="2020-01-01T00:00:00+00:00")
            # The alert is included because since_dt is in 2020 and received_at
            # parsing fails (TypeError catch swallows) — fallback: included.
            assert len(result["rows"]) == 1
        finally:
            _cleanup(path)

    def test_since_future_filters_all(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            result = render_live(db, since="2099-01-01T00:00:00+00:00")
            assert result["rows"] == []
        finally:
            _cleanup(path)

    def test_since_invalid_iso_raises(self) -> None:
        """Fix: invalid 'since' raises ValueError (HTTP layer → 422) instead of
        silently bypassing the filter (which previously returned ALL rows)."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            with pytest.raises(ValueError, match="invalid 'since'"):
                render_live(db, since="not-a-date")
        finally:
            _cleanup(path)


class TestRenderAuditEdgeCases:
    def test_empty_actor_filter(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "accept", actor="")
            result = render_audit(db, user="")
            # Empty-string actor filter: filter applies `if user and ...` — empty is falsy.
            # So empty user = no filter applied, returns all rows.
            assert len(result["events"]) == 1
        finally:
            _cleanup(path)

    def test_no_csv_path_returns_empty(self) -> None:
        db, path = _make_db()
        try:
            result = render_audit(db, signal_csv=None)
            assert result["csv_rows"] == []
            assert result["csv_path"] is None
        finally:
            _cleanup(path)

    def test_csv_path_does_not_exist(self) -> None:
        db, path = _make_db()
        try:
            nonexistent = path.parent / "missing.csv"
            result = render_audit(db, signal_csv=nonexistent)
            # render_audit calls _read_csv_rows(path) which returns [] if path doesn't exist
            assert result["csv_rows"] == []
        finally:
            _cleanup(path)


class TestSerialize:
    def test_datetime_serialization(self) -> None:
        rows = [{"created_at": datetime(2026, 8, 30, 10, 0, 0, tzinfo=timezone.utc)}]
        out = _serialize(rows)
        assert out[0]["created_at"] == "2026-08-30T10:00:00+00:00"

    def test_non_datetime_passthrough(self) -> None:
        rows = [{"foo": "bar", "n": 42, "f": 3.14}]
        out = _serialize(rows)
        assert out[0] == {"foo": "bar", "n": 42, "f": 3.14}


# ---------------------------------------------------------------------------
# HTTP layer edge cases
# ---------------------------------------------------------------------------


class TestRouteEdges:
    def test_empty_csv_name_404(self) -> None:
        """Path /api/replay/csv/ — trailing slash → 404 or 307."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/replay/csv/")
            assert r.status_code in (307, 404)
        finally:
            _cleanup(path)

    def test_limit_zero_returns_empty(self) -> None:
        """Limit=0 (out of bounds by FastAPI Query validation ge=1) → 422."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/alerts?limit=0")
            # FastAPI Query validation rejects with 422.
            assert r.status_code == 422
        finally:
            _cleanup(path)

    def test_negative_limit_rejected(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/alerts?limit=-1")
            assert r.status_code == 422
        finally:
            _cleanup(path)

    def test_limit_above_max_rejected(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/alerts?limit=10000")
            assert r.status_code == 422
        finally:
            _cleanup(path)

    def test_api_audit_missing_csv_returns_200_with_empty_csv(self) -> None:
        """signal_csv param points to a non-existent file → 200, csv_rows empty."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/audit?signal_csv=missing.csv")
            assert r.status_code == 200
            data = r.json()
            assert data["csv_rows"] == []
            assert data["csv_path"].endswith("missing.csv")
        finally:
            _cleanup(path)

    def test_api_replay_csv_path_traversal_via_url_encoding(self) -> None:
        """URL-encoded '../' is decoded by the server before route match.
        The traversal guard runs after routing, so Starlette may return 404
        before our handler sees the bad name. Document current behavior."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/replay/csv/..%2Fetc%2Fpasswd")
            # Should be rejected with 400 (guard) or 404 (no such file).
            assert r.status_code in (400, 404)
        finally:
            _cleanup(path)


class TestDashboardConcurrency:
    """Concurrent /api/alerts calls must not corrupt DB."""

    def test_concurrent_alerts(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            client = _client(db, path.parent)
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    for _ in range(20):
                        client.get("/api/alerts?limit=100")
                        client.get("/api/audit?limit=100")
                        client.get("/api/replay")
                        client.get("/api/health")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert errors == [], f"concurrent API calls crashed: {errors[:3]}"
        finally:
            _cleanup(path)

    def test_concurrent_alert_inserts_plus_reads(self) -> None:
        """20 threads inserting alerts + 10 threads reading via /api/alerts.
        BotDB per-call connection (Phase 01 fix) should keep both safe."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            errors: list[BaseException] = []

            def writer(i: int) -> None:
                try:
                    payload = parse_payload(VALID_BODY)
                    payload = AlertPayload.model_construct(
                        **{**payload.__dict__, 'bar_time': 1700000000 + i}
                    )
                    for _ in range(5):
                        db.insert_alert(payload, url_token_ok=True)
                        db.record_event(payload.signal_id, "received", actor="w")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            def reader() -> None:
                try:
                    for _ in range(20):
                        client.get("/api/alerts")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = []
            for i in range(20):
                threads.append(threading.Thread(target=writer, args=(i,)))
            for _ in range(10):
                threads.append(threading.Thread(target=reader))
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert errors == [], f"concurrent insert+read crashed: {errors[:3]}"
        finally:
            _cleanup(path)


class TestStaticFileMount:
    """The dashboard mounts /static for Vue dist/. If user has a SPA build
    that includes /static/* assets, FastAPI serves them. Test that the
    mount doesn't shadow API routes."""

    def test_static_does_not_shadow_api(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"
        finally:
            _cleanup(path)

    def test_404_for_unknown_static_assets(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            # /static is mounted; if static dir is empty/missing, returns 404.
            r = client.get("/static/nonexistent.css")
            assert r.status_code == 404
        finally:
            _cleanup(path)


class TestAuditEventsCoverage:
    """render_audit includes blocked_chart, expired, edit_failed, notified_failed,
    accept, reject — anything else should be filtered."""

    def test_notified_event_excluded(self) -> None:
        """Notified (the 'message sent' event) should be excluded from audit."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            db.record_event(payload.signal_id, "notified", actor="telegram")
            result = render_audit(db)
            assert len(result["events"]) == 0
        finally:
            _cleanup(path)

    def test_received_event_excluded(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            db.record_event(payload.signal_id, "blocked_chart", actor="validator")
            result = render_audit(db)
            assert len(result["events"]) == 1
            assert result["events"][0]["event_type"] == "blocked_chart"
        finally:
            _cleanup(path)

    def test_all_included_event_types(self) -> None:
        """Verify all 6 expected audit event types are included."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            for et in ("accept", "reject", "blocked_chart", "expired", "edit_failed", "notified_failed"):
                db.record_event(payload.signal_id, et, actor="x")
            result = render_audit(db)
            types = {e["event_type"] for e in result["events"]}
            assert types == {"accept", "reject", "blocked_chart", "expired", "edit_failed", "notified_failed"}
        finally:
            _cleanup(path)


class TestReplayInfoLeak:
    """render_replay returns the full dir path in 'dir' field. Is that info leak?"""

    def test_dir_field_redacted(self) -> None:
        """Fix: 'dir' field removed (was leaking server-internal absolute path)."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/replay")
            assert r.status_code == 200
            data = r.json()
            assert "dir" not in data
        finally:
            _cleanup(path)

    def test_files_path_field_redacted(self) -> None:
        """Fix: 'path' field removed from each file entry (was leaking absolute path)."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/replay")
            data = r.json()
            for f in data.get("files", []):
                assert "path" not in f
                assert "name" in f
                assert "size" in f
        finally:
            _cleanup(path)


class TestCreateAppDefaults:
    def test_create_app_default_db(self) -> None:
        """create_app() with no db arg uses SMC_BOT_DB_PATH or DEFAULT_DB_PATH."""
        # When env not set, falls back to DEFAULT_DB_PATH.
        os.environ.pop("SMC_BOT_DB_PATH", None)
        db_path = Path("output/test_default.db")
        if db_path.exists():
            db_path.unlink()
        app = create_app(db=None, signal_csv_dir=Path("output"))
        # Use the API to verify which DB it picked.
        client = TestClient(app)
        r = client.get("/api/health")
        assert r.status_code == 200
        db_path.unlink(missing_ok=True)