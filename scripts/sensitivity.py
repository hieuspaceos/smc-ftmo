"""Parameter sensitivity for Phase 09 Step 4.

One-at-a-time (OAT) sweep on key SMC parameters:
  - swing_length (10) ± 50%
  - sl_atr_buffer (0.2) ± 50%
  - displacement_atr_mult (1.5) ± 30%
  - min_confluence_score (4) ± 1 (integer step)

For each param, run backtest at [-50%, -25%, -10%, default, +10%, +25%, +50%]
and record TotalR, PF, MaxDD.

Acceptance: All 4 params survive ±10% perturbation (PF drop < 30%).
"Fragile" params: PF drops > 30% with ±10%.

Run:
  python -m scripts.sensitivity
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "smc_engine" / "src"))

from backtester import run_backtest  # noqa: E402


BASE_CFG = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0,
             "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 4.0,
        "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4, "require_displacement": True,
        "require_bias_aligned": True, "sl_atr_buffer": 0.2,
        "bias_mode": "strict", "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in",
        "leg2_tp1_r": None,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01",
    "end_date": "2026-08-21",
    "pd_lookback": 50,
    "execution": {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    },
}

# Param definitions: (key, default, perturbation_pcts, is_int)
# Reduced from 7 values to 3 (default + ±10%) for tractability (~24 min).
PARAMS = [
    ("swing_length", 10, [-10, 0, 10], True),
    ("sl_atr_buffer", 0.2, [-10, 0, 10], False),
    ("displacement_atr_mult", 1.5, [-10, 0, 10], False),
    ("min_confluence_score", 4, [-1, 0, 1], True),  # integer, ±1 only
]


def compute_metrics(trades: list, equity: list) -> dict:
    if not trades:
        return {"trades": 0, "pf": 0, "total_r": 0, "max_dd": 0}
    total_r = sum(float(t.get("r_multiple", 0)) for t in trades)
    gross_win = sum(float(t.get("r_multiple", 0)) for t in trades
                    if float(t.get("r_multiple", 0)) > 0)
    gross_loss = abs(sum(float(t.get("r_multiple", 0)) for t in trades
                          if float(t.get("r_multiple", 0)) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    max_dd = 0.0
    if equity:
        eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
        dd = (eq / eq.cummax() - 1) * 100
        max_dd = float(dd.min())
    return {"trades": len(trades), "pf": pf, "total_r": total_r, "max_dd": max_dd}


def run_with_param(key: str, value) -> dict:
    cfg = dict(BASE_CFG)
    cfg["strategy"] = dict(BASE_CFG["strategy"])
    cfg["strategy"][key] = value
    trades, equity = run_backtest("EURUSD", cfg)
    return compute_metrics(trades, equity)


def main() -> int:
    print("Phase 09 Step 4: Parameter Sensitivity (EURUSD scale_in 2R/4R)")
    print("=" * 70)

    # Get baseline
    print("Running baseline (default config)...")
    base_metrics = run_with_param("swing_length", 10)  # default
    # Use swing_length=10 explicitly
    cfg0 = dict(BASE_CFG)
    cfg0["strategy"] = dict(BASE_CFG["strategy"])
    trades, equity = run_backtest("EURUSD", cfg0)
    base_metrics = compute_metrics(trades, equity)
    print(f"  Baseline: trades={base_metrics['trades']}, PF={base_metrics['pf']:.2f}, "
          f"total_r={base_metrics['total_r']:+.1f}, max_dd={base_metrics['max_dd']:.2f}%\n")

    summary = []
    fragile_count = 0
    for key, default, pcts, is_int in PARAMS:
        print(f"\n--- Param: {key} (default={default}) ---")
        sweep = []
        for pct in pcts:
            if pct == 0:
                value = default
            else:
                factor = 1 + pct / 100
                if is_int:
                    value = max(1, int(round(default * factor)))
                else:
                    value = round(default * factor, 4)
            metrics = run_with_param(key, value)
            sweep.append((pct, value, metrics))
            print(f"  {pct:+4d}%  val={value}  trades={metrics['trades']:>3d}  "
                  f"PF={metrics['pf']:>5.2f}  total_r={metrics['total_r']:>+7.1f}  "
                  f"max_dd={metrics['max_dd']:>+6.2f}%")

        # Check fragility at ±10%
        baseline_pf = base_metrics["pf"]
        plus_10 = next(m for p, _, m in sweep if p == 10)
        minus_10 = next(m for p, _, m in sweep if p == -10)
        pf_drop_plus = (baseline_pf - plus_10["pf"]) / baseline_pf * 100
        pf_drop_minus = (baseline_pf - minus_10["pf"]) / baseline_pf * 100

        is_fragile = max(pf_drop_plus, pf_drop_minus) > 30.0
        if is_fragile:
            fragile_count += 1
        summary.append({
            "param": key,
            "fragile": is_fragile,
            "pf_drop_plus_10": pf_drop_plus,
            "pf_drop_minus_10": pf_drop_minus,
        })
        status = "FRAGILE" if is_fragile else "robust"
        print(f"  Verdict: {status} "
              f"(PF drop +10%: {pf_drop_plus:+.1f}%, -10%: {pf_drop_minus:+.1f}%)")

    # Aggregate verdict
    print("\n" + "=" * 70)
    print("  ACCEPTANCE VERDICT (from plan/phase-09)")
    print("=" * 70)
    checks = [
        (f"All params survive ±10% (PF drop < 30%)", fragile_count == 0),
        (f"Baseline PF > 1.5 ({base_metrics['pf']:.2f})",
         base_metrics["pf"] > 1.5),
    ]
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {status}  {name}")
    if all_pass:
        print("\n  OVERALL: ROBUST PARAMETER PLATEAU")
        print("  Verdict: Strategy survives small parameter perturbations.")
    else:
        print("\n  OVERALL: SOME FRAGILE PARAMETERS")
        print("  Verdict: Review fragile params — may need regularization or "
              "fewer knobs.")
    if fragile_count:
        print(f"\n  Fragile params ({fragile_count}):")
        for s in summary:
            if s["fragile"]:
                print(f"    - {s['param']} "
                      f"(+10%: {s['pf_drop_plus_10']:+.1f}%, "
                      f"-10%: {s['pf_drop_minus_10']:+.1f}%)")
    return 0 if all_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())