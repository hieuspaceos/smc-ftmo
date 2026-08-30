"""Breaker Block promotion — non-invasive layer over the base OB engine.

A Breaker Block is an invalidated Order Block that has been promoted to trade
in the *opposite* direction after a Change-of-Character (CHoCH) confirms a
trend reversal. This module implements the promotion as a **pure function**
that consumes an ``OrderBlockResult`` and a ``StructureResult`` and returns a
new ``OrderBlockResult`` augmented with breaker events.

The base engine in ``order_blocks.py`` is intentionally left untouched so all
existing tests, golden fixtures, and lifecycle invariants are preserved. This
is Plan 13's "non-invasive" implementation strategy: breakers are a
post-processing layer, not an engine mutation.

Causality invariants (Plan 13 validation session 1, Q1-Q3):

- A draft is eligible for promotion only when its
  ``invalidation_timestamp`` is **strictly less than** the CHoCH's
  ``activation_timestamp``. The promoting CHoCH must be observed strictly
  after the OB was invalidated.
- ``promotion_lookback_bars`` (default 50) bounds how many bars may pass
  between OB origin and the CHoCH. Stale OBs are rejected.
- Single-flip rule: each OB can be promoted at most once. CHoCHs processed
  in chronological order ensure the earliest valid promotion wins.
- Flip gate is **inclusive** (``ts >= role_flip_timestamp``): the CHoCH bar
  itself is entry-eligible, matching the established ``is_first_test_at``
  rule from Phase 12 validation Q7.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from smc_engine.order_blocks import OrderBlockEvent, OrderBlockResult
from smc_engine.structure import StructureResult


@dataclass(frozen=True)
class BreakerEvent:
    """A former Order Block promoted to trade in the opposite direction.

    Reuses the underlying OB's origin (top/bottom/timestamps) but flips
    direction. Carries provenance of the promoting CHoCH so causality can
    be audited.
    """

    ob_id: int
    direction: str  # opposite of the original OB direction
    top: float
    bottom: float
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp
    first_touch_timestamp: pd.Timestamp | None
    invalidation_timestamp: pd.Timestamp
    role_flip_timestamp: pd.Timestamp  # == choch_activation_timestamp
    role_flip_structure_id: int

    def is_entry_eligible_at(self, ts: pd.Timestamp) -> bool:
        """True when ``ts`` is at or after the CHoCH bar that promoted this
        breaker. Inherits the underlying OB's expiry window via the caller;
        this method only enforces the inclusive flip gate.
        """
        return ts >= self.role_flip_timestamp


def promote_breakers(
    ob_result: OrderBlockResult,
    structure: StructureResult,
    df_index: pd.DatetimeIndex,
    promotion_lookback_bars: int = 50,
) -> OrderBlockResult:
    """Return a new ``OrderBlockResult`` with invalidated OBs promoted to
    breakers where a CHoCH confirms a reversal.

    The original ``OrderBlockResult`` is **not mutated**; this function is
    a pure transformation. Pre-existing OBs are returned unchanged in
    ``events``; promotion diagnostics are appended to ``diagnostics`` under
    the ``"breaker_promoted:..."`` prefix.
    """
    breakers, _ = promote_breakers_with_events(
        ob_result, structure, df_index, promotion_lookback_bars
    )
    new_diagnostics = ob_result.diagnostics + tuple(
        f"breaker_promoted@ob_id={b.ob_id}:new_dir={b.direction}:choch_id={b.role_flip_structure_id}"
        for b in breakers
    )
    return OrderBlockResult(
        events=ob_result.events,
        diagnostics=new_diagnostics,
    )


def promote_breakers_with_events(
    ob_result: OrderBlockResult,
    structure: StructureResult,
    df_index: pd.DatetimeIndex,
    promotion_lookback_bars: int = 50,
) -> tuple[list[BreakerEvent], tuple[str, ...]]:
    """Lower-level: returns ``(list[BreakerEvent], diagnostics_addendum)``.

    Lets callers (e.g. SMCSignals adapter, backtester) inject breaker events
    into their own data structures without round-tripping through the
    ``OrderBlockResult`` diagnostics field.
    """
    if promotion_lookback_bars <= 0:
        raise ValueError(
            f"promotion_lookback_bars must be positive, got {promotion_lookback_bars}"
        )

    opposite = {"bullish": "bearish", "bearish": "bullish"}

    # Index OBs by id for quick lookup.
    ob_by_id: dict[int, OrderBlockEvent] = {ob.id: ob for ob in ob_result.events}

    # CHoCHs in chronological order (sort defensively in case callers pass
    # unsorted).
    choch_events = sorted(
        (ev for ev in structure.events if ev.type == "choch"),
        key=lambda ev: ev.activation_pos,
    )

    promoted_ids: set[int] = set()
    breakers: list[BreakerEvent] = []

    for choch in choch_events:
        choch_pos = choch.activation_pos
        choch_ts = df_index[choch_pos]

        # Collect candidate OBs: invalidated strictly before this CHoCH, and
        # within promotion_lookback_bars of the CHoCH.
        candidates = []
        for ob_id, ob in ob_by_id.items():
            if ob_id in promoted_ids:
                continue
            if ob.invalidation_timestamp is None:
                continue  # still alive as OB
            if ob.invalidation_timestamp >= choch_ts:
                continue  # causality: must invalidate BEFORE CHoCH
            if choch_pos - ob.origin_pos > promotion_lookback_bars:
                continue  # stale origin
            candidates.append(ob)

        # Earliest invalidation wins (single-flip per OB).
        if not candidates:
            continue
        chosen = min(candidates, key=lambda ob: ob.invalidation_timestamp)
        promoted_ids.add(chosen.id)

        breaker = BreakerEvent(
            ob_id=chosen.id,
            direction=opposite[chosen.direction],
            top=chosen.top,
            bottom=chosen.bottom,
            origin_pos=chosen.origin_pos,
            origin_timestamp=chosen.origin_timestamp,
            activation_pos=chosen.activation_pos,
            activation_timestamp=chosen.activation_timestamp,
            first_touch_timestamp=chosen.first_touch_timestamp,
            invalidation_timestamp=chosen.invalidation_timestamp,
            role_flip_timestamp=choch_ts,
            role_flip_structure_id=choch.id,
        )
        breakers.append(breaker)

    diagnostics = tuple(
        f"breaker_promoted@ob_id={b.ob_id}:new_dir={b.direction}:choch_id={b.role_flip_structure_id}"
        for b in breakers
    )
    return breakers, diagnostics