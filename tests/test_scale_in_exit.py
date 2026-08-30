"""Unit tests for ScaleInExit — 5 scenarios."""
import math
from src.scale_in_exit import ScaleInExit


# LONG side: entry=1.1000, sl=1.0950 (1R=10pips below entry)


def test_long_hit_4r_full():
    """Price hits 2R then 4R — full scale-in success."""
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")

    # Walk to 2R (1.1100)
    actions = ex.update(1.1100)
    assert ("close_pct", 0.5) in actions
    assert ("move_sl", 1.1000) in actions
    # open_leg2 with (0.5, 1.1000, 1.1200)
    leg2_action = [a for a in actions if a[0] == "open_leg2"][0]
    assert leg2_action[1] == 0.5  # lot
    assert leg2_action[2] == 1.1000  # SL = entry (BE)
    assert math.isclose(leg2_action[3], 1.1200, abs_tol=1e-9)  # TP = +4R
    assert ex.state == "phase2"

    # Walk to 4R (1.1200)
    actions = ex.update(1.1200)
    assert ("close_leg2",) in actions
    assert ("closed", "tp4r") in actions
    assert ex.closed
    # Realized: 1R (locked) + 2R (leg1 rem) + 1R (leg2) = 4R
    assert math.isclose(ex.realized_r, 4.0, abs_tol=1e-6)


def test_long_leg2_sl_after_2r_leg1_still_runs_to_4r():
    """Leg2 SL hit at entry, leg1 remaining hits 4R — total = +2R."""
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")

    # Trigger scale-in at 2R
    ex.update(1.1100)
    assert ex.state == "phase2"

    # Leg2 SL @ entry (1.1000) — cascade both close
    actions = ex.update(1.1000)
    # Both leg1 remaining (at entry) and leg2 (at entry) close
    # Trade closes with realized: +1R (locked) - 1R (leg2 SL) = 0
    assert ("closed", "leg2_sl") in actions
    assert ex.closed
    assert math.isclose(ex.realized_r, 0.0, abs_tol=1e-6)


def test_long_sl_before_2r():
    """SL hits before scale-in triggers — leg1 only, -1R loss."""
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")

    # Price hits SL directly (1.0950)
    actions = ex.update(1.0950)
    assert ("closed", "sl") in actions
    assert ex.closed
    assert math.isclose(ex.realized_r, -1.0, abs_tol=1e-6)


def test_short_hit_4r_full():
    """SHORT symmetry: hit -2R then -4R."""
    ex = ScaleInExit(entry=1.1000, sl=1.1050, side="short")

    # Walk to -2R (1.0900)
    actions = ex.update(1.0900)
    assert ("close_pct", 0.5) in actions
    assert ("move_sl", 1.1000) in actions
    leg2_action = [a for a in actions if a[0] == "open_leg2"][0]
    assert leg2_action[2] == 1.1000  # SL = entry (BE)
    assert math.isclose(leg2_action[3], 1.0800, abs_tol=1e-9)  # TP = -4R
    assert ex.state == "phase2"

    # Walk to -4R (1.0800)
    actions = ex.update(1.0800)
    assert ("close_leg2",) in actions
    assert ("closed", "tp4r") in actions
    assert math.isclose(ex.realized_r, 4.0, abs_tol=1e-6)


def test_short_sl_before_2r():
    """SHORT SL hits before scale-in — -1R loss."""
    ex = ScaleInExit(entry=1.1000, sl=1.1050, side="short")

    actions = ex.update(1.1050)
    assert ("closed", "sl") in actions
    assert math.isclose(ex.realized_r, -1.0, abs_tol=1e-6)


def test_long_leg2_sl_at_entry_only():
    """After scale-in, price dips to entry (leg2 SL hit) but leg1 still alive at BE.
    Per design: cascade both close at entry → total = 0 (breakeven).
    """
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")

    # Hit 2R → scale-in
    ex.update(1.1100)

    # Price returns exactly to entry
    actions = ex.update(1.1000)
    # Cascade close both legs at entry
    assert ("closed", "leg2_sl") in actions
    # Realized: 1R (leg1 partial close) - 1R (leg2 loss at 0.5*2R distance) = 0
    assert math.isclose(ex.realized_r, 0.0, abs_tol=1e-6)


