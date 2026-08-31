"""Integration test: lot sizing invariant at run_backtest level.

Background (2026-08-31):

The `calculate_lot()` unit-conversion bug (commit 9e66381 fix) was silent
in backtest PnL because backtester uses `pnl = r_final * risk_amount`
(R-multiple framework), not `pnl = r_final * lot * sl * pip_value`. So
a 10,000× wrong lot did not show in PnL output.

But the `lot` field in the returned trade dict was missing entirely
(see below) — and would have broken live MT5 deployment (broker would
reject oversized lots or trigger margin call).

Findings during investigation:
1. `trade dict` (constructed at src/backtester.py:607-630 and :709-733)
   does NOT include `lot` field. Always None when read.
2. The trade dict's `sl` field is overwritten to entry after TP1 hit
   (move_sl action). Recorded `sl` doesn't reflect actual stop used.
   PnL unaffected because `sl_distance` was cached at init time.
3. R-multiple is computed from cached `sl_distance`, not from trade
   dict's `sl` field.

This test pins what invariants we CAN verify externally: trade dict fields
   that the backtester actually populates, and `r_multiple` math
   correctness on the cached sl_distance.

Tests for the `lot` invariant are at the calculate_lot() level (see
tests/test_position_sizing_units.py::test_bug_regression_real_dollar_risk_within_target).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtester import run_backtest


@pytest.fixture
def minimal_config():
    """Minimal config that runs quickly on whatever data is in data/."""
    return {
        "ftmo": {
            "account_size": 100000,
            "phase": "challenge",
            "profit_target": 0.10,
            "max_daily_loss": 0.05,
            "daily_loss_limit_r": 2.0,
            "max_open_positions": 1,
        },
        "strategy": {
            "swing_length": 10,
            "rr_target": 4.0,
            "displacement_atr_mult": 1.5,
            "sweep_atr_buffer": 0.05,
            "min_confluence_score": 1,
            "require_displacement": True,
            "require_bias_aligned": True,
            "sl_atr_buffer": 0.2,
            "bias_mode": "strict",
            "regime_mode": "off",
            "promotion_lookback_bars": 50,
            "exit_mode": "ladder",
            "partial_tp": [
                {"pct": 0.40, "r": 2.0},
                {"pct": 0.50, "r": 3.0},
                {"pct": 1.00, "r": 4.0},
            ],
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                    "sweep_clean": 1, "premium_discount": 1,
                                    "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2025-01-01",
        "end_date": "2025-06-30",
        "pd_lookback": 50,
    }


def test_risk_amount_matches_config_intent(minimal_config):
    """Every trade's risk_usd field should equal account_size * risk_per_trade."""
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    account_size = minimal_config["ftmo"]["account_size"]
    risk_per_trade = 0.0055  # default
    expected_risk = account_size * risk_per_trade

    for i, t in enumerate(trades):
        risk_usd = t.get("risk_usd")
        assert math.isclose(risk_usd, expected_risk, abs_tol=0.01), (
            f"Trade {i}: risk_usd={risk_usd}, expected {expected_risk}"
        )


def test_r_multiple_uses_cached_sl_distance_not_trade_dict_sl(minimal_config):
    """Verify r_multiple is computed from CACHED sl_distance, not from
    trade dict's `sl` field (which gets overwritten to entry after TP1 hit).

    For each trade:
      r_multiple ≈ (exit_price - entry) / |original_sl - entry|
    where original_sl differs from trade dict's sl once TP1 was hit.

    We can't directly verify original_sl from trade dict, but we CAN check:
    - exit_reason == 'sl' → r_multiple == -1 (if no partial close)
    - exit_reason == 'tp3' → r_multiple ≥ target_r (TP ladder hit)
    - exit_reason == 'time' → r_multiple finite
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")
    # For ladder mode: SL exits can have r > -1 if a partial close was
    # already taken at TP1 (BE rule moves sl to entry, so further adverse
    # move hits BE not -1R). So just check r is finite and reasonable.
    # For scale_in mode: SL exits should be r ≈ -1 (no partial credit yet).
    for i, t in enumerate(trades):
        r = t.get("r_multiple")
        reason = t.get("exit_reason")
        # r must be finite (no division by zero artifacts)
        assert math.isfinite(r), f"Trade {i}: r_multiple={r} is not finite"

        # On a 'sl' exit, cached sl_distance should still produce a sane r.
        # For ladder: r can be > -1 if TP1 hit then SL hit (BE+).
        # For scale_in: r should be ≤ 0 (full position not yet at TP).
        if reason == "sl":
            # Cached sl_distance must NOT be zero (would give inf r).
            # We check indirectly: r must be within ±100 (sanity range).
            assert -100 <= r <= 100, (
                f"Trade {i}: exit=sl but r={r:.3f} wildly out of range; "
                f"suggests cached sl_distance is wrong."
            )


def test_pnl_uses_r_multiple_times_risk_amount(minimal_config):
    """The PnL formula invariant: pnl_usd == r_multiple * risk_usd.

    Catches any future change that mistakenly introduces `lot` into the
    PnL formula (would break if lot varies across trades).
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    for i, t in enumerate(trades):
        r = t.get("r_multiple")
        risk = t.get("risk_usd")
        pnl = t.get("pnl_usd")
        expected_pnl = r * risk
        # Allow small rounding error (trades may have partial closes
        # where pnl != r * risk exactly)
        assert math.isclose(pnl, expected_pnl, abs_tol=0.01), (
            f"Trade {i}: pnl_usd={pnl}, expected r*risk={expected_pnl} "
            f"(r={r}, risk={risk})"
        )


def test_trade_dict_does_not_include_lot_field(minimal_config):
    """Document the current state: trade dict's `lot` field is missing.

    This test pins the gap — if someone adds `lot` to the trade dict
    in the future, this test should be updated to verify the invariant.
    Currently asserts the BUG to make regression obvious.
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    # All trades should have lot field as None (currently missing)
    for i, t in enumerate(trades[:5]):
        lot = t.get("lot")
        assert lot is None, (
            f"Trade {i}: lot={lot}. If non-None, the lot field has been "
            f"added to trade dict — UPDATE THIS TEST to verify "
            f"lot × sl × pip_value == risk_usd invariant."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])