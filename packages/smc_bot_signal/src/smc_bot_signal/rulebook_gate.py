"""Entry gate mirroring ``src/confluence.score_setup`` + rule-book requireds.

Fail-closed: missing displacement or bias → no entry even if score looks high.
"""

from __future__ import annotations

from typing import Any


DEFAULT_MIN_SCORE = 4


def score_setup(
    setup: dict[str, Any],
    min_score: int = DEFAULT_MIN_SCORE,
) -> tuple[int, list[str], bool]:
    """Return (score, reasons, entry_allowed). Same contract as src/confluence."""
    if not isinstance(setup, dict):
        raise TypeError(f"score_setup expects dict, got {type(setup).__name__}")

    displacement = bool(setup.get("displacement", False))
    bias_aligned = bool(setup.get("bias_aligned", False))
    sweep_clean = bool(setup.get("sweep_clean", False))
    in_pd_zone = bool(setup.get("in_pd_zone", False))
    first_test = bool(setup.get("first_test", False))
    is_breaker_with_choch = bool(setup.get("is_breaker_with_choch", False))

    score = 0
    reasons: list[str] = []

    if displacement:
        score += 1
        reasons.append("Displacement manh")
    if bias_aligned:
        score += 1
        reasons.append("Thuan Bias H4/Daily")
    if sweep_clean or is_breaker_with_choch:
        score += 1
        reasons.append("Sweep sach" if sweep_clean else "CHoCH kem Breaker")
    if in_pd_zone:
        score += 1
        pd_zone = setup.get("pd_zone")
        if pd_zone in ("premium", "discount"):
            reasons.append(f"Dung vung {pd_zone}")
        else:
            reasons.append("Dung vung Premium/Discount")
    if first_test:
        score += 1
        reasons.append("Test lan dau, it mitigate")

    has_required = displacement and bias_aligned
    entry_allowed = has_required and (score >= min_score)
    return score, reasons, entry_allowed
