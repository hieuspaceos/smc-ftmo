"""Multi-timeframe bias detector.

Computes per-TF bias from the in-project SMC engine, then aligns Daily + H4
into one of: aligned_long, aligned_short, stand_aside.

Stable public API:
    detect_bias(df, swing_length=20) -> 'bull' | 'bear' | None
    detect_premium_discount(df, lookback=50) -> dict with keys
        zone, equilibrium, range_high, range_low, current_price
    score_setup(setup: dict) -> (score:int, reasons:list[str], entry_allowed:bool)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from smc_engine.context import (
    compute_dealing_range_context,
    compute_bias_series,
    context_snapshot,
    is_in_pd_zone as _is_in_pd_zone,
)
from smc_engine.displacement import calculate_atr
from smc_engine.structure import detect_structure
from smc_engine.swings import detect_swings

VALID_BIAS = {"bull", "bear", "neutral"}


def detect_bias(df: pd.DataFrame, swing_length: int = 20) -> Optional[str]:
    """Return 'bull' | 'bear' | None for one TF from the latest structure event.

    Uses the in-project SMC engine: confirmed swings → structure state
    machine → trend Series. Returns the trend at the last bar.
    """
    if df is None or df.empty:
        return None

    left = right = max(2, swing_length // 2)
    try:
        swings = detect_swings(df, left=left, right=right)
    except (ValueError, TypeError):
        return None
    if len(swings.events) == 0:
        return None

    structure = detect_structure(df, swings)
    bias_series = compute_bias_series(structure)
    last = bias_series.iloc[-1]
    if last == "bull":
        return "bull"
    if last == "bear":
        return "bear"
    return None


def compute_bias_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Convenience wrapper to expose ATR for chart annotations."""
    return calculate_atr(df, period=period)


detect_bias_atr = compute_bias_atr

def detect_bias_multi_tf(
    data: Dict[str, pd.DataFrame], swing_length: int = 20
) -> Dict[str, Optional[str]]:
    """Compute bias for each TF present in `data`."""
    result: Dict[str, Optional[str]] = {}
    for tf in ("D", "H4", "H1", "M15"):
        df = data.get(tf)
        if df is None or df.empty:
            result[tf] = None
            continue
        result[tf] = detect_bias(df, swing_length=swing_length)
    return result


def align_bias(bias_by_tf: Dict[str, Optional[str]]) -> str:
    bias_d = bias_by_tf.get("D")
    bias_h4 = bias_by_tf.get("H4")

    if bias_d == "bull" and bias_h4 == "bull":
        return "aligned_long"
    if bias_d == "bear" and bias_h4 == "bear":
        return "aligned_short"
    return "stand_aside"


def bias_panel(bias_by_tf: Dict[str, Optional[str]]) -> Dict[str, str]:
    panel = {}
    for tf in ("D", "H4", "H1", "M15"):
        b = bias_by_tf.get(tf)
        if b == "bull":
            panel[tf] = "Bull"
        elif b == "bear":
            panel[tf] = "Bear"
        else:
            panel[tf] = "Neutral"
    return panel


def trade_direction(bias_by_tf: Dict[str, Optional[str]]) -> Optional[str]:
    aligned = align_bias(bias_by_tf)
    if aligned == "aligned_long":
        return "long"
    if aligned == "aligned_short":
        return "short"
    return None


def is_bias_aligned(
    direction: str, bias_by_tf: Dict[str, Optional[str]]
) -> bool:
    if direction == "long":
        return align_bias(bias_by_tf) == "aligned_long"
    if direction == "short":
        return align_bias(bias_by_tf) == "aligned_short"
    return False


def bias_to_series(bias_by_tf: Dict[str, Optional[str]]) -> pd.Series:
    return pd.Series(bias_by_tf, name="bias")


