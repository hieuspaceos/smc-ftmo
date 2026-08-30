"""MT5 fill simulator — Python approximation of MT5 Strategy Tester behavior.

The MT5 Strategy Tester validation plan (260831-0437) needs to know how
Python backtest PnL would change under MT5's spread + slippage model.
This module provides that approximation without requiring an MT5
Windows install.

Approach
--------
The CSV export already includes `python_r_multiple` (baseline R-mult
without spread, computed by the Python backtester's scale-in state
machine). This simulator preserves the baseline R-mult for each trade
and applies a small R-multiple penalty for spread + slippage on top.

The penalty is computed per-trade:

  spread_cost_r   = (spread_pips / 2 + slippage_pips) / sl_distance_pips
  adjusted_r      = python_r_multiple - spread_cost_r * direction

For a typical EURUSD trade with 100 pip SL distance:
  - spread 0.5 pip half-spread entry + 0.5 pip exit = 0.5 pip total
  - slippage mean 0.1 pip × 2 = 0.2 pip
  - penalty = 0.7 / 100 = 0.007R per trade
  - For 603 trades → 4.2R total penalty (~$2,300 USD on $550 risk/trade)

This matches typical FTMO ECN slippage expectations (a few hundred
dollars per 100 trades on a $100K account).

Limitations
-----------
- Reads only M15 bars from `data/eurusd_m15.parquet`. Sub-M15 movement
  is invisible. For higher fidelity, use tick data + Strategy Tester.
- Spread + slippage are constant (not session-dependent).
- No requote simulation (assumes fills always succeed).
- No margin / lot-size validation.
- No commission (set `commission_per_lot_per_side` if needed).

For full fidelity, run the real MT5 Strategy Tester (see
`plans/260831-0437-mt5-strategy-tester-validation/`). This module
is the pre-MT5 sanity check.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "eurusd_m15.parquet"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class FillConfig:
    """Spread + slippage + commission knobs.

    Attributes
    ----------
    spread_pips : float
        One-way spread in pips (EURUSD default 0.5 pip).
    slippage_mean_pips : float
        Mean slippage per fill (entry + exit). Default 0.1.
    slippage_std_pips : float
        Stddev of slippage (Gaussian). Default 0.5 → 95th pct ~1.1 pip.
    commission_per_lot_per_side : float
        USD commission per lot per side. Default 0.
    pip_size : float
        Size of one pip for the symbol. EURUSD = 0.0001.
    risk_per_trade : float
        Risk per trade as fraction of account. Default 0.0055.
    account_size : float
        Account size in USD. Default 100000.
    seed : int
        Random seed for reproducibility.
    """

    spread_pips: float = 0.5
    slippage_mean_pips: float = 0.1
    slippage_std_pips: float = 0.5
    commission_per_lot_per_side: float = 0.0
    pip_size: float = 0.0001
    risk_per_trade: float = 0.0055
    account_size: float = 100_000.0
    seed: int = 42


# ---------------------------------------------------------------------------
# Per-trade penalty model
# ---------------------------------------------------------------------------


@dataclass
class FillResult:
    """Per-trade fill outcome from the simulator."""

    r_multiple: float
    pnl_usd: float
    spread_cost_r: float
    slippage_cost_r: float
    notes: list[str]


def simulate_trade(
    python_r_multiple: float,
    sl_distance_pips: float,
    cfg: FillConfig,
    rng: random.Random,
) -> FillResult:
    """Apply spread + slippage penalty to a Python baseline R-multiple.

    The simulator does NOT recompute the trade outcome from OHLCV
    because the Python backtester has already modeled scale-in's
    partial closes + cascade SL correctly. Instead it just applies
    the broker-side cost (spread + slippage) on top.

    Parameters
    ----------
    python_r_multiple : float
        Baseline R-multiple from Python backtest (already accounts
        for partial closes + scale-in state machine).
    sl_distance_pips : float
        Original SL distance in pips (from entry to SL at trade open).
        Zero or negative → degenerate, skip penalty.
    cfg : FillConfig
        Spread/slippage knobs.
    rng : random.Random
        RNG for reproducibility.
    """
    notes: list[str] = []
    if sl_distance_pips <= 0:
        return FillResult(
            r_multiple=python_r_multiple,
            pnl_usd=python_r_multiple * cfg.account_size * cfg.risk_per_trade,
            spread_cost_r=0.0,
            slippage_cost_r=0.0,
            notes=["degenerate SL distance — no spread cost applied"],
        )

    # Spread cost: half-spread on entry + half-spread on exit.
    # For a 0.5 pip spread, total cost = 0.5 pip round-trip.
    spread_cost_pips = cfg.spread_pips  # round-trip spread

    # Slippage: sample per fill, clamp at 0 (always bad).
    entry_slip = max(0.0, rng.gauss(cfg.slippage_mean_pips, cfg.slippage_std_pips))
    exit_slip = max(0.0, rng.gauss(cfg.slippage_mean_pips, cfg.slippage_std_pips))
    slippage_cost_pips = entry_slip + exit_slip

    # Convert to R-multiple cost.
    total_cost_pips = spread_cost_pips + slippage_cost_pips
    cost_r = total_cost_pips / sl_distance_pips

    # Apply cost regardless of direction: cost is always bad.
    adjusted_r = python_r_multiple - cost_r

    pnl_usd = adjusted_r * cfg.account_size * cfg.risk_per_trade

    if cost_r > 0.5:
        notes.append(f"high cost: {cost_r:.2f}R per trade ({total_cost_pips:.1f} pip)")

    return FillResult(
        r_multiple=adjusted_r,
        pnl_usd=pnl_usd,
        spread_cost_r=spread_cost_pips / sl_distance_pips,
        slippage_cost_r=slippage_cost_pips / sl_distance_pips,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# CSV driver
# ---------------------------------------------------------------------------


def simulate_trades_csv(
    csv_path: Path,
    cfg: FillConfig | None = None,
) -> list[dict]:
    """Run the simulator on every trade in the CSV.

    Returns list of new trade dicts (original schema + mt5_sim_diff).
    """
    if cfg is None:
        cfg = FillConfig()
    rng = random.Random(cfg.seed)

    out_trades: list[dict] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            python_r = float(row["python_r_multiple"])
            entry = float(row["entry"])
            sl = float(row["sl"])
            sl_dist_pips = abs(entry - sl) / cfg.pip_size if cfg.pip_size > 0 else 0.0

            result = simulate_trade(python_r, sl_dist_pips, cfg, rng)

            new = dict(row)
            new["mt5_sim_r_multiple"] = f"{result.r_multiple:.6f}"
            new["mt5_sim_pnl_usd"] = f"{result.pnl_usd:.2f}"
            new["mt5_sim_spread_cost_r"] = f"{result.spread_cost_r:.6f}"
            new["mt5_sim_slippage_cost_r"] = f"{result.slippage_cost_r:.6f}"
            new["mt5_sim_total_cost_pips"] = (
                f"{(result.spread_cost_r + result.slippage_cost_r) * sl_dist_pips:.2f}"
            )
            if result.notes:
                new["mt5_sim_notes"] = "; ".join(result.notes)
            out_trades.append(new)

    return out_trades


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def compute_sim_metrics(simulated: Iterable[dict]) -> dict:
    """Aggregate simulator output into winrate / PF / DD / total PnL."""
    pnls: list[float] = []
    for t in simulated:
        try:
            pnls.append(float(t["mt5_sim_pnl_usd"]))
        except (KeyError, ValueError):
            continue
    if not pnls:
        return {"trades": 0, "winrate": 0.0, "profit_factor": 0.0,
                "total_pnl_usd": 0.0, "max_dd_pct": 0.0, "avg_r": 0.0}

    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    pf = (sum_wins / sum_losses) if sum_losses > 0 else float("inf")
    wr = len(wins) / n if n > 0 else 0.0
    avg_pnl = sum(pnls) / n if n > 0 else 0.0

    eq = 100_000.0
    peak = eq
    max_dd_pct = 0.0
    for p in pnls:
        eq += p
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd

    # Avg R: total R / trade count (where each trade's R = pnl_usd / risk_amount)
    risk_amount = 100_000.0 * 0.0055
    avg_r = avg_pnl / risk_amount if risk_amount > 0 else 0.0

    return {
        "trades": n,
        "winrate": wr,
        "profit_factor": pf,
        "total_pnl_usd": sum(pnls),
        "max_dd_pct": max_dd_pct,
        "avg_r": avg_r,
    }


def diff_baseline_vs_sim(
    python_trades: list[dict],
    simulated: list[dict],
) -> dict:
    """Compare baseline vs simulated metrics.

    Parameters
    ----------
    python_trades : list of dict
        Trade list with `r_multiple` and `pnl_usd` keys (raw Python output).
    simulated : list of dict
        Output of `simulate_trades_csv` with `mt5_sim_*` keys.

    Returns
    -------
    dict with `baseline` and `simulated` metric blocks plus deltas.
    """
    py_pnls = [float(t["pnl_usd"]) for t in python_trades]
    sim_pnls = [float(t["mt5_sim_pnl_usd"]) for t in simulated]
    risk_amount = 100_000.0 * 0.0055

    def _agg(pnls: list[float]) -> dict:
        if not pnls:
            return {"trades": 0, "winrate": 0.0, "profit_factor": 0.0,
                    "total_pnl_usd": 0.0, "avg_r": 0.0}
        n = len(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        pf = (sum(wins) / abs(sum(losses))) if losses else float("inf")
        return {
            "trades": n,
            "winrate": len(wins) / n,
            "profit_factor": pf,
            "total_pnl_usd": sum(pnls),
            "avg_r": (sum(pnls) / n) / risk_amount,
        }

    base = _agg(py_pnls)
    sim = _agg(sim_pnls)
    delta = {k: sim[k] - base[k] for k in base if isinstance(base[k], (int, float))}
    delta["pct"] = (
        (sim["total_pnl_usd"] - base["total_pnl_usd"])
        / abs(base["total_pnl_usd"]) * 100
        if base["total_pnl_usd"] != 0
        else 0.0
    )
    return {"baseline": base, "simulated": sim, "delta": delta}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "output" / "mt5_replay_trades.csv",
        help="CSV from scripts/export_mt5_replay_csv.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "mt5_simulated_trades.csv",
        help="Output CSV with simulated PnL + diff",
    )
    parser.add_argument("--spread-pips", type=float, default=0.5)
    parser.add_argument("--slippage-mean-pips", type=float, default=0.1)
    parser.add_argument("--slippage-std-pips", type=float, default=0.5)
    parser.add_argument("--commission-per-lot", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = FillConfig(
        spread_pips=args.spread_pips,
        slippage_mean_pips=args.slippage_mean_pips,
        slippage_std_pips=args.slippage_std_pips,
        commission_per_lot_per_side=args.commission_per_lot,
        seed=args.seed,
    )
    simulated = simulate_trades_csv(args.input, cfg)
    if not simulated:
        print("simulator produced 0 trades", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(simulated[0].keys()))
        writer.writeheader()
        writer.writerows(simulated)

    metrics = compute_sim_metrics(simulated)
    print(f"Simulated {metrics['trades']} trades")
    print(f"Winrate: {metrics['winrate']:.1%}")
    print(f"Profit factor: {metrics['profit_factor']:.2f}")
    print(f"Avg R: {metrics['avg_r']:.3f}")
    print(f"Total PnL: ${metrics['total_pnl_usd']:,.2f}")
    print(f"Max DD: {metrics['max_dd_pct']:.2f}%")
    print(f"\nWrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())