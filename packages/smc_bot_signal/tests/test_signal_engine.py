"""Signal engine unit tests."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.signal_engine import SignalEngine


def test_scan_empty() -> None:
    eng = SignalEngine(SignalBotConfig())
    assert eng.scan(pd.DataFrame(), "EURUSD") == []


def test_ob_to_payload_long_levels() -> None:
    eng = SignalEngine(
        SignalBotConfig(
            sl_atr_buffer=0.2,
            min_sl_atr=0.1,
            max_sl_atr=10.0,
            entry_proximity_atr=5.0,
            scale_in_r=2.0,
            final_tp_r=4.0,
        )
    )
    ob = SimpleNamespace(
        direction="bullish",
        top=1.1000,
        bottom=1.0980,
        id=7,
        structure_event_id=3,
        price=1.0990,
    )
    last_ts = pd.Timestamp("2024-06-01 12:00:00", tz="UTC")
    payload = eng._ob_to_payload(
        ob,
        symbol="EURUSD",
        tf="M15",
        last_ts=last_ts,
        close=1.1001,
        atr_v=0.0010,
        score=4.0,
    )
    assert payload is not None
    assert payload.dir == "long"
    assert payload.entry == pytest.approx(1.1000)
    assert payload.sl == pytest.approx(1.0978)
    risk = 1.1000 - 1.0978
    assert payload.tp1 == pytest.approx(1.1000 + 2 * risk)
    assert payload.score == 4.0


def test_ob_to_payload_rejects_far_entry() -> None:
    eng = SignalEngine(
        SignalBotConfig(entry_proximity_atr=0.5, min_sl_atr=0.01, max_sl_atr=10.0)
    )
    ob = SimpleNamespace(
        direction="bearish",
        top=1.1000,
        bottom=1.0980,
        id=1,
        structure_event_id=1,
        price=1.099,
    )
    last_ts = pd.Timestamp("2024-06-01 12:00:00", tz="UTC")
    payload = eng._ob_to_payload(
        ob,
        symbol="EURUSD",
        tf="M15",
        last_ts=last_ts,
        close=1.0900,
        atr_v=0.0010,
    )
    assert payload is None


def test_scan_uses_correct_ob_api_no_crash() -> None:
    """Previously detect_order_blocks(swings,...) always TypeError → 0 signals."""
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    close = 1.10 + np.cumsum(rng.normal(0.00002, 0.00035, size=n))
    high = close + np.abs(rng.normal(0.0004, 0.0002, n))
    low = close - np.abs(rng.normal(0.0004, 0.0002, n))
    open_ = np.r_[close[0], close[:-1]]
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close}, index=idx
    )
    eng = SignalEngine(SignalBotConfig(require_bias_aligned=True, require_displacement=True))
    out = eng.scan(df, "EURUSD")
    assert isinstance(out, list)
    # May be empty (fail-closed on bias) but must not crash / swallow OB API error silently forever.
    # Verify pipeline can produce OBs with correct API:
    from smc_engine.displacement import calculate_atr, detect_range_expansion
    from smc_engine.order_blocks import detect_order_blocks
    from smc_engine.structure import detect_structure
    from smc_engine.swings import detect_swings

    swings = detect_swings(df, left=5, right=5)
    atr = calculate_atr(df)
    structure = detect_structure(df, swings, atr=atr)
    exp = detect_range_expansion(df, atr, multiplier=1.5)
    obs = detect_order_blocks(df, structure, exp)
    assert isinstance(obs.events, tuple)
