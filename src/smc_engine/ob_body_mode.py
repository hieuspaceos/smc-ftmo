"""OB Body-only zone recompute — non-invasive post-processing layer.

Plan 13 Phase 3: alternative OB zone definition that uses the origin
candle's body (open↔close) instead of the full wick range (high↔low).
Tighter entry zones often yield higher hit rates at the cost of fewer fills.

Like :mod:`breaker_blocks`, this is a pure post-processing function over the
existing ``OrderBlockResult``. It does NOT mutate the base
``detect_order_blocks`` engine.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from smc_engine.order_blocks import OrderBlockEvent, OrderBlockResult

OB_ZONE_MODES = ("full", "body")


def recompute_zones(
    ob_result: OrderBlockResult,
    df: pd.DataFrame,
    mode: str = "full",
) -> OrderBlockResult:
    """Return a new ``OrderBlockResult`` with ``top``/``bottom`` recomputed.

    - ``"full"`` (default): returns the original zones untouched (identity).
    - ``"body"``: ``top = max(open, close)``, ``bottom = min(open, close)``
      at each OB's origin position. Tighter zone, body-only.

    For ``"full"`` mode this is the identity function: same events, same
    diagnostics. For ``"body"`` mode the new events have narrower zones
    but identical origin/activation/invalidation metadata.
    """
    if mode not in OB_ZONE_MODES:
        raise ValueError(f"mode must be one of {OB_ZONE_MODES!r}, got {mode!r}")
    if mode == "full":
        return ob_result

    open_arr = df["open"].to_numpy(dtype=float, copy=False)
    close_arr = df["close"].to_numpy(dtype=float, copy=False)

    new_events: list[OrderBlockEvent] = []
    for ob in ob_result.events:
        i = ob.origin_pos
        if not (0 <= i < len(open_arr) and 0 <= i < len(close_arr)):
            new_events.append(ob)  # cannot recompute; keep original
            continue
        o = float(open_arr[i])
        c = float(close_arr[i])
        if not (np.isfinite(o) and np.isfinite(c)):
            new_events.append(ob)
            continue
        new_top = max(o, c)
        new_bottom = min(o, c)
        # OB direction already encodes which endpoint is entry side; this
        # recompute only narrows the zone without changing semantics.
        new_events.append(replace(ob, top=new_top, bottom=new_bottom))

    return OrderBlockResult(events=tuple(new_events), diagnostics=ob_result.diagnostics)