"""Tests for Phase 05 FastAPI dashboard backend + JSON API + SSR pages."""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot.dashboard.web import (
    DEFAULT_DB_PATH,
    create_app,
    render_audit,
    render_execution,
    render_live,
    render_replay,
)
from bot.storage.db import BotDB, init_db
from bot.webhook.payload import parse_payload

VALID_BODY = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


def _make_db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_dashboard_{int(time.time() * 1e6)}.db")
    init_db(p)
    return BotDB(p), p


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def _client(db: BotDB, csv_dir: Path, follow_redirects: bool = True) -> TestClient:
    app = create_app(db, signal_csv_dir=csv_dir)
    return TestClient(app, follow_redirects=follow_redirects)


# ---------------------------------------------------------------------------
# Render functions (pure)
# ---------------------------------------------------------------------------


class TestRenderLive:
    def test_empty_db_returns_empty_rows(self) -> None:
        db, path = _make_db()
        try:
            result = render_live(db)
            assert result == {"rows": []}
        finally:
            _cleanup(path)

    def test_one_alert_no_event(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook:127.0.0.1")
            result = render_live(db)
            assert len(result["rows"]) == 1
            row = result["rows"][0]
            assert row["signal_id"] == payload.signal_id
            assert row["decision"] == ""
            assert row["state"] == "chart-qualified"
            assert row["symbol"] == "EURUSD"
        finally:
            _cleanup(path)

    def test_alert_with_accept_decision(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            db.record_event(payload.signal_id, "accept", actor="tester1")
            result = render_live(db)
            row = result["rows"][0]
            assert row["decision"] == "accept"
            assert row["decision_actor"] == "tester1"
        finally:
            _cleanup(path)

    def test_filter_by_state(self) -> None:
        db, path = _make_db()
        try:
            from datetime import datetime, timezone
            from bot.webhook.payload import AlertPayload
            p1 = parse_payload(VALID_BODY)
            p2 = parse_payload(VALID_BODY.replace("state=chart-qualified", "state=watch"))
            # Force unique bar_time so both rows have distinct signal_ids.
            p2 = AlertPayload.model_construct(
                prefix=p2.prefix, version=p2.version,
                event=p2.event, symbol=p2.symbol, tf=p2.tf,
                dir=p2.dir, level=p2.level,
                bar_time=p1.bar_time + 1,
                ob_id=p2.ob_id, bos_id=p2.bos_id,
                state=p2.state, reason=p2.reason,
                received_at=datetime.now(timezone.utc), raw_payload=p2.raw_payload,
            )
            db.insert_alert(p1, url_token_ok=True)
            db.insert_alert(p2, url_token_ok=True)
            db.record_event(p1.signal_id, "received", actor="w")
            db.record_event(p2.signal_id, "received", actor="w")
            result = render_live(db, state="watch")
            assert len(result["rows"]) == 1
            assert result["rows"][0]["state"] == "watch"
        finally:
            _cleanup(path)

    def test_filter_by_since(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="w")
            result = render_live(db, since="2099-01-01T00:00:00+00:00")
            assert result["rows"] == []
            result = render_live(db, since="2020-01-01T00:00:00+00:00")
            assert len(result["rows"]) == 1
        finally:
            _cleanup(path)

    def test_limit_respected(self) -> None:
        db, path = _make_db()
        try:
            from datetime import datetime, timezone
            from bot.webhook.payload import AlertPayload
            for i in range(5):
                payload = parse_payload(VALID_BODY)
                # Force unique signal_id by varying bar_time.
                payload = AlertPayload.model_construct(
                    prefix=payload.prefix, version=payload.version,
                    event=payload.event, symbol=payload.symbol, tf=payload.tf,
                    dir=payload.dir, level=payload.level,
                    bar_time=1700000000 + i,
                    ob_id=payload.ob_id, bos_id=payload.bos_id,
                    state=payload.state, reason=payload.reason,
                    received_at=datetime.now(timezone.utc), raw_payload=payload.raw_payload,
                )
                db.insert_alert(payload, url_token_ok=True)
                db.record_event(payload.signal_id, "received", actor="w")
            result = render_live(db, limit=3)
            assert len(result["rows"]) == 3
        finally:
            _cleanup(path)


class TestRenderExecution:
    def test_stub_returns_note(self) -> None:
        db, path = _make_db()
        try:
            result = render_execution(db)
            assert "rows" in result
            assert "note" in result
            assert "Phase 06" in result["note"]
        finally:
            _cleanup(path)


class TestRenderReplay:
    def test_empty_dir_returns_empty_files(self, tmp_path: Path) -> None:
        result = render_replay(tmp_path)
        assert result == {"files": [], "dir": str(tmp_path)}

    def test_lists_signals_csv(self, tmp_path: Path) -> None:
        (tmp_path / "signals_a.csv").write_text("a,b\n1,2\n")
        (tmp_path / "signals_b.csv").write_text("a,b\n3,4\n")
        (tmp_path / "other.csv").write_text("ignored\n")
        result = render_replay(tmp_path)
        names = [f["name"] for f in result["files"]]
        assert "signals_a.csv" in names
        assert "signals_b.csv" in names
        assert "other.csv" not in names
        assert result["dir"] == str(tmp_path)


class TestRenderAudit:
    def test_empty_db_returns_empty_events(self) -> None:
        db, path = _make_db()
        try:
            result = render_audit(db)
            assert result["events"] == []
            assert result["csv_rows"] == []
        finally:
            _cleanup(path)

    def test_filter_by_decision(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            db.record_event(payload.signal_id, "accept", actor="tester1")
            db.record_event(payload.signal_id, "notified_failed", actor="telegram")
            result = render_audit(db, decision="accept")
            assert len(result["events"]) == 1
            assert result["events"][0]["event_type"] == "accept"
        finally:
            _cleanup(path)

    def test_filter_by_user(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            db.record_event(payload.signal_id, "accept", actor="alice")
            db.record_event(payload.signal_id, "reject", actor="bob")
            result = render_audit(db, user="alice")
            assert len(result["events"]) == 1
            assert result["events"][0]["actor"] == "alice"
        finally:
            _cleanup(path)

    def test_with_signal_csv(self, tmp_path: Path) -> None:
        db, path = _make_db()
        try:
            csv_path = tmp_path / "signals_test.csv"
            with csv_path.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["source", "signal_id"])
                w.writeheader()
                w.writerow({"source": "live", "signal_id": "abc"})
            result = render_audit(db, signal_csv=csv_path)
            assert len(result["csv_rows"]) == 1
            assert result["csv_rows"][0]["signal_id"] == "abc"
            assert result["csv_path"] == str(csv_path)
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class TestRoutes:
    def test_root_redirects_to_admin_legacy(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent, follow_redirects=False)
            r = client.get("/")
            assert r.status_code == 307
            assert r.headers["location"] == "/admin-legacy"
        finally:
            _cleanup(path)

    def test_healthz(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/healthz")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"
        finally:
            _cleanup(path)

    def test_api_alerts_empty(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/alerts")
            assert r.status_code == 200
            assert r.json() == {"rows": []}
        finally:
            _cleanup(path)

    def test_api_alerts_with_mock_data(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            db.record_event(payload.signal_id, "accept", actor="tester")
            client = _client(db, path.parent)
            r = client.get("/api/alerts")
            assert r.status_code == 200
            data = r.json()
            assert len(data["rows"]) == 1
            assert data["rows"][0]["decision"] == "accept"
        finally:
            _cleanup(path)

    def test_api_execution_returns_stub(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/execution")
            assert r.status_code == 200
            data = r.json()
            assert "rows" in data
            assert "note" in data
        finally:
            _cleanup(path)

    def test_api_replay_csv_returns_rows(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "signals_test.csv"
        with csv_path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["a", "b"])
            w.writeheader()
            w.writerow({"a": "1", "b": "2"})
        db = BotDB(DEFAULT_DB_PATH)
        client = _client(db, tmp_path)
        r = client.get("/api/replay/csv/signals_test.csv")
        assert r.status_code == 200
        assert r.json()["rows"] == [{"a": "1", "b": "2"}]

    def test_api_replay_csv_path_traversal_blocked(self, tmp_path: Path) -> None:
        db = BotDB(DEFAULT_DB_PATH)
        client = _client(db, tmp_path)
        for bad in [".hidden"]:
            r = client.get(f"/api/replay/csv/{bad}")
            assert r.status_code == 400

    def test_api_replay_csv_missing_returns_404(self, tmp_path: Path) -> None:
        db = BotDB(DEFAULT_DB_PATH)
        client = _client(db, tmp_path)
        r = client.get("/api/replay/csv/missing.csv")
        assert r.status_code == 404

    def test_api_audit(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "accept", actor="tester")
            client = _client(db, path.parent)
            r = client.get("/api/audit")
            assert r.status_code == 200
            data = r.json()
            assert len(data["events"]) == 1
        finally:
            _cleanup(path)

    def test_api_audit_path_traversal_blocked(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/audit?signal_csv=../etc/passwd")
            assert r.status_code == 400
        finally:
            _cleanup(path)

    def test_api_health(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/api/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert "recent_event_types" in data
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# SSR page rendering (Phase 05 plan §Live Queue page + SSR fallback)
# ---------------------------------------------------------------------------


class TestPageRendering:
    def test_admin_legacy_renders_live_table(self) -> None:
        """SSR fallback must render even with mock data, including design tokens."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            db.record_event(payload.signal_id, "accept", actor="tester")
            client = _client(db, path.parent)
            r = client.get("/admin-legacy")
            assert r.status_code == 200
            assert "Live Queue" in r.text
            assert payload.signal_id[:12] in r.text
            # Design system tokens (ak-ui-ux-pro-max MASTER.md)
            assert "--color-primary" in r.text
            assert "Fira" in r.text  # typography link
        finally:
            _cleanup(path)

    def test_admin_execution_returns_200(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/admin-execution")
            assert r.status_code == 200
            assert "Execution Log" in r.text
            assert "Phase 06" in r.text
        finally:
            _cleanup(path)

    def test_admin_replay_renders_page(self) -> None:
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            r = client.get("/admin-replay")
            assert r.status_code == 200
            assert "Replay" in r.text
            assert "Plotly" in r.text  # Plotly CDN
        finally:
            _cleanup(path)

    def test_admin_audit_renders_page(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "accept", actor="alice")
            client = _client(db, path.parent)
            r = client.get("/admin-audit")
            assert r.status_code == 200
            assert "Audit" in r.text
            assert "Export CSV" in r.text
        finally:
            _cleanup(path)

    def test_pages_contain_design_system_tokens(self) -> None:
        """All pages must inherit the same design tokens (consistency rule)."""
        db, path = _make_db()
        try:
            client = _client(db, path.parent)
            for url in ("/admin-legacy", "/admin-execution", "/admin-replay", "/admin-audit"):
                r = client.get(url)
                assert r.status_code == 200
                assert "--color-primary" in r.text
                assert "--space-md" in r.text
                assert "Fira" in r.text
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestDashboardConcurrency:
    def test_concurrent_api_alerts(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID_BODY)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="webhook")
            client = _client(db, path.parent)
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    for _ in range(20):
                        client.get("/api/alerts")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert errors == [], f"concurrent /api/alerts crashed: {errors[:3]}"
        finally:
            _cleanup(path)