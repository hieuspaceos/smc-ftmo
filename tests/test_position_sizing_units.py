"""Regression tests for calculate_lot() unit handling.

Bug history (2026-08-31): src/backtester.py:648 passed price-distance
(0.0050 for 50-pip EURUSD SL) directly to calculate_lot(), but the
function expects pips. Result: lot sized ~10000x larger than intended
(1.10 lots intended, 11000 lots actual), invalidating all backtest
USD figures.

Fix: convert price-distance to pips via pip_size_for_pair() before
calling calculate_lot().

These tests pin the contract so the bug cannot regress.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Allow `python tests/test_position_sizing_units.py` direct invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from risk_manager import calculate_lot
from strategy import pip_size_for_pair


# ---------------------------------------------------------------------------
# Pure calculate_lot() contract — uses pips as documented.
# ---------------------------------------------------------------------------


def test_calculate_lot_smoke_value_50_pips_eurusd():
    """Smoke value from risk_manager.py: 50-pip SL → 1.10 lots."""
    # 100k * 0.55% / (50 pips * $10/lot/pip) = 550 / 500 = 1.10
    assert calculate_lot(100000, 0.0055, 50, 10) == 1.10


def test_calculate_lot_minimum_lot_floor():
    """Tiny risk or huge SL → 0.005 lots → floor at 0.01."""
    assert calculate_lot(100000, 0.0001, 100, 10) == 0.01


def test_calculate_lot_zero_sl_returns_minimum():
    """Defensive: zero/negative SL must not crash or return 0."""
    assert calculate_lot(100000, 0.0055, 0, 10) == 0.01
    assert calculate_lot(100000, 0.0055, -5, 10) == 0.01


def test_calculate_lot_zero_pip_value_returns_minimum():
    """Defensive: zero pip_value must not crash."""
    assert calculate_lot(100000, 0.0055, 50, 0) == 0.01


def test_calculate_lot_scales_with_risk_pct():
    """Doubling risk_pct should double lot size (all else equal)."""
    a = calculate_lot(100000, 0.0055, 50, 10)
    b = calculate_lot(100000, 0.0110, 50, 10)
    assert math.isclose(b, a * 2, rel_tol=1e-9)


def test_calculate_lot_inverse_with_sl_pips():
    """Halving SL pips should double lot size (inverse relationship)."""
    a = calculate_lot(100000, 0.0055, 50, 10)
    b = calculate_lot(100000, 0.0055, 25, 10)
    assert math.isclose(b, a * 2, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# pip_size_for_pair() — used by backtester to convert price → pips.
# ---------------------------------------------------------------------------


def test_pip_size_eurusd():
    """EURUSD 5-digit broker: 1 pip = 0.0001."""
    assert pip_size_for_pair("EURUSD") == 0.0001


def test_pip_size_xauusd():
    """XAUUSD 2-digit quote (e.g. 2650.50): 1 pip = 0.01 by SMC convention."""
    assert pip_size_for_pair("XAUUSD") == 0.01


def test_pip_size_btcusd():
    """BTCUSD USD quote (e.g. 65000): 1 pip = 1.0 (whole USD)."""
    assert pip_size_for_pair("BTCUSD") == 1.0


def test_pip_size_unknown_pair_falls_back_to_fx():
    """Unknown pair → FX default 0.0001 (not crash)."""
    assert pip_size_for_pair("XYZABC") == 0.0001


def test_pip_size_case_insensitive():
    assert pip_size_for_pair("eurusd") == 0.0001
    assert pip_size_for_pair("EurUsd") == 0.0001


# ---------------------------------------------------------------------------
# The bug regression — verify the corrected unit conversion.
# ---------------------------------------------------------------------------


def test_bug_regression_price_to_pips_conversion_eurusd():
    """The exact scenario from the bug report.

    50-pip SL on EURUSD expressed as price-distance = 0.0050.
    After correct conversion: 0.0050 / 0.0001 = 50 pips → 1.10 lots.
    Before fix: passing 0.0050 directly → 11,000 lots (10000x off).
    """
    sl_dist_price = 0.0050  # 50 pips in EURUSD price units
    pip_size = pip_size_for_pair("EURUSD")
    sl_dist_pips = sl_dist_price / pip_size
    lot = calculate_lot(100000, 0.0055, sl_dist_pips, 10)
    assert lot == 1.10
    # Pin the factor that broke: passing price directly must NOT give 1.10.
    broken_lot = calculate_lot(100000, 0.0055, sl_dist_price, 10)
    assert broken_lot != lot
    assert broken_lot == 11000.0  # The bug: 10000x too large.


def test_bug_regression_price_to_pips_conversion_xauusd():
    """XAUUSD: 100-pip SL = $1.00 price distance → 0.55 lots @ 0.55% / $100k."""
    # XAUUSD: 1 pip = 0.01, pip_value = $1/lot/pip
    # Risk $550 on 100-pip SL → lot = 550 / (100 * 1) = 5.5
    sl_dist_price = 1.00  # 100 pips in XAUUSD price (0.01 each)
    pip_size = pip_size_for_pair("XAUUSD")
    sl_dist_pips = sl_dist_price / pip_size
    lot = calculate_lot(100000, 0.0055, sl_dist_pips, 1.0)
    assert lot == 5.5


def test_bug_regression_real_dollar_risk_within_target():
    """Real dollar risk must match intended risk_pct of account.

    This is the ultimate invariant: a $100k account with 0.55% risk
    targeting a 50-pip SL should risk exactly $550, not $5,500,000.
    """
    account = 100000.0
    risk_pct = 0.0055
    pip_value = 10.0  # EURUSD
    sl_pips = 50

    lot = calculate_lot(account, risk_pct, sl_pips, pip_value)
    actual_dollar_risk = lot * sl_pips * pip_value
    intended_dollar_risk = account * risk_pct

    # Must be within $1 (rounding to 0.01 lot)
    assert math.isclose(actual_dollar_risk, intended_dollar_risk, abs_tol=1.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
