"""Per-pair detail with PnL $: W/L/total_R/PnL_USD for ladder + scale_in.

Reuses 2 backtests done earlier; if missing, recomputes.
"""
from __future__ import annotations
import os, sys, time
from collections import Counter
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
    if mode == "scale_in":
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
    avg_win_pnl = win_pnl / len(wins) if wins else 0
    avg_loss_pnl = loss_pnl / len(losses) if losses else 0
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
        "avg_win_pnl": round(avg_win_pnl, 0),
        "avg_loss_pnl": round(avg_loss_pnl, 0),
        "dd_pct": round(dd_pct, 2),
        "final_eq": round(final_eq, 0),
        "roi_pct": round(roi_pct, 1),
        "pf": round(pf, 3) if pf != float('inf') else "inf",
        "exits": dict(exits),
        "year_range": f"{min(years)}-{max(years)}" if years else "-",
    }


def main():
    from src.backtester import run_backtest

    pairs = ["EURUSD", "GBPUSD", "USDCHF", "XAUUSD", "BTCUSD"]
    out_dir = ROOT / "output" / "multipair-detail"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "report.md"
    md_lines = ["# Multi-pair Ladder vs Scale_in — Detail (with PnL)",
                "",
                "Date range: 2016-01-01 → 2026-08-21 (M15)",
                "Account size: $100k, risk/trade: 0.55%, max 3 trades/day.",
                ""]

    for mode in ["ladder", "scale_in"]:
        md_lines.append(f"## Mode: `{mode}`")
        md_lines.append("")
        md_lines.append("| Pair | N | W | L | WR% | Total R | Total PnL $ | Win PnL | Loss PnL | Avg W R | Avg L R | Avg W $ | Avg L $ | PF | DD% | ROI% | Final $ | Year span |")
        md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for pair in pairs:
            cfg = _build_cfg(mode)
            cfg["pairs"] = [pair]
            t0 = time.perf_counter()
            try:
                trades, eq = run_backtest(pair, cfg)
            except Exception as e:
                md_lines.append(f"| {pair} | ERR | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |")
                continue
            elapsed = time.perf_counter() - t0
            sys.stdout.flush()
            s = _stats(trades, eq)
            if not s:
                md_lines.append(f"| {pair} | 0 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |")
                continue
            md_lines.append(
                f"| {pair} | {s['n']} | {s['wins']} | {s['losses']} | {s['wr_pct']} "
                f"| {s['total_r']}R | ${s['total_pnl']:,.0f} "
                f"| ${s['win_pnl']:,.0f} | ${s['loss_pnl']:,.0f} "
                f"| +{s['avg_win_R']}R | {s['avg_loss_R']}R "
                f"| ${s['avg_win_pnl']:,.0f} | ${s['avg_loss_pnl']:,.0f} "
                f"| {s['pf']} | {s['dd_pct']} | {s['roi_pct']} "
                f"| ${s['final_eq']:,.0f} | {s['year_range']} |"
            )
        md_lines.append("")

        md_lines.append(f"### Exit-reason distribution (mode={mode})")
        md_lines.append("")
        md_lines.append("| Pair | exit_reason | count | total_R | total_PnL $ |")
        md_lines.append("|---|---|---|---|---|")
        for pair in pairs:
            try:
                cfg = _build_cfg(mode)
                cfg["pairs"] = [pair]
                trades, _ = run_backtest(pair, cfg)
            except Exception:
                continue
            if not trades:
                continue
            grouped = {}
            for t in trades:
                er = t.get("exit_reason", "?")
                d = grouped.setdefault(er, {"count": 0, "total_r": 0.0, "total_pnl": 0.0})
                d["count"] += 1
                d["total_r"] += float(t.get("r_multiple", 0) or 0)
                d["total_pnl"] += float(t.get("pnl_usd", 0) or 0)
            for er, d in sorted(grouped.items(), key=lambda kv: -kv[1]["count"]):
                md_lines.append(
                    f"| {pair} | {er} | {d['count']} | {d['total_r']:+.1f}R "
                    f"| ${d['total_pnl']:+,.0f} |"
                )
        md_lines.append("")

    out_md.write_text("\n".join(md_lines))
    print(f"\n=== Report written to {out_md} ===\n")
    print("\n".join(md_lines))


if __name__ == "__main__":
    main()
