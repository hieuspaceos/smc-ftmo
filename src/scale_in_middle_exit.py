"""Scale-in Middle exit: leg2 entry on retracement to 1R instead of at 2R peak.

Difference vs ScaleInExit (Design A):
  - At 2R: close 50% of leg1 (lock +1R), move leg1 rem SL to BE. Do NOT
    open leg2 immediately. Wait for a retracement back to 1R.
  - At 1R: open leg2 with 0.5R-volume lot at current price. SL = BE (entry).
    TP = +4R from ORIGINAL entry (so leg2 has +3R distance, +1.5R effective
    in R-units because of 0.5 lot).

Math invariants (LONG side, mirrored for SHORT; R = |entry - sl|):
  Leg1: 1.0 lot @ E, SL = E - 1R (original).
  At 2R trigger:
      lock 1.0R (close 50% of leg1)
      move leg1 remaining SL -> E (BE)
      wait.
  At 1R retracement (after 2R was hit):
      open leg2: 0.5 lot @ E+1R, SL = E (BE = -1R from leg2 entry), TP = E+4R.
      leg2 effective reward = (4R - 1R) / 1R = 3R on a -1R SL.
      leg2 effective R-multiple when TP hit = +1.5R (3R on 0.5 lot).
  Outcomes:
      Hit 4R (after leg2 opens): +1R (locked) +2R (leg1 rem) +1.5R (leg2) = +4.5R
      Leg1 reaches TP alone (leg2 never opens: price 2R -> 4R with no retrace):
          +1R locked + 2R leg1 rem = +3R
      Leg2 SL @ BE, leg1 rem at 4R: +1R locked +2R leg1 rem +(-1R)*0.5 leg2 = +2.5R
      Both SL @ BE (cascade on retest): +1R locked + 0.5*(-1R) leg2 = +0.5R
      SL before 2R: leg1 = -1R (leg2 not yet opened) -> total = -1R

Public API (mirrors ScaleInExit for drop-in use in backtester):
    ScaleInMiddleExit(entry, sl, side, ...).update(price) -> list[tuple]

Actions emitted:
    ('close_pct', fraction)        close leg1 portion at scale-in trigger
    ('move_sl', new_sl)            move leg1 SL to BE
    ('open_leg2', lot, sl, tp)     open leg2 at retracement
    ('closed', reason)             fully closed; reason in {'tp4r','sl','leg2_sl'}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ScaleInMiddleExit:
    """Track a scale-in-middle position through price action.

    Parameters
    ----------
    entry : float
        Position entry price (Leg1).
    sl : float
        ORIGINAL stop-loss (entry - 1R for LONG; entry + 1R for SHORT).
    side : str
        'long' or 'short'.
    scale_in_r : float
        R-multiple at which to close 50% of leg1. Default 2.0.
    leg2_entry_r : float
        R-multiple (in original trade direction) at which leg2 opens after
        a retracement from scale_in_r. Default 1.0 (i.e. 1R retracement back
        toward entry).
    final_tp_r : float
        R-multiple at which to close both legs (final TP). Default 4.0.
    leg2_lot : float
        Lot size of leg2 (normalized to 1.0 lot leg1). Default 0.5.
    """

    entry: float
    sl: float
    side: str
    scale_in_r: float = 2.0
    leg2_entry_r: float = 1.0
    final_tp_r: float = 4.0
    leg2_lot: float = 0.5

    # Internal state — mutated by update()
    closed: bool = False
    state: str = "phase1"   # phase1 | awaiting_retracement | phase2 | closed
    realized_r: float = 0.0
    leg1_remaining: float = 1.0
    leg2_open: bool = False
    leg2_entry_price: float = 0.0
    last_close_price: float = 0.0
    saw_scale_in: bool = False  # True after price hit 2R once in phase1

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

    # ------------------------------------------------------------------ utils

    def _r(self, price: float) -> float:
        """Signed R-multiple at price (positive = in profit for direction)."""
        if self.side == "long":
            return (price - self.entry) / self.sl_distance
        return (self.entry - price) / self.sl_distance

    def _signed(self, price: float, *, offset_r: float) -> float:
        return self.entry + self._tp_dir * offset_r * self.sl_distance

    # ------------------------------------------------------------------ update

    def update(self, current_price: float) -> List[Tuple]:
        if self.closed:
            return []
        self.last_close_price = current_price
        r = self._r(current_price)
        actions: List[Tuple] = []

        # ---- PHASE 1: leg1 only, SL = original.
        if self.state == "phase1":
            # SL hit on leg1 before scale_in trigger?
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

            # Hit scale_in trigger (e.g. 2R)?
            if r + 1e-9 >= self.scale_in_r:
                close_frac = 0.5
                actions.append(("close_pct", close_frac))
                self.realized_r += close_frac * self.scale_in_r
                self.leg1_remaining *= 1.0 - close_frac

                # Move leg1 remaining SL -> entry (BE)
                actions.append(("move_sl", self.entry))
                self.saw_scale_in = True
                # Now wait for retracement to leg2_entry_r (default 1.0).
                self.state = "awaiting_retracement"
                return actions

            return actions

        # ---- AWAITING RETRACEMENT: leg1 50% running with SL=BE.
        # Wait for price to come back to leg2_entry_r (1R from original entry).
        # If price hits final_tp_r before retracement, leg2 never opens.
        if self.state == "awaiting_retracement":
            # Leg1 rem hits SL=BE first? -> close phase without leg2.
            leg1_sl_hit = (
                self.side == "long" and current_price <= self.entry + 1e-9
            ) or (
                self.side == "short" and current_price >= self.entry - 1e-9
            )
            if leg1_sl_hit:
                # Realized so far: only the locked 1R from scale_in trigger.
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += self.leg1_remaining * 0.0
                self.leg1_remaining = 0.0
                actions.append(("closed", "leg1_be"))
                self.closed = True
                self.state = "closed"
                return actions

            # Price hit 4R before retracement -> leg2 never opens, close leg1.
            if r + 1e-9 >= self.final_tp_r:
                leg1_pnl = self.leg1_remaining * self.final_tp_r
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += leg1_pnl
                self.leg1_remaining = 0.0
                actions.append(("closed", "tp4r"))
                self.closed = True
                self.state = "closed"
                return actions

            # Price retraced to leg2_entry_r (1R)? Open leg2 here.
            # We require price to FALL back from 2R peak to 1R.
            # For LONG: r == leg2_entry_r means price at E+1R.
            # Gate: r <= leg2_entry_r + a tiny eps (already past peak).
            # Note: if the move retraced without ever exceeding scale_in_r first,
            # we wouldn't be in this state. We did exceed it (`saw_scale_in`).
            if r <= self.leg2_entry_r + 1e-9:
                leg2_sl = self.entry  # break-even on original entry
                leg2_tp = self._signed(self.entry, offset_r=self.final_tp_r)
                actions.append(
                    ("open_leg2", self.leg2_lot, leg2_sl, leg2_tp)
                )
                self.leg2_open = True
                self.leg2_entry_price = current_price
                self.state = "phase2"
                return actions

            return actions

        # ---- PHASE 2: leg1 rem (SL=BE) + leg2 (SL=BE, TP=4R from E).
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
                # Leg2 SL @ entry: closed at -1R distance from leg2 entry,
                # which was 1R from origin. Leg2 lot = 0.5 -> -0.5R contribution.
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
                # Leg2: entry at +1R, TP at +4R. Distance = 3R on 0.5 lot.
                leg2_pnl = self.leg2_lot * (self.final_tp_r - self.leg2_entry_r)
                actions.append(("close_leg2",))
                self.realized_r += leg2_pnl
                actions.append(("closed", "tp4r"))
                self.closed = True
                self.state = "closed"
                return actions

        return actions

    # ------------------------------------------------------------------ state

    @property
    def r_multiple(self) -> float:
        return self.realized_r
