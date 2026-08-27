"""Risk manager — lot sizing and FTMO guard rails.

Public API (stable for backtester + app.py):
- calculate_lot(account_equity, risk_pct, sl_distance, pip_value) -> float
- FTMOGuard(account_size, max_daily_loss_pct, max_trades_per_day,
            max_daily_loss_r).can_trade(current_equity) -> (bool, reason)
- FTMOGuard.record_trade(r_multiple) — accumulate realized R.
"""
from __future__ import annotations

from datetime import date
from typing import List, Tuple


def calculate_lot(
    account_equity: float,
    risk_pct: float,
    sl_distance: float,
    pip_value: float,
) -> float:
    """Return lot size so that ``risk_pct * equity`` equals the dollar risk.

    Returns at least 0.01 lot; rounds down to 2 decimals.
    """
    if sl_distance <= 0 or pip_value <= 0:
        return 0.01
    risk_amount = account_equity * risk_pct
    lot = risk_amount / (sl_distance * pip_value)
    if lot < 0.01:
        return 0.01
    return round(lot, 2)


class FTMOGuard:
    """Track daily trading limits.

    Rules implemented (user's rules 9 & 10):
      - Daily loss limit: -2R cumulative → stop trading today.
      - Max 3 trades/day.
      - Equity-based daily loss ceiling (FTMO 5% default).

    The caller must invoke ``reset_daily()`` when a new trading day begins
    (the backtester handles this).
    """

    def __init__(
        self,
        account_size: float,
        max_daily_loss_pct: float,
        max_trades_per_day: int,
        max_daily_loss_r: float,
    ) -> None:
        self.account_size = float(account_size)
        self.max_daily_loss = self.account_size * float(max_daily_loss_pct)
        self.max_trades = int(max_trades_per_day)
        self.max_daily_loss_r = float(max_daily_loss_r)
        self.today_trades: List[float] = []
        self.today_r: float = 0.0
        self.last_reset_date: date = None

    # ----------------------------------------------------------------- guards

    def reset_daily(self, day: date = None) -> None:
        self.today_trades = []
        self.today_r = 0.0
        self.last_reset_date = day

    def can_trade(self, current_equity: float) -> Tuple[bool, str]:
        # Rule 9: -2R daily stop.
        if self.today_r <= -abs(self.max_daily_loss_r):
            return False, "Daily -2R stop hit"
        # Max trades per day.
        if len(self.today_trades) >= self.max_trades:
            return False, f"Max {self.max_trades} trades/day reached"
        # Equity-based daily loss ceiling.
        daily_pnl = current_equity - self.account_size
        if daily_pnl <= -self.max_daily_loss:
            return False, "Daily equity loss ceiling hit"
        return True, "OK"

    def record_trade(self, r_multiple: float) -> None:
        self.today_r += float(r_multiple)
        self.today_trades.append(float(r_multiple))

    # ----------------------------------------------------------------- state

    @property
    def trades_today(self) -> int:
        return len(self.today_trades)


if __name__ == "__main__":
    # Smoke tests
    assert calculate_lot(100000, 0.0055, 50, 10) == 1.10
    assert calculate_lot(100000, 0.0055, 100, 10) == 0.55

    g = FTMOGuard(
        account_size=100000,
        max_daily_loss_pct=0.05,
        max_trades_per_day=3,
        max_daily_loss_r=2.0,
    )
    ok, _ = g.can_trade(100000)
    assert ok, ok
    g.record_trade(-1.0)
    g.record_trade(-1.0)
    ok, reason = g.can_trade(100000)
    assert not ok and "2R" in reason, reason
    g.reset_daily()
    ok, _ = g.can_trade(100000)
    assert ok

    g2 = FTMOGuard(100000, 0.05, 3, 2.0)
    for _ in range(3):
        g2.record_trade(0.5)
    ok, reason = g2.can_trade(100000)
    assert not ok and "3 trades" in reason, reason

    g3 = FTMOGuard(100000, 0.05, 3, 10.0)
    ok, reason = g3.can_trade(94000)  # -6% equity > 5% limit
    assert not ok and "ceiling" in reason, reason

    print("risk_manager.py smoke tests passed.")