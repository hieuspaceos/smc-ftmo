"""Causal BOS-activated order block zones with chronological lifecycle.

Order blocks are generated only from BOS structure events. A candidate is the
last opposite-direction candle before the break (within lookback). The zone is
the full candle ``[low, high]`` and becomes trade-available only at the BOS
activation close. First-touch, invalidation, and expiry are resolved in one
forward pass with a bounded active set per direction.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_engine.displacement import ExpansionMetrics
from smc_engine.structure import StructureEvent, StructureResult

Direction = Literal["bullish", "bearish"]

_OHLC_COLS = ("open", "high", "low", "close")

DEFAULT_CANDIDATE_LOOKBACK = 20
DEFAULT_EXPIRY_BARS = 200
DEFAULT_MAX_ACTIVE_PER_DIRECTION = 128


@dataclass(frozen=True)
class OrderBlockEvent:
    """BOS-validated order block with provenance and lifecycle timestamps.

    ``direction`` is the expected setup direction (bullish OB after bullish BOS).
    The zone is unavailable before ``activation_timestamp`` and is queried via
    ``is_active_at`` / ``is_first_test_at`` so callers never need terminal
    mitigation flags for historical decisions.
    """

    id: int
    direction: Direction
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None
    invalidation_timestamp: pd.Timestamp | None
    expiry_timestamp: pd.Timestamp | None
    structure_event_id: int

    @property
    def price(self) -> float:
        """Midpoint compatibility helper; prefer ``top`` / ``bottom``."""
        return (float(self.top) + float(self.bottom)) * 0.5

    def is_active_at(self, ts: pd.Timestamp) -> bool:
        """True when activated and not yet invalidated or expired at ``ts``.

        Boundary rules (locked by tests):
        - available on the activation bar (``ts >= activation_timestamp``)
        - unavailable on/after invalidation or expiry timestamps
        """
        if ts < self.activation_timestamp:
            return False
        if self.invalidation_timestamp is not None and ts >= self.invalidation_timestamp:
            return False
        if self.expiry_timestamp is not None and ts >= self.expiry_timestamp:
            return False
        return True

    def is_first_test_at(self, ts: pd.Timestamp) -> bool:
        """True while active and at-or-before the first touch bar (inclusive).

        Untouched active zones remain first-test eligible. After the first-touch
        bar, returns False even if still active.
        """
        if not self.is_active_at(ts):
            return False
        if self.first_touch_timestamp is None:
            return True
        return ts <= self.first_touch_timestamp


@dataclass(frozen=True)
class OrderBlockResult:
    """Typed order-block output: ordered events plus lifecycle diagnostics."""

    events: tuple[OrderBlockEvent, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass
class _Draft:
    """Mutable draft used during the chronological lifecycle pass."""

    id: int
    direction: Direction
    origin_pos: int
    origin_timestamp: pd.Timestamp
    activation_pos: int
    activation_timestamp: pd.Timestamp
    top: float
    bottom: float
    first_touch_timestamp: pd.Timestamp | None
    invalidation_timestamp: pd.Timestamp | None
    expiry_timestamp: pd.Timestamp | None
    structure_event_id: int
    # Working flags (not exported)
    touch_done: bool = False
    dead: bool = False

    def to_event(self) -> OrderBlockEvent:
        return OrderBlockEvent(
            id=self.id,
            direction=self.direction,
            origin_pos=self.origin_pos,
            origin_timestamp=self.origin_timestamp,
            activation_pos=self.activation_pos,
            activation_timestamp=self.activation_timestamp,
            top=self.top,
            bottom=self.bottom,
            first_touch_timestamp=self.first_touch_timestamp,
            invalidation_timestamp=self.invalidation_timestamp,
            expiry_timestamp=self.expiry_timestamp,
            structure_event_id=self.structure_event_id,
        )


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in _OHLC_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame missing required OHLC columns: {missing}")


def _validate_index(index: pd.Index) -> None:
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")


def _validate_positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return int(value)


def _qualified_array(expansion: ExpansionMetrics | pd.Series, index: pd.Index) -> np.ndarray:
    if isinstance(expansion, ExpansionMetrics):
        q = expansion.qualified
    elif isinstance(expansion, pd.Series):
        q = expansion
    else:
        raise TypeError("expansion must be ExpansionMetrics or a boolean pandas Series")
    if not isinstance(q, pd.Series):
        raise TypeError("expansion.qualified must be a pandas Series")
    if not q.index.equals(index):
        q = q.reindex(index)
    return q.fillna(False).to_numpy(dtype=bool, copy=False)


def _find_origin(
    direction: Direction,
    break_pos: int,
    lookback: int,
    open_: np.ndarray,
    close: np.ndarray,
) -> int | None:
    """Last opposite candle in ``[break_pos - lookback, break_pos - 1]``."""
    if break_pos <= 0:
        return None
    start = max(0, break_pos - lookback)
    end = break_pos  # exclusive
    # Scan forward and keep the last match so origin is the nearest opposite candle.
    found: int | None = None
    if direction == "bullish":
        # Last bearish candle (close < open)
        for j in range(start, end):
            o = open_[j]
            c = close[j]
            if np.isfinite(o) and np.isfinite(c) and c < o:
                found = j
    else:
        # Last bullish candle (close > open)
        for j in range(start, end):
            o = open_[j]
            c = close[j]
            if np.isfinite(o) and np.isfinite(c) and c > o:
                found = j
    return found


def _expansion_near_break(qualified: np.ndarray, break_pos: int) -> bool:
    """Require range expansion at the break bar or the immediately previous bar."""
    if break_pos < 0 or break_pos >= len(qualified):
        return False
    if bool(qualified[break_pos]):
        return True
    if break_pos > 0 and bool(qualified[break_pos - 1]):
        return True
    return False


def _expire_draft(
    draft: _Draft,
    ts: pd.Timestamp,
    reason: str,
    diagnostics: list[str],
) -> None:
    if draft.dead:
        return
    draft.dead = True
    if draft.expiry_timestamp is None:
        draft.expiry_timestamp = ts
    diagnostics.append(
        f"{reason}@i_ts={ts}:ob_id={draft.id}:dir={draft.direction}:act={draft.activation_pos}"
    )


def detect_order_blocks(
    df: pd.DataFrame,
    structure: StructureResult,
    expansion: ExpansionMetrics | pd.Series,
    *,
    candidate_lookback: int = DEFAULT_CANDIDATE_LOOKBACK,
    expiry_bars: int = DEFAULT_EXPIRY_BARS,
    max_active_zones_per_direction: int = DEFAULT_MAX_ACTIVE_PER_DIRECTION,
) -> OrderBlockResult:
    """Detect BOS-activated order blocks with chronological lifecycle.

    Parameters
    ----------
    df:
        OHLC frame. Index must be unique and monotonic increasing.
    structure:
        Output of ``detect_structure``. Only ``type == "bos"`` events spawn OBs.
    expansion:
        ``ExpansionMetrics`` or a boolean ``qualified`` Series aligned to ``df``.
        Qualification is required at the BOS bar or the previous bar.
    candidate_lookback:
        Bars before the break searched for the last opposite candle.
    expiry_bars:
        Deterministic age expiry measured from ``activation_pos``.
    max_active_zones_per_direction:
        Soft bound; when exceeded, the oldest still-active zone is expired and
        a diagnostic is recorded.

    Notes
    -----
    Lifecycle for touch/invalidation begins on the bar *after* activation so the
    impulse break cannot instantly touch or invalidate its own OB. Cap and age
    expiry are applied in the same forward sweep.
    """
    _validate_ohlc(df)
    _validate_index(df.index)
    lookback = _validate_positive_int("candidate_lookback", candidate_lookback)
    exp_bars = _validate_positive_int("expiry_bars", expiry_bars)
    max_active = _validate_positive_int(
        "max_active_zones_per_direction", max_active_zones_per_direction
    )

    if not isinstance(structure, StructureResult):
        raise TypeError("structure must be a StructureResult")

    n = len(df)
    index = df.index
    open_ = df["open"].to_numpy(dtype=float, copy=False)
    high = df["high"].to_numpy(dtype=float, copy=False)
    low = df["low"].to_numpy(dtype=float, copy=False)
    close = df["close"].to_numpy(dtype=float, copy=False)
    qualified = _qualified_array(expansion, index)

    bos_by_pos: dict[int, list[StructureEvent]] = {}
    for ev in structure.events:
        if ev.type != "bos":
            continue
        pos = ev.activation_pos
        if pos < 0 or pos >= n:
            raise ValueError(
                f"structure event id={ev.id} activation_pos={pos} out of range for n={n}"
            )
        bos_by_pos.setdefault(pos, []).append(ev)

    drafts: list[_Draft] = []
    diagnostics: list[str] = []
    next_id = 0

    # Deques hold still-live drafts in activation order (oldest at left).
    active: dict[Direction, deque[_Draft]] = {
        "bullish": deque(),
        "bearish": deque(),
    }

    def _purge_dead(direction: Direction) -> None:
        q = active[direction]
        while q and q[0].dead:
            q.popleft()

    def _natural_expire(i: int, ts: pd.Timestamp) -> None:
        for direction in ("bullish", "bearish"):
            q = active[direction]  # type: ignore[index]
            # Age expiry: first bar where activation_pos + expiry_bars <= i
            while q:
                d = q[0]
                if d.dead:
                    q.popleft()
                    continue
                if d.activation_pos + exp_bars > i:
                    break
                _expire_draft(d, ts, "expiry", diagnostics)
                q.popleft()

    def _lifecycle_bar(i: int, ts: pd.Timestamp) -> None:
        h = high[i]
        l = low[i]
        c = close[i]
        h_ok = np.isfinite(h)
        l_ok = np.isfinite(l)
        c_ok = np.isfinite(c)

        for direction in ("bullish", "bearish"):
            q = active[direction]  # type: ignore[index]
            # Iterate a snapshot list so we can leave dead entries for purge.
            for d in list(q):
                if d.dead:
                    continue
                # Only bars strictly after activation participate in touch/invalidation.
                if i <= d.activation_pos:
                    continue

                if direction == "bullish":
                    if not d.touch_done and l_ok and l <= d.top:
                        d.first_touch_timestamp = ts
                        d.touch_done = True
                    if c_ok and c < d.bottom:
                        d.invalidation_timestamp = ts
                        d.dead = True
                else:
                    if not d.touch_done and h_ok and h >= d.bottom:
                        d.first_touch_timestamp = ts
                        d.touch_done = True
                    if c_ok and c > d.top:
                        d.invalidation_timestamp = ts
                        d.dead = True
            _purge_dead(direction)  # type: ignore[arg-type]

    def _activate_bos(ev: StructureEvent, i: int, ts: pd.Timestamp) -> None:
        nonlocal next_id
        if not _expansion_near_break(qualified, i):
            diagnostics.append(
                f"skip_no_expansion@i={i}:structure_id={ev.id}:dir={ev.direction}"
            )
            return

        origin = _find_origin(ev.direction, i, lookback, open_, close)
        if origin is None:
            diagnostics.append(
                f"skip_no_origin@i={i}:structure_id={ev.id}:dir={ev.direction}"
            )
            return

        top = float(high[origin])
        bottom = float(low[origin])
        if not (np.isfinite(top) and np.isfinite(bottom)):
            diagnostics.append(
                f"skip_bad_origin_ohlc@i={i}:structure_id={ev.id}:origin={origin}"
            )
            return
        if bottom > top:
            # Malformed candle — swap defensively and record.
            top, bottom = bottom, top
            diagnostics.append(
                f"origin_ohlc_swapped@i={i}:structure_id={ev.id}:origin={origin}"
            )

        direction: Direction = ev.direction  # type: ignore[assignment]
        _purge_dead(direction)
        q = active[direction]
        while len(q) >= max_active:
            oldest = q.popleft()
            if oldest.dead:
                continue
            _expire_draft(oldest, ts, "cap_expiry", diagnostics)

        draft = _Draft(
            id=next_id,
            direction=direction,
            origin_pos=origin,
            origin_timestamp=index[origin],
            activation_pos=i,
            activation_timestamp=ts,
            top=top,
            bottom=bottom,
            first_touch_timestamp=None,
            invalidation_timestamp=None,
            expiry_timestamp=None,
            structure_event_id=ev.id,
        )
        next_id += 1
        drafts.append(draft)
        q.append(draft)

    for i in range(n):
        ts = index[i]
        # 1) Age-based expiry at the start of the bar.
        _natural_expire(i, ts)
        # 2) Touch / invalidation for zones already active before this bar.
        _lifecycle_bar(i, ts)
        # 3) Activate new BOS-derived OBs (eligible from next bar for lifecycle).
        for ev in bos_by_pos.get(i, ()):
            _activate_bos(ev, i, ts)

    # Any remaining live drafts keep expiry_timestamp None if age never reached.
    events = tuple(d.to_event() for d in drafts)
    return OrderBlockResult(events=events, diagnostics=tuple(diagnostics))
