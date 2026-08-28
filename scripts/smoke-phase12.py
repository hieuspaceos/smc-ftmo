"""Phase 12 smoke output — characterizes the engine after cutover.

Outputs a deterministic JSON snapshot of bias distributions, trade sides,
backtest metrics, runtime and M15 dataset checksum.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backtester import run_backtest, compute_metrics
from data_loader import load_multi_tf_data
from bias_detector import detect_bias_multi_tf


def _checksum(series) -> str:
    arr = series.astype("float64").round(6).to_numpy()
    payload = f"{arr.shape[0]}|" + ",".join(f"{x:.6f}" for x in arr)
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> dict:
    cfg = {
        "risk": {"per_trade_pct": 0.0055, "max_trades_per_day": 3,
                 "daily_loss_limit_r": 2.0, "max_open_positions": 1},
        "strategy": {"swing_length": 10, "rr_target": 2.5,
                      "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
                      "min_confluence_score": 4, "require_displacement": True,
                      "require_bias_aligned": True, "sl_atr_buffer": 0.2},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "pd_lookback": 50,
    }
    data = load_multi_tf_data("EURUSD")
    bias = detect_bias_multi_tf(data, swing_length=10)
    t0 = time.perf_counter()
    trades, eq = run_backtest(pair="EURUSD", config=cfg)
    t1 = time.perf_counter()
    metrics = compute_metrics(trades, eq)
    sides = Counter(t["side"] for t in trades)
    smoke = {
        "pair": "EURUSD",
        "bias_multi_tf": {tf: v for tf, v in bias.items()},
        "bias_distribution": dict(Counter(bias.values())),
        "trade_total": metrics["total_trades"],
        "trade_long": sides.get("long", 0),
        "trade_short": sides.get("short", 0),
        "winrate": metrics["winrate"],
        "profit_factor": metrics["profit_factor"],
        "avg_r": metrics["avg_r"],
        "total_r": metrics["total_r"],
        "max_dd_pct": metrics["max_dd_pct"],
        "final_equity": metrics["final_equity"],
        "m15_bars": len(data["M15"]),
        "m15_close_sha256": _checksum(data["M15"]["close"]),
        "runtime_seconds": round(t1 - t0, 4),
    }
    out_dir = ROOT / "plans" / "12-smc-engine-rewrite" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "smoke-final.json").write_text(json.dumps(smoke, indent=2))
    return smoke


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
