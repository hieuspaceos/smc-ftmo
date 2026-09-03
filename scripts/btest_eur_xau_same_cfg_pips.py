"""EURUSD + XAUUSD backtest with IDENTICAL config; report min/max SL pips.

Same strategy block as scripts/btest_multipair.py (ScaleIn Design A).
Pip definition (price distance of |entry-sl|):
  EURUSD: 1 pip = 0.0001
  XAUUSD: 1 pip = 0.01   (gold convention in this repo)

Usage (repo root):
  PYTHONPATH=src:packages/smc_engine/src python -m scripts.btest_eur_xau_same_cfg_pips
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from src.backtester import run_backtest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "backtest_10y_eur_xau"
OUT.mkdir(parents=True, exist_ok=True)

# === SINGLE shared config (identical for both pairs) ===
# Mirrors scripts/btest_multipair.py DEFAULT_CFG exactly.
SHARED_CFG = {
    "ftmo": {
        "account_size": 100000,
        "phase": "challenge",
        "profit_target": 0.10,
        "max_daily_loss": 0.05,
        "daily_loss_limit_r": 2.0,
        "max_open_positions": 1,
    },
    "strategy": {
        "swing_length": 10,
        "rr_target": 4.0,
        "displacement_atr_mult": 1.5,
        "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4,
        "require_displacement": True,
        "require_bias_aligned": True,
        "sl_atr_buffer": 0.2,
        # config.yaml — without these, OB ~1 pip leaks (seen min 0.86 pip)
        "min_sl_atr": 0.3,
        "max_sl_atr": 4.0,
        "min_sl_pips": {"EURUSD": 17, "XAUUSD": 100},
        "rulebook_entry_proximity_atr": 1.5,
        "htf_daily_enabled": False,
        "htf_h4_enabled": False,
        "bias_mode": "strict",
        "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": None,
    },
    "confluence": {
        "weights": {
            "displacement": 1,
            "bias_aligned": 1,
            "sweep_clean": 1,
            "premium_discount": 1,
            "first_test": 1,
        }
    },
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
}

# Price → pip size (1 pip in price units)
PIP_SIZE = {
    "EURUSD": 0.0001,
    "XAUUSD": 0.01,
}

PAIRS = ("EURUSD", "XAUUSD")


def sl_pips(trade: dict, pair: str) -> float:
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    return abs(entry - sl) / PIP_SIZE[pair]


def summarize(pair: str, trades: list, equity: list, elapsed: float) -> dict:
    pip_size = PIP_SIZE[pair]
    rows = []
    for t in trades:
        pips = sl_pips(t, pair)
        rows.append(
            {
                "timestamp_entry": str(t.get("timestamp_entry")),
                "side": t.get("side"),
                "entry": float(t["entry"]),
                "sl": float(t["sl"]),
                "sl_pips": pips,
                "r_multiple": float(t.get("r_multiple", 0) or 0),
                "exit_reason": t.get("exit_reason"),
            }
        )

    n = len(trades)
    out: dict = {
        "pair": pair,
        "pip_size": pip_size,
        "trades": n,
        "elapsed_sec": round(elapsed, 1),
        "config_fingerprint": "btest_multipair.DEFAULT_CFG identical",
    }
    if n == 0:
        out["sl_pips"] = None
        return out

    pip_s = pd.Series([r["sl_pips"] for r in rows])
    n_win = sum(1 for r in rows if r["r_multiple"] > 0)
    total_r = sum(r["r_multiple"] for r in rows)
    gross_w = sum(r["r_multiple"] for r in rows if r["r_multiple"] > 0)
    gross_l = abs(sum(r["r_multiple"] for r in rows if r["r_multiple"] < 0))
    pf = (gross_w / gross_l) if gross_l > 0 else float("inf")

    out.update(
        {
            "wins": n_win,
            "losses": n - n_win,
            "winrate_pct": round(n_win / n * 100, 2),
            "total_r": round(total_r, 2),
            "avg_r": round(total_r / n, 4),
            "profit_factor_r": round(pf, 3),
            "exit_reasons": dict(Counter(r["exit_reason"] for r in rows)),
            "sl_pips": {
                "min": round(float(pip_s.min()), 2),
                "max": round(float(pip_s.max()), 2),
                "mean": round(float(pip_s.mean()), 2),
                "median": round(float(pip_s.median()), 2),
                "p10": round(float(pip_s.quantile(0.10)), 2),
                "p90": round(float(pip_s.quantile(0.90)), 2),
            },
        }
    )

    if equity:
        eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
        dd_pct = (eq / eq.cummax() - 1) * 100
        final = float(eq.iloc[-1])
        out["max_dd_pct"] = round(float(dd_pct.min()), 3)
        out["final_equity"] = round(final, 2)
        out["net_pnl"] = round(final - 100_000, 2)
        out["roi_pct"] = round((final - 100_000) / 100_000 * 100, 2)

    # Persist trade-level pip table
    pd.DataFrame(rows).to_csv(OUT / f"{pair.lower()}_trades_pips.csv", index=False)
    return out


def main() -> int:
    print("SHARED CONFIG (identical both pairs):")
    print(json.dumps(SHARED_CFG, indent=2, default=str))
    print(f"\nWindow: {SHARED_CFG['start_date']} → {SHARED_CFG['end_date']}")
    print(f"Pairs: {PAIRS}\n")

    all_m: list[dict] = []
    for pair in PAIRS:
        print(f"=== RUN {pair} ===", flush=True)
        t0 = time.perf_counter()
        trades, equity = run_backtest(pair=pair, config=dict(SHARED_CFG))
        elapsed = time.perf_counter() - t0
        m = summarize(pair, trades, equity, elapsed)
        all_m.append(m)
        print(json.dumps(m, indent=2), flush=True)
        print(flush=True)

    (OUT / "summary.json").write_text(
        json.dumps({"shared_cfg": SHARED_CFG, "results": all_m}, indent=2, default=str),
        encoding="utf-8",
    )

    print("=" * 72)
    print("MIN / MAX SL PIPS (same config both pairs)")
    print("=" * 72)
    print(f"{'Pair':8} {'N':>6} {'min_pip':>10} {'max_pip':>10} {'mean':>10} {'WR%':>7} {'PF':>6} {'MaxDD%':>8}")
    for m in all_m:
        sp = m.get("sl_pips") or {}
        print(
            f"{m['pair']:8} {m.get('trades', 0):>6} "
            f"{sp.get('min', float('nan')):>10} {sp.get('max', float('nan')):>10} "
            f"{sp.get('mean', float('nan')):>10} "
            f"{m.get('winrate_pct', float('nan')):>7} "
            f"{m.get('profit_factor_r', float('nan')):>6} "
            f"{m.get('max_dd_pct', float('nan')):>8}"
        )
    print(f"\nArtifacts: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
