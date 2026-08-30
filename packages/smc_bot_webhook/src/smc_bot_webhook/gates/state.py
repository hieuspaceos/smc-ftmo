"""Gate state — query/upsert gate_ack rows + NY session date helper.

The 6 manual gates are persisted in ``gate_ack`` keyed by ``(trade_date, gate_name)``.
Each row has an ``expires_at`` so the validator can reject stale acks.

NY session date
---------------
NY trading day rolls over at the NY open (17:00 ET in summer = 16:00 ET in winter
after DST ends). Use ``zoneinfo.ZoneInfo("America/New_York")`` to keep the
rollover DST-aware. ``ny_session_date(now)`` returns the YYYY-MM-DD label that
the current time belongs to (in NY timezone).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from smc_bot_core.db import BotDB

NY_TZ = ZoneInfo("America/New_York")
# NY session opens at 17:00 ET during the day; we'll use 17:00 local year-round
# because the trader keeps the same mental "session start" wall clock. (Most
# prop firms reset at 17:00 ET regardless of DST — see journal/rule-book.md.)
NY_SESSION_OPEN_HOUR = 17
NY_SESSION_OPEN_MINUTE = 0

# Daily-reset gates (risk, trades_left, daily_loss, no_position) stay fresh for 24h
# from the NY session start. Signal-specific gates (no_position, spread_news,
# judgment) expire after 10 minutes OR one Accept/Reject decision.
GATE_ACK_WINDOW_MINUTES = 5 * 60  # 5 hours — long enough to cover a NY session
SIGNAL_GATE_WINDOW_MINUTES = 10

# The six manual gates the rulebook requires before a trade.
MANUAL_GATE_NAMES: tuple[str, ...] = (
    "risk_ok",                # gate 7:  Risk 0.55% acknowledged
    "trades_left",            # gate 8:  Trades today left (>0)
    "daily_loss_ok",          # gate 9:  Daily loss -2R acknowledged OR not breached
    "no_position",            # gate 10: No open position
    "spread_news_clean",      # gate 11a: Spread/news clean
    "judgment_clear",         # gate 11b: Trader judgment clear
)
SIGNAL_SPECIFIC_GATE_NAMES: frozenset[str] = frozenset(
    {"no_position", "spread_news_clean", "judgment_clear"}
)


def ny_session_date(now: datetime | None = None) -> str:
    """Return YYYY-MM-DD for the NY trading day that ``now`` belongs to.

    Before the NY open hour on a calendar day, the session label is the
    PREVIOUS calendar day (since the session started yesterday).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    local = now.astimezone(NY_TZ)
    if (local.hour, local.minute) < (NY_SESSION_OPEN_HOUR, NY_SESSION_OPEN_MINUTE):
        # Pre-open — belongs to previous session.
        previous_day = local.date().toordinal() - 1
        from datetime import date

        return date.fromordinal(previous_day).isoformat()
    return local.date().isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp. Accepts trailing Z by normalizing to +00:00."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


@dataclass(frozen=True)
class GateStatus:
    """Result of one manual gate check."""

    name: str
    fresh: bool  # True iff a recent acknowledgment exists
    value: bool | None  # acknowledged value (None if no ack)
    expires_at: datetime
    expired: bool  # True iff ack is past expires_at


@dataclass(frozen=True)
class GateState:
    """Snapshot of the 6 manual gates for a given trade_date."""

    trade_date: str
    statuses: dict[str, GateStatus]

    def is_fresh(self, gate_name: str, now: datetime | None = None) -> bool:
        s = self.statuses.get(gate_name)
        if s is None:
            return False
        if now is None:
            now = datetime.now(timezone.utc)
        return s.fresh and not s.expired and now < s.expires_at


class GateStateStore:
    """Read/write helpers for the ``gate_ack`` table."""

    def __init__(self, db: BotDB) -> None:
        self._db = db

    def upsert(
        self,
        gate_name: str,
        value: bool,
        *,
        acknowledged_by: str | None = None,
        window_minutes: int = GATE_ACK_WINDOW_MINUTES,
        trade_date: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Persist a gate acknowledgment.

        ``window_minutes`` controls ``expires_at``. Use 10 for signal-specific
        gates (no_position, spread_news, judgment), 300 (= 5h) for daily gates.
        Returns the new row id.
        """
        if gate_name not in MANUAL_GATE_NAMES:
            raise ValueError(f"unknown manual gate: {gate_name!r}")
        if trade_date is None:
            trade_date = ny_session_date(now)
        if now is None:
            now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + window_minutes * 60
        # SQLite stores ISO; we write UTC ISO without microseconds for readability.
        from datetime import timedelta

        expires_iso = (now + timedelta(seconds=window_minutes * 60)).astimezone(
            timezone.utc
        ).replace(microsecond=0).isoformat()
        return self._db.upsert_gate_ack(
            trade_date=trade_date,
            gate_name=gate_name,
            value=value,
            expires_at=expires_iso,
            acknowledged_by=acknowledged_by,
        )

    def snapshot(
        self, trade_date: str | None = None, now: datetime | None = None
    ) -> GateState:
        """Return all 6 manual gate statuses for the given (or current) trade_date."""
        if trade_date is None:
            trade_date = ny_session_date(now)
        if now is None:
            now = datetime.now(timezone.utc)
        rows = self._db.get_gate_acks(trade_date)
        statuses: dict[str, GateStatus] = {}
        # Default: every gate is "no ack yet" → fresh=False, value=None,
        # expires_at = epoch 0 (always expired).
        epoch_zero = datetime.fromtimestamp(0, tz=timezone.utc)
        for name in MANUAL_GATE_NAMES:
            statuses[name] = GateStatus(
                name=name, fresh=False, value=None, expires_at=epoch_zero, expired=True,
            )
        for row in rows:
            try:
                exp = _parse_iso(row["expires_at"])
            except (ValueError, TypeError):
                exp = epoch_zero
            expired = now >= exp
            statuses[row["gate_name"]] = GateStatus(
                name=row["gate_name"],
                fresh=bool(row["value"]),
                value=bool(row["value"]),
                expires_at=exp,
                expired=expired,
            )
        return GateState(trade_date=trade_date, statuses=statuses)

    def clear_signal_specific(self, trade_date: str | None = None) -> int:
        """Clear no_position, spread_news_clean, judgment_clear rows for the
        trade_date. Returns number of rows deleted. Called after one Accept/Reject."""
        if trade_date is None:
            trade_date = ny_session_date()
        with self._db._conn_ctx() as conn:  # noqa: SLF001 — internal helper
            cur = conn.execute(
                "DELETE FROM gate_ack WHERE trade_date = ? AND gate_name IN (?, ?, ?)",
                (trade_date, "no_position", "spread_news_clean", "judgment_clear"),
            )
            return int(cur.rowcount)