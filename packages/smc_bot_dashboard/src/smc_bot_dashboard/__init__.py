"""Phase 05: FastAPI admin dashboard backend + Vue SPA on Cloudflare Pages."""

from smc_bot_dashboard.web import (
    DEFAULT_DB_PATH,
    DEFAULT_SIGNAL_CSV_DIR,
    create_app,
    render_audit,
    render_execution,
    render_live,
    render_replay,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_SIGNAL_CSV_DIR",
    "create_app",
    "render_live",
    "render_execution",
    "render_replay",
    "render_audit",
]