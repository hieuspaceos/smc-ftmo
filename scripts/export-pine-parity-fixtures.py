#!/usr/bin/env python3
"""Export deterministic Pine parity fixtures from the Python SMC engine."""
from __future__ import annotations

import sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _pkg in ("smc_engine", "smc_bot_core", "smc_bot_webhook", "smc_bot_backtest", "smc_bot_dashboard"):
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# Workspace-aware path setup: each package exposes its own src/.
for _pkg in ("smc_engine", "smc_bot_core", "smc_bot_webhook", "smc_bot_backtest", "smc_bot_dashboard"):
    _src = ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from smc_engine.context import compute_dealing_range_context  # noqa: E402
from smc_engine.displacement import calculate_atr, detect_range_expansion  # noqa: E402
from smc_engine.fvg import detect_fvgs  # noqa: E402
from smc_engine.liquidity_pools import detect_liquidity_pools  # noqa: E402
from smc_engine.order_blocks import detect_order_blocks  # noqa: E402
from smc_engine.structure import detect_structure  # noqa: E402
from smc_engine.sweeps import detect_sweeps  # noqa: E402
from smc_engine.swings import detect_swings  # noqa: E402

FLOAT_FORMAT = "%.10f"
DEFAULT_SETTINGS: dict[str, Any] = {
    "atr_period": 14,
    "swing_length": 10,
    "close_break_buffer_atr": 0.0,
    "displacement_atr_mult": 1.5,
    "sweep_atr_buffer": 0.05,
    "order_block_lookback": 20,
    "order_block_expiry_bars": 200,
    "order_block_cap": 128,
    "fvg_expiry_bars": 200,
    "fvg_cap": 128,
}
BOOL_COLUMNS = {
    "expansion_qualified",
    "range_expansion",
    "swept",
}
FLOAT_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "atr",
    "range_atr",
    "body_atr",
    "body_ratio",
    "close_location",
    "structure_bos",
    "structure_choch",
    "structure_broken_level",
    "last_swing_high",
    "last_swing_low",
    "swing_direction",
    "context_equilibrium",
    "context_range_high",
    "context_range_low",
    "current_price",
    "level",
    "top",
    "bottom",
    "broken_level",
    "wick_atr",
    "level_mean",
    "level_min",
    "level_max",
}
CSV_COLUMNS = [
    "dataset",
    "row_type",
    "module",
    "bar_time",
    "event_id",
    "event_type",
    "direction",
    "open",
    "high",
    "low",
    "close",
    "pivot_time",
    "pivot_pos",
    "origin_time",
    "origin_pos",
    "activation_time",
    "activation_pos",
    "level",
    "top",
    "bottom",
    "source_swing_id",
    "source_structure_event_id",
    "prior_trend",
    "next_trend",
    "first_touch_time",
    "invalidation_time",
    "expiry_time",
    "fill_time",
    "sweep_time",
    "sweep_pos",
    "swept",
    "wick_atr",
    "range_expansion",
    "member_swing_ids",
    "member_levels",
    "atr",
    "range_atr",
    "body_atr",
    "body_ratio",
    "close_location",
    "expansion_direction",
    "expansion_qualified",
    "structure_trend",
    "structure_bos",
    "structure_choch",
    "structure_broken_level",
    "last_swing_high",
    "last_swing_low",
    "swing_direction",
    "context_bias",
    "context_zone",
    "context_equilibrium",
    "context_range_high",
    "context_range_low",
    "current_price",
    "broken_level",
    "level_mean",
    "level_min",
    "level_max",
    "diagnostic_code",
    "diagnostic_detail",
]


