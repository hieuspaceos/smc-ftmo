"""Scale-in 2R/4R exit logic — independent module.

Public API (mirrors PartialTPExit for drop-in use in backtester):
- ScaleInExit(entry, sl, side, ...).update(price) -> list[tuple]

Actions emitted by update():
    ('close_pct', fraction)        fraction of CURRENT leg1 to close
    ('move_sl', new_sl)            move leg1 remaining SL to new_sl (entry = BE)
    ('open_leg2', lot, sl, tp)     open scale-in leg2 with given lot/sl/tp
    ('closed', reason)             position fully closed; reason in {'tp4r','sl','leg2_sl'}

State machine:
    phase1 (leg1=1.0, SL=original)
        ↓ price hits 2R
    phase2 (leg1=0.5 SL=BE, leg2=0.5 SL=entry TP=4R)
        ↓ price hits 4R (both close)
        OR price drops to entry (leg2 SL hits + leg1 SL hits if at entry)

Math invariants (LONG side, mirrored for SHORT):
    entry = E, sl_distance = 1R
    Leg1: 1.0 lot @ E, SL = E-1R (original)
    At 2R: close 0.5 lot → +1R realized
           open leg2: 0.5 lot @ E+2R, SL = E (BE), TP = E+4R
           move leg1 remaining (0.5) SL → E (BE)
    Outcomes (Design A — default):
        Hit 4R: leg1 rem +2R, leg2 +1R, total = +1R (locked) +2R +1R = +4R
        Leg2 SL @ E (only): leg2 = -1R, leg1 rem hits 4R = +2R → total = +2R
        Both SL @ E (cascade): leg2 = -1R, leg1 rem = 0 → total = 0 (breakeven)
        SL before 2R: leg1 = -1R (leg2 not yet opened) → total = -1R
    Outcomes (Design B with leg2_tp1_r=3.0, 50% leg2 close at TP1):
        Hit 4R: phase1 lock +1R, leg1 rem +2R, leg2 TP1 (+0.25R locked at
            3R), leg2 rem runs to 4R (+0.5R from leg2 entry) → +3.75R
        Hit 3R then cascade to entry: phase1 lock +1R, leg1 rem = 0 (BE at
            entry), leg2 TP1 +0.25R (locked), leg2 rem closes at locked
            SL=3R (+1R × 0.25 lot = +0.25R) → +1.5R
        Cascade immediately to entry (no 3R hit): phase1 lock +1R, leg1 rem = 0,
            leg2 full -1R → 0R
        SL before 2R: -1R (leg2 not yet opened)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ScaleInExit:
    """Track a scale-in 2R/4R position through price action.

    Parameters
    ----------
    entry : float
        Position entry price.
    sl : float
        ORIGINAL stop-loss price (entry - 1R for LONG, entry + 1R for SHORT).
    side : str
        'long' or 'short'.
    scale_in_r : float
        R-multiple at which to close 50% of leg1 and open leg2. Default 2.0.
    final_tp_r : float
        R-multiple at which to close both legs (final TP). Default 4.0.
    leg2_lot : float
        Lot size of leg2 (normalized to 1R = 1.0 leg1 lot). Default 0.5.
    leg2_tp1_r : float | None
        Optional: R-multiple (from ORIGINAL entry) at which to take profit on
        50% of leg2 (Design B). Default None disables intermediate leg2 TP.
        Example: leg2_tp1_r=3.0 means "when price reaches 3R from original
        entry, close 0.25 lot of leg2 and move remaining leg2 SL to
        leg2_entry + 1R (= 3R from original entry, lock 1R above BE)".
    """

    entry: float
    sl: float
    side: str
    scale_in_r: float = 2.0
    final_tp_r: float = 4.0
    leg2_lot: float = 0.5
    leg2_tp1_r: float | None = None  # None = Design A (legacy). Float = Design B.

    # Internal state — mutated by update()
    closed: bool = False
    state: str = "phase1"  # 'phase1' | 'phase2' | 'closed'
    realized_r: float = 0.0
    leg1_remaining: float = 1.0  # fraction of original leg1 still open
    leg2_open: bool = False
    leg2_remaining: float = 0.0  # Design B: tracks unfilled portion of leg2
    leg2_tp1_hit: bool = False  # Design B: True after 50% leg2 closed at TP1
    last_close_price: float = 0.0

    def __post_init__(self) -> None:
        self.sl_distance = abs(self.entry - self.sl)
        if self.sl_distance <= 0:
            raise ValueError("entry and sl must differ")
        self.side = self.side.lower()
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        # Effective SL distance (always positive for math)
        # Effective entry-relative direction
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
        """Price at +offset_r from entry (positive = profitable direction)."""
        return self.entry + self._tp_dir * offset_r * self.sl_distance

    # ------------------------------------------------------------------ update

    def update(self, current_price: float) -> List[Tuple]:
        """Advance the position one bar.

        Returns the list of actions for this bar (possibly empty).
        """
        if self.closed:
            return []
        self.last_close_price = current_price
        r = self._r(current_price)
        actions: List[Tuple] = []

        # ---- PHASE 1: leg1 only, SL = original.
        if self.state == "phase1":
            # SL hit on leg1?
            sl_hit = (
                self.side == "long" and current_price <= self.sl + 1e-9
            ) or (
                self.side == "short" and current_price >= self.sl - 1e-9
            )
            if sl_hit:
                actions.append(("close_pct", self.leg1_remaining))
                actions.append(("closed", "sl"))
                # SL closes leg1 at exactly -1R, NOT at the gap-overshoot
                # close price. Without this cap, M15 bars that gap through
                # SL would over-debit PnL.
                self.realized_r += self.leg1_remaining * (-1.0)
                self.leg1_remaining = 0.0
                self.closed = True
                self.state = "closed"
                return actions

            # Hit scale_in trigger (e.g. 2R)?
            if r + 1e-9 >= self.scale_in_r:
                # Close 50% of leg1, realize at scale_in_r (NOT at overshoot r).
                # Without the cap, a bar that overshoots 2R (e.g. closes at 2.5R)
                # would over-credit the partial close: 0.5 * 2.5 = 1.25R instead
                # of 1R locked at the scale-in trigger.
                close_frac = 0.5
                actions.append(("close_pct", close_frac))
                self.realized_r += close_frac * self.scale_in_r
                self.leg1_remaining *= 1.0 - close_frac  # 0.5

                # Move leg1 remaining SL → entry (BE)
                actions.append(("move_sl", self.entry))

                # Open leg2: lot=0.5, SL=entry (BE), TP=final_tp_r
                leg2_sl = self.entry  # break-even on entry
                leg2_tp = self._signed(self.entry, offset_r=self.final_tp_r)
                actions.append(("open_leg2", self.leg2_lot, leg2_sl, leg2_tp))
                self.leg2_open = True
                # Design B: track leg2 unfilled portion (starts full at leg2_lot)
                self.leg2_remaining = self.leg2_lot

                self.state = "phase2"
        # ---- PHASE 2: leg1 remaining (SL=BE) + leg2 (SL=entry, TP=4R)
        # Optional Design B: leg2 takes 50% profit at leg2_tp1_r and moves
        # remaining leg2 SL → leg2 entry + 1R (lock 1R above BE).
        elif self.state == "phase2":
            # SL hit on leg1 remaining (now @ entry)?
            leg1_sl_hit = (
                self.side == "long" and current_price <= self.entry + 1e-9
            ) or (
                self.side == "short" and current_price >= self.entry - 1e-9
            )
            if leg1_sl_hit:
                # Close leg1 remaining at entry → realized = 0 (BE)
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += self.leg1_remaining * 0.0
                self.leg1_remaining = 0.0
                # Leg2 closes at its CURRENT SL (not always entry). After TP1
                # the leg2 SL is moved up to leg2_tp1_r in original R terms,
                # so cascade-through-lock prices there and locks the gain.
                # Pre-TP1: SL = entry → leg2_loss = leg2_remaining * scale_in_r.
                # Post-TP1: SL = leg2_tp1_r → leg2 profit = leg2_remaining *
                # (leg2_tp1_r - scale_in_r) — lock the +1R above BE.
                if self.leg2_tp1_hit:
                    leg2_pnl_r = self.leg2_remaining * (
                        self.leg2_tp1_r - self.scale_in_r
                    )
                else:
                    leg2_pnl_r = -self.leg2_remaining * self.scale_in_r
                actions.append(("close_leg2",))
                self.realized_r += leg2_pnl_r
                actions.append(("closed", "leg2_sl"))
                self.closed = True
                self.state = "closed"
                return actions

            # ---- Design B: leg2 TP1 at leg2_tp1_r (e.g. 3R from original entry)
            if (
                self.leg2_tp1_r is not None
                and not self.leg2_tp1_hit
                and r + 1e-9 >= self.leg2_tp1_r
            ):
                # Close 50% of leg2 (half of remaining lot).
                tp1_close_lot = self.leg2_remaining * 0.5
                # Profit at TP1: from leg2 entry (scale_in_r) to TP1 (leg2_tp1_r).
                tp1_profit_r = tp1_close_lot * (self.leg2_tp1_r - self.scale_in_r)
                actions.append(("close_leg2_partial", tp1_close_lot))
                self.realized_r += tp1_profit_r
                self.leg2_remaining -= tp1_close_lot
                self.leg2_tp1_hit = True
                # Move remaining leg2 SL → leg2 entry + 1R (= leg2_tp1_r in
                # original R terms, i.e. lock 1R above BE for leg2).
                leg2_lock_sl = self._signed(
                    self.entry, offset_r=self.leg2_tp1_r
                )
                actions.append(("move_leg2_sl", leg2_lock_sl))
                actions.append(("leg2_tp1",))
                # Do NOT close trade — leg1 + leg2 remainder still active.
                return actions

            # Final TP hit (e.g. 4R)?
            if r + 1e-9 >= self.final_tp_r:
                # TP closes BOTH legs at the final_tp_r target, NOT at the
                # overshoot price. Without this cap, runaway trends where
                # price reaches 5R+ before the next bar would over-credit
                # PnL (leg1 gets the full `r` instead of `final_tp_r`).
                # Cap leg1 remaining at final_tp_r exit price:
                leg1_pnl = self.leg1_remaining * self.final_tp_r
                actions.append(("close_pct", self.leg1_remaining))
                self.realized_r += leg1_pnl

                # Leg2 remaining closed at final_tp_r. With Design B, part of
                # leg2 was already taken at TP1; only leg2_remaining here.
                # Leg2 entry was at scale_in_r; remaining distance = final_tp_r - scale_in_r.
                leg2_pnl = self.leg2_remaining * (
                    self.final_tp_r - self.scale_in_r
                )
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
        """Aggregate realized R for the trade so far.

        Returns the SUM of realized_r across all legs, including locked-in
        partial close profit. Used by backtester for trade accounting.
        """
        return self.realized_r