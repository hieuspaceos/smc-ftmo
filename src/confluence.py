"""Confluence scoring per the user's 12 SMC trading rules.

A setup gets a score in 0..5 based on five criteria. Two criteria are
REQUIRED before any entry is allowed:

    1. Displacement  (candle range > 1.5x ATR)
    2. Bias aligned  (D and H4 bias both agree with trade direction)

The remaining three are additive bonuses:

    3. Sweep clean   (a liquidity sweep just occurred) OR breaker-with-CHoCH
    4. In P/D zone   (entry is in discount for longs, premium for shorts)
    5. First test    (untested OB/FVG; price hasn't mitigated the level yet)

Entry condition: score >= min_score (default 4) AND both required criteria
are True.

Stable public API (consumed by app.py and backtester):
    score_setup(setup: dict) -> (score:int, reasons:list[str], entry_allowed:bool)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


DEFAULT_MIN_SCORE = 4


def score_setup(
    setup: Dict[str, Any],
    min_score: int = DEFAULT_MIN_SCORE,
) -> Tuple[int, List[str], bool]:
    """Score a single setup dict against the 5-criteria confluence rules.

    Expected keys (booleans):
        displacement   : bool   REQUIRED
        bias_aligned   : bool   REQUIRED
        sweep_clean    : bool   bonus
        in_pd_zone     : bool   bonus
        first_test     : bool   bonus

    Optional keys:
        is_breaker_with_choch : bool   — substitute credit for sweep_clean
        pd_zone               : str    — used in the reason text only

    Returns:
        (score, reasons, entry_allowed)
        score          : int in [0, 5]
        reasons        : list[str] of human-readable reasons for the marks
        entry_allowed  : True iff score >= min_score AND both required criteria
                         are present
    """
    if not isinstance(setup, dict):
        raise TypeError(f"score_setup expects dict, got {type(setup).__name__}")

    displacement = bool(setup.get("displacement", False))
    bias_aligned = bool(setup.get("bias_aligned", False))
    sweep_clean = bool(setup.get("sweep_clean", False))
    in_pd_zone = bool(setup.get("in_pd_zone", False))
    first_test = bool(setup.get("first_test", False))
    is_breaker_with_choch = bool(setup.get("is_breaker_with_choch", False))

    score = 0
    reasons: List[str] = []

    # --- REQUIRED criteria ----------------------------------------------------
    if displacement:
        score += 1
        reasons.append("Displacement manh")
    if bias_aligned:
        score += 1
        reasons.append("Thuan Bias H4/Daily")

    # --- ADDITIVE bonus 1: sweep clean OR breaker + CHoCH --------------------
    if sweep_clean or is_breaker_with_choch:
        score += 1
        if sweep_clean:
            reasons.append("Sweep sach")
        else:
            reasons.append("CHoCH kem Breaker")

    # --- ADDITIVE bonus 2: in P/D zone --------------------------------------
    if in_pd_zone:
        score += 1
        pd_zone = setup.get("pd_zone")
        if pd_zone in ("premium", "discount"):
            reasons.append(f"Dung vung {pd_zone}")
        else:
            reasons.append("Dung vung Premium/Discount")

    # --- ADDITIVE bonus 3: first test (untouched level) ----------------------
    if first_test:
        score += 1
        reasons.append("Test lan dau, it mitigate")

    # --- ENTRY GATE ----------------------------------------------------------
    has_required = displacement and bias_aligned
    entry_allowed = has_required and (score >= min_score)

    return score, reasons, entry_allowed


def build_setup_dict(
    *,
    displacement: bool,
    bias_aligned: bool,
    sweep_clean: bool = False,
    in_pd_zone: bool = False,
    first_test: bool = False,
    is_breaker_with_choch: bool = False,
    pd_zone: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Helper to assemble a setup dict for the backtester / chart layers.

    Extra metadata can be attached via `extra` (merged into the result).
    """
    setup: Dict[str, Any] = {
        "displacement": bool(displacement),
        "bias_aligned": bool(bias_aligned),
        "sweep_clean": bool(sweep_clean),
        "in_pd_zone": bool(in_pd_zone),
        "first_test": bool(first_test),
        "is_breaker_with_choch": bool(is_breaker_with_choch),
    }
    if pd_zone is not None:
        setup["pd_zone"] = pd_zone
    if extra:
        setup.update(extra)
    return setup


