"""SQLite helpers for bot storage — alert_log CRUD.

Schema is additive (``output/bot.db``). Existing ``output/trades.db`` is
untouched. Phase 01 only writes to ``alert_log``. ``signal_events``,
``gate_ack``, ``execution_log`` are reserved for later phases.

Thread-safety
-------------
SQLite connection objects are not thread-safe even with
``check_same_thread=False`` — concurrent cursor reuse corrupts state
(``cannot start a transaction within a transaction``,
``no more rows available``). Every public method therefore opens its own
short-lived connection via a private context manager. The shared
``BotDB`` instance is safe to share across threads.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import logging

logger = logging.getLogger("bot.storage")
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterator

from smc_bot_webhook.payload import AlertPayload  # tolerated transitional dep — webhook package only uses this for type hint

DEFAULT_DB_PATH: Final[Path] = Path("output/bot.db")
_SCHEMA_PATH: Final[Path] = Path(__file__).resolve().parent / "schema.sql"


def get_default_db_path() -> Path:
    """Default path: ``output/bot.db`` (additive vs ``output/trades.db``)."""
    return DEFAULT_DB_PATH


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Create the bot DB file and run schema migration. Idempotent."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(p)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        # Phase 02 (audit fix): add pnl column to execution_log for
        # existing DBs that pre-date the column. Idempotent.
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(execution_log)").fetchall()]
        if "pnl" not in cols:
            conn.execute("ALTER TABLE execution_log ADD COLUMN pnl REAL")
        conn.commit()
    return p


class BotDB:
    """Thin SQLite wrapper exposing alert_log CRUD for Phase 01.

    Stateless from the connection's perspective — every public method
    opens and closes its own connection. Safe to share across threads.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            init_db(self.db_path)

    # ------------------------------------------------------------------
    # Per-call connection (thread-safe)
    # ------------------------------------------------------------------

    @contextmanager
    def _conn_ctx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # autocommit; we use explicit BEGIN/COMMIT
            check_same_thread=False,
            timeout=10.0,
        )
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def close(self) -> None:  # kept for API parity; no-op now
        return

    def __enter__(self) -> "BotDB":
        return self

    def __exit__(self, *exc: Any) -> None:
        return

    # ------------------------------------------------------------------
    # Phase 01: alert_log operations
    # ------------------------------------------------------------------

    def insert_alert(
        self,
        payload: AlertPayload,
        *,
        client_ip: str | None = None,
        url_token_ok: bool = False,
    ) -> tuple[int, bool]:
        """Insert parsed alert. Returns ``(id, is_new)``.

        ``is_new`` is True iff a new row was inserted. False means a row with the
        same ``(signal_id, prefix)`` already existed and ``dedupe_count`` was bumped.

        Thread-safe: opens its own connection. SQLite's
        ``UNIQUE(signal_id, prefix)`` constraint plus ``BEGIN IMMEDIATE``
        guarantees serialization across threads.
        """
        received_at = (
            payload.received_at.isoformat()
            if payload.received_at
            else _utc_now_iso()
        )
        with self._conn_ctx() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.execute(
                    "SELECT id, dedupe_count FROM alert_log "
                    "WHERE signal_id = ? AND prefix = ?",
                    (payload.signal_id, payload.prefix),
                )
                row = cur.fetchone()
                if row is not None:
                    conn.execute(
                        "UPDATE alert_log SET dedupe_count = dedupe_count + 1 "
                        "WHERE id = ?",
                        (row["id"],),
                    )
                    conn.execute("COMMIT")
                    return int(row["id"]), False
                cur = conn.execute(
                    """
                    INSERT INTO alert_log (
                        signal_id, prefix, version, event, symbol, tf, side, level,
                        bar_time, ob_id, bos_id, state, reason, raw_payload,
                        received_at, client_ip, url_token_ok, dedupe_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        payload.signal_id,
                        payload.prefix,
                        payload.version,
                        payload.event,
                        payload.symbol,
                        payload.tf,
                        payload.dir,
                        float(payload.level),
                        int(payload.bar_time),
                        int(payload.ob_id),
                        int(payload.bos_id),
                        payload.state,
                        payload.reason,
                        payload.raw_payload,
                        received_at,
                        client_ip,
                        1 if url_token_ok else 0,
                    ),
                )
                new_id = cur.lastrowid
                conn.execute("COMMIT")
                return int(new_id), True
            except sqlite3.IntegrityError:
                # Race: another thread inserted between our SELECT and INSERT.
                # UNIQUE constraint caught it; treat as duplicate.
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                cur = conn.execute(
                    "SELECT id FROM alert_log WHERE signal_id = ? AND prefix = ?",
                    (payload.signal_id, payload.prefix),
                )
                row = cur.fetchone()
                if row is None:
                    raise
                conn.execute(
                    "UPDATE alert_log SET dedupe_count = dedupe_count + 1 "
                    "WHERE id = ?",
                    (row["id"],),
                )
                conn.execute("COMMIT")
                return int(row["id"]), False

    def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        with self._conn_ctx() as conn:
            cur = conn.execute("SELECT * FROM alert_log WHERE id = ?", (alert_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_alert_by_signal_id(self, signal_id: str) -> dict[str, Any] | None:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT * FROM alert_log WHERE signal_id = ? ORDER BY id DESC LIMIT 1",
                (signal_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def count_alerts(self) -> int:
        with self._conn_ctx() as conn:
            cur = conn.execute("SELECT COUNT(*) AS c FROM alert_log")
            return int(cur.fetchone()["c"])
    # ------------------------------------------------------------------
    # Phase 02: signal_events lifecycle + gate_ack helpers
    # ------------------------------------------------------------------

    MAX_EVENT_PAYLOAD_BYTES = 32 * 1024  # 32 KB hard cap on signal_events.payload

    def record_event(
        self,
        signal_id: str,
        event_type: str,
        *,
        payload: str | None = None,
        actor: str | None = None,
    ) -> int:
        """Append a lifecycle event row. Returns the new event id.

        ``payload`` is truncated to ``MAX_EVENT_PAYLOAD_BYTES`` (32 KB) — protects
        against a runaway caller storing MB-sized strings in SQLite.
        """
        if payload is not None and len(payload.encode("utf-8")) > self.MAX_EVENT_PAYLOAD_BYTES:
            logger.warning(
                "truncating oversized signal_events payload: signal_id=%s type=%s size=%d",
                signal_id, event_type, len(payload),
            )
            payload = payload.encode("utf-8")[: self.MAX_EVENT_PAYLOAD_BYTES].decode(
                "utf-8", errors="replace"
            )
        with self._conn_ctx() as conn:
            cur = conn.execute(
                """
                INSERT INTO signal_events (signal_id, event_type, payload, actor, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (signal_id, event_type, payload, actor, _utc_now_iso()),
            )
            return int(cur.lastrowid)

    def latest_event(self, signal_id: str) -> dict[str, Any] | None:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT * FROM signal_events WHERE signal_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (signal_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT * FROM signal_events ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
            return [dict(r) for r in cur.fetchall()]

    def count_failed_notifications(self) -> int:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM signal_events WHERE event_type = 'notified_failed'"
            )
            return int(cur.fetchone()["c"])

    # gate_ack helpers (used by Phase 03, declared now to keep API stable)
    def upsert_gate_ack(
        self,
        trade_date: str,
        gate_name: str,
        value: bool,
        *,
        expires_at: str,
        acknowledged_by: str | None = None,
    ) -> int:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                """
                INSERT INTO gate_ack (trade_date, gate_name, value, expires_at, acknowledged_by, acknowledged_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, gate_name) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at,
                    acknowledged_by = excluded.acknowledged_by,
                    acknowledged_at = excluded.acknowledged_at
                """,
                (
                    trade_date,
                    gate_name,
                    1 if value else 0,
                    expires_at,
                    acknowledged_by,
                    _utc_now_iso(),
                ),
            )
            return int(cur.lastrowid)

    def get_gate_acks(self, trade_date: str) -> list[dict[str, Any]]:
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT * FROM gate_ack WHERE trade_date = ? ORDER BY gate_name",
                (trade_date,),
            )
            return [dict(r) for r in cur.fetchall()]

    # --- Phase 06: execution_log CRUD ---
    def upsert_execution(
        self,
        signal_id: str,
        transport: str,
        state: str,
        *,
        payload: str | None = None,
        mt5_ticket: str | None = None,
        fill_price: float | None = None,
        pnl: float | None = None,
        error: str | None = None,
    ) -> int:
        """Insert or update execution_log row keyed by (signal_id, transport).

        Returns the row id. If a row already exists for this (signal_id,
        transport), updates state + ack metadata + updated_at. ``pnl`` is
        set when the EA reports a realized P&L (e.g. on 'filled' / 'closed'
        state); pass None to leave the existing value intact.
        """
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT id FROM execution_log WHERE signal_id = ? AND transport = ?",
                (signal_id, transport),
            )
            row = cur.fetchone()
            if row is None:
                cur = conn.execute(
                    """INSERT INTO execution_log
                       (signal_id, transport, state, payload, mt5_ticket,
                        fill_price, pnl, error, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        signal_id, transport, state, payload,
                        mt5_ticket, fill_price, pnl, error, now, now,
                    ),
                )
                return int(cur.lastrowid)
            conn.execute(
                """UPDATE execution_log SET state = ?, payload = ?, mt5_ticket = ?,
                   fill_price = ?, pnl = COALESCE(?, pnl), error = ?, updated_at = ?
                   WHERE id = ?""",
                (state, payload, mt5_ticket, fill_price, pnl, error, now, row["id"]),
            )
            return int(row["id"])

    # --- Phase 02 (audit fix): FTMO guard aggregations ---
    def get_daily_pnl(self, since_iso: str) -> float:
        """Sum of realized P&L across all closed/filled executions since
        ``since_iso`` (UTC ISO-8601). Used to enforce daily loss limit.

        Returns 0.0 when no rows. Rows with NULL pnl are skipped.
        """
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT COALESCE(SUM(pnl), 0.0) AS total FROM execution_log "
                "WHERE created_at >= ? AND pnl IS NOT NULL "
                "AND state IN ('filled', 'closed')",
                (since_iso,),
            )
            row = cur.fetchone()
            return float(row["total"]) if row else 0.0

    def get_trades_today(self, since_iso: str) -> int:
        """Count of executions accepted today (queued or beyond)."""
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM execution_log "
                "WHERE created_at >= ? "
                "AND state IN ('queued', 'sent', 'acked', 'filled', 'closed')",
                (since_iso,),
            )
            row = cur.fetchone()
            return int(row["c"]) if row else 0

    def get_open_positions(self) -> dict[str, int]:
        """Per-symbol count of positions currently open (state='filled' with
        no closing event yet). For Phase 02 we use state='filled' as a proxy
        for "open" — a more complete implementation would track a separate
        open_positions table populated by EA close events.
        """
        with self._conn_ctx() as conn:
            cur = conn.execute(
                "SELECT symbol, COUNT(*) AS c FROM alert_log a "
                "WHERE EXISTS (SELECT 1 FROM execution_log e "
                "  WHERE e.signal_id = a.signal_id "
                "  AND e.state = 'filled' "
                "  AND e.transport IN ('file', 'metaapi')) "
                "GROUP BY symbol"
            )
            return {row["symbol"]: int(row["c"]) for row in cur.fetchall()}

    def list_executions(
        self,
        limit: int = 100,
        transport: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM execution_log WHERE 1=1"
        params: list[Any] = []
        if transport:
            sql += " AND transport = ?"
            params.append(transport)
        if state:
            sql += " AND state = ?"
            params.append(state)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._conn_ctx() as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]