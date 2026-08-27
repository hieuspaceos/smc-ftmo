"""Premium / Discount zone classifier.

Computes the equilibrium (50% level) over a swing range and classifies the
current price as premium, discount, or neutral. Pure pandas.

Stable public API (consumed by app.py):
    detect_premium_discount(df, lookback=50) -> dict
        keys: zone ('premium'|'discount'|'neutral'),
              equilibrium (float), range_high (float), range_low (float),
              current_price (float), lookback (int)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


ZONE_PREMIUM = "premium"
ZONE_DISCOUNT = "discount"
ZONE_NEUTRAL = "neutral"


def detect_premium_discount(
    df: pd.DataFrame,
    lookback: int = 50,
    price: Optional[float] = None,
) -> Dict:
    """Classify a price relative to the equilibrium (50% of recent swing range).

    Args:
        df: OHLCV frame with DatetimeIndex, columns open/high/low/close/volume.
        lookback: number of bars to consider for the swing range.
        price: override price to classify (defaults to last close).

    Returns:
        dict with keys: zone, equilibrium, range_high, range_low,
                        current_price, lookback
    """
    empty = {
        "zone": ZONE_NEUTRAL,
        "equilibrium": 0.0,
        "range_high": 0.0,
        "range_low": 0.0,
        "current_price": float(price) if price is not None else 0.0,
        "lookback": int(lookback),
    }
    if df is None or len(df) < 5:
        return empty

    window = df.iloc[-lookback:] if lookback > 0 else df
    range_high = float(window["high"].max())
    range_low = float(window["low"].min())
    equilibrium = (range_high + range_low) / 2.0

    if price is None:
        price = float(df["close"].iloc[-1])

    if price > equilibrium:
        zone = ZONE_PREMIUM
    elif price < equilibrium:
        zone = ZONE_DISCOUNT
    else:
        zone = ZONE_NEUTRAL

    return {
        "zone": zone,
        "equilibrium": equilibrium,
        "range_high": range_high,
        "range_low": range_low,
        "current_price": float(price),
        "lookback": int(lookback),
    }


def pd_series(df: pd.DataFrame, lookback: int = 50) -> pd.Series:
    """Per-bar P/D zone classification aligned with df.index.

    At bar i the range covers bars [i-lookback+1 .. i]. The first
    `lookback-1` bars default to 'neutral' (insufficient history).
    """
    if df is None or len(df) == 0:
        return pd.Series(dtype=object)

    high = df["high"].rolling(window=lookback, min_periods=1).max()
    low = df["low"].rolling(window=lookback, min_periods=1).min()
    eq = (high + low) / 2.0
    close = df["close"]

    zones = pd.Series(ZONE_NEUTRAL, index=df.index, dtype=object)
    zones[close > eq] = ZONE_PREMIUM
    zones[close < eq] = ZONE_DISCOUNT
    return zones


def is_in_pd_zone(
    zone: str,
    direction: str,
    *,
    long_in_discount: bool = True,
    short_in_premium: bool = True,
) -> bool:
    """Direction-aware check: is `zone` the right one for the trade?

    Longs: want discount. Shorts: want premium.
    Returns False for 'neutral' or mismatched direction.
    """
    if zone == ZONE_NEUTRAL:
        return False
    if direction == "long" and zone == ZONE_DISCOUNT and long_in_discount:
        return True
    if direction == "short" and zone == ZONE_PREMIUM and short_in_premium:
        return True
    return False


def pd_annotations(
    df: pd.DataFrame, lookback: int = 50
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Plot-ready equilibrium/range bands aligned with df.

    Returns (equilibrium, range_high, range_low) Series for direct plotting.
    """
    high = df["high"].rolling(window=lookback, min_periods=1).max()
    low = df["low"].rolling(window=lookback, min_periods=1).min()
    eq = (high + low) / 2.0
    return eq, high, low


if __name__ == "__main__":
    # Verification
    print("Testing premium_discount module...")
    rng = pd.date_range("2024-01-01", periods=300, freq="15min")
    np.random.seed(11)
    base = np.cumsum(np.random.randn(300)) + 100
    test_df = pd.DataFrame(
        {
            "open": base,
            "high": base + np.abs(np.random.randn(300)) * 0.4,
            "low": base - np.abs(np.random.randn(300)) * 0.4,
            "close": base + np.random.randn(300) * 0.1,
            "volume": np.random.randint(1000, 5000, 300),
        },
        index=rng,
    )
    test_df.index.name = "timestamp"

    last_close = float(test_df["close"].iloc[-1])
    res = detect_premium_discount(test_df, lookback=50, price=last_close)
    print(
        f"P/D dict: zone={res['zone']} eq={res['equilibrium']:.5f} "
        f"range=({res['range_low']:.5f},{res['range_high']:.5f}) "
        f"price={res['current_price']:.5f}"
    )
    assert isinstance(res, dict), "detect_premium_discount must return dict"
    assert set(res.keys()) == {
        "zone", "equilibrium", "range_high", "range_low",
        "current_price", "lookback",
    }
    assert res["zone"] in {ZONE_PREMIUM, ZONE_DISCOUNT, ZONE_NEUTRAL}

    # Series version
    series = pd_series(test_df, lookback=50)
    print(f"P/D series length={len(series)}, value counts={series.value_counts().to_dict()}")
    assert len(series) == len(test_df)

    # is_in_pd_zone logic
    assert is_in_pd_zone(ZONE_DISCOUNT, "long") is True
    assert is_in_pd_zone(ZONE_DISCOUNT, "short") is False
    assert is_in_pd_zone(ZONE_PREMIUM, "short") is True
    assert is_in_pd_zone(ZONE_PREMIUM, "long") is False
    assert is_in_pd_zone(ZONE_NEUTRAL, "long") is False
    assert is_in_pd_zone(ZONE_NEUTRAL, "short") is False

    # Empty / short df → neutral dict
    short = detect_premium_discount(test_df.iloc[:3])
    print(f"Short df P/D: {short}")
    assert short["zone"] == ZONE_NEUTRAL

    print("premium_discount verified.")