def reasons_to_text(reasons: List[str]) -> str:
    """Render a reasons list as a single human-readable string."""
    if not reasons:
        return "no reasons"
    return ", ".join(reasons)


if __name__ == "__main__":
    # ------------------------------------------------------------------
    # Verification — covers all critical anchors:
    #   - displacement REQUIRED
    #   - bias_aligned REQUIRED
    #   - sweep_clean OR breaker-with-choch credit
    #   - entry_allowed = (score >= 4) AND both required
    # ------------------------------------------------------------------
    print("Testing confluence module...")

    # 1) Perfect 5/5 setup — all required + all bonuses
    perfect = build_setup_dict(
        displacement=True, bias_aligned=True,
        sweep_clean=True, in_pd_zone=True, first_test=True,
        pd_zone="discount",
    )
    score, reasons, allowed = score_setup(perfect)
    print(f"Perfect: score={score} reasons={reasons} allowed={allowed}")
    assert score == 5
    assert allowed is True
    assert len(reasons) == 5

    # 2) Missing required (displacement=False) → entry blocked even if 4 bonuses
    no_disp = build_setup_dict(
        displacement=False, bias_aligned=True,
        sweep_clean=True, in_pd_zone=True, first_test=True,
        pd_zone="discount",
    )
    score, reasons, allowed = score_setup(no_disp)
    print(f"No displacement: score={score} reasons={reasons} allowed={allowed}")
    assert score == 4
    assert allowed is False, "entry must be blocked when displacement is missing"

    # 3) Missing required (bias_aligned=False) → entry blocked
    no_bias = build_setup_dict(
        displacement=True, bias_aligned=False,
        sweep_clean=True, in_pd_zone=True, first_test=True,
        pd_zone="premium",
    )
    score, reasons, allowed = score_setup(no_bias)
    print(f"No bias aligned: score={score} reasons={reasons} allowed={allowed}")
    assert score == 4
    assert allowed is False, "entry must be blocked when bias_aligned is missing"

    # 4) Both required present but only 1 bonus → score 3 → blocked
    weak = build_setup_dict(
        displacement=True, bias_aligned=True,
        sweep_clean=True, in_pd_zone=False, first_test=False,
    )
    score, reasons, allowed = score_setup(weak)
    print(f"Weak (3/5): score={score} reasons={reasons} allowed={allowed}")
    assert score == 3
    assert allowed is False, "score 3 must not allow entry"

    # 5) Both required + 2 bonuses → score 4 → allowed
    four = build_setup_dict(
        displacement=True, bias_aligned=True,
        sweep_clean=False, in_pd_zone=True, first_test=True,
        pd_zone="discount",
    )
    score, reasons, allowed = score_setup(four)
    print(f"Four (4/5): score={score} reasons={reasons} allowed={allowed}")
    assert score == 4
    assert allowed is True

    # 6) Breaker-with-choch substitutes for sweep_clean
    breaker = build_setup_dict(
        displacement=True, bias_aligned=True,
        sweep_clean=False, in_pd_zone=True, first_test=True,
        is_breaker_with_choch=True, pd_zone="discount",
    )
    score, reasons, allowed = score_setup(breaker)
    print(f"Breaker: score={score} reasons={reasons} allowed={allowed}")
    assert score == 5
    assert allowed is True
    assert any("Breaker" in r for r in reasons)

    # 7) Custom min_score threshold
    custom = build_setup_dict(
        displacement=True, bias_aligned=True, first_test=True,
    )
    score, reasons, allowed = score_setup(custom, min_score=2)
    print(f"Custom min_score=2: score={score} allowed={allowed}")
    assert score == 3 and allowed is True

    blocked = score_setup(custom, min_score=5)
    print(f"Custom min_score=5: score={blocked[0]} allowed={blocked[2]}")
    assert blocked[2] is False

    # 8) Empty setup → score 0, blocked
    empty_score, empty_reasons, empty_allowed = score_setup({})
    print(f"Empty: score={empty_score} reasons={empty_reasons} allowed={empty_allowed}")
    assert empty_score == 0 and empty_allowed is False

    print("confluence verified.")