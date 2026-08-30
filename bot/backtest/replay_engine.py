"""Deterministic Python replay of the SMC engine over a frozen OHLC bundle.

Wraps the existing ``src.smc_engine`` surfaces (swings, structure, OB,
displacement, sweeps) and emits ``AlertPayload``-equivalent signal
decisions at the same bar indices the live Pine indicator would fire.

Determinism guarantee: same input ``ohlc`` DataFrame + same config →
byte-identical output rows in the same order.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from bot.webhook.payload import AlertPayload, compute_signal_id


# Required OHLC columns. Validation upfront so a typo fails fast.
_REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class ReplayRun:
    """A single deterministic replay execution."""

    run_id: str
    ohlc_checksum: str  # SHA-256 of canonical OHLC bytes
    symbol: str
    tf: str
    started_at: datetime
    finished_at: datetime
    signal_count: int


@dataclass(frozen=True)
class ReplayResult:
    """Output of a replay run: signal rows + run metadata."""

    run: ReplayRun
    signals: tuple[AlertPayload, ...]


def _ohlc_checksum(ohlc: pd.DataFrame) -> str:
    """Deterministic SHA-256 over canonical (sorted index + float values)."""
    canonical = ohlc.sort_index().to_numpy().tobytes()
    return hashlib.sha256(canonical).hexdigest()


def _detect_swings(ohlc: pd.DataFrame, left: int = 5, right: int = 5) -> pd.DataFrame:
    """Detect fractal swing pivots at confirmed indices (causal activation).

    Returns DataFrame with columns ``activation_index, pivot_index, direction,
    level``. ``activation_index`` is a regular column (not the index) so that
    ``swings[swings.activation_index == i]`` returns scalar values downstream
    even when multiple swings activate on the same bar.
    """
    from smc_engine.swings import detect_swings_symmetric
    result = detect_swings_symmetric(ohlc, swing_length=left)

    rows: list[dict[str, Any]] = []
    for event in result.events:
        rows.append(
            {
                "activation_index": event.activation_pos,
                "pivot_index": event.pivot_pos,
                "direction": event.direction,  # "high" | "low"
                "level": event.level,
                "timestamp": event.activation_timestamp,
            }
        )
    return pd.DataFrame(rows)


def _detect_bos_choch(ohlc: pd.DataFrame, swings: pd.DataFrame) -> pd.DataFrame:
    """Detect Break-of-Structure / Change-of-Character events.

    Causal: a BOS at bar ``i`` requires the swing at ``i-1`` to be confirmed.
    We join on ``activation_index <= current_bar`` so only past swings
    are visible.
    """
    if swings.empty:
        return pd.DataFrame(columns=["bar_index", "kind", "level", "broken_swing_idx"])

    events: list[dict[str, Any]] = []
    last_swing_high_idx = -1
    last_swing_low_idx = -1
    last_swing_high_level = float("nan")
    last_swing_low_level = float("nan")

    for i in range(len(ohlc)):
        # Reveal any swings that just activated at this bar.
        active = swings[swings["activation_index"] == i]
        for _, row in active.iterrows():
            if row["direction"] == "high":
                last_swing_high_idx = int(row["pivot_index"])
                last_swing_high_level = float(row["level"])
            else:
                last_swing_low_idx = int(row["pivot_index"])
                last_swing_low_level = float(row["level"])
        close = float(ohlc["close"].iloc[i])
        high = float(ohlc["high"].iloc[i])
        low = float(ohlc["low"].iloc[i])

        # BOS bullish: close breaks above last swing high.
        if last_swing_high_idx >= 0 and close > last_swing_high_level:
            events.append(
                {
                    "bar_index": i,
                    "kind": "bos",
                    "dir": "long",
                    "level": close,
                    "broken_swing_idx": last_swing_high_idx,
                }
            )
        # BOS bearish: close breaks below last swing low.
        if last_swing_low_idx >= 0 and close < last_swing_low_level:
            events.append(
                {
                    "bar_index": i,
                    "kind": "bos",
                    "dir": "short",
                    "level": close,
                    "broken_swing_idx": last_swing_low_idx,
                }
            )
    return pd.DataFrame(events)


def _build_signals(
    bos: pd.DataFrame,
    ohlc: pd.DataFrame,
    symbol: str,
    tf: str,
) -> list[AlertPayload]:
    """Convert BOS events to AlertPayload-shaped rows.

    The replay emits one signal per BOS event. OB/FVG/Pine-specific gate
    fields default to -1 (N/A) since the replay focuses on structure.
    """
    signals: list[AlertPayload] = []
    if bos.empty:
        return signals
    # Validate index is DatetimeIndex before iterating (avoid bar_time=0 for
    # non-datetime indices, which would later be rejected by AlertPayload).
    idx = ohlc.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError(
            f"replay requires a DatetimeIndex (got {type(idx).__name__}); "
            "call ohlc.index = pd.DatetimeIndex(...) before replay_from_ohlc()."
        )
    for _, row in bos.iterrows():
        bar_idx = int(row["bar_index"])
        ts = idx[bar_idx]
        bar_time = int(ts.timestamp())
        event = "bos" if row["kind"] == "bos" else "choch"
        direction = row.get("dir", "long") if row["kind"] == "bos" else (
            "short" if row.get("dir") == "long" else "long"
        )
        if event == "bos":
            direction = row["dir"]
        else:  # choch
            direction = "short" if row["dir"] == "long" else "long"
        signals.append(
            AlertPayload(
                prefix="SMC",
                version="v1",
                event=event,  # type: ignore[arg-type]
                symbol=symbol,
                tf=tf,
                dir=direction,  # type: ignore[arg-type]
                level=float(row["level"]),
                bar_time=bar_time,
                ob_id=-1,
                bos_id=-1,
                state="watch",  # replay shows candidate but not gate-qualified
                reason=f"replay:{row['kind']}",
                received_at=datetime.now(timezone.utc),
                raw_payload="",
            )
        )
    return signals


class ReplayEngine:
    """Run a deterministic replay over an OHLC frame.

    Use ``ReplayEngine.run(ohlc)`` or the convenience function
    ``replay_from_ohlc(ohlc)``.
    """

    def __init__(
        self,
        *,
        symbol: str = "EURUSD",
        tf: str = "M15",
        swing_left: int = 5,
        swing_right: int = 5,
    ) -> None:
        if swing_left < 1 or swing_right < 1:
            raise ValueError("swing_left and swing_right must be >= 1")
        self.symbol = symbol
        self.tf = tf
        self.swing_left = swing_left
        self.swing_right = swing_right

    def run(self, ohlc: pd.DataFrame) -> ReplayResult:
        if not isinstance(ohlc, pd.DataFrame):
            raise TypeError(f"ohlc must be a DataFrame, got {type(ohlc)}")
        missing = [c for c in _REQUIRED_COLUMNS if c not in ohlc.columns]
        if missing:
            raise ValueError(f"ohlc missing required columns: {missing}")

        started = datetime.now(timezone.utc)
        checksum = _ohlc_checksum(ohlc)
        swings = _detect_swings(ohlc, self.swing_left, self.swing_right)
        bos = _detect_bos_choch(ohlc, swings)
        signals = _build_signals(bos, ohlc, self.symbol, self.tf)
        finished = datetime.now(timezone.utc)

        run_id = f"replay-{checksum[:12]}"
        run = ReplayRun(
            run_id=run_id,
            ohlc_checksum=checksum,
            symbol=self.symbol,
            tf=self.tf,
            started_at=started,
            finished_at=finished,
            signal_count=len(signals),
        )
        return ReplayResult(run=run, signals=tuple(signals))


def replay_from_ohlc(
    ohlc: pd.DataFrame,
    *,
    symbol: str = "EURUSD",
    tf: str = "M15",
    swing_left: int = 5,
    swing_right: int = 5,
) -> ReplayResult:
    """Convenience wrapper: build engine, run, return result."""
    engine = ReplayEngine(symbol=symbol, tf=tf, swing_left=swing_left, swing_right=swing_right)
    return engine.run(ohlc)