def _timestamp_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not np.isfinite(value):
        return ""
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).isoformat()


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return ""
        return FLOAT_FORMAT % float(value)
    if pd.isna(value):
        return ""
    return str(value)


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df.pop("timestamp"), utc=True)
        df.index = idx
    elif "time" in df.columns:
        idx = pd.to_datetime(df.pop("time"), utc=True)
        df.index = idx
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("input must provide a DatetimeIndex or timestamp/time column")

    index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True))
    if not index.is_unique:
        raise ValueError("index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("index must be monotonic increasing")

    missing = [column for column in ("open", "high", "low", "close") if column not in df.columns]
    if missing:
        raise ValueError(f"missing OHLC columns: {missing}")

    out = df.loc[:, ["open", "high", "low", "close"]].copy()
    out.index = index
    out.index.name = "timestamp"
    for column in out.columns:
        out[column] = out[column].astype(float)
    return out


def load_ohlc(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        raise ValueError(f"unsupported input format: {path.suffix}")
    return _normalize_ohlc(df)


def export_ohlc_csv(df: pd.DataFrame, output_path: Path) -> str:
    rows = ["timestamp,open,high,low,close"]
    for ts, row in df.iterrows():
        rows.append(
            ",".join(
                [
                    pd.Timestamp(ts).isoformat(),
                    FLOAT_FORMAT % float(row["open"]),
                    FLOAT_FORMAT % float(row["high"]),
                    FLOAT_FORMAT % float(row["low"]),
                    FLOAT_FORMAT % float(row["close"]),
                ]
            )
        )
    text = "\n".join(rows) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_row(dataset: str, row_type: str, module: str, **values: Any) -> dict[str, str]:
    row = {column: "" for column in CSV_COLUMNS}
    row["dataset"] = dataset
    row["row_type"] = row_type
    row["module"] = module
    for key, value in values.items():
        if key not in row:
            raise KeyError(f"unknown fixture column: {key}")
        if key.endswith("_time") or key == "bar_time":
            row[key] = _timestamp_text(value)
        else:
            row[key] = _scalar_text(value)
    return row


def _sorted_frame(rows: list[dict[str, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=CSV_COLUMNS)
    sort_columns = ["bar_time", "row_type", "module", "activation_pos", "event_id", "diagnostic_code"]
    return frame.sort_values(sort_columns, kind="stable", na_position="last").reset_index(drop=True)


def _diagnostic_rows(dataset: str, module: str, diagnostics: tuple[Any, ...]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for pos, item in enumerate(diagnostics):
        if hasattr(item, "timestamp"):
            rows.append(
                _canonical_row(
                    dataset,
                    "diagnostic",
                    module,
                    event_id=pos,
                    bar_time=getattr(item, "timestamp"),
                    activation_pos=getattr(item, "pos", ""),
                    diagnostic_code=getattr(item, "code", ""),
                    diagnostic_detail=json.dumps(
                        {
                            "high_swing_id": getattr(item, "high_swing_id", None),
                            "low_swing_id": getattr(item, "low_swing_id", None),
                        },
                        sort_keys=True,
                    ),
                )
            )
        else:
            rows.append(
                _canonical_row(
                    dataset,
                    "diagnostic",
                    module,
                    event_id=pos,
                    diagnostic_code=str(item).split("@", 1)[0],
                    diagnostic_detail=str(item),
                )
            )
    return rows


def build_reference_rows(df: pd.DataFrame, dataset: str, settings: dict[str, Any]) -> list[dict[str, str]]:
    left = right = max(2, int(settings["swing_length"]) // 2)
    atr = calculate_atr(df, period=int(settings["atr_period"]))
    swings = detect_swings(df, left=left, right=right)
    expansion = detect_range_expansion(df, atr, multiplier=float(settings["displacement_atr_mult"]))
    structure = detect_structure(
        df,
        swings,
        atr=atr,
        close_break_buffer_atr=float(settings["close_break_buffer_atr"]),
    )
    sweeps = detect_sweeps(
        df,
        swings,
        atr,
        atr_buffer=float(settings["sweep_atr_buffer"]),
        range_expansion_mult=float(settings["displacement_atr_mult"]),
    )
    order_blocks = detect_order_blocks(
        df,
        structure,
        expansion,
        candidate_lookback=int(settings["order_block_lookback"]),
        expiry_bars=int(settings["order_block_expiry_bars"]),
        max_active_zones_per_direction=int(settings["order_block_cap"]),
    )
    fvgs = detect_fvgs(
        df,
        expiry_bars=int(settings["fvg_expiry_bars"]),
        max_active_per_direction=int(settings["fvg_cap"]),
    )
    context = compute_dealing_range_context(df, structure)
    pools = detect_liquidity_pools(df, swings, atr)

    rows: list[dict[str, str]] = []

    for ts in df.index:
        rows.append(
            _canonical_row(
                dataset,
                "bar_state",
                "core",
                bar_time=ts,
                open=df.at[ts, "open"],
                high=df.at[ts, "high"],
                low=df.at[ts, "low"],
                close=df.at[ts, "close"],
                atr=atr.at[ts],
                range_atr=expansion.range_atr.at[ts],
                body_atr=expansion.body_atr.at[ts],
                body_ratio=expansion.body_ratio.at[ts],
                close_location=expansion.close_location.at[ts],
                expansion_direction=expansion.direction.at[ts],
                expansion_qualified=expansion.qualified.at[ts],
                structure_trend=structure.trend.at[ts],
                structure_bos=structure.bos.at[ts],
                structure_choch=structure.choch.at[ts],
                structure_broken_level=structure.broken_level.at[ts],
                last_swing_high=structure.last_swing_high.at[ts],
                last_swing_low=structure.last_swing_low.at[ts],
                swing_direction=structure.swing_direction.at[ts],
                context_bias=context.bias.at[ts],
                context_zone=context.zone.at[ts],
                context_equilibrium=context.equilibrium.at[ts],
                context_range_high=context.range_high.at[ts],
                context_range_low=context.range_low.at[ts],
                current_price=context.current_price.at[ts],
            )
        )

    for event in swings.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "swing",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                direction=event.direction,
                pivot_time=event.pivot_timestamp,
                pivot_pos=event.pivot_pos,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                level=event.level,
            )
        )

    for event in structure.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "structure",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                event_type=event.type,
                direction=event.direction,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                broken_level=event.broken_level,
                source_swing_id=event.source_swing_id,
                prior_trend=event.prior_trend,
                next_trend=event.next_trend,
            )
        )

    for event in sweeps.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "sweep",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                direction=event.direction,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                source_swing_id=event.source_swing_id,
                level=event.swept_level,
                wick_atr=event.wick_atr,
                close_location=event.close_location,
                range_expansion=event.range_expansion,
            )
        )

    for event in order_blocks.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "order_block",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                direction=event.direction,
                origin_time=event.origin_timestamp,
                origin_pos=event.origin_pos,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                top=event.top,
                bottom=event.bottom,
                first_touch_time=event.first_touch_timestamp,
                invalidation_time=event.invalidation_timestamp,
                expiry_time=event.expiry_timestamp,
                source_structure_event_id=event.structure_event_id,
            )
        )

    for event in fvgs.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "fvg",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                direction=event.direction,
                origin_time=event.origin_timestamp,
                origin_pos=event.origin_pos,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                top=event.top,
                bottom=event.bottom,
                first_touch_time=event.first_touch_timestamp,
                fill_time=event.fill_timestamp,
                expiry_time=event.expiry_timestamp,
            )
        )

    for event in pools.events:
        rows.append(
            _canonical_row(
                dataset,
                "event",
                "liquidity_pool",
                bar_time=event.activation_timestamp,
                event_id=event.id,
                direction=event.side,
                activation_time=event.activation_timestamp,
                activation_pos=event.activation_pos,
                level_mean=event.level_mean,
                level_min=event.level_min,
                level_max=event.level_max,
                member_swing_ids="|".join(str(value) for value in event.member_swing_ids),
                member_levels="|".join(FLOAT_FORMAT % float(value) for value in event.member_levels),
                swept=event.swept,
                sweep_pos=event.sweep_pos,
                sweep_time=event.sweep_timestamp,
            )
        )

    rows.extend(_diagnostic_rows(dataset, "structure", structure.diagnostics))
    rows.extend(_diagnostic_rows(dataset, "sweep", sweeps.diagnostics))
    rows.extend(_diagnostic_rows(dataset, "order_block", order_blocks.diagnostics))
    rows.extend(_diagnostic_rows(dataset, "fvg", fvgs.diagnostics))
    return rows


