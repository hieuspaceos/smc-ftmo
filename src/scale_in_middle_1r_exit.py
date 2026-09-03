"""Scale-in Middle 1R: same retracement-to-1R leg2 trigger as
ScaleInMiddleExit, but leg2 volume = 1.0 (full R-multiple) instead of 0.5.

Effect on outcomes (LONG side):
  Hit 4R (after leg2 opens):
      +1R (locked at 2R) + 2R (leg1 rem) + 3R (leg2: 4R - 1R entry @ full vol)
      = +6R
  Leg2 SL @ BE (cascade), leg1 rem at 4R:
      +1R + 2R + (-1R)*1.0 = +2R
  Both SL @ BE (cascade immediately on 1R retest):
      +1R + 0R + (-1R)*1.0 = 0R  <- new invariant: true breakeven
  Hit 4R without retrace (leg2 never opens):
      +1R (locked) + 2R (leg1 rem) = +3R
  SL before 2R: -1R (leg2 not opened yet)

Compared to ScaleInMiddleExit (0.5 vol):
  Cascade BE: middle=+0.5R vs middle_1R=0R (middle loses 0.5R when leg2 opens)
  Hit 4R with leg2: middle=+4.5R vs middle_1R=+6R (1.5R more upside)

Risk profile: leg2 fully sized means a single leg2 SL = -1R to total. Net
trade variance is larger than middle (0.5).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ScaleInMiddle1RExit:
    """Track a scale-in-middle position with 1R leg2 volume."""

    entry: float
    sl: float
    side: str
    scale_in_r: float = 2.0
    leg2_entry_r: float = 1.0
    final_tp_r: float = 4.0
    leg2_lot: float = 1.0  # full R-multiple leg2 by default

    # Internal state
    closed: bool = False
    state: str = "phase1"
    realized_r: float = 0.0
    leg1_remaining: float = 1.0
    leg2_open: bool = False
    leg2_entry_price: float = 0.0
    last_close_price: float = 0.0
    saw_scale_in: bool = False

    def __post_init__(self) -> None:
        self.sl_distance = abs(self.entry - self.sl)
        if self.sl_distance <= 0:
            raise ValueError("entry and sl must differ")
        self.side = self.side.lower()
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        if self.side == "long":
            self._tp_dir = +1.0
        else:
            self._tp_dir = -1.0

    def _r(self, price: float) -> float:
        if self.side == "long":
            return (price - self.entry) / self.sl_distance
        return (self.entry - price) / self.sl_distance

    def _signed(self, price: float, *, offset_r: float) -> float:
        return self.entry + self._tp_dir * offset_r * self.sl_distance

    def update(self, current_price: float) -> List[Tuple]:
        if self.closed:
            return []
        self.last_close_price = current_price
        r = self._r(current_price)
        actions: List[Tuple] = []

        # ---- PHASE 1: leg1 only.
        if self.state == "phase1":
            sl_hit = (
                self.side == "long" and current_price <= self.sl + 1e-9
            ) or (
                self.side == "short" and current_price >= self.sl - 1e-9
            )
            if sl_hit:
                actions.append(("close_pct", self.leg1_remaining))
                actions.append(("closed", "sl"))
                self.realized_r += self.leg1_remaining * (-1.0)
                self.leg1_remaining = 0.0
                self.closed = True
                self.state = "closed"
                return actions

            if r + 1e-9 >= self.scale_in_r:
                close_frac = 0.5
                actions.append(("close_pct", close_frac))
                self.realized_r += close_frac * self.scale_in_r
                self.leg1_remaining *= 1.0 - close_frac
                actions.append(("move_sl", self.entry))
                self.saw_scale_in = True
                self.state = "awaiting_retracement"
                return actions

            return actions

        # ---- AWAITING RETRACEMENT.
        if self.state == "awaiting_retracement":
            leg1_sl_hit = (
                self.side == "long" and current_price <= self.entry + 1e-9
            ) or (
                self.side == "short" and current_price >= self.entry - 1e-9
            )
            if leg1_sl_hit:
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += self.leg1_remaining * 0.0
                self.leg1_remaining = 0.0
                actions.append(("closed", "leg1_be"))
                self.closed = True
                self.state = "closed"
                return actions

            if r + 1e-9 >= self.final_tp_r:
                leg1_pnl = self.leg1_remaining * self.final_tp_r
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += leg1_pnl
                self.leg1_remaining = 0.0
                actions.append(("closed", "tp4r"))
                self.closed = True
                self.state = "closed"
                return actions

            if r <= self.leg2_entry_r + 1e-9:
                leg2_sl = self.entry
                leg2_tp = self._signed(self.entry, offset_r=self.final_tp_r)
                actions.append(
                    ("open_leg2", self.leg2_lot, leg2_sl, leg2_tp)
                )
                self.leg2_open = True
                self.leg2_entry_price = current_price
                self.state = "phase2"
                return actions

            return actions

        # ---- PHASE 2: leg1 rem + leg2.
        if self.state == "phase2":
            leg1_sl_hit = (
                self.side == "long" and current_price <= self.entry + 1e-9
            ) or (
                self.side == "short" and current_price >= self.entry - 1e-9
            )
            if leg1_sl_hit:
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += self.leg1_remaining * 0.0
                self.leg1_remaining = 0.0
                # leg2 SL @ BE: full 1R distance on 1.0 lot = -1R
                leg2_loss = self.leg2_lot * (-1.0)
                actions.append(("close_leg2",))
                self.realized_r += leg2_loss
                actions.append(("closed", "leg2_sl"))
                self.closed = True
                self.state = "closed"
                return actions

            if r + 1e-9 >= self.final_tp_r:
                leg1_pnl = self.leg1_remaining * self.final_tp_r
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += leg1_pnl
                # Leg2: from +1R entry to +4R TP = 3R distance, full lot
                leg2_pnl = self.leg2_lot * (self.final_tp_r - self.leg2_entry_r)
                actions.append(("close_leg2",))
                self.realized_r += leg2_pnl
                actions.append(("closed", "tp4r"))
                self.closed = True
                self.state = "closed"
                return actions

        return actions

    @property
    def r_multiple(self) -> float:
        return self.realized_r
