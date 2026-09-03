"""SQLite alert dedup store."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_alerts (
    signal_id   TEXT PRIMARY KEY,
    sent_at     REAL NOT NULL,
    symbol      TEXT NOT NULL DEFAULT '',
    bar_time    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sent_alerts_sent_at ON sent_alerts(sent_at);
"""


@dataclass
class SignalStateStore:
    """Persist sent signal ids and enforce a time-based dedup window."""

    db_path: Path
    dedup_window_minutes: int = 360

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def should_notify(self, signal_id: str, *, now: float | None = None) -> bool:
        if not signal_id:
            return False
        now = time.time() if now is None else now
        window_s = max(0, int(self.dedup_window_minutes)) * 60
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sent_at FROM sent_alerts WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
        if row is None:
            return True
        age = now - float(row["sent_at"])
        return age >= window_s

    def record_alert(
        self,
        signal_id: str,
        *,
        symbol: str = "",
        bar_time: int = 0,
        now: float | None = None,
    ) -> None:
        if not signal_id:
            return
        now = time.time() if now is None else now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sent_alerts (signal_id, sent_at, symbol, bar_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    sent_at = excluded.sent_at,
                    symbol = excluded.symbol,
                    bar_time = excluded.bar_time
                """,
                (signal_id, now, symbol, int(bar_time)),
            )
            conn.commit()
