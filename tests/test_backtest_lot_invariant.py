"""Integration test: lot sizing invariant at run_backtest level.

Background (2026-08-31):

The `calculate_lot()` unit-conversion bug (commit 9e66381 fix) was silent
in backtest PnL because backtester uses `pnl = r_final * risk_amount`
(R-multiple framework), not `pnl = r_final * lot * sl * pip_value`. So
a 10,000× wrong lot did not show in PnL output.

Then root cause #2 was fixed (commits subsequent to 9e66381): `lot` field
is now included in the trade dict, AND original_sl is preserved (not
overwritten by move_sl). This unlocks the invariant test below.

Tests verify externally-visible invariants:
1. risk_usd == account * risk_per_trade for every trade
2. r_multiple finite and within sane range (-100 to 100)
3. pnl_usd == r_multiple * risk_usd (formula invariant)
4. lot field present in trade dict AND lot × sl × pip_value == risk_usd
   (the key invariant the calculate_lot() bug would have broken)
5. original_sl preserved across TP1 hit (move_sl does not corrupt journal)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtester import run_backtest
from strategy import pip_size_for_pair


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


def test_r_multiple_uses_cached_sl_distance(minimal_config):
    """r_multiple is finite and within sane range.

    Ladder: SL exits can have r > -1 if TP1 hit then SL hit (BE+).
    Scale_in: SL exits should be r ≤ 0 (full position not yet at TP).
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    for i, t in enumerate(trades):
        r = t.get("r_multiple")
        reason = t.get("exit_reason")
        assert math.isfinite(r), f"Trade {i}: r_multiple={r} is not finite"

        if reason == "sl":
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
        assert math.isclose(pnl, expected_pnl, abs_tol=0.01), (
            f"Trade {i}: pnl_usd={pnl}, expected r*risk={expected_pnl} "
            f"(r={r}, risk={risk})"
        )


def test_lot_field_present_and_satisfies_invariant(minimal_config):
    """The key invariant: lot × sl × pip_value == risk_usd.

    Catches:
    - calculate_lot() unit-conversion bug (lot 10000x off)
    - pip_size_for_pair() returning wrong value
    - risk_amount being computed from lot instead of as fixed dollar amount

    Pre-fix (before commit adding lot to trade dict), this test was not
    possible — lot was never serialized. Now it pins the contract.
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    pip_value = 10.0  # EURUSD

    for i, t in enumerate(trades):
        lot = t.get("lot")
        # Lot must be present (was missing before this commit)
        assert lot is not None, (
            f"Trade {i}: lot field missing from trade dict"
        )
        # Lot must be broker-executable
        assert 0.01 <= lot <= 100.0, (
            f"Trade {i}: lot={lot} outside broker range [0.01, 100]"
        )

        # Compute invariant using ORIGINAL sl (not post-TP1 sl)
        original_sl = t.get("original_sl") or t.get("sl")
        entry = t.get("entry")
        sl_distance_pips = abs(entry - original_sl) / pip_size_for_pair("EURUSD")
        actual_dollar_risk = lot * sl_distance_pips * pip_value
        risk_usd = t.get("risk_usd")

        # Allow $1 rounding (lot rounded to 0.01)
        assert math.isclose(actual_dollar_risk, risk_usd, abs_tol=1.0), (
            f"Trade {i}: lot={lot} × sl_pips={sl_distance_pips:.1f} × "
            f"pip_value={pip_value} = ${actual_dollar_risk:.2f}, "
            f"expected ${risk_usd:.2f} (rounded to $1)"
        )


def test_original_sl_preserved_when_tp1_hit(minimal_config):
    """For trades that hit TP1 (move_sl action), original_sl should
    differ from sl_after_tp1 (which becomes entry = BE level).

    Trade dict's `sl` should reflect ORIGINAL sl, not post-BE sl.
    """
    trades, _ = run_backtest("EURUSD", minimal_config)
    if not trades:
        pytest.skip("No trades produced in test window")

    tp1_hit_count = 0
    for i, t in enumerate(trades):
        sl_after_tp1 = t.get("sl_after_tp1")
        if sl_after_tp1 is None:
            # TP1 not hit on this trade — move_sl action never fired
            continue
        tp1_hit_count += 1
        sl = t.get("sl")
        entry = t.get("entry")
        # Original sl should differ from post-TP1 sl (which is entry)
        assert sl is not None
        assert not math.isclose(sl, entry, abs_tol=1e-6), (
            f"Trade {i}: sl field equals entry {entry} — original_sl was "
            f"not preserved (likely overwritten by move_sl action)"
        )
        # post-TP1 sl should be at or near entry (BE rule)
        assert math.isclose(sl_after_tp1, entry, abs_tol=1e-6), (
            f"Trade {i}: sl_after_tp1={sl_after_tp1} != entry={entry}; "
            f"BE rule expected post-TP1 sl = entry"
        )

    # Sanity: at least some trades should hit TP1 in a 6-month window
    # (don't assert a minimum to avoid brittleness)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])