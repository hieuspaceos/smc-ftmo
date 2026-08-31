"""FastAPI webhook server + 11-gate validation + background notification dispatch.

Endpoints
---------
- ``POST /webhooks/tradingview`` — accept Pine ``SMC|v1|...`` payload
- ``POST /telegram/callback`` — accept Telegram inline button presses (ack / accept / reject)
- ``POST /telegram/command`` — accept Telegram ``/ack <gate>`` text commands
- ``GET  /healthz`` — liveness probe

Pipeline (per Phase 01 + 02 + 03 plans)
----------------------------------------
1. Verify source (TradingView IP allowlist + URL secret).
2. Enforce 4 KB body cap.
3. Parse ``SMC|v1|...`` into ``AlertPayload``.
4. INSERT into ``alert_log`` (idempotent on ``signal_id + prefix``).
5. Record ``signal_events`` row ``received``.
6. Background: validate 11 gates; if BLOCKED/EXPIRED skip Telegram; else
   send_with_gates (with ack rows when manual gates missing).
7. Record audit rows for every Telegram/Discord outcome.
----"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from smc_bot_webhook.gates.state import GateStateStore
from smc_bot_webhook.gates.validator import Decision, Validator
from smc_bot_webhook.mt5_bridge.executor import build_executor, FileBridgeExecutor, DisabledExecutor
from smc_bot_webhook.mt5_bridge.ftmo_guard import FtmoGuard, GuardState
from smc_bot_webhook.mt5_bridge.signal_writer import SignalRecord, SignalAlreadyWrittenError, SignalExpiredError
from smc_bot_webhook.notify.discord import DiscordMirror, mirror_from_env
from smc_bot_webhook.notify.formatting import (
    ACCEPT_PREFIX,
    ACK_PREFIX,
    REJECT_PREFIX,
    callback_payload_json,
)
from smc_bot_webhook.notify.telegram import (
    CallbackDecision,
    TelegramDispatcher,
    dispatcher_from_env,
)
from smc_bot_core.db import BotDB, get_default_db_path, init_db
from smc_bot_webhook.payload import AlertPayload, PayloadParseError, parse_payload
from smc_bot_webhook.security import (
    SecurityConfig,
    body_within_cap,
    check_ip_allowlist,
    check_telegram_secret,
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


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class AppSettings:
    url_secret: str
    db_path: Path
    security: SecurityConfig
    trusted_proxy: bool
    telegram_callback_secret: str | None = None

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
        telegram_secret = _env("TELEGRAM_CALLBACK_SECRET", "") or ""
        bot_token = _env("TELEGRAM_BOT_TOKEN", "") or ""
        if bot_token and not telegram_secret:
            raise RuntimeError(
                "TELEGRAM_CALLBACK_SECRET is required when TELEGRAM_BOT_TOKEN is set. "
                "Set TELEGRAM_CALLBACK_SECRET to the same value configured in your "
                "Telegram bot webhook (X-Telegram-Bot-Api-Secret-Token header)."
            )
        if telegram_secret and len(telegram_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"TELEGRAM_CALLBACK_SECRET is too short ({len(telegram_secret)} chars). "
                f"Use at least {MIN_SECRET_LENGTH} chars."
            )
        return cls(
            url_secret=secret,
            db_path=db,
            security=SecurityConfig(url_secret=secret),
            trusted_proxy=_env("SMC_TRUSTED_PROXY", "0") == "1",
            telegram_callback_secret=telegram_secret or None,
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
# Background dispatch helpers (Phase 03)
# ---------------------------------------------------------------------------


async def _safe_record(db: BotDB, signal_id: str, event_type: str, **kwargs: Any) -> None:
    try:
        db.record_event(signal_id, event_type, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("record_event failed: signal_id=%s type=%s", signal_id, event_type)


async def _safe_dispatch_telegram(
    dispatcher: Any,
    db: BotDB,
    payload: AlertPayload,
    payload_json: str,
    signal_id: str,
    *,
    gate_states: dict[str, bool | None] | None = None,
    missing_gates: list[str] | None = None,
) -> None:
    if not getattr(dispatcher, "enabled", False):
        await _safe_record(db, signal_id, "notified_skipped", payload=payload_json, actor="telegram")
        return
    try:
        if missing_gates is not None:
            msg_id = await dispatcher.send_with_gates(
                payload, gate_states=gate_states or {}, missing_gates=missing_gates,
            )
        else:
            msg_id = await dispatcher.send_signal(payload, gate_states=gate_states)
        if msg_id is not None:
            await _safe_record(db, signal_id, "notified", payload=payload_json, actor="telegram")
        else:
            await _safe_record(db, signal_id, "notified_failed", payload=payload_json, actor="telegram")
    except Exception as exc:  # noqa: BLE001
        logger.warning("telegram send crashed: signal_id=%s exc=%s", signal_id, exc)
        await _safe_record(db, signal_id, "notified_failed", actor="telegram", payload=str(exc))


async def _safe_dispatch_mirror(
    mirror: Any, db: BotDB, payload: AlertPayload, payload_json: str, signal_id: str,
) -> None:
    try:
        ok = await mirror.send_signal(payload)
        if not ok:
            await _safe_record(db, signal_id, "mirror_failed", payload=payload_json, actor="discord")
    except Exception as exc:  # noqa: BLE001
        logger.warning("discord mirror crashed: signal_id=%s exc=%s", signal_id, exc)
        await _safe_record(db, signal_id, "mirror_failed", actor="discord", payload=str(exc))


async def _dispatch_signal(
    payload: AlertPayload,
    dispatcher: Any,
    mirror: Any,
    db: BotDB,
    validator: Validator | None = None,
    gate_store: GateStateStore | None = None,
) -> None:
    """Background dispatch. Validator short-circuits Telegram when blocked/expired."""
    signal_id = payload.signal_id
    payload_json = callback_payload_json(payload)

    if validator is not None and gate_store is not None:
        try:
            outcome = validator.validate(payload)
            if outcome.decision is Decision.BLOCKED:
                reasons = "; ".join(outcome.blocking_reasons())
                await _safe_record(
                    db, signal_id, "blocked_chart",
                    actor="validator", payload=reasons,
                )
                logger.info("alert blocked by chart gates: signal_id=%s reasons=%s", signal_id, reasons)
                if getattr(mirror, "enabled", False):
                    await _safe_dispatch_mirror(mirror, db, payload, payload_json, signal_id)
                return
            if outcome.decision is Decision.EXPIRED:
                await _safe_record(
                    db, signal_id, "expired",
                    actor="validator", payload="signal-specific gates expired",
                )
                if getattr(mirror, "enabled", False):
                    await _safe_dispatch_mirror(mirror, db, payload, payload_json, signal_id)
                return
            snapshot = gate_store.snapshot()
            gate_states: dict[str, bool | None] = {}
            for name, status_obj in snapshot.statuses.items():
                gate_states[name] = status_obj.value if not status_obj.expired else None
            missing_gates = list(outcome.missing_manual)
            await _safe_dispatch_telegram(
                dispatcher, db, payload, payload_json, signal_id,
                gate_states=gate_states, missing_gates=missing_gates,
            )
            if getattr(mirror, "enabled", False):
                await _safe_dispatch_mirror(mirror, db, payload, payload_json, signal_id)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "validator crashed: signal_id=%s exc=%s; falling back to plain send",
                signal_id, exc,
            )

    # Fallback: no validator or validator crashed → Phase 02 behavior.
    await _safe_dispatch_telegram(dispatcher, db, payload, payload_json, signal_id)
    if getattr(mirror, "enabled", False):
        await _safe_dispatch_mirror(mirror, db, payload, payload_json, signal_id)


# ---------------------------------------------------------------------------
# Telegram callback / command handlers (Phase 03)
# ---------------------------------------------------------------------------


async def _handle_telegram_callback(
    request: Request,
    db: BotDB,
    dispatcher: Any,
    validator: Validator,
    gate_store: GateStateStore,
    executor: Any | None = None,
    ftmo_guard: Any | None = None,
) -> JSONResponse:
    """Process a Telegram inline button press.

    Body shape (JSON):
      ``{"callback_data": "accept:<sid>:<nonce>", "from_user_id": 123}``
    """
    body = await request.body()
    try:
        import json as _json
        obj = _json.loads(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"bad json: {exc}")
    callback_data = obj.get("callback_data", "")
    from_user_id = int(obj.get("from_user_id", 0))
    decision: CallbackDecision | None = await dispatcher.handle_callback(callback_data, from_user_id)
    if decision is None:
        return JSONResponse({"decision": "ignored"}, status_code=status.HTTP_200_OK)
    if not decision.accepted:
        return JSONResponse(
            {"decision": "rejected", "reason": decision.reason},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Phase 03: handle ack vs accept/reject.
    if callback_data.startswith(ACK_PREFIX):
        parsed = dispatcher.parse_ack_callback(callback_data)
        if parsed is None:
            return JSONResponse(
                {"decision": "rejected", "reason": "malformed ack"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        gate_name, signal_id = parsed
        gate_store.upsert(gate_name, value=True, acknowledged_by=str(from_user_id))
        return JSONResponse(
            {"decision": "acked", "gate": gate_name, "signal_id": signal_id}
        )

    if callback_data.startswith(ACCEPT_PREFIX):
        return await _accept_signal(db, dispatcher, validator, gate_store, executor, ftmo_guard, callback_data, decision)

    if callback_data.startswith(REJECT_PREFIX):
        return await _reject_signal(db, dispatcher, gate_store, callback_data, decision)
    return JSONResponse({"decision": "rejected", "reason": "unknown action"}, status_code=status.HTTP_400_BAD_REQUEST)




async def _execute_via_executor(
    db: Any,
    payload: Any,
    signal_id: str,
    actor: str,
    executor: Any,
    ftmo_guard: Any,
) -> dict[str, Any]:
    """Hand an accepted signal off to the MT5 executor.

    Always records a row in execution_log so audit + /api/execution can
    surface it. Returns a small dict for the HTTP response.

    Transport selection is already baked into the executor instance
    (DisabledExecutor / FileBridgeExecutor). FTMO guard runs first.
    """
    from datetime import datetime as _dt, timezone as _tz
    from smc_bot_webhook.mt5_bridge.signal_writer import SignalRecord

    if not executor or not getattr(executor, "enabled", False):
        # Disabled path: record a 'queued' row with transport='disabled' so
        # the dashboard shows the signal was accepted but not executed.
        payload_json = payload.model_dump_json() if hasattr(payload, "model_dump_json") else str(payload)
        db.upsert_execution(
            signal_id=signal_id, transport="disabled", state="queued",
            payload=payload_json,
        )
        return {"transport": "disabled", "state": "queued", "message": "transport not configured"}

    # Phase 02 (audit fix): FTMO guard snapshot is real DB-backed.
    # Reads execution_log via BotDB aggregations. compute NY session start
    # for proper session alignment (NY open is 17:00 local).
    from smc_bot_webhook.gates.state import ny_session_date
    from smc_bot_webhook.mt5_bridge.ftmo_guard import build_guard_state_from_db
    from datetime import datetime as _ny_dt, timezone as _ny_tz, timedelta as _ny_td
    # NY session start is 17:00 local; compute its UTC equivalent for
    # SQLite created_at comparison.
    try:
        from zoneinfo import ZoneInfo as _ZI
        _ny = _ny_dt.now(_ZI("America/New_York")).replace(
            hour=17, minute=0, second=0, microsecond=0,
        )
        if _ny_dt.now(_ZI("America/New_York")) < _ny:
            _ny = _ny - _ny_td(days=1)
        _today_start = _ny.astimezone(_ny_tz.utc).isoformat()
    except Exception:
        # zoneinfo missing on Windows < 3.9 — fall back to UTC midnight.
        _now = _ny_dt.now(_ny_tz.utc)
        _today_start = _now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    guard_state = build_guard_state_from_db(
        db, payload.symbol, today_start=_today_start,
    )
    if ftmo_guard is not None and getattr(ftmo_guard, "enabled", True):
        guard_check = ftmo_guard.check(guard_state, payload.symbol)
    else:
        guard_check = None
    if guard_check is not None and not guard_check.allowed:
        db.upsert_execution(
            signal_id=signal_id, transport="file", state="rejected",
            payload=str(guard_check.reason),
            error="ftmo_guard_blocked:" + guard_check.limit_name,
        )
        return {
            "transport": "file", "state": "rejected",
            "reason": guard_check.reason, "limit": guard_check.limit_name,
        }

    # Build SignalRecord from the AlertPayload.
    record = SignalRecord.from_alert_payload(
        signal_id=signal_id,
        symbol=payload.symbol,
        side=payload.dir,
        level=payload.level,
        bar_time=payload.received_at or _dt.now(_tz.utc),
        ob_id=payload.ob_id,
        bos_id=payload.bos_id,
        approved_by=actor,
        guard_snapshot={
            "trades_today": guard_state.trades_today,
            "daily_pnl": guard_state.daily_pnl,
            "open_position": guard_state.open_position(payload.symbol),
        },
    )
    ok, msg = executor.execute(record)
    state = "queued" if ok else "failed"
    db.upsert_execution(
        signal_id=signal_id,
        transport=executor.name,
        state=state,
        payload=record.to_json() if hasattr(record, "to_json") else None,
        error=None if ok else msg,
    )
    return {"transport": executor.name, "state": state, "message": msg}


async def _accept_signal(
    db: BotDB,
    dispatcher: Any,
    validator: Validator,
    gate_store: GateStateStore,
    executor: Any | None,
    ftmo_guard: Any | None,
    callback_data: str,
    decision: CallbackDecision,
) -> JSONResponse:
    """Re-validate gates on Accept; mark accepted or refused."""
    from smc_bot_webhook.notify.formatting import parse_callback_data as _pcd

    parsed = _pcd(callback_data)
    if parsed is None:
        return JSONResponse({"decision": "rejected", "reason": "malformed"}, status_code=status.HTTP_400_BAD_REQUEST)
    signal_id = parsed.signal_id
    alert = db.get_alert_by_signal_id(signal_id)
    if alert is None:
        return JSONResponse({"decision": "rejected", "reason": "unknown signal"}, status_code=status.HTTP_404_NOT_FOUND)

    # Build AlertPayload from stored row so validator re-checks chart gates.
    # model_construct skips Pydantic validators (we re-read what parser already
    # validated).
    payload = AlertPayload.model_construct(
        prefix=alert["prefix"],
        version=alert["version"],
        event=alert["event"],
        symbol=alert["symbol"],
        tf=alert["tf"],
        dir=alert["side"],
        level=float(alert["level"]),
        bar_time=int(alert["bar_time"]),
        ob_id=int(alert["ob_id"]),
        bos_id=int(alert["bos_id"]),
        state=alert["state"],
        reason=alert["reason"],
        received_at=datetime.now(timezone.utc),
        raw_payload=alert["raw_payload"],
        signal_id=alert["signal_id"],
    )
    outcome = validator.validate(payload)
    if outcome.decision is not Decision.ACCEPTED_READY:
        # Refuse + edit message to show why.
        reasons = "; ".join(outcome.blocking_reasons())
        msg_id = dispatcher.get_message_id(signal_id)
        if msg_id is not None:
            await dispatcher.edit_signal(msg_id, payload, decision="reject", actor=decision.actor)
            dispatcher.record_edit_failure if False else None  # type: ignore[unreachable]
        dispatcher.record_decision(
            db, signal_id,
            decision="reject", actor=decision.actor, nonce=parsed.nonce,
        )
        return JSONResponse(
            {"decision": "refused", "reason": reasons, "validator_decision": outcome.decision.value},
            status_code=status.HTTP_409_CONFLICT,
        )

    # Pass: mark accepted, edit Telegram message, clear signal-specific gates.
    dispatcher.record_decision(
        db, signal_id,
        decision="accept", actor=decision.actor, nonce=parsed.nonce,
    )
    msg_id = dispatcher.get_message_id(signal_id)
    if msg_id is not None:
        await dispatcher.edit_signal(msg_id, payload, decision="accept", actor=decision.actor)
    gate_store.clear_signal_specific()
    # Phase 06: hand off to MT5 executor (disabled by default; transport='file' writes JSON)
    exec_result = await _execute_via_executor(
        db=db, payload=payload, signal_id=signal_id, actor=decision.actor,
        executor=executor, ftmo_guard=ftmo_guard,
    )
    return JSONResponse({
        "decision": "accepted",
        "signal_id": signal_id,
        "actor": decision.actor,
        "execution": exec_result,
    })


async def _reject_signal(
    db: BotDB,
    dispatcher: Any,
    gate_store: GateStateStore,
    callback_data: str,
    decision: CallbackDecision,
) -> JSONResponse:
    from smc_bot_webhook.notify.formatting import parse_callback_data as _pcd

    parsed = _pcd(callback_data)
    if parsed is None:
        return JSONResponse({"decision": "rejected", "reason": "malformed"}, status_code=status.HTTP_400_BAD_REQUEST)
    signal_id = parsed.signal_id
    dispatcher.record_decision(
        db, signal_id,
        decision="reject", actor=decision.actor, nonce=parsed.nonce,
    )
    # Reject also clears signal-specific gates — same semantics as Accept
    # (the trader is no longer pursuing this signal).
    gate_store.clear_signal_specific()
    msg_id = dispatcher.get_message_id(signal_id)
    if msg_id is not None:
        alert = db.get_alert_by_signal_id(signal_id)
        if alert is not None:
            payload = AlertPayload.model_construct(
                prefix=alert["prefix"], version=alert["version"],
                event=alert["event"], symbol=alert["symbol"], tf=alert["tf"],
                dir=alert["side"], level=float(alert["level"]),
                bar_time=int(alert["bar_time"]),
                ob_id=int(alert["ob_id"]), bos_id=int(alert["bos_id"]),
                state=alert["state"], reason=alert["reason"],
                received_at=datetime.now(timezone.utc),
                raw_payload=alert["raw_payload"],
                signal_id=alert["signal_id"],
            )
            await dispatcher.edit_signal(msg_id, payload, decision="reject", actor=decision.actor)
    return JSONResponse({"decision": "rejected", "signal_id": signal_id, "actor": decision.actor})


async def _handle_telegram_command(
    request: Request,
    db: BotDB,
    dispatcher: Any,
    gate_store: GateStateStore,
) -> JSONResponse:
    """Process Telegram ``/ack <gate_name>`` text commands.

    Body shape (JSON): ``{"text": "/ack risk_ok", "from_user_id": 123}``

    Authorization: ``from_user_id`` MUST be in dispatcher's allowlist. Without
    this check, anyone with the webhook URL secret could spoof /ack commands
    and bypass manual gate requirements.
    """
    body = await request.body()
    try:
        import json as _json
        obj = _json.loads(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"bad json: {exc}")
    text = (obj.get("text") or "").strip()
    from_user_id_raw = obj.get("from_user_id", 0)
    try:
        from_user_id = int(from_user_id_raw)
    except (TypeError, ValueError):
        return JSONResponse({"handled": False, "reason": "invalid from_user_id"}, status_code=status.HTTP_400_BAD_REQUEST)
    allowed_ids = getattr(dispatcher, "allowed_user_ids", frozenset())
    if from_user_id not in allowed_ids:
        logger.warning("rejecting /ack from unauthorized user_id=%s", from_user_id)
        return JSONResponse(
            {"handled": False, "reason": "user not allowed"},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if not text.startswith("/ack"):
        return JSONResponse({"handled": False, "reason": "not a /ack command"}, status_code=status.HTTP_200_OK)
    parts = text.split()
    if len(parts) != 2:
        return JSONResponse({"handled": False, "reason": "usage: /ack <gate_name>"}, status_code=status.HTTP_200_OK)
    gate_name = parts[1]
    try:
        gate_store.upsert(gate_name, value=True, acknowledged_by=str(from_user_id))
    except ValueError as exc:
        return JSONResponse({"handled": False, "reason": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)
    return JSONResponse({"handled": True, "gate": gate_name, "by": str(from_user_id)})


def create_app(
    settings: AppSettings | None = None,
    *,
    db: BotDB | None = None,
    dispatcher: Any | None = None,
    mirror: Any | None = None,
    validator: Validator | None = None,
    gate_store: GateStateStore | None = None,
    executor: Any | None = None,
    ftmo_guard: FtmoGuard | None = None,
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
    if executor is None:
        executor = build_executor(db=db)
    if ftmo_guard is None:
        # Phase 02 (audit fix): build FTMO guard from config.yaml so the
        # daily loss / trade count / open position limits reflect the
        # trader's real risk settings. Falls back to a disabled guard
        # when no config file is found.
        try:
            import yaml
            from pathlib import Path as _Path
            _config_path = _Path(os.environ.get("SMC_CONFIG_PATH", "config.yaml"))
            if _config_path.exists():
                with _config_path.open(encoding="utf-8") as _f:
                    _config = yaml.safe_load(_f) or {}
                ftmo_guard = FtmoGuard.from_config(_config)
            else:
                ftmo_guard = FtmoGuard()
                ftmo_guard.enabled = False
        except Exception as exc:
            logger.warning("FTMO guard config load failed: %s; using defaults", exc)
            ftmo_guard = FtmoGuard()
            ftmo_guard.enabled = False
        gate_store = GateStateStore(active_db)
    if validator is None:
        validator = Validator(
            gate_store,
            admin_override=_env_bool("GATE_ADMIN_OVERRIDE", False),
        )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = active_db
        app.state.limiter = limiter
        app.state.dispatcher = dispatcher
        app.state.mirror = mirror
        app.state.validator = validator
        app.state.gate_store = gate_store
        app.state.executor = executor
        app.state.ftmo_guard = ftmo_guard
        logger.info(
            "bot webhook ready: db=%s telegram=%s discord=%s",
            settings.db_path,
            getattr(dispatcher, "enabled", False),
            getattr(mirror, "enabled", False),
        )
        try:
            yield
        finally:
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
        version="0.3.0",
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
    app.state.validator = validator
    app.state.gate_store = gate_store
    app.state.executor = executor
    app.state.ftmo_guard = ftmo_guard

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

    async def _verify_telegram_source(request: Request) -> None:
        """Verify Telegram callback secret header.

        Telegram bot API can be configured with a secret token in
        ``setWebhook(secret_token=...)``; subsequent callback updates carry
        that token in the ``X-Telegram-Bot-Api-Secret-Token`` header.
        We require the header to match ``TELEGRAM_CALLBACK_SECRET``. When
        no secret is configured, all Telegram callback traffic is
        rejected (fail-closed) so a misconfigured bot cannot accept
        spoofed callbacks.
        """
        if not settings.telegram_callback_secret:
            log_throttle.log(
                logging.WARNING, "tg:no_secret_configured",
                "rejecting /telegram request: TELEGRAM_CALLBACK_SECRET not set",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="telegram callback secret not configured",
            )
        provided = request.headers.get("x-telegram-bot-api-secret-token")
        if not check_telegram_secret(provided, settings.telegram_callback_secret):
            log_throttle.log(
                logging.WARNING, "tg:bad_secret",
                "rejecting /telegram request: bad or missing secret",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bad or missing telegram secret",
            )
    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "smc-bot-webhook",
            "version": "0.3.0",
            "telegram": bool(getattr(dispatcher, "enabled", False)),
            "discord": bool(getattr(mirror, "enabled", False)),
            "admin_override": validator._admin_override,  # type: ignore[attr-defined]
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
            payload, client_ip=client_ip, url_token_ok=True,
        )

        if is_new:
            try:
                active_db.record_event(
                    payload.signal_id, "received",
                    payload=callback_payload_json(payload),
                    actor=f"webhook:{client_ip or 'unknown'}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("failed to record received event for %s", payload.signal_id)

            background.add_task(
                _dispatch_signal,
                payload,
                dispatcher,
                mirror,
                active_db,
                validator,
                gate_store,
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

    @app.post("/telegram/callback")
    async def telegram_callback(
        request: Request,
        _: None = Depends(_verify_telegram_source),
    ) -> JSONResponse:
        return await _handle_telegram_callback(
            request, active_db, dispatcher, validator, gate_store,
            executor, ftmo_guard,
        )

    @app.post("/telegram/command")
    async def telegram_command(
        request: Request,
        _: None = Depends(_verify_telegram_source),
    ) -> JSONResponse:
        return await _handle_telegram_command(request, active_db, dispatcher, gate_store)

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