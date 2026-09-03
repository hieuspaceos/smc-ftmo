"""Re-validate Python SMC backtest with Pine `untitled.md` chart parameters.

Pine inputs (untitled.md):
    swingWindow        = 5
    displacementMult   = 2.5
    rulebookMinRR      = 2.0

These differ from config.yaml (swing=10, displacement=1.5, rr=2.5).

Run:
    python -m scripts.btest_pivot_params

Outputs 3 reports under output/pivot-validation-<date>/:
    - baseline.yaml (original config.yaml params)
    - pine-pivot.yaml (Pine chart params)
    - delta.md (side-by-side comparison)
"""
from __future__ import annotations

import os
import sys
import time
import json
import math
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

# Make repo modules importable
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packages" / "smc_engine" / "src"))

import yaml
from src.backtester import run_backtest, compute_metrics


CFGS = {
    # Repo `config.yaml` defaults — these are what passed Phase 09
    "baseline_repo": {
        "ftmo": {
            "account_size": 100000, "phase": "challenge",
            "profit_target": 0.10, "max_daily_loss": 0.05,
            "max_total_loss": 0.10, "timezone": "Europe/Paris",
            "max_open_positions": 1,
            "daily_loss_limit_r": 2.0,
        },
        "execution": {
            "spread_pips": {"EURUSD": 0.5, "GBPUSD": 0.7, "XAUUSD": 2.0},
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3},
        },
        "risk": {
            "per_trade_pct": 0.0055, "max_trades_per_day": 3,
            "daily_loss_limit_r": 2.0, "max_open_positions": 1,
        },
        "strategy": {
            "swing_length": 10, "rr_target": 2.5,
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
            "exit_mode": "ladder",
            "leg2_tp1_r": None,
        },
        "confluence": {
            "weights": {"displacement": 1, "bias_aligned": 1,
                        "sweep_clean": 1, "premium_discount": 1,
                        "first_test": 1},
        },
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01",
        "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50,
        "pairs": ["EURUSD"],
    },

    # Pine `untitled.md` actual chart values
    "pine_pivot": {
        "ftmo": {
            "account_size": 100000, "phase": "challenge",
            "profit_target": 0.10, "max_daily_loss": 0.05,
            "max_total_loss": 0.10, "timezone": "Europe/Paris",
            "max_open_positions": 1,
            "daily_loss_limit_r": 2.0,
        },
        "execution": {
            "spread_pips": {"EURUSD": 0.5, "GBPUSD": 0.7, "XAUUSD": 2.0},
            "commission_per_lot_per_side": 2.50,
            "slippage_pips": {"mean": 0.1, "std": 0.3},
        },
        "risk": {
            "per_trade_pct": 0.0055, "max_trades_per_day": 3,
            "daily_loss_limit_r": 2.0, "max_open_positions": 1,
        },
        "strategy": {
            "swing_length": 5, "rr_target": 2.0,
            "displacement_atr_mult": 2.5, "sweep_atr_buffer": 0.05,
            "min_confluence_score": 4, "require_displacement": True,
            "require_bias_aligned": True, "sl_atr_buffer": 0.2,
            "bias_mode": "strict", "regime_mode": "off",
            "promotion_lookback_bars": 50,
            # Pine chart_qualified emits at first qualifying OB; Python ladder
            # exit partials stay consistent with repo profile.
            "partial_tp": [
                {"pct": 0.40, "r": 2.0},
                {"pct": 0.30, "r": 3.0},
                {"pct": 0.30, "r": 4.0},
            ],
            "exit_mode": "ladder",
            "leg2_tp1_r": None,
        },
        "confluence": {
            "weights": {"displacement": 1, "bias_aligned": 1,
                        "sweep_clean": 1, "premium_discount": 1,
                        "first_test": 1},
        },
        "filters": {"sweep": False, "pd": False, "first_test": False},
        "start_date": "2016-01-01",
        "end_date": "2026-08-21",
        "tf_m15": True, "tf_h1": True, "tf_h4": False, "tf_d": False,
        "pd_lookback": 50,
        "pairs": ["EURUSD"],
    },
}


def _safe_metric(trades, equity_curve, key, default=0.0):
    if not trades or not equity_curve:
        return default
    try:
        m = compute_metrics(trades, equity_curve)
        return m.get(key, default)
    except Exception:
        return default


def _summarize(label, trades, equity_curve, elapsed):
    n = len(trades)
    if n == 0 or not equity_curve:
        return {"label": label, "n_trades": 0, "elapsed_s": elapsed}

    metrics = compute_metrics(trades, equity_curve)

    n_win = sum(1 for t in trades if float(t.get("r_multiple", 0) or 0) > 0)
    n_loss = n - n_win
    wr = (n_win / n * 100) if n else 0.0
    total_r = sum(float(t.get("r_multiple", 0) or 0) for t in trades)

    eq = pd.DataFrame(equity_curve, columns=["ts", "eq"]).set_index("ts")["eq"]
    dd_pct = ((eq / eq.cummax()) - 1).min() * 100
    final_eq = float(eq.iloc[-1])
    roi_pct = (final_eq / 100000.0 - 1) * 100

    years = Counter(pd.Timestamp(t["timestamp_entry"]).year for t in trades)

    return {
        "label": label,
        "n_trades": n,
        "elapsed_s": elapsed,
        "winrate_pct": round(wr, 2),
        "total_r": round(total_r, 2),
        "max_dd_pct": round(dd_pct, 2),
        "final_eq": round(final_eq, 2),
        "roi_pct": round(roi_pct, 2),
        "profit_factor": round(float(metrics.get("profit_factor", 0.0)), 3),
        "sharpe": round(float(metrics.get("sharpe", 0.0)), 3),
        "n_wins": n_win,
        "n_losses": n_loss,
        "per_year": {str(y): c for y, c in sorted(years.items())},
        "raw_metrics": {k: float(v) if isinstance(v, (int, float)) else str(v)
                        for k, v in metrics.items()},
    }


