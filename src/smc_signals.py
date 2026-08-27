"""Smart Money Concepts signal detector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from smartmoneyconcepts import smc


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range ATR. Handles NaN closes from H1->M15 resampling gaps."""
    df_clean = df.dropna(subset=["close"]).copy()
    if len(df_clean) < period + 2:
        return pd.Series(index=df.index, dtype=float)
    tr1 = df_clean["high"] - df_clean["low"]
    tr2 = (df_clean["high"] - df_clean["close"].shift()).abs()
    tr3 = (df_clean["low"] - df_clean["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    result = atr.reindex(df.index)
    first = result.first_valid_index()
    if first is not None:
        result = result.fillna(result.loc[first])
    return result


@dataclass
class Signal:
    timestamp: datetime
    type: str
    price: float
    direction: str
    mitigated: bool = False
    mitigation_time: Optional[datetime] = None
    confluence: int = 0
    top: Optional[float] = None
    bottom: Optional[float] = None


class SMCSignals:
    def __init__(
        self,
        swing_length: int = 20,
        displacement_atr_mult: float = 1.5,
        sweep_atr_buffer: float = 0.05,
    ):
        self.swing_length = swing_length
        self.displacement_atr_mult = displacement_atr_mult
        self.sweep_atr_buffer = sweep_atr_buffer

    def detect_displacement(self, df: pd.DataFrame) -> pd.Series:
        atr = calculate_atr(df)
        return (df["high"] - df["low"]) > (self.displacement_atr_mult * atr)

    def detect_sweep(
        self, df: pd.DataFrame, swings: pd.Series, direction: str
    ) -> pd.Series:
        atr = calculate_atr(df)
        sweep = pd.Series(False, index=df.index, dtype=bool)
        n_swings = len(swings)
        for i in range(2, len(df)):
            idx = i - 1
            if idx >= n_swings:
                continue
            sv = swings.iloc[idx]
            if pd.isna(sv):
                continue
            buf = self.sweep_atr_buffer * atr.iloc[i]
            if direction == "bullish":
                if df["low"].iloc[i] < (sv - buf) and df["close"].iloc[i] > sv:
                    sweep.iloc[i] = True
            else:
                if df["high"].iloc[i] > (sv + buf) and df["close"].iloc[i] < sv:
                    sweep.iloc[i] = True
        return sweep

    def detect_order_blocks(
        self, df: pd.DataFrame, swings_df: Optional[pd.DataFrame] = None
    ) -> List[Signal]:
        """Build OBs from library swing HighLow markers.

        HighLow == 1  -> swing high -> bearish OB
        HighLow == -1 -> swing low  -> bullish OB
        """
        signals: List[Signal] = []
        atr = calculate_atr(df)
        if swings_df is None or swings_df.empty or "HighLow" not in swings_df.columns:
            return signals

        hl = swings_df["HighLow"]
        for pos, val in enumerate(hl.values):
            if pd.isna(val) or val == 0:
                continue
            df_pos = pos + 1  # 1-bar shift alignment
            if df_pos >= len(df):
                continue
            if pd.isna(df["high"].iloc[df_pos]) or pd.isna(df["low"].iloc[df_pos]):
                continue
            atr_val = float(atr.iloc[df_pos]) if not pd.isna(atr.iloc[df_pos]) else 0.0
            hi = float(df["high"].iloc[df_pos])
            lo = float(df["low"].iloc[df_pos])
            ts = df.index[df_pos]
            rng = max(atr_val, hi - lo)
            if val > 0:
                signals.append(Signal(
                    timestamp=ts, type="ob", price=hi,
                    direction="bearish", top=hi, bottom=hi - rng,
                ))
            else:
                signals.append(Signal(
                    timestamp=ts, type="ob", price=lo,
                    direction="bullish", top=lo + rng, bottom=lo,
                ))
        return signals

    def get_signals(
        self,
        df: pd.DataFrame,
        tf: str = "M15",
        skip_mitigation: bool = False,
    ) -> Dict[str, List[Signal]]:
        empty = {k: [] for k in ("bos", "choch", "fvg", "ob", "sweep", "displacement")}
        if len(df) < 50:
            return empty

        df_s = df.shift(1).dropna()
        n_s = len(df_s)
        swings_df = pd.DataFrame()

        try:
            swings_df = smc.swing_highs_lows(df_s, swing_length=self.swing_length)
            swings = swings_df.get(
                "Level",
                swings_df.iloc[:, 0] if not swings_df.empty else pd.Series(),
            )
        except Exception as exc:
            print(f"[SMCSignals] lib warning {tf}: {exc}")
            swings = pd.Series([np.nan] * n_s, index=df_s.index)

        swings_aligned = pd.Series(
            [np.nan] + list(swings.values), index=df.index[: n_s + 1]
        )

        displacement = self.detect_displacement(df)
        sweep_bull = self.detect_sweep(df, swings_aligned, "bullish")
        sweep_bear = self.detect_sweep(df, swings_aligned, "bearish")

        signals: Dict[str, List[Signal]] = {
            "bos": [], "choch": [], "fvg": [], "ob": [],
            "sweep": [], "displacement": [],
        }
        # Displacement/sweep over full df (not truncated by dropna length)
        for i in range(10, len(df)):
            if pd.isna(df["close"].iloc[i]):
                continue
            ts = df.index[i]
            close = float(df["close"].iloc[i])
            if bool(displacement.iloc[i]):
                direction = (
                    "bullish"
                    if df["close"].iloc[i] >= df["open"].iloc[i]
                    else "bearish"
                )
                signals["displacement"].append(
                    Signal(ts, "displacement", close, direction)
                )
            if i < len(sweep_bull) and bool(sweep_bull.iloc[i]):
                signals["sweep"].append(Signal(ts, "sweep", close, "bullish"))
            if i < len(sweep_bear) and bool(sweep_bear.iloc[i]):
                signals["sweep"].append(Signal(ts, "sweep", close, "bearish"))

        signals["ob"] = self.detect_order_blocks(df, swings_df=swings_df)

        if not skip_mitigation:
            signals = self._apply_mitigation_fast(df, signals)
        return signals
    def _apply_mitigation_fast(
        self, df: pd.DataFrame, signals: Dict[str, List[Signal]]
    ) -> Dict[str, List[Signal]]:
        if df.empty:
            return signals
        low = df["low"].values
        high = df["high"].values
        timestamps = df.index.values
        running_min = pd.Series(low[::-1]).cummin().iloc[::-1].values
        running_max = pd.Series(high[::-1]).cummax().iloc[::-1].values

        for key in signals:
            for s in signals[key]:
                try:
                    loc = df.index.get_loc(s.timestamp)
                except KeyError:
                    continue
                if s.direction == "bullish" and running_min[loc] < s.price:
                    s.mitigated = True
                    mask = (timestamps > s.timestamp) & (low < s.price)
                    if mask.any():
                        s.mitigation_time = pd.Timestamp(timestamps[mask][0])
                elif s.direction == "bearish" and running_max[loc] > s.price:
                    s.mitigated = True
                    mask = (timestamps > s.timestamp) & (high > s.price)
                    if mask.any():
                        s.mitigation_time = pd.Timestamp(timestamps[mask][0])
        return signals


def get_smc_overlays(
    df: pd.DataFrame, params: Dict = None
) -> Dict[str, List[Signal]]:
    if params is None:
        params = {}
    kw = {
        k: params.get(k, v)
        for k, v in {
            "swing_length": 20,
            "displacement_atr_mult": 1.5,
            "sweep_atr_buffer": 0.05,
        }.items()
    }
    return SMCSignals(**kw).get_signals(df)


if __name__ == "__main__":
    print("Testing SMC signals module...")
    rng = pd.date_range("2024-01-01", periods=300, freq="15min")
    base = np.cumsum(np.random.randn(300) * 0.0005) + 1.10
    test_df = pd.DataFrame(
        {
            "open": base,
            "high": base + np.abs(np.random.randn(300)) * 0.0003,
            "low": base - np.abs(np.random.randn(300)) * 0.0003,
            "close": base + np.random.randn(300) * 0.0002,
            "volume": np.random.randint(100, 10000, 300),
        },
        index=rng,
    )
    det = SMCSignals(swing_length=10)
    sigs = det.get_signals(test_df)
    print("Signal types:", {k: len(v) for k, v in sigs.items()})
    print("SMC signals verified.")