def test_validation_invalid_side():
    import pytest
    with pytest.raises(ValueError, match="side"):
        ScaleInExit(entry=1.0, sl=0.9, side="invalid")


def test_validation_zero_sl_distance():
    import pytest
    with pytest.raises(ValueError, match="differ"):
        ScaleInExit(entry=1.0, sl=1.0, side="long")


def test_long_sl_gap_overshoot_caps_at_minus_1r():
    """Regression: SL gap-overshoot (bar opens/closes well past SL) must cap
    loss at exactly -1R. Without the cap, a -1.8R close would over-debit.
    """
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")
    # Bar closes 50 pips below SL → r = -5.0 mathematically, but SL hit
    # means we exit at the SL price, i.e. -1R.
    actions = ex.update(1.0850)
    assert ("closed", "sl") in actions
    assert math.isclose(ex.realized_r, -1.0, abs_tol=1e-6), (
        f"SL gap must cap at -1R, got {ex.realized_r}"
    )

def test_long_phase1_trigger_overshoot_caps_partial_at_scale_in_r():
    """Regression: when the scale-in trigger bar overshoots 2R (e.g. closes
    at 2.5R), the partial close must realize at scale_in_r (2R), NOT at the
    overshoot r. Otherwise total PnL compounds above the 4R cap.
    """
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")
    # Bar closes at 2.5R (1.1250)
    actions = ex.update(1.1250)
    # Partial close should be capped at scale_in_r → 0.5 * 2 = 1.0R
    assert math.isclose(ex.realized_r, 1.0, abs_tol=1e-6), (
        f"phase1 overshoot must cap partial at +1R, got {ex.realized_r}"
    )
    # Now finish to 4R TP — total must be exactly 4R.
    actions = ex.update(1.1200)
    assert ("closed", "tp4r") in actions
    assert math.isclose(ex.realized_r, 4.0, abs_tol=1e-6), (
        f"overshoot scenario must still sum to 4R, got {ex.realized_r}"
    )



def test_long_tp_overshoot_caps_at_final_tp_r():
    """Regression: runaway trends where price overshoots TP must NOT over-credit
    PnL. Cap leg1 remaining + leg2 at final_tp_r (4R) regardless of how far
    the bar close actually is. With phase1 locked at +1R and phase2 legs
    capped: 1 + 0.5*4 + 0.5*(4-2) = 4R total.
    """
    ex = ScaleInExit(entry=1.1000, sl=1.0950, side="long")

    # Trigger scale-in at 2R (1.1100)
    ex.update(1.1100)
    assert ex.state == "phase2"

    # Bar overshoots to 5.5R (1.1550) — TP must still cap at 4R.
    actions = ex.update(1.1550)
    assert ("closed", "tp4r") in actions
    assert math.isclose(ex.realized_r, 4.0, abs_tol=1e-6), (
        f"overshoot must cap at 4R, got {ex.realized_r}"
    )



def test_design_b_long_tp1_then_tp4r():
    """Design B: hit 2R (open leg2), 3R (TP1 50% leg2), 4R (final TP).
    Total: 1R (phase1) + 2R (leg1 rem) + 0.25R (leg2 TP1) + 0.5R (leg2 rem) = 3.75R.
    """
    ex = ScaleInExit(
        entry=1.1000, sl=1.0950, side="long", leg2_tp1_r=3.0
    )
    # 2R
    ex.update(1.1100)
    assert ex.state == "phase2"
    # 3R — TP1 fires
    actions = ex.update(1.1150)
    assert ("leg2_tp1",) in actions
    assert ("close_leg2_partial", 0.25) in actions
    move_leg2_actions = [a for a in actions if a[0] == "move_leg2_sl"]
    assert len(move_leg2_actions) == 1
    assert math.isclose(move_leg2_actions[0][1], 1.1150, abs_tol=1e-9)
    assert ex.leg2_tp1_hit is True
    assert math.isclose(ex.realized_r, 1.25, abs_tol=1e-6), (
        f"after TP1 expected +1.25R (1R phase1 + 0.25R leg2 TP1), got {ex.realized_r}"
    )
    # 4R — final TP closes leg1 rem + leg2 rem
    actions = ex.update(1.1200)
    assert ("closed", "tp4r") in actions
    assert math.isclose(ex.realized_r, 3.75, abs_tol=1e-6), (
        f"Design B hit-4R expected +3.75R, got {ex.realized_r}"
    )


