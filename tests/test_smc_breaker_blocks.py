"""Causality oracle tests for the Breaker Block promotion layer (Plan 13).

These tests verify Plan 13's hard invariants:
- A draft is eligible for promotion only when its invalidation_timestamp is
  strictly less than the CHoCH's activation_timestamp.
- Single-flip rule: each OB can be promoted at most once.
- promotion_lookback_bars bounds origin distance.
- Without any CHoCH events, no breakers appear.

Non-invasive strategy: we exercise ``promote_breakers_with_events`` against
synthetic ``OrderBlockResult`` and ``StructureResult`` fixtures built
manually, not via the engine. The base engine's golden fixtures remain
untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.breaker_blocks import (  # noqa: E402
    BreakerEvent,
    promote_breakers,
    promote_breakers_with_events,
)
from smc_engine.order_blocks import (  # noqa: E402
    OrderBlockEvent,
    OrderBlockResult,
)
from smc_engine.structure import (  # noqa: E402
    StructureEvent,
    StructureResult,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="15min")


def _ob(
    id_: int,
    direction: str,
    origin_pos: int,
    activation_pos: int,
    invalidation_pos: int | None = None,
) -> OrderBlockEvent:
    """Build a synthetic OrderBlockEvent for tests."""
    idx = _idx(40)
    invalidation_ts = (
        idx[invalidation_pos] if invalidation_pos is not None else None
    )
    return OrderBlockEvent(
        id=id_,
        direction=direction,
        origin_pos=origin_pos,
        origin_timestamp=idx[origin_pos],
        activation_pos=activation_pos,
        activation_timestamp=idx[activation_pos],
        top=1.106,
        bottom=1.100,
        first_touch_timestamp=None,
        invalidation_timestamp=invalidation_ts,
        expiry_timestamp=None,
        structure_event_id=0,
    )


def _choch(
    id_: int,
    direction: str,
    activation_pos: int,
    broken_level: float = 1.085,
) -> StructureEvent:
    """Build a synthetic CHoCH structure event."""
    return StructureEvent(
        id=id_,
        type="choch",
        direction=direction,
        activation_pos=activation_pos,
        activation_timestamp=_idx(40)[activation_pos],
        broken_level=broken_level,
        source_swing_id=0,
        prior_trend="bullish" if direction == "bearish" else "bearish",
        next_trend=direction,
    )


def _structure(events: tuple[StructureEvent, ...]) -> StructureResult:
    """Wrap events in a minimal StructureResult for tests."""
    idx = _idx(40)
    return StructureResult(
        events=events,
        trend=pd.Series("bull", index=idx),
        bos=pd.Series(False, index=idx),
        choch=pd.Series(False, index=idx),
        broken_level=pd.Series(np.nan, index=idx),
        last_swing_high=pd.Series(np.nan, index=idx),
        last_swing_low=pd.Series(np.nan, index=idx),
        swing_direction=pd.Series("none", index=idx, dtype=object),
    )


def _ob_result(events: tuple[OrderBlockEvent, ...]) -> OrderBlockResult:
    return OrderBlockResult(events=events, diagnostics=())


class TestBreakerBlockCausality:
    def test_promoted_only_after_choch(self):
        """A bullish OB invalidated at idx=20 is promoted by a CHoCH at idx=24.
        Direction flips, role_flip_timestamp equals the CHoCH timestamp,
        invalidation_timestamp is strictly less than role_flip_timestamp.
        """
        ob = _ob(id_=0, direction="bullish", origin_pos=5, activation_pos=10,
                 invalidation_pos=20)
        choch = _choch(id_=1, direction="bearish", activation_pos=24)
        ob_res = _ob_result((ob,))
        structure = _structure((choch,))

        breakers, diags = promote_breakers_with_events(ob_res, structure, _idx(40))

        assert len(breakers) == 1
        b = breakers[0]
        assert b.ob_id == 0
        assert b.direction == "bearish"  # flipped
        assert b.top == ob.top  # preserved
        assert b.bottom == ob.bottom  # preserved
        assert b.role_flip_timestamp == _idx(40)[24]
        assert b.role_flip_structure_id == 1
        assert b.invalidation_timestamp < b.role_flip_timestamp
        assert any(d.startswith("breaker_promoted@") for d in diags)

    def test_no_promotion_when_choch_before_invalidation(self):
        """If the CHoCH occurs BEFORE the OB is invalidated (or on the same bar),
        no promotion. Causality lock.
        """
        ob = _ob(id_=0, direction="bullish", origin_pos=5, activation_pos=10,
                 invalidation_pos=24)
        choch = _choch(id_=1, direction="bearish", activation_pos=24)
        ob_res = _ob_result((ob,))
        structure = _structure((choch,))

        breakers, _ = promote_breakers_with_events(ob_res, structure, _idx(40))
        assert breakers == []

    def test_no_breaker_without_choch(self):
        """Without any CHoCH events in structure, breakers list is empty
        regardless of how many OBs are invalidated.
        """
        obs = tuple(
            _ob(id_=i, direction="bullish", origin_pos=5 + i, activation_pos=10 + i,
                 invalidation_pos=20 + i)
            for i in range(3)
        )
        ob_res = _ob_result(obs)
        structure = _structure(())  # no CHoCH

        breakers, _ = promote_breakers_with_events(ob_res, structure, _idx(40))
        assert breakers == []

    def test_single_flip_per_ob(self):
        """An OB invalidated at idx=20 with TWO subsequent CHoCHs (idx=22 and
        idx=30) is promoted at most once — the earliest valid CHoCH wins.
        """
        ob = _ob(id_=0, direction="bullish", origin_pos=5, activation_pos=10,
                 invalidation_pos=20)
        choch_early = _choch(id_=1, direction="bearish", activation_pos=22)
        choch_late = _choch(id_=2, direction="bullish", activation_pos=30)
        ob_res = _ob_result((ob,))
        structure = _structure((choch_late, choch_early))  # unsorted on purpose

        breakers, _ = promote_breakers_with_events(ob_res, structure, _idx(40))
        assert len(breakers) == 1
        assert breakers[0].role_flip_structure_id == 1  # earliest CHoCH wins

    def test_promotion_lookback_honored(self):
        """An OB whose origin is more than ``promotion_lookback_bars`` away
        from the CHoCH is NOT promoted (stale-zone guard).
        """
        ob = _ob(id_=0, direction="bullish", origin_pos=2, activation_pos=10,
                 invalidation_pos=20)
        choch = _choch(id_=1, direction="bearish", activation_pos=30)
        ob_res = _ob_result((ob,))
        structure = _structure((choch,))

        # Origin at idx=2, CHoCH at idx=30 → distance 28. Default lookback=50
        # permits. Tightening to 20 should reject.
        breakers, _ = promote_breakers_with_events(
            ob_res, structure, _idx(40), promotion_lookback_bars=20
        )
        assert breakers == []
        # Default lookback permits:
        breakers_default, _ = promote_breakers_with_events(
            ob_res, structure, _idx(40)
        )
        assert len(breakers_default) == 1

    def test_promote_breakers_returns_new_ob_result(self):
        """The non-invasive wrapper preserves the original events tuple and
        appends diagnostics.
        """
        ob = _ob(id_=0, direction="bullish", origin_pos=5, activation_pos=10,
                 invalidation_pos=20)
        choch = _choch(id_=1, direction="bearish", activation_pos=24)
        ob_res = _ob_result((ob,))
        structure = _structure((choch,))

        new_res = promote_breakers(ob_res, structure, _idx(40))
        # events unchanged (idempotent on OB identity)
        assert new_res.events == ob_res.events
        assert len(new_res.diagnostics) >= 1
        assert any(d.startswith("breaker_promoted@") for d in new_res.diagnostics)
        # Original ob_res untouched
        assert ob_res.diagnostics == ()
        assert ob_res.events == (ob,)

    def test_invalid_lookback_raises(self):
        with pytest.raises(ValueError, match="promotion_lookback_bars"):
            promote_breakers_with_events(_ob_result(()), _structure(()), _idx(40),
                                          promotion_lookback_bars=0)