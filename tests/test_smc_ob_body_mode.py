"""Tests for the OB body-only zone recompute layer (Plan 13, Phase 3).

- ``"full"`` mode is the identity function (no change).
- ``"body"`` mode narrows zones to the origin candle's body
  (max(open, close), min(open, close)).
- Invalid mode raises ``ValueError``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smc_engine.ob_body_mode import recompute_zones  # noqa: E402
from smc_engine.order_blocks import (  # noqa: E402
    OrderBlockEvent,
    OrderBlockResult,
)


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="15min")


def _ob(top: float, bottom: float, origin_pos: int = 5) -> OrderBlockEvent:
    idx = _idx(40)
    return OrderBlockEvent(
        id=0,
        direction="bullish",
        origin_pos=origin_pos,
        origin_timestamp=idx[origin_pos],
        activation_pos=10,
        activation_timestamp=idx[10],
        top=top,
        bottom=bottom,
        first_touch_timestamp=None,
        invalidation_timestamp=None,
        expiry_timestamp=None,
        structure_event_id=0,
    )


def _ohlc(n: int = 40) -> pd.DataFrame:
    """Frame where idx=5 is a bearish origin candle with body in [1.100, 1.106].
    Includes long upper and lower wicks so full mode extends beyond body.
    """
    opens = [1.10] * n
    highs = [1.10] * n
    lows = [1.10] * n
    closes = [1.10] * n
    opens[5] = 1.106  # body top
    highs[5] = 1.120  # long upper wick
    lows[5] = 1.080   # long lower wick
    closes[5] = 1.100  # body bottom (bearish)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=_idx(n))


class TestOBBodyMode:
    def test_full_mode_is_identity(self):
        df = _ohlc()
        ob = _ob(top=1.106, bottom=1.100)
        ob_res = OrderBlockResult(events=(ob,), diagnostics=())
        new_res = recompute_zones(ob_res, df, mode="full")
        assert new_res is ob_res  # exact same object, identity preserved
        assert new_res.events == (ob,)

    def test_body_mode_narrows_zone(self):
        df = _ohlc()
        ob = _ob(top=1.106, bottom=1.100)  # full zone from previous engine
        ob_res = OrderBlockResult(events=(ob,), diagnostics=())
        new_res = recompute_zones(ob_res, df, mode="body")

        assert len(new_res.events) == 1
        e = new_res.events[0]
        # Body of idx=5 candle: open=1.106, close=1.100 → top=1.106, bottom=1.100
        # (in this case the OB's full top equals body top; but the OB might
        # carry full-range top/bottom that includes wicks).
        assert e.top <= ob.top
        assert e.bottom >= ob.bottom
        # With this fixture body endpoints are at [1.100, 1.106], so they
        # should match exactly.
        assert e.top == pytest.approx(1.106)
        assert e.bottom == pytest.approx(1.100)

    def test_body_mode_uses_origin_open_close(self):
        """When origin candle body endpoints differ from full range, body mode
        must use the BODY endpoints (max/min of open, close), not the wicks.
        """
        df = _ohlc()
        # An OB whose full range was [low, high] of origin — wider than body.
        ob = _ob(top=1.120, bottom=1.080)
        ob_res = OrderBlockResult(events=(ob,), diagnostics=())
        new_res = recompute_zones(ob_res, df, mode="body")
        e = new_res.events[0]
        # Body endpoints from idx=5: max(1.106, 1.100)=1.106, min(...)=1.100
        assert e.top == pytest.approx(1.106)
        assert e.bottom == pytest.approx(1.100)
        assert e.top < ob.top  # narrower
        assert e.bottom > ob.bottom  # narrower

    def test_body_mode_preserves_metadata(self):
        df = _ohlc()
        ob = _ob(top=1.106, bottom=1.100)
        ob_res = OrderBlockResult(events=(ob,), diagnostics=())
        new_res = recompute_zones(ob_res, df, mode="body")
        e = new_res.events[0]
        # Lifecycle metadata unchanged
        assert e.id == ob.id
        assert e.direction == ob.direction
        assert e.origin_pos == ob.origin_pos
        assert e.activation_pos == ob.activation_pos
        assert e.origin_timestamp == ob.origin_timestamp
        assert e.activation_timestamp == ob.activation_timestamp
        assert e.invalidation_timestamp == ob.invalidation_timestamp

    def test_invalid_mode_raises(self):
        df = _ohlc()
        ob = _ob(top=1.106, bottom=1.100)
        ob_res = OrderBlockResult(events=(ob,), diagnostics=())
        with pytest.raises(ValueError, match="mode must be one of"):
            recompute_zones(ob_res, df, mode="bogus")

    def test_empty_ob_result_handled(self):
        df = _ohlc()
        ob_res = OrderBlockResult(events=(), diagnostics=())
        assert recompute_zones(ob_res, df, mode="full") is ob_res
        new_res = recompute_zones(ob_res, df, mode="body")
        assert new_res.events == ()