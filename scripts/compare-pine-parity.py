#!/usr/bin/env python3
"""Compare Python and Pine parity CSV exports with stable tolerances."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

KEY_COLUMNS = ["dataset", "row_type", "module", "bar_time", "event_id"]
FLOAT_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "level",
    "top",
    "bottom",
    "wick_atr",
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
    "broken_level",
    "level_mean",
    "level_min",
    "level_max",
}
BOOL_COLUMNS = {"swept", "range_expansion", "expansion_qualified"}


def load_fixture(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in KEY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} missing key columns: {missing}")
    return frame.fillna("")


def _same_float(lhs: str, rhs: str, abs_tol: float) -> bool:
    if lhs == rhs:
        return True
    if lhs == "" or rhs == "":
        return lhs == rhs
    left = float(lhs)
    right = float(rhs)
    if not np.isfinite(left) or not np.isfinite(right):
        return bool(np.isnan(left) and np.isnan(right))
    return abs(left - right) <= abs_tol


def _same_bool(lhs: str, rhs: str) -> bool:
    return lhs.strip().lower() == rhs.strip().lower()


def compare_frames(
    lhs: pd.DataFrame,
    rhs: pd.DataFrame,
    *,
    abs_tol: float = 1e-9,
    max_examples: int = 20,
) -> dict[str, Any]:
    lhs_indexed = lhs.set_index(KEY_COLUMNS, drop=False)
    rhs_indexed = rhs.set_index(KEY_COLUMNS, drop=False)
    lhs_keys = set(lhs_indexed.index.tolist())
    rhs_keys = set(rhs_indexed.index.tolist())

    missing_in_rhs = sorted(lhs_keys - rhs_keys)[:max_examples]
    extra_in_rhs = sorted(rhs_keys - lhs_keys)[:max_examples]
    shared_columns = [column for column in lhs.columns if column in rhs.columns and column not in KEY_COLUMNS]
    mismatches: list[dict[str, Any]] = []

    for key in sorted(lhs_keys & rhs_keys):
        left_row = lhs_indexed.loc[key]
        right_row = rhs_indexed.loc[key]
        if isinstance(left_row, pd.DataFrame) or isinstance(right_row, pd.DataFrame):
            raise ValueError(f"duplicate key row detected: {key}")
        for column in shared_columns:
            left_value = str(left_row[column])
            right_value = str(right_row[column])
            if column in FLOAT_COLUMNS:
                same = _same_float(left_value, right_value, abs_tol)
            elif column in BOOL_COLUMNS:
                same = _same_bool(left_value, right_value)
            else:
                same = left_value == right_value
            if same:
                continue
            mismatches.append(
                {
                    "key": dict(zip(KEY_COLUMNS, key, strict=False)),
                    "column": column,
                    "lhs": left_value,
                    "rhs": right_value,
                }
            )
            if len(mismatches) >= max_examples:
                break
        if len(mismatches) >= max_examples:
            break

    return {
        "lhs_rows": int(len(lhs)),
        "rhs_rows": int(len(rhs)),
        "missing_rows": len(lhs_keys - rhs_keys),
        "extra_rows": len(rhs_keys - lhs_keys),
        "value_mismatches": len(mismatches),
        "missing_examples": [dict(zip(KEY_COLUMNS, key, strict=False)) for key in missing_in_rhs],
        "extra_examples": [dict(zip(KEY_COLUMNS, key, strict=False)) for key in extra_in_rhs],
        "mismatch_examples": mismatches,
        "matches": not missing_in_rhs and not extra_in_rhs and not mismatches,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-reference", required=True, type=Path)
    parser.add_argument("--pine-output", required=True, type=Path)
    parser.add_argument("--abs-tol", type=float, default=1e-9)
    parser.add_argument("--max-examples", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = compare_frames(
        load_fixture(args.python_reference),
        load_fixture(args.pine_output),
        abs_tol=args.abs_tol,
        max_examples=args.max_examples,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"matches={summary['matches']}")
        print(f"missing_rows={summary['missing_rows']}")
        print(f"extra_rows={summary['extra_rows']}")
        print(f"value_mismatches={summary['value_mismatches']}")
        if summary["mismatch_examples"]:
            first = summary["mismatch_examples"][0]
            print(f"first_mismatch={json.dumps(first, sort_keys=True)}")
    return 0 if summary["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
