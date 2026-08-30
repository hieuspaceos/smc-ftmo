"""Export Python backtest trade list to MT5-replay CSV.

The MT5 Strategy Tester validation plan (260831-0437) needs a CSV of
trades that an MQL5 EA can replay bar-by-bar. This script runs the
existing scale-in backtest and writes that CSV with all the fields the
replay EA needs:

  - signal_id   : unique id (bt-NNNNN) so the EA can dedupe
  - side        : 'long' | 'short'
  - entry       : entry price (level from Pine)
  - sl          : stop loss (original SL; for scale-in, this is often
                  moved to entry (BE) after the 2R trigger)
  - tp1/tp2/tp3 : the 3 take-profit ladder levels (Python emits all 3
                  even when only one fires — the EA uses tp1 only by
                  default to match mql5_reader.mq5 behavior)
  - risk_pct    : 0.0055 for FTMO default
  - timestamp_entry : bar close time when trade opened (ISO 8601)
  - timestamp_exit  : bar close time when trade closed (ISO 8601)
  - python_r_multiple : baseline R-multiple from Python (no spread) —
                  the simulator uses this as the "ground truth" so
                  that scale-in partial closes (e.g. +1R locked at 2R
                  + cascade 0R at entry) are preserved.
  - python_pnl_usd : baseline PnL in USD (no spread)
  - exit_reason : 'tp4r' | 'sl' | 'leg2_sl' (scale-in exit taxonomy)

Run from project root:
    python -m scripts.export_mt5_replay_csv
    python -m scripts.export_mt5_replay_csv --out output/mt5_replay_trades.csv

Actual baseline on EURUSD 2016-2026 (2026-08-31):
  - Trades: ~603
  - PnL: ~$456K
  - Winrate: ~37%
  - Profit factor: ~3.57
  - Max DD: ~3.4%
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backtester import run_backtest  # noqa: E402


# Default config — must match scripts/btest_scale_in.py to produce the
# documented scale_in Design A numbers (~603 trades, +$456K, PF ~3.57).
DEFAULT_CONFIG = {
    "ftmo": {"account_size": 100_000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0, "max_open_positions": 1},
    "strategy": {
        "swing_length": 10,
        "rr_target": 4.0,
        "displacement_atr_mult": 1.5,
        "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4,
        "require_displacement": True,
        "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        "bias_mode": "strict",
        "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": None,  # Design A
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
}


CSV_FIELDS = [
    "signal_id", "side", "entry", "sl", "tp1", "tp2", "tp3",
    "risk_pct", "timestamp_entry", "timestamp_exit",
    "python_r_multiple", "python_pnl_usd", "exit_reason",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "output" / "mt5_replay_trades.csv",
        help="Output CSV path (default: output/mt5_replay_trades.csv)",
    )
    parser.add_argument(
        "--pair",
        default="EURUSD",
        help="Symbol to backtest (default: EURUSD)",
    )
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    trades, _ = run_backtest(pair=args.pair, config=DEFAULT_CONFIG)
    if not trades:
        print("backtest produced 0 trades — abort", file=sys.stderr)
        return 2

    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for i, t in enumerate(trades):
            writer.writerow({
                "signal_id": f"bt-{i:05d}",
                "side": t["side"],
                "entry": f"{t['entry']:.5f}",
                "sl": f"{t['sl']:.5f}",
                "tp1": f"{t['tp1']:.5f}",
                "tp2": f"{t['tp2']:.5f}",
                "tp3": f"{t['tp3']:.5f}",
                "risk_pct": "0.0055",
                "timestamp_entry": t["timestamp_entry"],
                "timestamp_exit": t["timestamp_exit"],
                "python_r_multiple": f"{t['r_multiple']:.6f}",
                "python_pnl_usd": f"{t['pnl_usd']:.2f}",
                "exit_reason": t["exit_reason"],
            })
    print(f"Wrote {len(trades)} trades to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())