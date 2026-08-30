"""Format raw HistData DAT_ASCII CSV → M1 + D + H4 + H1 + M15 parquet.

Input format (HistData DAT_ASCII, e.g. EURUSD_M1_202601.csv):
    YYYYMMDD HHMMSS;OPEN;HIGH;LOW;CLOSE;VOL

Outputs:
    eurusd_m1.parquet      every-minute detail (1.7M rows for 10y)
    eurusd_d.parquet       resampled daily (3324 rows for 10y)
    eurusd_h4.parquet      resampled 4-hourly (17080 rows for 10y)
    eurusd_h1.parquet      resampled hourly (65408 rows for 10y)
    eurusd_m15.parquet     resampled 15-min (replaces existing 8-month file)
    eurusd_m15_full.parquet  same M15 with _full suffix (kept for parity)

Usage:
    python scripts/format_histdata.py [INPUT_DIR] [OUTPUT_DIR]

Defaults: ./histdata → ./data

Backtest uses D/H4/H1/M15 from output dir — this script now also writes
D/H4/H1 (critical: without them, the backtest only scans data where all 4
timeframes overlap, e.g. 8 months instead of 10 years).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def format_histdata(
    input_dir: Path,
    output_dir: Path,
    symbol: str = "EURUSD",
    timeframe: str = "M15",
) -> dict[str, int]:
    """Read all DAT_ASCII_<symbol>_<tf>_<YYYYMM>.csv → parquet.

    Outputs M1, M15, D, H4, H1. The HTF files (D, H4, H1) are critical for
    backtest bias alignment — without them, scan range shrinks to wherever
    HTF data overlaps with M15 (typically 8 months if only 2026 HTF exists).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = f"DAT_ASCII_{symbol}_*"
    csv_files = sorted(input_dir.glob(pattern))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files matching {pattern} in {input_dir}")

    print(f"Reading {len(csv_files)} CSV file(s) from {input_dir}...")
    all_dfs = []
    for csv in csv_files:
        print(f"  {csv.name}... ", end="", flush=True)
        df = pd.read_csv(
            csv, sep=";", header=None,
            names=["timestamp_str", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp_str"], format="%Y%m%d %H%M%S")
        df = df.drop(columns=["timestamp_str"])
        all_dfs.append(df)
        print(f"{len(df):,} rows")

    raw = pd.concat(all_dfs, ignore_index=True)
    print(f"\n  total raw rows: {len(raw):,}")
    raw = raw.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    print(f"  after dedupe:   {len(raw):,}")

    # Save M1 parquet (every-minute detail preserved).
    m1_path = output_dir / f"{symbol.lower()}_m1.parquet"
    raw.to_parquet(m1_path)
    print(f"  wrote {m1_path.name}: {m1_path.stat().st_size:,} bytes")

    # Resample to higher timeframes.
    m1_indexed = raw.set_index("timestamp")

    # Daily (1D)
    df_d = m1_indexed.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    d_path = output_dir / f"{symbol.lower()}_d.parquet"
    df_d_out = df_d.copy(); df_d_out.index.name = "timestamp"
    df_d_out.to_parquet(d_path)
    print(f"  wrote {d_path.name}: {d_path.stat().st_size:,} bytes ({len(df_d_out):,} rows)")

    # 4-hourly (4h)
    df_h4 = m1_indexed.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    h4_path = output_dir / f"{symbol.lower()}_h4.parquet"
    df_h4_out = df_h4.copy(); df_h4_out.index.name = "timestamp"
    df_h4_out.to_parquet(h4_path)
    print(f"  wrote {h4_path.name}: {h4_path.stat().st_size:,} bytes ({len(df_h4_out):,} rows)")

    # Hourly (1h)
    df_h1 = m1_indexed.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])
    h1_path = output_dir / f"{symbol.lower()}_h1.parquet"
    df_h1_out = df_h1.copy(); df_h1_out.index.name = "timestamp"
    df_h1_out.to_parquet(h1_path)
    print(f"  wrote {h1_path.name}: {h1_path.stat().st_size:,} bytes ({len(df_h1_out):,} rows)")

    # Target timeframe (default M15)
    resample_period = f"{int(timeframe[1:]):}min" if timeframe.startswith("M") else timeframe
    higher = m1_indexed.resample(resample_period).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["open"])

    out_path = output_dir / f"{symbol.lower()}_{timeframe.lower()}_full.parquet"
    higher.to_parquet(out_path)
    print(f"  wrote {out_path.name}: {out_path.stat().st_size:,} bytes")
    print(f"  {timeframe} rows: {len(higher):,}")
    print(f"  {timeframe} range: {higher.index.min()} → {higher.index.max()}")

    # Replace the main M15 file too (used by backtest).
    m15_path = output_dir / f"{symbol.lower()}_{timeframe.lower()}.parquet"
    higher.to_parquet(m15_path)
    print(f"  wrote {m15_path.name}: {m15_path.stat().st_size:,} bytes (replaces existing 8-month file)")

    # Compare to existing main file in same output dir (now overwritten).
    existing_name = f"{symbol.lower()}_{timeframe.lower()}.parquet"
    existing_path = output_dir / existing_name
    if existing_path.exists():
        existing = pd.read_parquet(existing_path)
        common_idx = higher.index.intersection(existing.index)
        print(f"\n  vs existing {existing_name} ({len(existing):,} rows):")
        print(f"    common timestamps: {len(common_idx):,}")
        if len(common_idx) > 0:
            close_diff = (
                higher.loc[common_idx, "close"] - existing.loc[common_idx, "close"]
            ).abs().max()
            print(f"    max close-price diff: {close_diff}")

    return {
        "raw_rows": len(raw),
        f"{timeframe}_rows": len(higher),
        "D_rows": len(df_d_out),
        "H4_rows": len(df_h4_out),
        "H1_rows": len(df_h1_out),
        "input_files": len(csv_files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Format HistData CSV → parquet")
    parser.add_argument("input_dir", nargs="?", default="histdata", type=Path)
    parser.add_argument("output_dir", nargs="?", default="data", type=Path)
    parser.add_argument("--symbol", default="EURUSD", help="symbol (default EURUSD)")
    parser.add_argument("--timeframe", default="M15", choices=["M1", "M5", "M15", "M30", "H1"],
                        help="resample timeframe (default M15)")
    args = parser.parse_args()

    try:
        stats = format_histdata(args.input_dir, args.output_dir, args.symbol, args.timeframe)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"\nDone: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
