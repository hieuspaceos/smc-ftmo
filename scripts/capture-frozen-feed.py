#!/usr/bin/env python3
"""Capture a frozen-feed parity bundle for a single TradingView symbol/timeframe.

This script takes a raw OHLC CSV/parquet for a frozen TradingView window,
normalizes it, and produces the parity artifacts:

- normalized OHLC CSV
- SHA-256 metadata (source, symbol, feed, timeframe, timezone, session, window,
  engine settings, OHLC checksum)
- Python reference CSV
- Pine capture placeholder file with the matching header so the comparator can
  diff against a real Pine dump once TradingView replay is finished

The Pine output is intentionally empty in this script; populate it manually
from a Bar Replay export in the same canonical shape, then run
``compare-pine-parity.py`` to diff.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "export_pine_parity_fixtures", SCRIPTS_DIR / "export-pine-parity-fixtures.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover - guard
    raise ImportError("could not load export-pine-parity-fixtures module")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
DEFAULT_SETTINGS = _mod.DEFAULT_SETTINGS
build_metadata = _mod.build_metadata
export_ohlc_csv = _mod.export_ohlc_csv
export_reference_csv = _mod.export_reference_csv
load_ohlc = _mod.load_ohlc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Raw OHLC CSV or parquet for the frozen feed window",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Logical dataset name (e.g. fxpro-eurusd-m15)",
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="TradingView ticker, e.g. FXPRO:EURUSD",
    )
    parser.add_argument(
        "--feed",
        required=True,
        help="TradingView feed/exchange label, e.g. FXPRO",
    )
    parser.add_argument(
        "--timeframe",
        required=True,
        help="Timeframe, e.g. M15, H1",
    )
    parser.add_argument(
        "--timezone",
        default="UTC",
        help="Timezone string (UTC or IANA name)",
    )
    parser.add_argument(
        "--session",
        default="America/New_York",
        help="Session timezone used for window boundaries",
    )
    parser.add_argument(
        "--window-start",
        required=True,
        help="ISO timestamp (inclusive) for the frozen window start",
    )
    parser.add_argument(
        "--window-end",
        required=True,
        help="ISO timestamp (inclusive) for the frozen window end",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Output directory for the bundle",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)

    df = load_ohlc(args.input)
    if df.empty:
        print("input contains no rows", file=sys.stderr)
        return 2

    normalized_path = args.out_dir / f"{args.dataset}-ohlc.csv"
    reference_path = args.out_dir / f"{args.dataset}-python-reference.csv"
    pine_placeholder = args.out_dir / f"{args.dataset}-pine-output.csv"
    metadata_path = args.out_dir / f"{args.dataset}-metadata.json"

    ohlc_sha = export_ohlc_csv(df, normalized_path)
    frame = export_reference_csv(df, reference_path, args.dataset, DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    metadata = build_metadata(
        dataset=args.dataset,
        source=args.feed,
        symbol=args.symbol,
        timeframe=args.timeframe,
        timezone=args.timezone,
        session=args.session,
        settings=settings,
        ohlc_sha256=ohlc_sha,
        bars=int(len(df)),
        window_start=df.index[0],
        window_end=df.index[-1],
    )
    metadata["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["feed"] = args.feed
    metadata["python_event_count"] = int((frame["row_type"] == "event").sum())
    metadata["python_modules"] = sorted(
        frame.loc[frame["row_type"] == "event", "module"].unique().tolist()
    )
    metadata["user_window_start"] = args.window_start
    metadata["user_window_end"] = args.window_end
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not pine_placeholder.exists():
        # Write the same header so the comparator can diff once Pine data arrives.
        pine_placeholder.write_text(
            "dataset,row_type,module,bar_time,event_id,event_type,direction\n",
            encoding="utf-8",
        )

    print(json.dumps(
        {
            "dataset": args.dataset,
            "rows": int(len(df)),
            "ohlc_csv": str(normalized_path),
            "reference_csv": str(reference_path),
            "pine_placeholder": str(pine_placeholder),
            "metadata": str(metadata_path),
            "ohlc_sha256": ohlc_sha,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
