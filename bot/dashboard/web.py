"""Phase 05: FastAPI admin dashboard backend.

Routes:
    /                     → redirect to /admin-legacy (SSR fallback)
    /admin-legacy         → Jinja2 SSR page (Vue SPA offload)
    /healthz              → JSON health check
    /api/alerts            → Live Queue JSON
    /api/execution         → Execution log JSON (Phase 06 stub)
    /api/replay            → list signal CSVs
    /api/replay/csv/{name} → CSV rows (path-traversal guarded)
    /api/audit             → accept/reject events JSON + optional CSV dump
    /api/health            → bot health summary

The Vue SPA (deployed to Cloudflare Pages) consumes the /api/* endpoints.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from bot.storage.db import BotDB

logger = logging.getLogger("bot.dashboard")

DEFAULT_DB_PATH = Path("output/bot.db")
DEFAULT_SIGNAL_CSV_DIR = Path("output")
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _serialize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert SQLite rows to JSON-safe dicts (datetime → ISO string)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Render helpers (pure; testable independently)
# ---------------------------------------------------------------------------


def render_live(
    db: BotDB,
    *,
    limit: int = 100,
    state: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Live Queue data: latest alerts joined with most recent accept/reject."""
    events = db.list_recent_events(limit=limit * 2)
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            pass

    # Group events by signal_id, keep latest per group.
    by_sig: dict[str, dict[str, Any]] = {}
    for ev in events:
        sid = ev["signal_id"]
        if sid not in by_sig:
            by_sig[sid] = {"alert": db.get_alert_by_signal_id(sid), "events": [ev]}
        else:
            by_sig[sid]["events"].append(ev)

    rows: list[dict[str, Any]] = []
    for sid, rec in by_sig.items():
        alert = rec["alert"]
        if alert is None:
            continue
        if state and alert.get("state") != state:
            continue
        received_at = alert.get("received_at")
        if since_dt and received_at:
            try:
                if isinstance(received_at, str):
                    rec_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                else:
                    rec_dt = received_at
                if rec_dt < since_dt:
                    continue
            except (ValueError, TypeError):
                pass
        decision = ""
        decision_at = ""
        decision_actor = ""
        for ev in rec["events"]:
            if ev["event_type"] in ("accept", "reject"):
                decision = ev["event_type"]
                decision_at = ev["created_at"]
                decision_actor = ev.get("actor") or ""
                break
        rows.append(
            {
                "signal_id": sid,
                "event": alert["event"],
                "symbol": alert["symbol"],
                "tf": alert["tf"],
                "side": alert["side"],
                "level": f"{float(alert['level']):.5f}",
                "bar_time": alert["bar_time"],
                "state": alert["state"],
                "reason": alert["reason"],
                "received_at": received_at,
                "decision": decision,
                "decision_at": decision_at,
                "decision_actor": decision_actor,
                "ob_id": alert["ob_id"],
                "bos_id": alert["bos_id"],
            }
        )
    rows.sort(key=lambda r: (r["received_at"] or ""), reverse=True)
    return {"rows": _serialize(rows[:limit])}


def render_execution(db: BotDB, *, limit: int = 100) -> dict[str, Any]:
    """Execution log (Phase 06 stub — execution_log is empty until P6)."""
    return {"rows": [], "note": "Execution log populates after Phase 06"}


