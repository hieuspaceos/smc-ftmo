"""FastAPI webhook server.

Endpoints
---------
- ``POST /webhooks/tradingview`` — accept Pine ``SMC|v1|...`` payload
- ``GET  /healthz`` — liveness probe

Source controls (per plan phase-01 §FastAPI server):
- TradingView IP allowlist (configurable, defaults to published ranges)
- Shared URL secret query param (HMAC-free for P0; relies on HTTPS)
- 4 KB body cap
- Per-IP + per-token rate limit (default 60 req/min)
- Returns ``202 Accepted`` (new valid), ``200 OK`` (duplicate),
  ``400 Bad Request`` (malformed), ``401 Unauthorized`` (auth fail),
  ``413 Content Too Large`` (body > 4 KB), ``429 Too Many Requests``.

Persistence happens BEFORE any external dispatch — TradingView 3-second
webhook timeout means we must ``202 Accepted`` ASAP. Phase 02 will add
background Telegram dispatch via ``BackgroundTasks``; P0 only persists.

Thread-safety
-------------
Rate limiter uses a per-app ``threading.Lock``. DB calls open a fresh
connection per call (see ``bot.storage.db``). Auth-rejection logs are
throttled per (ip, reason) so a single attacker cannot flood stderr.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from bot.storage.db import BotDB, get_default_db_path, init_db
from bot.webhook.payload import PayloadParseError, parse_payload
from bot.webhook.security import (
    SecurityConfig,
    body_within_cap,
    check_ip_allowlist,
    check_url_secret,
    extract_client_ip,
)

logger = logging.getLogger("bot.webhook")

MIN_SECRET_LENGTH = 16  # reject obviously-weak tokens at boot time


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


@dataclass(frozen=True)
class AppSettings:
    url_secret: str
    db_path: Path
    security: SecurityConfig
    trusted_proxy: bool

    @classmethod
    def from_env(cls) -> "AppSettings":
        secret = _env("SMC_WEBHOOK_TOKEN", "") or ""
        if not secret:
            raise RuntimeError(
                "SMC_WEBHOOK_TOKEN env var is required. "
                "Set it to a long random string shared with TradingView alert URL."
            )
        if len(secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"SMC_WEBHOOK_TOKEN is too short ({len(secret)} chars). "
                f"Use at least {MIN_SECRET_LENGTH} chars — e.g. "
                "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"`."
            )
        db = Path(_env("SMC_BOT_DB_PATH", str(get_default_db_path())) or str(get_default_db_path()))
        return cls(
            url_secret=secret,
            db_path=db,
            security=SecurityConfig(url_secret=secret),
            trusted_proxy=_env("SMC_TRUSTED_PROXY", "0") == "1",
        )


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (in-process, per-IP + per-token)
# ---------------------------------------------------------------------------


class _RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    def hit(self, key: str, now: int | None = None) -> bool:
        """Return True iff allowed. Thread-safe."""
        ts = now if now is not None else int(time.time())
        window_start = ts - 60
        with self._lock:
            # Access dict under lock so first-touch of a key can't race-create
            # competing deques.
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= self._per_minute:
                return False
            bucket.append(ts)
            return True


# ---------------------------------------------------------------------------
# Throttled logger (avoid spam from one attacker IP)
# ---------------------------------------------------------------------------


class _ThrottledLogger:
    """Per-key log throttle: at most one entry per ``window_seconds``."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def log(self, level: int, key: str, msg: str, *args: Any) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, 0.0)
            if now - last < self._window:
                return
            self._last[key] = now
        logger.log(level, msg, *args)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: AppSettings | None = None,
    *,
    db: BotDB | None = None,
) -> FastAPI:
    settings = settings or AppSettings.from_env()
    # Closure-visible limiter so tests that bypass lifespan still get a working instance.
    limiter = _RateLimiter(settings.security.rate_limit_per_min)
    # Closure-visible DB: tests pass `db=`, real lifespan creates one.
    if db is None:
        init_db(settings.db_path)
        active_db: BotDB = BotDB(settings.db_path)
    else:
        active_db = db
    log_throttle = _ThrottledLogger(window_seconds=60.0)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Mirror the closure reference into app.state for any external code that needs it.
        app.state.db = active_db
        app.state.limiter = limiter
        logger.info("bot webhook ready: db=%s", settings.db_path)
        try:
            yield
        finally:
            if db is None:  # only close if we created it
                active_db.close()

    app = FastAPI(
        title="SMC Bot Webhook",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url=None,  # hide /docs — keep attack surface small
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.url_secret = settings.url_secret
    app.state.limiter = limiter
    app.state.db = active_db

    async def _verify_source(request: Request) -> None:
        client_ip = extract_client_ip(
            forwarded_for=request.headers.get("x-forwarded-for"),
            direct_ip=(request.client.host if request.client else None),
            trusted_proxy=settings.trusted_proxy,
        )
        token = request.query_params.get("token")
        if not check_ip_allowlist(client_ip, settings.security.ipv4_allowlist):
            log_throttle.log(
                logging.WARNING,
                f"ip:{client_ip}:not_allowed",
                "rejecting webhook from disallowed ip=%s",
                client_ip,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ip not allowed")
        if not check_url_secret(token, settings.url_secret):
            log_throttle.log(
                logging.WARNING,
                f"ip:{client_ip}:bad_token",
                "rejecting webhook from ip=%s: bad token",
                client_ip,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad token")
        # Rate limit: combine ip + token so a leaked token from one IP can't drown others.
        rl_key = f"{client_ip}:{token[:6] if token else ''}"
        if not limiter.hit(rl_key):
            log_throttle.log(
                logging.WARNING,
                f"ip:{client_ip}:rate_limit",
                "rate-limit hit for ip=%s",
                client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )
        request.state.client_ip = client_ip

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": "smc-bot-webhook", "version": "0.1.0"}

    @app.post("/webhooks/tradingview")
    async def receive_alert(
        request: Request,
        response: Response,
        _: None = Depends(_verify_source),
    ) -> JSONResponse:
        body = await request.body()
        if not body_within_cap(body, settings.security.body_max_bytes):
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"body exceeds {settings.security.body_max_bytes} bytes",
            )
        content_type = request.headers.get("content-type")
        try:
            payload = parse_payload(body, content_type=content_type)
        except PayloadParseError as exc:
            logger.info("rejecting malformed payload: %s", exc)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        client_ip = getattr(request.state, "client_ip", None)
        alert_id, is_new = active_db.insert_alert(
            payload,
            client_ip=client_ip,
            url_token_ok=True,
        )

        body_json = {
            "alert_id": alert_id,
            "signal_id": payload.signal_id,
            "is_new": is_new,
            "state": payload.state,
        }
        if is_new:
            logger.info(
                "alert accepted: signal_id=%s event=%s state=%s",
                payload.signal_id, payload.event, payload.state,
            )
            return JSONResponse(
                body_json,
                status_code=status.HTTP_202_ACCEPTED,
            )
        logger.info("alert duplicate (signal_id=%s) bumped dedupe_count", payload.signal_id)
        return JSONResponse(
            body_json,
            status_code=status.HTTP_200_OK,
        )

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


# Default module-level app for ``uvicorn bot.webhook.server:app``.


def _build_default_app() -> FastAPI | None:
    try:
        return create_app(AppSettings.from_env())
    except RuntimeError as exc:
        # Avoid blowing up imports during tests / docs builds.
        logger.debug("default app not built: %s", exc)
        return None


app = _build_default_app()


def main() -> None:  # pragma: no cover - manual runner
    import uvicorn

    settings = AppSettings.from_env()
    uvicorn.run(
        "bot.webhook.server:app",
        host="127.0.0.1",
        port=int(_env("PORT", "8000") or "8000"),
        factory=False,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()