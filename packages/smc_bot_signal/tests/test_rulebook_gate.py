"""Rule-book gate unit tests — fail-closed."""

from __future__ import annotations

from smc_bot_signal.rulebook_gate import score_setup


def test_requires_displacement_and_bias() -> None:
    score, _, allowed = score_setup(
        {
            "displacement": False,
            "bias_aligned": True,
            "sweep_clean": True,
            "in_pd_zone": True,
            "first_test": True,
        },
        min_score=4,
    )
    assert score == 4
    assert allowed is False


def test_score_4_with_requireds_allows() -> None:
    score, reasons, allowed = score_setup(
        {
            "displacement": True,
            "bias_aligned": True,
            "sweep_clean": True,
            "in_pd_zone": False,
            "first_test": True,
        },
        min_score=4,
    )
    assert score == 4
    assert allowed is True
    assert any("Displacement" in r for r in reasons)


def test_score_3_blocks() -> None:
    score, _, allowed = score_setup(
        {
            "displacement": True,
            "bias_aligned": True,
            "sweep_clean": False,
            "in_pd_zone": False,
            "first_test": True,
        },
        min_score=4,
    )
    assert score == 3
    assert allowed is False