def test_design_b_long_tp1_then_cascade_saves_partial():
    """Design B: hit 2R (open leg2), 3R (TP1), then reverse to entry.
    After TP1, leg2 SL moves to 3R — cascade closes leg2 rem at that
    locked price, not at entry. Saved from 0R (Design A) to +1.5R.
    """
    ex = ScaleInExit(
        entry=1.1000, sl=1.0950, side="long", leg2_tp1_r=3.0
    )
    ex.update(1.1100)  # 2R — open leg2
    ex.update(1.1150)  # 3R — TP1: +0.25R locked, leg2 SL → 1.1150
    # Now reverse to entry — cascade leg1 rem + leg2 rem
    actions = ex.update(1.1000)
    assert ("closed", "leg2_sl") in actions
    # 1R (phase1) + 0.25R (leg2 TP1) + 0R (leg1 rem at BE) + 0.25R (leg2 rem
    # closes at locked SL=1.1150, profit 1R × 0.25 lot) = +1.5R
    assert math.isclose(ex.realized_r, 1.5, abs_tol=1e-6), (
        f"Design B cascade-after-TP1 expected +1.5R, got {ex.realized_r}"
    )



def test_design_b_immediate_cascade_no_tp1():
    """Design B: hit 2R, immediately reverse to entry (skip TP1).
    Behaves like Design A: 0R total (1R locked - 1R leg2 loss).
    """
    ex = ScaleInExit(
        entry=1.1000, sl=1.0950, side="long", leg2_tp1_r=3.0
    )
    ex.update(1.1100)  # 2R — open leg2
    actions = ex.update(1.1000)  # immediate cascade
    assert ("closed", "leg2_sl") in actions
    assert ex.leg2_tp1_hit is False
    assert math.isclose(ex.realized_r, 0.0, abs_tol=1e-6), (
        f"immediate cascade expected 0R, got {ex.realized_r}"
    )


def test_design_b_default_unchanged():
    """Backward compat: leg2_tp1_r=None (default) = Design A behavior."""
    ex_a = ScaleInExit(entry=1.1000, sl=1.0950, side="long", leg2_tp1_r=None)
    ex_default = ScaleInExit(entry=1.1000, sl=1.0950, side="long")
    # Walk to 3R — neither should trigger any TP1 action
    actions_a = ex_a.update(1.1150)
    actions_d = ex_default.update(1.1150)
    assert not any(a[0] == "leg2_tp1" for a in actions_a)
    assert not any(a[0] == "leg2_tp1" for a in actions_d)
    # Both should still be in phase2
    assert ex_a.state == "phase2"
    assert ex_default.state == "phase2"



if __name__ == "__main__":
    test_long_hit_4r_full()
    test_long_leg2_sl_after_2r_leg1_still_runs_to_4r()
    test_long_sl_before_2r()
    test_short_hit_4r_full()
    test_short_sl_before_2r()
    test_long_leg2_sl_at_entry_only()
    test_validation_invalid_side()
    test_validation_zero_sl_distance()
    test_long_sl_gap_overshoot_caps_at_minus_1r()
    test_long_phase1_trigger_overshoot_caps_partial_at_scale_in_r()
    test_long_tp_overshoot_caps_at_final_tp_r()
    print("All ScaleInExit tests passed.")