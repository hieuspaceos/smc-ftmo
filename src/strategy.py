"""Strategy module — entry rules and partial TP exit logic.

Implements the user's 12-point SMC trading rules:
- Rule 7 (entry): confluence score >= 4 AND displacement + bias aligned required.
- Rule 8 (partial TP): 40% at 2R with BE move, 30% at 3R, 30% at 4R.
- SL = OB edge - 0.2*ATR buffer.

Public API (stable for journal.py + app.py consumers):
- PartialTPExit(entry, sl, side, atr_buffer).update(price) -> list[tuple]
- check_entry(snapshot: dict) -> dict | None
- PIP_VALUE_FOR_PAIR helper
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Standard pip value per lot (USD per 0.0001 move for FX, per 0.01 for XAU, per USD for BTC).
PIP_VALUES: Dict[str, float] = {
    "EURUSD": 10.0,
    "XAUUSD": 1.0,
    "BTCUSD": 1.0,
}


def pip_value_for_pair(pair: str) -> float:
    """USD value of one pip per 1.0 lot. Fallback to 10.0 (FX default)."""
    return PIP_VALUES.get(pair.upper(), 10.0)


# ---------------------------------------------------------------------------
# Partial TP Exit
# ---------------------------------------------------------------------------


@dataclass
class PartialTPExit:
    """Track a single open position through 40/30/30 partial TP ladder.

    Long:    profit_r = (price - entry) / sl_distance
    Short:   profit_r = (entry - price) / sl_distance

    Stages (per unified plan / config.yaml):
      - hit 2R with full position  -> close 40%, move SL to entry (BE).
      - hit 3R with 60% remaining -> close half of remaining (= 30% original).
      - hit 4R with 30% remaining -> close 100% of remaining.
      - SL hit                    -> close all remaining.

    Actions emitted by update():
      ('close_pct', fraction)  fraction is fraction-of-current-position to close.
      ('move_sl', new_sl)      emitted together with the 2R stage.
      ('closed', reason)       when position is fully closed; reason in {'tp1','tp2','tp3','sl'}.
    """

    entry: float
    sl: float
    side: str  # 'long' | 'short'
    atr_buffer: float = 0.0
    remaining_pct: float = 1.0
    be_moved: bool = False
    closed: bool = False
    stage: int = 0  # 0 open, 1 tp1 hit, 2 tp2 hit, 3 closed
    last_close_price: float = 0.0

    def __post_init__(self) -> None:
        self.sl_distance = abs(self.entry - self.sl)
        if self.sl_distance <= 0:
            raise ValueError("entry and sl must differ")
        self.side = self.side.lower()
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")

    # ------------------------------------------------------------------ utils

    def _r(self, price: float) -> float:
        if self.side == "long":
            return (price - self.entry) / self.sl_distance
        return (self.entry - price) / self.sl_distance

    # ------------------------------------------------------------------ update

    def update(self, current_price: float) -> List[Tuple]:
        """Advance the position one bar.

        Returns the list of actions for this bar (possibly empty). Each action
        is a tuple consumable by the backtester for PnL accounting and the
        trade journal.
        """
        if self.closed:
            return []
        self.last_close_price = current_price
        actions: List[Tuple] = []
        r = self._r(current_price)

        # ---- SL hit? (always evaluated first within this bar)
        if self.side == "long" and current_price <= self.sl + 1e-9:
            actions.append(("close_pct", self.remaining_pct))
            actions.append(("closed", "sl"))
            self.remaining_pct = 0.0
            self.closed = True
            return actions
        if self.side == "short" and current_price >= self.sl - 1e-9:
            actions.append(("close_pct", self.remaining_pct))
            actions.append(("closed", "sl"))
            self.remaining_pct = 0.0
            self.closed = True
            return actions
        # ---- TP stages — must check in order; stages are monotonic.
        # 1e-9 epsilon absorbs floating-point noise on exact-R boundaries.
        if self.stage == 0 and r + 1e-9 >= 2.0:
            # 40% at 2R with BE move.
            actions.append(("close_pct", 0.40))
            actions.append(("move_sl", self.entry))
            self.remaining_pct = 0.60
            self.be_moved = True
            self.sl = self.entry
            self.stage = 1
            actions.append(("partial", "tp1"))
            return actions  # one stage per bar to avoid path-dependence surprises.

        if self.stage == 1 and r + 1e-9 >= 3.0:
            # 30% of original (= 50% of remaining 60%).
            actions.append(("close_pct", 0.50))
            self.remaining_pct = 0.30
            self.stage = 2
            actions.append(("partial", "tp2"))
            return actions

        if self.stage == 2 and r + 1e-9 >= 4.0:
            # Remaining 30% closed at 4R.
            actions.append(("close_pct", 1.0))
            self.remaining_pct = 0.0
            self.stage = 3
            self.closed = True
            actions.append(("closed", "tp3"))
            return actions

        return actions

    # ------------------------------------------------------------------ state

    @property
    def r_multiple(self) -> float:
        return self._r(self.last_close_price)

    def unrealized_r(self, current_price: float) -> float:
        return self._r(current_price)


# ---------------------------------------------------------------------------
# Entry logic
# ---------------------------------------------------------------------------


def check_entry(snapshot: Dict) -> Optional[Dict]:
    """Decide whether to open a trade at this bar.

    `snapshot` keys (produced by backtester):
      side_request: 'long' | 'short' — direction implied by bias.
      score: int
      entry_allowed: bool
      displacement: bool
      bias_aligned: bool
      sweep_clean: bool
      in_pd_zone: bool
      first_test: bool
      pd_zone: 'premium' | 'discount' | 'neutral'
      ob_top, ob_bottom: float  (most recent unmitigated OB in trade direction)
      atr: float                (current bar ATR)
      pair: str
      sl_atr_buffer: float = 0.2

    Returns dict {side, entry, sl, tp1, tp2, tp3, ob_top, ob_bottom, reasons}
    or None if the setup fails any rule.
    """
    if not snapshot.get("entry_allowed"):
        return None
    if not (snapshot.get("displacement") and snapshot.get("bias_aligned")):
        return None
    side = snapshot.get("side_request")
    if side not in ("long", "short"):
        return None
    ob_top = snapshot.get("ob_top")
    ob_bottom = snapshot.get("ob_bottom")
    atr = snapshot.get("atr", 0.0)
    if atr is None or atr <= 0:
        return None
    # Require a real OB from structure
    if ob_top is None or ob_bottom is None:
        return None
    buffer = snapshot.get("sl_atr_buffer", 0.2) * atr
    if side == "long":
        entry = float(ob_top)
        sl = float(ob_bottom) - buffer
    else:
        entry = float(ob_bottom)
        sl = float(ob_top) + buffer
    # Price must be near the OB edge (within 1.5 ATR) — no distant entries
    bar_close = snapshot.get("close")
    if bar_close is not None and abs(float(bar_close) - entry) > 1.5 * atr:
        return None

    if sl == entry:
        return None

    risk_per_unit = abs(entry - sl)
    # TP ladder: 2R / 3R / 4R
    if side == "long":
        tp1 = entry + 2.0 * risk_per_unit
        tp2 = entry + 3.0 * risk_per_unit
        tp3 = entry + 4.0 * risk_per_unit
    else:
        tp1 = entry - 2.0 * risk_per_unit
        tp2 = entry - 3.0 * risk_per_unit
        tp3 = entry - 4.0 * risk_per_unit

    reasons = list(snapshot.get("reasons", []))
    return {
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "ob_top": ob_top,
        "ob_bottom": ob_bottom,
        "risk_per_unit": risk_per_unit,
        "atr": atr,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Long PartialTPExit smoke test.
    exit_obj = PartialTPExit(entry=1.1000, sl=1.0950, side="long")
    assert exit_obj.update(1.1000) == [], "no action at BE"

    a = exit_obj.update(1.1100)  # +2R -> close 40% + move BE
    assert any(x[0] == "close_pct" and abs(x[1] - 0.40) < 1e-9 for x in a), a
    assert any(x[0] == "move_sl" for x in a), a
    assert exit_obj.be_moved and exit_obj.sl == 1.1000

    a = exit_obj.update(1.1150)  # +3R -> close 50% of remaining
    assert any(x[0] == "close_pct" and abs(x[1] - 0.50) < 1e-9 for x in a), a
    assert abs(exit_obj.remaining_pct - 0.30) < 1e-9

    a = exit_obj.update(1.1200)  # +4R -> close 100%
    assert any(x[0] == "closed" for x in a), a
    assert exit_obj.closed

    # Short SL hit before any TP.
    e2 = PartialTPExit(entry=1.2000, sl=1.2050, side="short")
    a = e2.update(1.2070)
    assert any(x[0] == "closed" and x[1] == "sl" for x in a), a

    # Long SL hit before any TP -> close 100% at -1R.
    e3 = PartialTPExit(entry=1.1000, sl=1.0950, side="long")
    a = e3.update(1.0940)
    assert any(x[0] == "close_pct" and abs(x[1] - 1.0) < 1e-9 for x in a), a
    assert any(x[0] == "closed" and x[1] == "sl" for x in a), a

    print("strategy.py smoke tests passed.")