def export_reference_csv(df: pd.DataFrame, output_path: Path, dataset: str, settings: dict[str, Any]) -> pd.DataFrame:
    rows = build_reference_rows(df, dataset, settings)
    frame = _sorted_frame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def build_metadata(
    *,
    dataset: str,
    source: str,
    symbol: str,
    timeframe: str,
    timezone: str,
    session: str | None,
    settings: dict[str, Any],
    ohlc_sha256: str,
    bars: int,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": timezone,
        "session": session,
        "bars": bars,
        "window_start": pd.Timestamp(window_start).isoformat(),
        "window_end": pd.Timestamp(window_end).isoformat(),
        "ohlc_sha256": ohlc_sha256,
        "settings": settings,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-reference", required=True, type=Path)
    parser.add_argument("--output-ohlc", type=Path)
    parser.add_argument("--output-metadata", type=Path)
    parser.add_argument("--dataset-name", default="dataset")
    parser.add_argument("--source", default="local")
    parser.add_argument("--symbol", default="UNKNOWN")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--session")
    parser.add_argument("--atr-period", type=int, default=DEFAULT_SETTINGS["atr_period"])
    parser.add_argument("--swing-length", type=int, default=DEFAULT_SETTINGS["swing_length"])
    parser.add_argument("--close-break-buffer-atr", type=float, default=DEFAULT_SETTINGS["close_break_buffer_atr"])
    parser.add_argument("--displacement-atr-mult", type=float, default=DEFAULT_SETTINGS["displacement_atr_mult"])
    parser.add_argument("--sweep-atr-buffer", type=float, default=DEFAULT_SETTINGS["sweep_atr_buffer"])
    parser.add_argument("--order-block-lookback", type=int, default=DEFAULT_SETTINGS["order_block_lookback"])
    parser.add_argument("--order-block-expiry-bars", type=int, default=DEFAULT_SETTINGS["order_block_expiry_bars"])
    parser.add_argument("--order-block-cap", type=int, default=DEFAULT_SETTINGS["order_block_cap"])
    parser.add_argument("--fvg-expiry-bars", type=int, default=DEFAULT_SETTINGS["fvg_expiry_bars"])
    parser.add_argument("--fvg-cap", type=int, default=DEFAULT_SETTINGS["fvg_cap"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = {
        "atr_period": args.atr_period,
        "swing_length": args.swing_length,
        "close_break_buffer_atr": args.close_break_buffer_atr,
        "displacement_atr_mult": args.displacement_atr_mult,
        "sweep_atr_buffer": args.sweep_atr_buffer,
        "order_block_lookback": args.order_block_lookback,
        "order_block_expiry_bars": args.order_block_expiry_bars,
        "order_block_cap": args.order_block_cap,
        "fvg_expiry_bars": args.fvg_expiry_bars,
        "fvg_cap": args.fvg_cap,
    }
    df = load_ohlc(args.input)

    ohlc_sha256 = ""
    if args.output_ohlc is not None:
        ohlc_sha256 = export_ohlc_csv(df, args.output_ohlc)

    export_reference_csv(df, args.output_reference, args.dataset_name, settings)

    if args.output_metadata is not None:
        if not ohlc_sha256:
            ohlc_sha256 = export_ohlc_csv(df, args.output_reference.with_name(f"{args.output_reference.stem}-ohlc.csv"))
        metadata = build_metadata(
            dataset=args.dataset_name,
            source=args.source,
            symbol=args.symbol,
            timeframe=args.timeframe,
            timezone=args.timezone,
            session=args.session,
            settings=settings,
            ohlc_sha256=ohlc_sha256,
            bars=len(df),
            window_start=df.index[0],
            window_end=df.index[-1],
        )
        args.output_metadata.parent.mkdir(parents=True, exist_ok=True)
        args.output_metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
