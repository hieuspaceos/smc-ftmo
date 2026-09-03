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


# Pip SIZE (price distance per pip) — distinct from pip_value (USD per pip per lot).
# FX pairs on 5-digit brokers (EURUSD, GBPUSD): 1 pip = 0.0001.
# XAUUSD 2-digit quote: 1 "pip" by SMC convention = 0.01.
# BTCUSD trades in USD: 1 pip = 1.0.
PIP_SIZES: Dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDCHF": 0.0001,
    "XAUUSD": 0.01,
    "BTCUSD": 1.0,
}

PIP_VALUES: Dict[str, float] = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDCHF": 10.0,
    "XAUUSD": 1.0,
    "BTCUSD": 1.0,
}

def pip_value_for_pair(pair: str) -> float:
    """USD value of one pip per 1.0 lot. Fallback to 10.0 (FX default)."""
    return PIP_VALUES.get(pair.upper(), 10.0)


def pip_size_for_pair(pair: str) -> float:
    """Price distance of one pip. Used to convert price-distance to pips.

    EURUSD 5-digit broker: 1 pip = 0.0001.
    XAUUSD 2-digit quote:  1 pip = 0.01.
    BTCUSD USD quote:      1 pip = 1.0.
    Fallback to 0.0001 (FX default).
    """
    return PIP_SIZES.get(pair.upper(), 0.0001)




# ---------------------------------------------------------------------------
# Partial TP Exit
# ---------------------------------------------------------------------------

@dataclass
class PartialTPExit:
    """Track a single open position through a parameterized partial TP ladder.

    Long:    profit_r = (price - entry) / sl_distance
    Short:   profit_r = (entry - price) / sl_distance

    Stages are configurable via `tp_stages`: a list of
    ``(r_multiple, close_pct_of_remaining)`` tuples evaluated in order.
    Default ladder matches the legacy 40/30/30 plan:

      - hit 2R with full position  -> close 40%, move SL to entry (BE).
      - hit 3R with 60% remaining -> close 50% of remaining (= 30% original).
      - hit 4R with 30% remaining -> close 100% of remaining.
      - SL hit                    -> close all remaining.

    The first stage (lowest r_multiple) always moves SL to entry (BE) — this
    is the core risk-neutralisation rule and only applies to stage index 0.
    Later stages are pure take-profit.

    Actions emitted by update():
      ('close_pct', fraction)  fraction is fraction-of-current-position to close.
      ('move_sl', new_sl)      emitted together with stage 0.
      ('closed', reason)       when position is fully closed; reason in {'tp1','tp2','tp3','sl'}.
    """

    DEFAULT_STAGES = ((2.0, 0.40), (3.0, 0.50), (4.0, 1.0))

    entry: float
    sl: float
    side: str  # 'long' | 'short'
    atr_buffer: float = 0.0
    remaining_pct: float = 1.0
    be_moved: bool = False
    closed: bool = False
    stage: int = 0  # 0 = open, N = N stages hit (max = len(tp_stages))
    last_close_price: float = 0.0
    tp_stages: tuple = ()  # populated in __post_init__; public for tests/inspection

    def __post_init__(self) -> None:
        self.sl_distance = abs(self.entry - self.sl)
        if self.sl_distance <= 0:
            raise ValueError("entry and sl must differ")
        self.side = self.side.lower()
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        if not self.tp_stages:
            self.tp_stages = self.DEFAULT_STAGES
        # Validate: strictly ascending r_multiple; close_pct in (0, 1].
        rs = [r for r, _ in self.tp_stages]
        if rs != sorted(rs) or any(r <= 0 for r in rs):
            raise ValueError(f"tp_stages r_multiples must be strictly ascending > 0: {self.tp_stages}")
        if not all(0.0 < p <= 1.0 for _, p in self.tp_stages):
            raise ValueError(f"tp_stages close_pct must be in (0, 1]: {self.tp_stages}")

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
        # ---- TP stages — driven by self.tp_stages, evaluated in order.
        # One stage per bar to avoid path-dependence surprises (matches legacy).
        # 1e-9 epsilon absorbs floating-point noise on exact-R boundaries.
        n_stages = len(self.tp_stages)
        if self.stage < n_stages:
            target_r, close_pct = self.tp_stages[self.stage]
            if r + 1e-9 >= target_r:
                actions.append(("close_pct", close_pct))
                # Move SL to entry only on the first stage (BE rule).
                if self.stage == 0:
                    actions.append(("move_sl", self.entry))
                    self.be_moved = True
                    self.sl = self.entry
                self.remaining_pct *= max(0.0, 1.0 - close_pct)
                tag = f"tp{self.stage+1}"
                self.stage += 1
                if self.remaining_pct <= 1e-9:
                    self.closed = True
                    actions.append(("closed", tag))
                else:
                    actions.append(("partial", tag))
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

    # Phase 08 update 2026-09-02: filter OB candidates by SL distance in ATR units.
    # Mirrors Pine `rulebookSlMinAtr` and `rulebookSlMaxAtr` inputs.
    # Skip OBs with SL too tight (< min) — spread/commission erodes the budget.
    # Skip OBs with SL too wide (> max) — risk per trade > max acceptable.
    min_sl_atr = float(snapshot.get("min_sl_atr", 0.0))
    max_sl_atr = float(snapshot.get("max_sl_atr", 99.0))
    if min_sl_atr > 0 and risk_per_unit < min_sl_atr * atr:
        return None
    if max_sl_atr < 99.0 and risk_per_unit > max_sl_atr * atr:
        return None
    # TP ladder from snapshot (falls back to legacy 2R/3R/4R if absent).
    # snapshot["tp_stages"] is a sequence of (r_multiple, close_pct_of_remaining).
    # We surface only the first 3 R-multiples as tp1/tp2/tp3 — these are
    # informational for the journal; the live ladder is enforced by
    # PartialTPExit using the full tp_stages tuple.
    tp_stages = snapshot.get("tp_stages") or PartialTPExit.DEFAULT_STAGES
    target_rs = [r for r, _ in tp_stages[:3]]
    while len(target_rs) < 3:
        target_rs.append(target_rs[-1] if target_rs else 4.0)
    if side == "long":
        tp1 = entry + target_rs[0] * risk_per_unit
        tp2 = entry + target_rs[1] * risk_per_unit
        tp3 = entry + target_rs[2] * risk_per_unit
    else:
        tp1 = entry - target_rs[0] * risk_per_unit
        tp2 = entry - target_rs[1] * risk_per_unit
        tp3 = entry - target_rs[2] * risk_per_unit

    reasons = list(snapshot.get("reasons", []))
    return {
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp_stages": tuple(tp_stages),
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