def detect_premium_discount(df, lookback: int = 50, price=None):
    """Compatibility wrapper using the structure dealing-range context."""
    if df is None or df.empty:
        return {
            "zone": "neutral",
            "equilibrium": 0.0,
            "range_high": 0.0,
            "range_low": 0.0,
            "current_price": float(price) if price is not None else 0.0,
            "lookback": int(lookback),
        }
    left = right = max(2, lookback // 4 or 4)
    try:
        swings = detect_swings(df, left=left, right=right)
    except (ValueError, TypeError):
        swings = None
    if swings is None or len(swings.events) == 0:
        return {
            "zone": "neutral",
            "equilibrium": 0.0,
            "range_high": 0.0,
            "range_low": 0.0,
            "current_price": float(price) if price is not None else float(df["close"].iloc[-1]),
            "lookback": int(lookback),
        }
    structure = detect_structure(df, swings)
    context = compute_dealing_range_context(df, structure)
    snap = context_snapshot(context, lookback=lookback)
    snap["lookback"] = int(lookback)
    if price is not None:
        snap["current_price"] = float(price)
    return snap


def score_setup(setup: Dict, min_score: int = 4):
    """5-criteria setup scoring (kept for backward compatibility)."""
    displacement = bool(setup.get("displacement", False))
    bias_aligned = bool(setup.get("bias_aligned", False))
    sweep_clean = bool(setup.get("sweep_clean", False))
    in_pd_zone = bool(setup.get("in_pd_zone", False))
    first_test = bool(setup.get("first_test", False))

    score = int(displacement) + int(bias_aligned) + int(sweep_clean) + int(in_pd_zone) + int(first_test)
    reasons = []
    if displacement:
        reasons.append("Displacement manh")
    if bias_aligned:
        reasons.append("Thuan Bias H4/Daily")
    if sweep_clean:
        reasons.append("Sweep sach")
    if in_pd_zone:
        reasons.append("Dung vung Premium/Discount")
    if first_test:
        reasons.append("Test lan dau")

    has_required = displacement and bias_aligned
    entry_allowed = has_required and score >= min_score
    return score, reasons, entry_allowed


def build_setup_dict(
    *,
    displacement: bool = False,
    bias_aligned: bool = False,
    sweep_clean: bool = False,
    in_pd_zone: bool = False,
    first_test: bool = True,
    pd_zone: Optional[str] = None,
) -> Dict:
    return {
        "displacement": bool(displacement),
        "bias_aligned": bool(bias_aligned),
        "sweep_clean": bool(sweep_clean),
        "in_pd_zone": bool(in_pd_zone),
        "first_test": bool(first_test),
        "pd_zone": pd_zone,
    }


def reasons_to_text(reasons) -> str:
    return "\n".join(reasons)


def is_in_pd_zone(zone: str, direction: str, **kwargs) -> bool:
    return _is_in_pd_zone(zone, direction, **kwargs)


if __name__ == "__main__":
    print("Testing bias_detector module...")
    rng = pd.date_range("2024-01-01", periods=400, freq="15min")
    np.random.seed(7)
    base = np.cumsum(np.random.randn(400)) + 100
    test_df = pd.DataFrame(
        {
            "open": base + np.random.randn(400) * 0.1,
            "high": base + np.abs(np.random.randn(400)) * 0.3 + 0.2,
            "low": base - np.abs(np.random.randn(400)) * 0.3 - 0.2,
            "close": base + np.random.randn(400) * 0.1,
            "volume": np.random.randint(1000, 5000, 400),
        },
        index=rng,
    )
    test_df.index.name = "timestamp"

    bias = detect_bias(test_df, swing_length=20)
    print(f"Single-TF bias: {bias} (must be 'bull' | 'bear' | None)")
    assert bias in (None, "bull", "bear")

    tiny = test_df.iloc[:10]
    assert detect_bias(tiny) is None

    sample = {"D": "bull", "H4": "bull", "H1": "bear", "M15": "bull"}
    assert align_bias(sample) == "aligned_long"
    sample2 = {"D": "bull", "H4": "bear", "H1": "bull", "M15": "bear"}
    assert align_bias(sample2) == "stand_aside"
    sample3 = {"D": "bear", "H4": "bear", "H1": "bull", "M15": "bear"}
    assert align_bias(sample3) == "aligned_short"
    sample4 = {"D": None, "H4": "bull"}
    assert align_bias(sample4) == "stand_aside"

    assert trade_direction(sample2) is None
    assert trade_direction(sample) == "long"

    print("bias_detector verified.")
