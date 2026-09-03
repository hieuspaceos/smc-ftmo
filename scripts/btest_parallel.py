"""Parallel backtest: 3 scale_in modes × XAU/BTC/USDCHF.

Runs 9 jobs concurrently using multiprocessing (3 modes x 3 pairs).
Per-pair writes its CSV immediately on completion so you can read
partial output as it arrives.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
from collections import Counter
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.backtester import run_backtest


def _build_cfg(mode, pair):
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
            "exit_mode": mode, "leg2_tp1_r": None,
        },
        "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                   "sweep_clean": 1, "premium_discount": 1,
                                   "first_test": 1}},
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01", "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50, "pairs": [pair],
    }
    if mode != "ladder":
        cfg["strategy"].pop("partial_tp", None)
    return cfg


def _stats(trades, eq):
    if not trades:
        return {}
    n = len(trades)
    wins = [t for t in trades if float(t.get("r_multiple", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("r_multiple", 0) or 0) <= 0]
    be = sum(1 for t in trades if abs(float(t.get("r_multiple", 0) or 0)) < 1e-9)
    total_r = sum(float(t.get("r_multiple", 0) or 0) for t in trades)
    total_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in trades)
    win_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in wins)
    loss_pnl = sum(float(t.get("pnl_usd", 0) or 0) for t in losses)
    avg_win_r = sum(float(t["r_multiple"]) for t in wins) / len(wins) if wins else 0
    avg_loss_r = sum(float(t["r_multiple"]) for t in losses) / len(losses) if losses else 0
    eq_df = pd.DataFrame(eq, columns=["ts", "val"]).set_index("ts")["val"] if eq else None
    dd_pct = ((eq_df / eq_df.cummax() - 1).min() * 100) if eq_df is not None and not eq_df.empty else 0.0
    final_eq = float(eq_df.iloc[-1]) if eq_df is not None and not eq_df.empty else 0.0
    roi_pct = (final_eq / 100000.0 - 1) * 100
    exits = Counter(t.get("exit_reason", "?") for t in trades)
    years = sorted(set(pd.Timestamp(t["timestamp_entry"]).year for t in trades))
    pos_r = sum(float(t["r_multiple"]) for t in wins)
    neg_r = sum(float(t["r_multiple"]) for t in losses)
    pf = abs(pos_r / neg_r) if neg_r else float('inf')
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "wr_pct": round(len(wins) / n * 100, 1),
        "be_count": be,
        "total_r": round(total_r, 1),
        "total_pnl": round(total_pnl, 0),
        "win_pnl": round(win_pnl, 0),
        "loss_pnl": round(loss_pnl, 0),
        "avg_win_R": round(avg_win_r, 2),
        "avg_loss_R": round(avg_loss_r, 2),
        "dd_pct": round(dd_pct, 2),
        "final_eq": round(final_eq, 0),
        "roi_pct": round(roi_pct, 1),
        "pf": round(pf, 3) if pf != float('inf') else "inf",
        "exits": dict(exits),
        "year_range": f"{min(years)}-{max(years)}" if years else "-",
    }


def _monthly(trades):
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "ts": pd.Timestamp(t["timestamp_entry"]),
        "r": float(t.get("r_multiple", 0) or 0),
        "pnl": float(t.get("pnl_usd", 0) or 0),
    } for t in trades])
    df["ym"] = df["ts"].dt.strftime("%Y-%m")
    g = df.groupby("ym").agg(
        N=("r", "size"),
        Wins=("r", lambda s: int((s > 0).sum())),
        Losses=("r", lambda s: int((s <= 0).sum())),
        Total_R=("r", "sum"),
        Total_PnL=("pnl", "sum"),
        WR_pct=("r", lambda s: float((s > 0).sum()) / len(s) * 100),
    ).reset_index().sort_values("ym")
    g["Total_R"] = g["Total_R"].round(2)
    g["Total_PnL"] = g["Total_PnL"].round(0)
    g["WR_pct"] = g["WR_pct"].round(1)
    return g


def _run_one(mode, pair):
    """Worker function for parallel execution."""
    t0 = time.perf_counter()
    cfg = _build_cfg(mode, pair)
    trades, eq = run_backtest(pair, cfg)
    elapsed = time.perf_counter() - t0
    s = _stats(trades, eq)
    mg = _monthly(trades)
    return {
        "mode": mode, "pair": pair,
        "stats": s, "elapsed_s": round(elapsed, 1),
        "trades": trades, "monthly": mg,
    }


def main():
    modes = ["scale_in", "scale_in_middle", "scale_in_middle_1r"]
    pairs = ["XAUUSD", "BTCUSD", "USDCHF"]
    jobs = [(m, p) for m in modes for p in pairs]
    print(f"Starting {len(jobs)} jobs in parallel: {len(modes)} modes x {len(pairs)} pairs")
    print(f"Jobs: {[(m, p) for m, p in jobs]}")

    out_dir = ROOT / "output" / "parallel-scale-in"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use multiprocessing for parallelism
    import multiprocessing as mp
    start = time.perf_counter()
    with mp.Pool(processes=min(len(jobs), os.cpu_count() or 4)) as pool:
        results = pool.starmap(_run_one, jobs)
    elapsed_total = time.perf_counter() - start
    print(f"\nAll done in {elapsed_total:.0f}s")

    # Aggregate
    summary_rows = []
    detail_rows = []
    for r in results:
        mode = r["mode"]
        pair = r["pair"]
        s = r["stats"]
        mg = r["monthly"]
        trades = r["trades"]
        if not s:
            print(f"  {mode}/{pair}: no trades")
            continue
        print(f"\n--- {pair} / {mode} ---")
        print(f"  n={s['n']:>4d}  WR={s['wr_pct']:>5.1f}%  Total_R={s['total_r']:>+6.1f}R  "
              f"PnL=${s['total_pnl']:>+10,.0f}  DD={s['dd_pct']:>5.2f}%  "
              f"PF={s['pf']}  ({r['elapsed_s']:.0f}s)")
        print(f"    Avgs: Win_R=+{s['avg_win_R']}R  Loss_R={s['avg_loss_R']}R  "
              f"Final_$={s['final_eq']:,.0f}")
        print(f"    exits: {s['exits']}")
        # Monthly
        cols = ["ym", "N", "Wins", "Losses", "Total_R", "Total_PnL", "WR_pct"]
        with pd.option_context("display.max_rows", None, "display.width", 200):
            print(mg[cols].to_string(index=False))

        # Save CSVs
        csv_file = out_dir / f"{pair}-{mode}-monthly.csv"
        mg.to_csv(csv_file, index=False)
        trade_file = out_dir / f"{pair}-{mode}-trades.csv"
        pd.DataFrame([{
            "ts_entry": t["timestamp_entry"],
            "ts_exit": t["timestamp_exit"],
            "side": t["side"],
            "r": float(t.get("r_multiple", 0) or 0),
            "pnl": float(t.get("pnl_usd", 0) or 0),
            "exit": t.get("exit_reason", "?"),
        } for t in trades]).to_csv(trade_file, index=False)
        summary_rows.append({
            "mode": mode, "pair": pair, **s, "elapsed_s": r["elapsed_s"],
        })
        for er, cnt in s["exits"].items():
            detail_rows.append({
                "mode": mode, "pair": pair, "exit_reason": er, "count": cnt,
            })

    summary_path = out_dir / "summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    detail_path = out_dir / "exit_reasons.csv"
    pd.DataFrame(detail_rows).to_csv(detail_path, index=False)

    print(f"\n=== Summary ===")
    df = pd.DataFrame(summary_rows)
    pivot = df.pivot(index="mode", columns="pair",
                     values=["n", "total_pnl", "total_r", "dd_pct",
                             "wr_pct", "final_eq", "pf"])
    print(pivot.to_string())
    print(f"\nSummary CSV: {summary_path}")
    print(f"Detail  CSV: {detail_path}")


if __name__ == "__main__":
    main()
