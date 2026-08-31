"""FTMO guard — daily loss + trade count + open position checks.

Pure functions over a ``GuardState`` snapshot — the executor queries the
guard before writing a signal and refuses if any check fails.

Limits per plan §FTMO guard integration:
  - Daily loss: refuse if daily_pnl <= -2R (configurable; default -0.011
    for a 0.55% risk-per-trade account = -2R)
  - Trades today: refuse if trades_today >= 3
  - Open position per symbol: refuse if open_position

All limits are configurable via ``FtmoGuard(limits=...)`` for different
account tiers (FTMO 10k Challenge = 1% daily loss; FTMO 100k = 5%).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# FTMO Phase 1 default: 1% max daily loss, 5% max total loss.
# Per-trade risk 0.55% × 2R = 1.1% (rounded to 1% in their rules).
FTMO_DEFAULT_MAX_DAILY_PNL = -0.011   # -1.1% (= -2R of 0.55% risk)
FTMO_DEFAULT_MAX_TRADES_PER_DAY = 3
FTMO_DEFAULT_MAX_OPEN_POSITIONS = 1


@dataclass
class GuardState:
    """Snapshot of trading state used by the guard.

    ``daily_pnl`` is in account equity units (negative = loss).
    """

    daily_pnl: float = 0.0
    trades_today: int = 0
    open_positions: dict[str, int] = field(default_factory=dict)

    def open_position(self, symbol: str) -> int:
        return self.open_positions.get(symbol, 0)


@dataclass(frozen=True)
class FtmoGuardResult:
    """Outcome of a guard check.

    ``allowed=False`` means the executor MUST refuse the signal and
    record a ``blocked_by_guard`` audit event. ``reason`` is human-readable
    for Telegram + dashboard display.
    """

    allowed: bool
    reason: str = ""
    limit_name: str = ""   # e.g. "daily_loss" or "open_position"
    observed: float = 0.0
    threshold: float = 0.0


class FtmoGuard:
    """FTMO guard checker — pure, no I/O.

    Construct with ``FtmoGuard()`` for default FTMO 10k Challenge limits,
    or pass custom limits for different tiers / paper trading.
    """

    def __init__(
        self,
        *,
        max_daily_pnl: float = FTMO_DEFAULT_MAX_DAILY_PNL,
        max_trades_per_day: int = FTMO_DEFAULT_MAX_TRADES_PER_DAY,
        max_open_positions: int = FTMO_DEFAULT_MAX_OPEN_POSITIONS,
    ) -> None:
        if max_daily_pnl >= 0:
            raise ValueError("max_daily_pnl must be negative (loss threshold)")
        if max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1")
        self._max_daily_pnl = max_daily_pnl
        self._max_trades = max_trades_per_day
        self._max_open = max_open_positions
        self.enabled = True

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "FtmoGuard":
        """Build a guard from a parsed config.yaml dict.

        Uses ``config["risk"]["per_trade_pct"]`` and
        ``config["risk"]["daily_loss_limit_r"]`` to derive the daily loss
        threshold (e.g. -0.0055 * 2 = -0.011). Reads
        ``config["risk"]["max_trades_per_day"]`` and
        ``config["risk"]["max_open_positions"]`` for trade-count and
        open-position limits. ``config["ftmo"]["max_daily_loss"]`` is
        referenced for documentation but not used to override the derived
        limit (FTMO challenge rules are external; the bot's internal stop
        is the -2R derived value).

        If ``config`` is None, returns a disabled guard (no-op) so
        existing tests / dev environments without config.yaml keep working.
        """
        if not config or not isinstance(config.get("risk"), dict):
            # No config or no risk section → guard is disabled (no-op).
            # The trader's config.yaml must have a populated ``risk:`` block
            # before the guard enforces any limit.
            instance = cls()
            instance.enabled = False
            return instance
        risk = config["risk"]
        per_trade_pct = float(risk.get("per_trade_pct", 0.0055))
        daily_loss_limit_r = float(risk.get("daily_loss_limit_r", 2.0))
        # Daily loss in account-fraction = -(per_trade_pct × daily_loss_limit_r).
        max_daily_pnl = -abs(per_trade_pct * daily_loss_limit_r)
        max_trades_per_day = int(risk.get("max_trades_per_day", 3))
        max_open_positions = int(risk.get("max_open_positions", 1))
        return cls(
            max_daily_pnl=max_daily_pnl,
            max_trades_per_day=max_trades_per_day,
            max_open_positions=max_open_positions,
        )

    def check(self, state: GuardState, symbol: str) -> FtmoGuardResult:
        """Run all 3 checks. First failure short-circuits.

        Order: daily_loss → trades_today → open_position (per-symbol).
        """
        if state.daily_pnl <= self._max_daily_pnl:
            return FtmoGuardResult(
                allowed=False,
                reason=(
                    f"daily P&L {state.daily_pnl * 100:.2f}% <= threshold "
                    f"{self._max_daily_pnl * 100:.2f}%"
                ),
                limit_name="daily_loss",
                observed=state.daily_pnl,
                threshold=self._max_daily_pnl,
            )
        if state.trades_today >= self._max_trades:
            return FtmoGuardResult(
                allowed=False,
                reason=(
                    f"trades today {state.trades_today} >= limit {self._max_trades}"
                ),
                limit_name="trades_today",
                observed=float(state.trades_today),
                threshold=float(self._max_trades),
            )
        if state.open_position(symbol) >= self._max_open:
            return FtmoGuardResult(
                allowed=False,
                reason=(
                    f"open position on {symbol} = {state.open_position(symbol)} "
                    f">= limit {self._max_open}"
                ),
                limit_name="open_position",
                observed=float(state.open_position(symbol)),
                threshold=float(self._max_open),
            )
        return FtmoGuardResult(allowed=True)


def build_guard_state_from_db(
    db: Any,
    symbol: str,
    today_start: str | None = None,
) -> GuardState:
    """Compute a ``GuardState`` from the bot DB.

    Real implementation (Phase 02 audit fix): reads the
    ``execution_log`` table via the BotDB aggregation methods
    ``get_daily_pnl``, ``get_trades_today``, and ``get_open_positions``.

    Parameters
    ----------
    today_start:
        UTC ISO-8601 timestamp marking the start of the trading day.
        If None, uses midnight UTC today — caller should pass the NY
        session open timestamp for proper session alignment.
    """
    if today_start is None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        daily_pnl = float(db.get_daily_pnl(today_start))
        trades_today = int(db.get_trades_today(today_start))
        open_positions = dict(db.get_open_positions())
    except AttributeError as exc:
        # db missing one of the aggregation methods → fail loud.
        raise RuntimeError(
            f"BotDB missing aggregation method: {exc}. "
            "Phase 02 audit fix requires get_daily_pnl/get_trades_today/"
            "get_open_positions on BotDB."
        ) from exc
    return GuardState(
        daily_pnl=daily_pnl,
        trades_today=trades_today,
        open_positions=open_positions,
    )