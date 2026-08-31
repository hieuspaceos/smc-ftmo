"""Run all backtest scripts and snapshot outputs.

Post-fix baseline (Phase 08 Step 1): calculate_lot() bug fixed, so USD
figures will differ from pre-fix claimed numbers. This script runs every
btest_*.py module and saves stdout to output/baselines_post_step1_fix/.

Usage from project root:
    python scripts/run_backtest_baselines.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "baselines_post_step1_fix"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Modules in scripts/ that start with btest_ and are runnable as scripts.
SCRIPTS = [
    "btest_scale_in",
    "btest_scale_in_design_b",
    "btest_balanced",
    "btest_h4_only",
    "btest_ui_defaults",
]


def run_one(name: str) -> tuple[str, str, int, float]:
    """Run scripts.btest_<name> as a module, capture stdout."""
    env = os.environ.copy()
    # Path setup mirroring conftest.py + the leading 'src' so 'from src.X' works.
    extra = [
        str(ROOT / "src"),
        str(ROOT / "packages" / "smc_engine" / "src"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(extra + env.get("PYTHONPATH", "").split(os.pathsep))

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", f"scripts.{name}"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed = time.perf_counter() - t0

    out = proc.stdout
    if proc.stderr:
        out += "\n--- STDERR ---\n" + proc.stderr

    out_path = OUT_DIR / f"{name}.txt"
    out_path.write_text(out, encoding="utf-8")

    return name, out, proc.returncode, elapsed


def main() -> int:
    print(f"Output dir: {OUT_DIR}")
    print(f"Running {len(SCRIPTS)} backtest scripts...\n")

    results = []
    for name in SCRIPTS:
        print(f"[run] {name} ...", flush=True)
        try:
            n, out, rc, dt = run_one(name)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT after 600s")
            results.append((name, "TIMEOUT", -1, 600.0))
            continue
        status = "OK" if rc == 0 else f"FAIL (rc={rc})"
        print(f"  {status}  ({dt:.0f}s)")
        results.append((name, status, rc, dt))

    print("\n=== Summary ===")
    for name, status, rc, dt in results:
        print(f"  {name:30s}  {status:20s}  {dt:.0f}s")

    return 0 if all(rc == 0 for _, _, rc, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
