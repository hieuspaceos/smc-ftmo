"""Monthly breakdown: per (mode, pair, year-month) — N/W/L/R/PnL.

Pair/timeframe: configurable, defaults to EURUSD only with 4 modes.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _build_cfg(mode):
    cfg = {
        "ftmo": {"account_size": 100000, "phase": "challenge",
                 "profit_target": 0.10, "max_daily_loss": 0.05,
                 "max_total_loss": 0.10, "max_open_positions": 1,
                 "daily_loss_limit_r": 2.0},
        "execution": {
            "spread_pips": {
                "EURUSD": 0.5, "GBPUSD": 0.7, "USDCHF": 0.8,
                "XAUUSD": 2.0, "BTCUSD": 5.0,
            },
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3},
        },
        "risk": {"per_trade_pct": 0.0055, "max_trades_per_day": 3,
                 "daily_loss_limit_r": 2.0, "max_open_positions": 1},
        "strategy": {
            "swing_length": 10, "rr_target": 4.0,
            "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
            "min_confluence_score": 4, "require_displacement": True,
            "require_bias_aligned": True, "sl_atr_buffer": 0.2,
            "bias_mode": "strict", "regime_mode": "off",
            "promotion_lookback_bars": 50,
            "partial_tp": [
                {"pct": 0.40, "r": 2.0},
                {"pct": 0.30, "r": 3.0},
                {"pct": 0.30, "r": 4.0},
            ],
            "exit_mode": mode, "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                   "sweep_clean": 1, "premium_discount": 1,
                                   "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01", "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50, "pairs": ["EURUSD"],
    }
    if mode != "ladder":
        cfg["strategy"].pop("partial_tp", None)
    return cfg


def _monthly(trades):
    """Group trades by year-month bucket. Returns DataFrame."""
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "ts": pd.Timestamp(t["timestamp_entry"]),
        "side": t["side"],
        "r": float(t.get("r_multiple", 0) or 0),
        "pnl": float(t.get("pnl_usd", 0) or 0),
        "exit": t.get("exit_reason", "?"),
    } for t in trades])
    df["ym"] = df["ts"].dt.strftime("%Y-%m")
    g = df.groupby("ym").agg(
        N=("r", "size"),
        Wins=("r", lambda s: int((s > 0).sum())),
        Losses=("r", lambda s: int((s <= 0).sum())),
        BE=("r", lambda s: int((s.abs() < 1e-9).sum())),
        Total_R=("r", "sum"),
        Total_PnL=("pnl", "sum"),
        Avg_R=("r", "mean"),
        WR_pct=("r", lambda s: float((s > 0).sum()) / len(s) * 100),
    ).reset_index().sort_values("ym")
    g["Total_R"] = g["Total_R"].round(2)
    g["Total_PnL"] = g["Total_PnL"].round(0)
    g["Avg_R"] = g["Avg_R"].round(3)
    g["WR_pct"] = g["WR_pct"].round(1)
    return g


def main():
    from src.backtester import run_backtest

    pair = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    pairs = [pair]
    modes = ["ladder", "scale_in", "scale_in_middle", "scale_in_middle_1r"]
    out_dir = ROOT / "output" / f"monthly-{pair}"
    out_dir.mkdir(parents=True, exist_ok=True)
    all_md = []

    for mode in modes:
        print(f"\n========== {pair} / {mode} ==========", flush=True)
        cfg = _build_cfg(mode)
        cfg["pairs"] = pairs
        t0 = time.perf_counter()
        trades, eq = run_backtest(pair, cfg)
        elapsed = time.perf_counter() - t0
        mg = _monthly(trades)
        if mg.empty:
            print("  no trades")
            continue
        # Per-pair exit reasons
        from collections import Counter
        exits = Counter(t.get("exit_reason", "?") for t in trades)
        # Print monthly table
        print(f"  n={len(trades)}  elapsed={elapsed:.0f}s")
        print(f"  exits: {dict(exits)}")
        print()
        cols = ["ym", "N", "Wins", "Losses", "Total_R", "Total_PnL", "WR_pct", "Avg_R"]
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(mg[cols].to_string(index=False))

        # Save to disk (one CSV per mode)
        csv_file = out_dir / f"{pair}-{mode}-monthly.csv"
        mg.to_csv(csv_file, index=False)
        print(f"  -> {csv_file}")

        # Save all-months detail trade list
        trade_file = out_dir / f"{pair}-{mode}-trades.csv"
        pd.DataFrame([{
            "ts_entry": t["timestamp_entry"],
            "ts_exit": t["timestamp_exit"],
            "side": t["side"],
            "r": float(t.get("r_multiple", 0) or 0),
            "pnl": float(t.get("pnl_usd", 0) or 0),
            "exit": t.get("exit_reason", "?"),
            "score": t.get("confluence_score"),
        } for t in trades]).to_csv(trade_file, index=False)
        print(f"  -> {trade_file}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
