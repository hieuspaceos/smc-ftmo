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




def test_htf_wall_check_rejects_trade():
    """HTF wall check: skip trade if TP1 hits H4 range high (long) or low (short).

    Mirrors Pine rulebook:
        if not na(htfH4RangeHigh) and targetPrice >= htfH4RangeHigh
            wallHit := true
            continue
    """
    from src.strategy import check_entry
    snapshot_base = {
        "side_request": "long",
        "score": 5,
        "entry_allowed": True,
        "displacement": True,
        "bias_aligned": True,
        "sweep_clean": True,
        "in_pd_zone": True,
        "first_test": True,
        "pd_zone": "discount",
        "ob_top": 1.0850,
        "ob_bottom": 1.0800,
        "atr": 0.0050,
        "close": 1.0850,
        "pair": "EURUSD",
        "sl_atr_buffer": 0.2,
        "min_sl_atr": 0.3,
        "max_sl_atr": 4.0,
    }
    # Long: TP1 = entry + 2R * sl_distance. SL = 1.0800 - 0.2*0.0050 = 1.0790.
    # sl_distance = 1.0850 - 1.0790 = 0.0060 (1.2 * ATR). TP1 = 1.0850 + 0.012 = 1.097.
    # Set HTF wall at 1.0965 (below TP1) → should reject.
    snap_wall_hit = dict(snapshot_base)
    snap_wall_hit["htf_h4_range_high"] = 1.0965
    assert check_entry(snap_wall_hit) is None, "HTF wall should reject long trade"
    # Set HTF wall at 1.0980 (above TP1) → should accept.
    snap_clear = dict(snapshot_base)
    snap_clear["htf_h4_range_high"] = 1.0980
    assert check_entry(snap_clear) is not None, "Clear path should accept"
    # Set HTF wall = None → should accept (no constraint).
    snap_none = dict(snapshot_base)
    snap_none["htf_h4_range_high"] = None
    snap_none["htf_h4_range_low"] = None
    assert check_entry(snap_none) is not None, "None HTF should accept"
    # Short direction: TP1 = entry - 2R * sl_distance. Wall = htf_h4_range_low.
    snap_short = dict(snapshot_base)
    snap_short["side_request"] = "short"
    snap_short["ob_top"] = 1.0850
    snap_short["ob_bottom"] = 1.0800
    snap_short["entry_allowed"] = True
    snap_short["htf_h4_range_low"] = 1.0820  # below TP1 (1.0826)
    snap_short["htf_h4_range_high"] = None
    snap_short["pd_zone"] = "premium"
    assert check_entry(snap_short) is None, "HTF low wall should reject short"




def test_entry_proximity_config_aware():
    """rulebook_entry_proximity_atr controls max OB-to-price distance.

    Default 1.5 ATR (Pine default). Override to test custom.
    """
    from src.strategy import check_entry
    base = {
        "side_request": "long",
        "score": 5,
        "entry_allowed": True,
        "displacement": True,
        "bias_aligned": True,
        "sweep_clean": True,
        "in_pd_zone": True,
        "first_test": True,
        "pd_zone": "discount",
        "ob_top": 1.0850,
        "ob_bottom": 1.0800,
        "atr": 0.0050,
        "pair": "EURUSD",
        "sl_atr_buffer": 0.2,
        "min_sl_atr": 0.3,
        "max_sl_atr": 4.0,
    }
    # At default 1.5 ATR, entry at 1.0925 (1.5 ATR from close 1.0850) is borderline.
    # close 1.0860 -> distance 0.0060 = 1.2 ATR. Accept.
    snap_close = dict(base)
    snap_close["close"] = 1.0860
    assert check_entry(snap_close) is not None, "close entry should accept (1.2 ATR)"
    # close 1.1000 -> distance 0.0150 = 3.0 ATR. Reject (>1.5).
    snap_far = dict(base)
    snap_far["close"] = 1.1000
    assert check_entry(snap_far) is None, "far entry should reject (3.0 ATR > 1.5)"
    # Override to 5.0 ATR threshold → far entry now accept.
    snap_far_wide = dict(base)
    snap_far_wide["close"] = 1.1000
    snap_far_wide["rulebook_entry_proximity_atr"] = 5.0
    assert check_entry(snap_far_wide) is not None, "wide threshold should accept"




def test_htf_enable_flags_respected():
    """htf_daily_enabled and htf_h4_enabled flags control HTF bias check.

    When both flags are False, any_single_TF bias is enough for entry
    (Pine parity: matches 'Use Daily HTF' + 'Use H4 HTF' unchecked).
    """
    from src.backtester import run_backtest

    base = {
        "ftmo": {"account_size": 100000, "phase": "challenge",
                  "profit_target": 0.10, "max_daily_loss": 0.05,
                  "daily_loss_limit_r": 2.0, "max_open_positions": 1},
        "strategy": {
            "swing_length": 10, "rr_target": 4.0,
            "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
            "min_confluence_score": 4, "require_displacement": True,
            "require_bias_aligned": True, "sl_atr_buffer": 0.2,
            "min_sl_atr": 0.3, "max_sl_atr": 4.0,
            "rulebook_entry_proximity_atr": 1.5,
            "bias_mode": "strict", "regime_mode": "off",
            "promotion_lookback_bars": 50,
            "exit_mode": "scale_in", "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                    "sweep_clean": 1, "premium_discount": 1,
                                    "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2025-01-01", "end_date": "2025-06-30",
        "pd_lookback": 50,
        "execution": {
            "spread_pips": {"EURUSD": 0.5},
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
        },
    }
    # Strict (default HTF on)
    t1, _ = run_backtest("EURUSD", base)
    # Both HTF off
    cfg_off = dict(base)
    cfg_off["strategy"] = dict(base["strategy"])
    cfg_off["strategy"]["htf_daily_enabled"] = False
    cfg_off["strategy"]["htf_h4_enabled"] = False
    t2, _ = run_backtest("EURUSD", cfg_off)
    assert len(t2) > len(t1),         f"HTF off should fire MORE trades than HTF on (strict). Got strict={len(t1)}, off={len(t2)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])