def main():
    out_dir = ROOT / "output" / f"pivot-validation-{datetime.now(timezone.utc):%Y%m%d-%H%M}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    raw_trades = {}

    for label, cfg in CFGS.items():
        # Pair scope from config.pairs
        pairs = cfg.get("pairs") or ["EURUSD"]
        print(f"\n=== {label} ({' / '.join(pairs)}) ===")
        t0 = time.perf_counter()
        all_trades = []
        all_eq = []
        for pair in pairs:
            trades, eq = run_backtest(pair, cfg)
            print(f"  {pair}: trades={len(trades)} eq_pts={len(eq)}")
            all_trades.extend(trades)
            all_eq.extend(eq)
        elapsed = time.perf_counter() - t0
        summary = _summarize(label, all_trades, all_eq, elapsed)
        results[label] = summary
        raw_trades[label] = all_trades
        print(f"  -> winrate={summary.get('winrate_pct', 0):.1f}% "
              f"n={summary['n_trades']} "
              f"DD={summary.get('max_dd_pct', 0):.2f}% "
              f"PF={summary.get('profit_factor', 0):.3f} "
              f"ROI={summary.get('roi_pct', 0):.1f}%")

    # Persist
    with (out_dir / "report.json").open("w") as f:
        json.dump({"results": results,
                   "pine_params_compared": {
                       "swing_length": {"config.yaml": 10, "untitled.md": 5},
                       "displacement_atr_mult": {"config.yaml": 1.5, "untitled.md": 2.5},
                       "rr_target": {"config.yaml": 2.5, "untitled.md": 2.0},
                   }}, f, indent=2)

    # Compact delta table
    base = results.get("baseline_repo", {})
    piv = results.get("pine_pivot", {})

    md = ["# Pivot-Params Validation Report",
          "",
          f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
          "",
          "## Parameter delta",
          "",
          "| Param | `config.yaml` (validated) | `untitled.md` (Pine chart) |",
          "|---|---|---|",
          "| swing_length | 10 | 5 |",
          "| displacement_atr_mult | 1.5 | 2.5 |",
          "| rr_target | 2.5 | 2.0 |",
          "",
          "## Metrics side-by-side",
          ""]
    rows = [
        ("n_trades",       "Trades"),
        ("n_wins",         "Wins"),
        ("n_losses",       "Losses"),
        ("winrate_pct",    "Winrate %"),
        ("profit_factor",  "Profit Factor"),
        ("sharpe",         "Sharpe"),
        ("total_r",        "Total R"),
        ("max_dd_pct",     "Max DD %"),
        ("roi_pct",        "ROI %"),
        ("final_eq",       "Final Equity $"),
    ]
    md.append("| Metric | baseline_repo | pine_pivot | Δ |")
    md.append("|---|---|---|---|")
    for k, label in rows:
        b = base.get(k, 0)
        p = piv.get(k, 0)
        if isinstance(b, (int, float)) and isinstance(p, (int, float)):
            delta = p - b
            delta_s = f"{delta:+.2f}"
        else:
            delta_s = "n/a"
        md.append(f"| {label} | {b} | {p} | {delta_s} |")

    md.append("")
    md.append("## Verdict")
    md.append("")
    md.append("(See CLI stdout above for explicit verdict.)")
    md.append("")
    (out_dir / "delta.md").write_text("\n".join(md))

    # Verdict logic
    n_base = base.get("n_trades", 0)
    n_piv = piv.get("n_trades", 0)
    pf_base = base.get("profit_factor", 0)
    pf_piv = piv.get("profit_factor", 0)
    dd_base = base.get("max_dd_pct", 0)
    dd_piv = base.get("max_dd_pct", 0)
    wr_base = base.get("winrate_pct", 0)
    wr_piv = piv.get("winrate_pct", 0)

    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    degrading = []
    if pf_piv < pf_base * 0.5:
        degrading.append(f"PF dropped >50%: {pf_base:.2f} -> {pf_piv:.2f}")
    if wr_piv < wr_base * 0.7:
        degrading.append(f"WR dropped >30%: {wr_base:.1f}% -> {wr_piv:.1f}%")
    if n_piv < max(5, n_base * 0.2):
        degrading.append(f"Trade count dropped >80%: {n_base} -> {n_piv}")
    if piv.get("max_dd_pct", 0) > abs(dd_base) + 3:
        degrading.append(f"DD worse by >3pp: {dd_base:.2f}% -> {piv['max_dd_pct']:.2f}%")

    if degrading:
        print("\n".join(degrading))
        print(f"\nReport: {out_dir / 'delta.md'}")
        print(f"Bản Pine pivot params LOOK FRAGILE — recommend FIX Pine to match config.yaml.")
        return 1

    print(f"Pine pivot params: PF {pf_piv:.2f} (baseline {pf_base:.2f}), "
          f"WR {wr_piv:.1f}% (baseline {wr_base:.1f}%), "
          f"n={n_piv} (baseline {n_base}), "
          f"DD {piv.get('max_dd_pct', 0):.2f}% (baseline {dd_base:.2f}%)")
    print("Pine pivot params STAY EDGE — safe to trade on Pine chart.")
    print(f"Report: {out_dir / 'delta.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
