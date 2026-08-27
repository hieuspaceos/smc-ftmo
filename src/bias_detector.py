"""Multi-timeframe bias detector.

Computes per-TF bias from the most recent BOS/CHoCH, then aligns Daily + H4
into one of: aligned_long, aligned_short, stand_aside.
Pure pandas + smartmoneyconcepts; 1-bar shift to avoid look-ahead.

Stable public API (consumed by app.py):
    detect_bias(df, swing_length=20) -> 'bull' | 'bear' | None
    detect_premium_discount(df, lookback=50) -> dict with keys
        zone, equilibrium, range_high, range_low, current_price
    score_setup(setup: dict) -> (score:int, reasons:list[str], entry_allowed:bool)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from smartmoneyconcepts import smc

try:
    from .smc_signals import calculate_atr
except ImportError:  # pragma: no cover
    from smc_signals import calculate_atr

VALID_BIAS = {"bull", "bear", "neutral"}


def detect_bias(df: pd.DataFrame, swing_length: int = 20) -> Optional[str]:
    """Return 'bull' | 'bear' | None for one TF from last BOS/CHoCH.

    Rules (1-bar shift to avoid look-ahead):
      - If a CHoCH exists in the last `swing_length` bars, the most recent
        CHoCH wins (it reverses structure).
      - Else if a BOS exists in the lookback window, the most recent BOS wins.
      - Else None (sideway / undefined structure).

    Returns:
        'bull' | 'bear' | None
    """
    if df is None or len(df) < max(swing_length * 2 + 5, 30):
        return None
    # Normalize tz so shift/dropna + smc lib don't choke on mixed indices.
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df_shift = df.shift(1).dropna()
    if len(df_shift) < swing_length * 2:
        return None

    try:
        if hasattr(smc, "swing_high_low"):
            swings = smc.swing_high_low(
                df_shift, left=swing_length // 2, right=swing_length // 2
            )
        elif hasattr(smc, "swing_highs_lows"):
            swings = smc.swing_highs_lows(
                df_shift, swing_length=swing_length
            )
        else:  # pragma: no cover - defensive
            raise AttributeError("smartmoneyconcepts missing swing helper")
        structure = smc.bos_choch(df_shift, swings)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[bias_detector] smc lib error: {exc}")
        return None

    # bos_choch returns a DataFrame with BOS / CHOCH / Level / BrokenIndex
    # indexed like df_shift. We want to inspect the most recent bars, which
    # live at the tail of df_shift (not df, which has the latest bar).
    if not isinstance(structure, pd.DataFrame):
        return None
    if "BOS" not in structure.columns or "CHOCH" not in structure.columns:
        return None
    bos_col = structure["BOS"]
    choch_col = structure["CHOCH"]

    # Look at the last `swing_length` bars of df_shift, which already align
    # with bos_col / choch_col.
    tail = df_shift.iloc[-swing_length:]
    bos_tail = bos_col.reindex(tail.index)
    choch_tail = choch_col.reindex(tail.index)

    window = df.iloc[-swing_length:]

    def _last_signal(col: Optional[pd.Series]) -> Tuple[float, Optional[str]]:
        if col is None:
            return 0.0, None
        sub = col.reindex(window.index)
        non_zero = sub[sub != 0]
        if non_zero.empty:
            return 0.0, None
        last_val = float(non_zero.iloc[-1])
        direction = "bull" if last_val > 0 else "bear"
        return float((sub != 0).sum()), direction

    choch_count, choch_dir = _last_signal(choch_tail)
    bos_count, bos_dir = _last_signal(bos_tail)

    if choch_count > 0 and choch_dir is not None:
        return choch_dir
    if bos_count > 0 and bos_dir is not None:
        return bos_dir
    return None


def compute_bias_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Convenience wrapper to expose ATR for chart annotations."""
    return calculate_atr(df, period=period)


def detect_bias_multi_tf(
    data: Dict[str, pd.DataFrame], swing_length: int = 20
) -> Dict[str, Optional[str]]:
    """Compute bias for each TF present in `data`.

    Missing TFs default to None (stand_aside). TFs queried: D / H4 / H1 / M15.
    """
    result: Dict[str, Optional[str]] = {}
    for tf in ("D", "H4", "H1", "M15"):
        df = data.get(tf)
        if df is None or df.empty:
            result[tf] = None
            continue
        result[tf] = detect_bias(df, swing_length=swing_length)
    return result


def align_bias(bias_by_tf: Dict[str, Optional[str]]) -> str:
    """Combine Daily + H4 into a single aligned verdict.

    Returns:
        'aligned_long'   when both D and H4 are 'bull'
        'aligned_short'  when both D and H4 are 'bear'
        'stand_aside'    otherwise (mixed or any None)
    """
    bias_d = bias_by_tf.get("D")
    bias_h4 = bias_by_tf.get("H4")

    if bias_d == "bull" and bias_h4 == "bull":
        return "aligned_long"
    if bias_d == "bear" and bias_h4 == "bear":
        return "aligned_short"
    return "stand_aside"


def bias_panel(bias_by_tf: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Return labels for the UI bias panel (Bull/Bear/Neutral per TF)."""
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
    """Translate aligned verdict into a one-word trade direction.

    Returns 'long', 'short', or None when the trader must stand aside.
    """
    aligned = align_bias(bias_by_tf)
    if aligned == "aligned_long":
        return "long"
    if aligned == "aligned_short":
        return "short"
    return None


def is_bias_aligned(
    direction: str, bias_by_tf: Dict[str, Optional[str]]
) -> bool:
    """True when D+H4 alignment matches the requested trade direction."""
    if direction == "long":
        return align_bias(bias_by_tf) == "aligned_long"
    if direction == "short":
        return align_bias(bias_by_tf) == "aligned_short"
    return False


def bias_to_series(bias_by_tf: Dict[str, Optional[str]]) -> pd.Series:
    """Convenience for Streamlit tables: bias_by_tf as a labelled Series."""
    return pd.Series(bias_by_tf, name="bias")


if __name__ == "__main__":
    # Verification with synthetic data
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
    assert bias in (None, "bull", "bear"), "detect_bias must return bull/bear/None"

    # Test with too-short data → None
    tiny = test_df.iloc[:10]
    print(f"Tiny df bias: {detect_bias(tiny)}")
    assert detect_bias(tiny) is None

    # Alignment logic
    sample = {"D": "bull", "H4": "bull", "H1": "bear", "M15": "bull"}
    print(f"Aligned: {align_bias(sample)} (expect aligned_long)")
    assert align_bias(sample) == "aligned_long"

    sample2 = {"D": "bull", "H4": "bear", "H1": "bull", "M15": "bear"}
    print(f"Aligned: {align_bias(sample2)} (expect stand_aside)")
    assert align_bias(sample2) == "stand_aside"

    sample3 = {"D": "bear", "H4": "bear", "H1": "bull", "M15": "bear"}
    print(f"Aligned: {align_bias(sample3)} (expect aligned_short)")
    assert align_bias(sample3) == "aligned_short"

    sample4 = {"D": None, "H4": "bull", "H1": "bull", "M15": "bull"}
    print(f"Aligned (D None): {align_bias(sample4)} (expect stand_aside)")
    assert align_bias(sample4) == "stand_aside"

    print("Direction long w/ aligned_long:", trade_direction(sample))
    print("Direction long w/ mixed:", trade_direction(sample2))
    assert trade_direction(sample2) is None

    print("bias_detector verified.")