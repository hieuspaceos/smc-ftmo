"""FastAPI webhook server + background notification dispatch.

Endpoints
---------
- ``POST /webhooks/tradingview`` — accept Pine ``SMC|v1|...`` payload
- ``GET  /healthz`` — liveness probe

Pipeline (per Phase 01 + 02 plans)
-----------------------------------
1. Verify source (TradingView IP allowlist + URL secret).
2. Enforce 4 KB body cap.
3. Parse ``SMC|v1|...`` into ``AlertPayload``.
4. INSERT into ``alert_log`` (idempotent on ``signal_id + prefix``).
5. Record ``signal_events`` row ``received`` (best-effort).
6. Background task: dispatch to Telegram + Discord mirror.
7. Record ``signal_events`` row ``notified`` / ``notified_failed``.

Returns
-------
``202 Accepted`` (new valid), ``200 OK`` (duplicate),
``400 Bad Request`` (malformed), ``401 Unauthorized`` (auth fail),
``413 Content Too Large`` (body > 4 KB), ``429 Too Many Requests``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from bot.notify.discord import DiscordMirror, mirror_from_env
from bot.notify.formatting import callback_payload_json
from bot.notify.telegram import TelegramDispatcher, dispatcher_from_env
from bot.storage.db import BotDB, get_default_db_path, init_db
from bot.webhook.payload import AlertPayload, PayloadParseError, parse_payload
from bot.webhook.security import (
    SecurityConfig,
    body_within_cap,
    check_ip_allowlist,
    check_url_secret,
    extract_client_ip,
)

logger = logging.getLogger("bot.webhook")

MIN_SECRET_LENGTH = 16


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
            raise RuntimeError("SMC_WEBHOOK_TOKEN env var is required.")
        if len(secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"SMC_WEBHOOK_TOKEN is too short ({len(secret)} chars). "
                f"Use at least {MIN_SECRET_LENGTH} chars."
            )
        db = Path(_env("SMC_BOT_DB_PATH", str(get_default_db_path())) or str(get_default_db_path()))
        return cls(
            url_secret=secret,
            db_path=db,
            security=SecurityConfig(url_secret=secret),
            trusted_proxy=_env("SMC_TRUSTED_PROXY", "0") == "1",
        )


# ---------------------------------------------------------------------------
# Rate limiter + throttled logger
# ---------------------------------------------------------------------------


class _RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    def hit(self, key: str, now: int | None = None) -> bool:
        ts = now if now is not None else int(time.time())
        window_start = ts - 60
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= self._per_minute:
                return False
            bucket.append(ts)
            return True


class _ThrottledLogger:
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
# Background dispatch
# ---------------------------------------------------------------------------


async def _safe_record(db: BotDB, signal_id: str, event_type: str, **kwargs: Any) -> None:
    """Record a signal_events row; swallow DB failures so background dispatch never crashes."""
    try:
        db.record_event(signal_id, event_type, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("record_event failed: signal_id=%s type=%s", signal_id, event_type)


async def _dispatch_signal(
    payload: AlertPayload,
    dispatcher: Any,
    mirror: Any,
    db: BotDB,
) -> None:
    """Send to Telegram + Discord mirror; record signal_events audit rows.

    Designed to run inside ``BackgroundTasks`` — exceptions are caught and
    logged so background failures never crash the server. Telegram and
    Discord are independent: a Telegram failure does NOT block Discord.
    """
    signal_id = payload.signal_id
    payload_json = callback_payload_json(payload)

    # Telegram — independent of Discord.
    if getattr(dispatcher, "enabled", False):
        try:
            msg_id = await dispatcher.send_signal(payload)
            if msg_id is not None:
                await _safe_record(db, signal_id, "notified", payload=payload_json, actor="telegram")
            else:
                await _safe_record(db, signal_id, "notified_failed", payload=payload_json, actor="telegram")
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram send crashed: signal_id=%s exc=%s", signal_id, exc)
            await _safe_record(db, signal_id, "notified_failed", actor="telegram", payload=str(exc))
    else:
        await _safe_record(db, signal_id, "notified_skipped", payload=payload_json, actor="telegram")

    # Discord mirror — independent of Telegram.
    if getattr(mirror, "enabled", False):
        try:
            ok = await mirror.send_signal(payload)
            if not ok:
                await _safe_record(db, signal_id, "mirror_failed", payload=payload_json, actor="discord")
        except Exception as exc:  # noqa: BLE001
            logger.warning("discord mirror crashed: signal_id=%s exc=%s", signal_id, exc)
            await _safe_record(db, signal_id, "mirror_failed", actor="discord", payload=str(exc))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: AppSettings | None = None,
    *,
    db: BotDB | None = None,
    dispatcher: Any | None = None,
    mirror: Any | None = None,
) -> FastAPI:
    settings = settings or AppSettings.from_env()
    limiter = _RateLimiter(settings.security.rate_limit_per_min)
    if db is None:
        init_db(settings.db_path)
        active_db: BotDB = BotDB(settings.db_path)
    else:
        active_db = db
    log_throttle = _ThrottledLogger(window_seconds=60.0)
    if dispatcher is None:
        dispatcher = dispatcher_from_env()
    if mirror is None:
        mirror = mirror_from_env()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = active_db
        app.state.limiter = limiter
        app.state.dispatcher = dispatcher
        app.state.mirror = mirror
        logger.info(
            "bot webhook ready: db=%s telegram=%s discord=%s",
            settings.db_path,
            getattr(dispatcher, "enabled", False),
            getattr(mirror, "enabled", False),
        )
        try:
            yield
        finally:
            # Close Discord httpx client to avoid connection leak on shutdown.
            close = getattr(mirror, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    logger.exception("failed to close discord mirror")
            if db is None:
                active_db.close()

    app = FastAPI(
        title="SMC Bot Webhook",
        version="0.2.0",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.url_secret = settings.url_secret
    app.state.limiter = limiter
    app.state.db = active_db
    app.state.dispatcher = dispatcher
    app.state.mirror = mirror

    async def _verify_source(request: Request) -> None:
        client_ip = extract_client_ip(
            forwarded_for=request.headers.get("x-forwarded-for"),
            direct_ip=(request.client.host if request.client else None),
            trusted_proxy=settings.trusted_proxy,
        )
        token = request.query_params.get("token")
        if not check_ip_allowlist(client_ip, settings.security.ipv4_allowlist):
            log_throttle.log(
                logging.WARNING, f"ip:{client_ip}:not_allowed",
                "rejecting webhook from disallowed ip=%s", client_ip,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ip not allowed")
        if not check_url_secret(token, settings.url_secret):
            log_throttle.log(
                logging.WARNING, f"ip:{client_ip}:bad_token",
                "rejecting webhook from ip=%s: bad token", client_ip,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad token")
        rl_key = f"{client_ip}:{token[:6] if token else ''}"
        if not limiter.hit(rl_key):
            log_throttle.log(
                logging.WARNING, f"ip:{client_ip}:rate_limit",
                "rate-limit hit for ip=%s", client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )
        request.state.client_ip = client_ip

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "smc-bot-webhook",
            "version": "0.2.0",
            "telegram": bool(getattr(dispatcher, "enabled", False)),
            "discord": bool(getattr(mirror, "enabled", False)),
        }

    @app.post("/webhooks/tradingview")
    async def receive_alert(
        request: Request,
        response: Response,
        background: BackgroundTasks,
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

        if is_new:
            # 'received' audit (best-effort, never break ingestion).
            try:
                active_db.record_event(
                    payload.signal_id, "received",
                    payload=callback_payload_json(payload),
                    actor=f"webhook:{client_ip or 'unknown'}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to record received event for %s", payload.signal_id)

            # Background dispatch. BackgroundTasks runs AFTER response is sent
            # in production Starlette (and in TestClient too). Dispatch itself
            # NEVER blocks the response.
            background.add_task(
                _dispatch_signal,
                payload,
                dispatcher,
                mirror,
                active_db,
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
            return JSONResponse(body_json, status_code=status.HTTP_202_ACCEPTED)
        logger.info("alert duplicate (signal_id=%s) bumped dedupe_count", payload.signal_id)
        return JSONResponse(body_json, status_code=status.HTTP_200_OK)

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


def _build_default_app() -> FastAPI | None:
    try:
        return create_app(AppSettings.from_env())
    except RuntimeError as exc:
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