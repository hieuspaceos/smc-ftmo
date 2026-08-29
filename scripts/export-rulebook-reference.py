#!/usr/bin/env python3
"""Deterministic Rulebook 8W selector reference for parity against Pine.

This module runs the same 11-gate pipeline the Pine indicator uses
(linked BOS provenance, strict bias match, first-test eligibility, no
later CHoCH, proximity, SL width, HTF wall, score threshold, recency,
edge proximity, OB id tiebreak) on top of the existing Python engine
output and emits a per-bar candidate row CSV. The Pine indicator should
produce an equivalent row set when run on the same frozen feed.

The output schema mirrors the parity exporter:

- bar_time, candidate_id, direction, top, bottom, entry, sl, target,
  score, state, rejection, linked_bos_id
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import importlib.util  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "export_pine_parity_fixtures", _SCRIPTS_DIR / "export-pine-parity-fixtures.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
DEFAULT_SETTINGS = _mod.DEFAULT_SETTINGS
FLOAT_FORMAT = _mod.FLOAT_FORMAT
load_ohlc = _mod.load_ohlc
_calculate_atr = _mod.calculate_atr if hasattr(_mod, "calculate_atr") else None

from smc_engine.context import compute_dealing_range_context  # noqa: E402
from smc_engine.displacement import detect_range_expansion  # noqa: E402
from smc_engine.fvg import detect_fvgs  # noqa: E402
from smc_engine.liquidity_pools import detect_liquidity_pools  # noqa: E402
from smc_engine.order_blocks import detect_order_blocks  # noqa: E402
from smc_engine.structure import detect_structure  # noqa: E402
from smc_engine.swings import detect_swings, detect_swings_symmetric  # noqa: E402
from smc_engine.sweeps import detect_sweeps  # noqa: E402


SCORE_THRESHOLD = 4.0
ENTRY_PROXIMITY_ATR = 1.5
SL_EDGE_ATR = 0.2
SL_MAX_ATR = 1.2
MIN_RR = 2.0
CLEAN_SWEEP_ATR = 0.25
MANUAL_GATES_ALL_OK_DEFAULT = True
MANUAL_GATES_UNKNOWN_DEFAULT = False


def session_allowed_america_new_york(ts: pd.Timestamp) -> bool:
    """Rule book §14: only London 02:00-05:00 EST and NY 07:00-10:00 EST.

    Excludes first 15 minutes of London open (02:00-02:15 EST).
    The chart must be set to America/New_York timezone for this to be
    deterministic; otherwise the test caller must pre-shift timestamps.
    """
    h = int(ts.hour)
    m = int(ts.minute)
    in_london = 2 <= h < 5
    in_ny = 7 <= h < 10
    blocked = in_london and h == 2 and m < 15
    return (in_london or in_ny) and not blocked

def _row(bar_time: pd.Timestamp, **values: Any) -> dict[str, str]:
    schema = [
        "dataset",
        "row_type",
        "module",
        "bar_time",
        "event_id",
        "direction",
        "ob_id",
        "linked_bos_id",
        "top",
        "bottom",
        "entry",
        "sl",
        "target",
        "score",
        "state",
        "rejection",
    ]
    row = {key: "" for key in schema}
    row["dataset"] = values.get("dataset", "synthetic")
    row["row_type"] = "candidate"
    row["module"] = "rulebook_selector"
    row["bar_time"] = pd.Timestamp(bar_time).isoformat()
    for key, value in values.items():
        if key in row:
            row[key] = _format_value(value)
    return row


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(float(value)):
            return ""
        return FLOAT_FORMAT % float(value)
    return str(value)


def _atr_series(df: pd.DataFrame, period: int) -> pd.Series:
    if _calculate_atr is not None:
        return _calculate_atr(df, period=period)
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def select_candidates(
    df: pd.DataFrame,
    *,
    dataset: str = "synthetic",
    settings: dict[str, Any] | None = None,
    manual_gates_all_ok: bool = MANUAL_GATES_ALL_OK_DEFAULT,
    manual_gates_unknown: bool = MANUAL_GATES_UNKNOWN_DEFAULT,
    htf_d_trend: int = 0,
    htf_h4_trend: int = 0,
    htf_daily_enabled: bool = True,
    htf_h4_enabled: bool = True,
) -> pd.DataFrame:
    """Run the deterministic Rulebook selector on the input frame.

    Returns a per-bar DataFrame with the schema above.
    """
    cfg = dict(DEFAULT_SETTINGS if settings is None else settings)
    swings = detect_swings_symmetric(df, cfg["swing_length"])
    structure = detect_structure(df, swings)
    context = compute_dealing_range_context(df, structure)
    atr = _atr_series(df, cfg["atr_period"])
    expansion = detect_range_expansion(df, atr, multiplier=cfg["displacement_atr_mult"])
    sweeps = detect_sweeps(
        df,
        swings,
        atr,
        atr_buffer=cfg["sweep_atr_buffer"],
        range_expansion_mult=cfg["displacement_atr_mult"],
    )
    order_blocks = detect_order_blocks(
        df,
        structure,
        expansion,
        candidate_lookback=cfg["order_block_lookback"],
        expiry_bars=cfg["order_block_expiry_bars"],
        max_active_zones_per_direction=cfg["order_block_cap"],
    )
    fvgs = detect_fvgs(
        df,
        expiry_bars=cfg["fvg_expiry_bars"],
        max_active_per_direction=cfg["fvg_cap"],
    )
    pools = detect_liquidity_pools(df, swings, atr)

    # Build per-bar clean-sweep lookup (rule book §8: wick >= 0.25*ATR + reclaim)
    clean_sweep_dir = pd.Series(0, index=df.index, dtype=int)
    clean_sweep_bar = pd.Series(-1, index=df.index, dtype=int)
    atr_buffer_clean = atr * CLEAN_SWEEP_ATR
    for ev in sweeps.events:
        pos = ev.activation_pos
        if pos < 0 or pos >= len(df):
            continue
        atr_now = atr.iloc[pos]
        if not np.isfinite(atr_now) or atr_now <= 0:
            continue
        dir_sign = 1 if ev.direction == "bullish" else -1
        wick_ok = False
        if dir_sign == 1:
            wick_ok = df["low"].iloc[pos] <= ev.swept_level - atr_buffer_clean.iloc[pos]
        else:
            wick_ok = df["high"].iloc[pos] >= ev.swept_level + atr_buffer_clean.iloc[pos]
        if not wick_ok:
            continue
        clean_sweep_dir.iloc[pos] = dir_sign
        clean_sweep_bar.iloc[pos] = pos

    bos_by_id = {event.id: event for event in structure.events}
    choch_by_id = {event.id: event for event in structure.events if event.type == "choch"}

    last_bull_bos_id = -1
    last_bear_bos_id = -1
    last_bull_choch_id = -1
    last_bear_choch_id = -1
    for event in structure.events:
        if event.direction == "bullish":
            if event.type == "choch":
                last_bull_choch_id = event.id
            else:
                last_bull_bos_id = event.id
        else:
            if event.type == "choch":
                last_bear_choch_id = event.id
            else:
                last_bear_bos_id = event.id

    rows: list[dict[str, str]] = []
    last_bull_bos_idx = -1
    last_bear_bos_idx = -1
    last_bull_choch_idx = -1
    last_bear_choch_idx = -1
    structure_trend = 0
    last_idx = len(df) - 1
    pool_high_max = max([event.level_max for event in pools.events if event.side == "high"], default=np.nan)
    pool_low_min = min([event.level_min for event in pools.events if event.side == "low"], default=np.nan)
    for pos in range(len(df)):
        ts = df.index[pos]
        atr_now = atr.iloc[pos] if pos < len(atr) else np.nan
        if not np.isfinite(atr_now) or atr_now <= 0:
            rows.append(_row(ts, dataset=dataset, rejection="no-atr"))
            continue
        # update structure_trend from prior events
        for ev in structure.events:
            if ev.activation_pos == pos:
                structure_trend = 1 if ev.direction == "bullish" else -1
                if ev.type == "bos":
                    if ev.direction == "bullish":
                        last_bull_bos_id = ev.id
                        last_bull_bos_idx = pos
                    else:
                        last_bear_bos_id = ev.id
                        last_bear_bos_idx = pos
                else:
                    if ev.direction == "bullish":
                        last_bull_choch_id = ev.id
                        last_bull_choch_idx = pos
                    else:
                        last_bear_choch_id = ev.id
                        last_bear_choch_idx = pos

        candidates: list[dict[str, Any]] = []
        for ob in order_blocks.events:
            if ob.activation_pos != pos or ob.expired or ob.invalidated:
                continue
            if ob.linked_structure_event_id is None:
                continue
            linked = bos_by_id.get(ob.linked_structure_event_id)
            if linked is None or linked.type != "bos":
                continue
            dir_sign = 1 if ob.direction == "bullish" else -1
            # §4 Bias strict: D == H4 == M15, no neutral
            if htf_daily_enabled and (htf_d_trend == 0 or htf_d_trend != dir_sign):
                continue
            if htf_h4_enabled and (htf_h4_trend == 0 or htf_h4_trend != dir_sign):
                continue
            if dir_sign != structure_trend:
                continue
            if ob.first_touch_pos is not None:
                continue
            if dir_sign == 1 and last_bull_choch_idx > linked.activation_pos:
                continue
            if dir_sign == -1 and last_bear_choch_idx > linked.activation_pos:
                continue
            # §14 Session filter (only effective when df index is in America/New_York)
            if not session_allowed_america_new_york(ts):
                continue
            close_now = df["close"].iloc[pos]
            entry = ob.top if dir_sign == 1 else ob.bottom
            proximity = abs(close_now - entry)
            if proximity > ENTRY_PROXIMITY_ATR * atr_now:
                continue
            sl_edge = ob.bottom - atr_now * SL_EDGE_ATR if dir_sign == 1 else ob.top + atr_now * SL_EDGE_ATR
            sl_dist = abs(entry - sl_edge)
            if sl_dist > SL_MAX_ATR * atr_now:
                continue
            target = entry + MIN_RR * sl_dist if dir_sign == 1 else entry - MIN_RR * sl_dist
            if dir_sign == 1 and np.isfinite(pool_high_max) and target >= pool_high_max:
                continue
            if dir_sign == -1 and np.isfinite(pool_low_min) and target <= pool_low_min:
                continue
            # §13 Score = disp(1) + bias(1) + first-test(1) + sweep_clean(1) OR pd(1)
            score = 0.0
            if expansion.qualified.iloc[pos]:
                score += 1.0
            score += 1.0  # bias matched (already filtered)
            score += 1.0  # first-test eligible
            if int(clean_sweep_dir.iloc[pos]) == dir_sign:
                score += 1.0
            zone_pd = context.zone.iloc[pos] if hasattr(context, "zone") else None
            if (dir_sign == 1 and zone_pd == "discount") or (dir_sign == -1 and zone_pd == "premium"):
                score += 1.0
            if score < SCORE_THRESHOLD:
                continue
            if manual_gates_all_ok:
                state = "chart-qualified"
            elif manual_gates_unknown:
                state = "watch"
            else:
                state = "blocked"
            candidates.append(
                {
                    "ob_id": ob.id,
                    "direction": ob.direction,
                    "top": ob.top,
                    "bottom": ob.bottom,
                    "entry": entry,
                    "sl": sl_edge,
                    "target": target,
                    "score": score,
                    "linked_bos_id": linked.id,
                    "state": state,
                    "activation_pos": ob.activation_pos,
                    "proximity": proximity,
                }
            )
        if not candidates:
            state = "chart-qualified" if manual_gates_all_ok else "watch" if manual_gates_unknown else "blocked"
            rows.append(_row(ts, dataset=dataset, rejection="no-qualifying-ob", state=state))
            continue
        candidates.sort(
            key=lambda c: (-c["activation_pos"], c["proximity"], c["ob_id"])
        )
        winner = candidates[0]
        rows.append(
            _row(
                ts,
                dataset=dataset,
                event_id=winner["ob_id"],
                direction=winner["direction"],
                ob_id=winner["ob_id"],
                linked_bos_id=winner["linked_bos_id"],
                top=winner["top"],
                bottom=winner["bottom"],
                entry=winner["entry"],
                sl=winner["sl"],
                target=winner["target"],
                score=winner["score"],
                state=winner["state"],
                rejection="ok",
            )
        )

    return pd.DataFrame(rows, columns=[
        "dataset",
        "row_type",
        "module",
        "bar_time",
        "event_id",
        "direction",
        "ob_id",
        "linked_bos_id",
        "top",
        "bottom",
        "entry",
        "sl",
        "target",
        "score",
        "state",
        "rejection",
    ])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--dataset", default="synthetic")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--manual-gates",
        choices=["all_ok", "unknown", "blocked"],
        default="all_ok",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    df = load_ohlc(args.input)
    if df.empty:
        print("input contains no rows", file=sys.stderr)
        return 2
    manual_all_ok = args.manual_gates == "all_ok"
    manual_unknown = args.manual_gates == "unknown"
    frame = select_candidates(
        df,
        dataset=args.dataset,
        manual_gates_all_ok=manual_all_ok,
        manual_gates_unknown=manual_unknown,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    print(
        f"wrote {len(frame)} candidate rows for {args.dataset} "
        f"(manual_gates={args.manual_gates}) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