def _list_signal_csvs(signal_dir: Path) -> list[dict[str, Any]]:
    if not signal_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(signal_dir.glob("signals_*.csv")):
        stat = p.stat()
        out.append(
            {
                "path": str(p),
                "name": p.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out


def render_replay(signal_dir: Path, *, limit: int = 50) -> dict[str, Any]:
    files = _list_signal_csvs(signal_dir)
    return {"files": files[:limit], "dir": str(signal_dir)}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open() as fh:
        return list(csv.DictReader(fh))


def render_audit(
    db: BotDB,
    signal_csv: Path | None = None,
    *,
    decision: str | None = None,
    user: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Audit view: recent accept/reject/blocked events + optional CSV rows."""
    events = db.list_recent_events(limit=limit * 3)
    rows: list[dict[str, Any]] = []
    for ev in events:
        if ev["event_type"] not in (
            "accept", "reject", "blocked_chart", "expired", "edit_failed", "notified_failed"
        ):
            continue
        if decision and ev["event_type"] != decision:
            continue
        if user and (ev.get("actor") or "") != user:
            continue
        rows.append(
            {
                "signal_id": ev["signal_id"],
                "event_type": ev["event_type"],
                "actor": ev.get("actor") or "",
                "created_at": ev["created_at"],
                "payload": ev.get("payload") or "",
            }
        )
        if len(rows) >= limit:
            break
    csv_rows = _read_csv_rows(signal_csv) if signal_csv else []
    return {
        "events": _serialize(rows),
        "csv_rows": csv_rows,
        "csv_path": str(signal_csv) if signal_csv else None,
    }


# ---------------------------------------------------------------------------
# FastAPI factory
# ---------------------------------------------------------------------------


def create_app(
    db: BotDB | None = None,
    *,
    signal_csv_dir: Path | None = None,
) -> FastAPI:
    if db is None:
        db = BotDB(DEFAULT_DB_PATH)
    csv_dir = signal_csv_dir or DEFAULT_SIGNAL_CSV_DIR
    env = _jinja_env()
    static_dir = STATIC_DIR if STATIC_DIR.exists() else None

    app = FastAPI(
        title="SMC Bot Admin",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.db = db
    app.state.csv_dir = csv_dir
    app.state.jinja_env = env

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/admin-legacy", status_code=307)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": "smc-bot-dashboard", "version": "0.1.0"}

    @app.get("/admin-legacy", response_class=HTMLResponse)
    async def admin_legacy() -> HTMLResponse:
        """Jinja2 SSR fallback. Production UI is the Vue SPA on Cloudflare Pages;
        this page is a graceful-degradation route that serves the live queue
        directly with no JS required.
        """
        template = env.get_template("live.html")
        live_data = render_live(db, limit=50)
        return HTMLResponse(
            template.render(
                page="live", page_title="Live Queue",
                breadcrumb="Live", alerts_json=json.dumps(live_data["rows"]),
            )
        )

    @app.get("/admin-execution", response_class=HTMLResponse)
    async def admin_execution() -> HTMLResponse:
        template = env.get_template("execution.html")
        return HTMLResponse(
            template.render(
                page="execution", page_title="Execution Log",
                breadcrumb="Execution",
            )
        )

    @app.get("/admin-replay", response_class=HTMLResponse)
    async def admin_replay() -> HTMLResponse:
        template = env.get_template("replay.html")
        return HTMLResponse(
            template.render(
                page="replay", page_title="Replay",
                breadcrumb="Replay",
            )
        )

    @app.get("/admin-audit", response_class=HTMLResponse)
    async def admin_audit() -> HTMLResponse:
        template = env.get_template("audit.html")
        return HTMLResponse(
            template.render(
                page="audit", page_title="Audit",
                breadcrumb="Audit",
            )
        )

    # ------------------------------------------------------------------
    # JSON API for Vue SPA + manual programmatic access
    # ------------------------------------------------------------------

    @app.get("/api/alerts")
    async def api_alerts(
        limit: int = Query(100, ge=1, le=1000),
        state: str | None = Query(None),
        since: str | None = Query(None),
    ) -> dict[str, Any]:
        return render_live(db, limit=limit, state=state, since=since)

    @app.get("/api/execution")
    async def api_execution(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
        return render_execution(db, limit=limit)

    @app.get("/api/replay")
    async def api_replay(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return render_replay(csv_dir, limit=limit)

    @app.get("/api/replay/csv/{name}")
    async def api_replay_csv(name: str) -> dict[str, Any]:
        if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
            raise HTTPException(status_code=400, detail="invalid name")
        target = csv_dir / name
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return {"name": name, "rows": _read_csv_rows(target)}

    @app.get("/api/audit")
    async def api_audit(
        decision: str | None = Query(None),
        user: str | None = Query(None),
        signal_csv: str | None = Query(None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict[str, Any]:
        csv_path: Path | None = None
        if signal_csv:
            if "/" in signal_csv or "\\" in signal_csv or ".." in signal_csv:
                raise HTTPException(status_code=400, detail="invalid path")
            csv_path = csv_dir / signal_csv
        return render_audit(db, csv_path, decision=decision, user=user, limit=limit)

    @app.get("/api/health")
    async def api_health() -> dict[str, Any]:
        """Bot health summary: last alert time + count + recent event types."""
        events = db.list_recent_events(limit=100)
        last_alert = events[0]["created_at"] if events else None
        last_decision = next(
            (ev["created_at"] for ev in events if ev["event_type"] in ("accept", "reject")),
            None,
        )
        return {
            "status": "ok",
            "last_alert_at": last_alert,
            "last_decision_at": last_decision,
            "recent_event_count": len(events),
            "recent_event_types": sorted({ev["event_type"] for ev in events}),
        }

    if static_dir is not None:
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def main() -> None:  # pragma: no cover - manual runner
    """Run dashboard: uvicorn bot.dashboard.web:app --host 127.0.0.1 --port 8501

    Cloudflare Tunnel in front of 127.0.0.1:8501 + Cloudflare Access on
    /admin* exposes this to the trader.
    """
    import uvicorn

    from bot.storage.db import init_db

    db_path = Path(_env("SMC_BOT_DB_PATH", str(DEFAULT_DB_PATH)))
    if not db_path.exists():
        logger.info("initializing empty bot DB at %s", db_path)
        init_db(db_path)

    db = BotDB(db_path)
    csv_dir = Path(_env("SMC_SIGNAL_CSV_DIR", str(DEFAULT_SIGNAL_CSV_DIR)))

    host = _env("HOST", "127.0.0.1")
    port = int(_env("PORT", "8501") or "8501")
    logger.info("starting dashboard on %s:%d (db=%s, csv_dir=%s)", host, port, db_path, csv_dir)
    app = create_app(db, signal_csv_dir=csv_dir)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    main()