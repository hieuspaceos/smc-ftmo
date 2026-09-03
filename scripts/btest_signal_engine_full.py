"""Full backtest driving smc_bot_signal.SignalEngine per M15 bar,
replicating the dispatch logic of scripts/btest_scale_in.py and adding
realistic FTMO execution costs (spread + slippage + commission).

SL floor: min_sl_pips=17 for EURUSD — enforced at entry gate.

Execution costs (per config.yaml execution block, FTMO defaults):
  - Spread EURUSD: 0.5 pips (applied at entry, half each side as slip)
  - Slippage: Gaussian pips (mean 0.1, std 0.3) added against trader at entry
  - Commission: $2.50/side per lot, charged on each partial close
  - Lot size: sized via risk_pct * equity / risk_per_unit

ScaleInExit emits up to 2 closes (50% @ 2R + 50% leg2 @ 4R) plus SL hit.
Commission applied per side × lot × fraction closed.

Run from repo root:
    PYTHONPATH=src:packages/smc_engine/src:packages/smc_bot_core/src:\
packages/smc_bot_webhook/src:packages/smc_bot_signal/src \
    python -m scripts.btest_signal_engine_full [overrides]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for p in (
    SRC,
    ROOT / "packages" / "smc_engine" / "src",
    ROOT / "packages" / "smc_bot_core" / "src",
    ROOT / "packages" / "smc_bot_webhook" / "src",
    ROOT / "packages" / "smc_bot_signal" / "src",
):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from scale_in_exit import ScaleInExit  # noqa: E402

from smc_bot_signal.rulebook_gate import score_setup as bot_score_setup  # noqa: E402
from smc_engine.context import (  # noqa: E402
    compute_bias_series,
    compute_dealing_range_context,
    is_in_pd_zone,
)
from smc_engine.displacement import (  # noqa: E402
    calculate_atr,
    detect_range_expansion,
)
from smc_engine.structure import detect_structure  # noqa: E402
from smc_engine.swings import detect_swings  # noqa: E402
from smc_engine.order_blocks import detect_order_blocks  # noqa: E402

PAIR = "EURUSD"
PIP_SIZE = 0.0001
MIN_SL_PIPS_EURUSD = 17.0
RISK_PCT = 0.0055
ACCOUNT_SIZE = 100_000.0
WINDOW_END = pd.Timestamp("2026-08-21 23:59:59", tz="UTC")

# FTMO execution costs (config.yaml execution block).
SPREAD_PIPS_EURUSD = 0.5
COMMISSION_PER_SIDE_USD = 2.50  # $5 round trip / 2 sides
SLIPPAGE_MEAN_PIPS = 0.1
SLIPPAGE_STD_PIPS = 0.3
SLIPPAGE_SEED = 42


@dataclass
class SimTrade:
    signal_id: str
    symbol: str
    side: str
    entry_time: pd.Timestamp
    entry: float
    sl: float
    sl_pips: float
    exit_time: pd.Timestamp | None = None
    exit_reason: str = ""
    r_multiple: float = 0.0
    pnl_dollar: float = 0.0
    commission_paid: float = 0.0


@dataclass
class EquityPoint:
    ts: pd.Timestamp
    equity: float


def _load_data(window: tuple | None = None) -> pd.DataFrame:
    df = pd.read_parquet(ROOT / "data" / f"{PAIR.lower()}_m15.parquet")
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    if window:
        lo = pd.Timestamp(window[0], tz="UTC")
        hi = pd.Timestamp(window[1], tz="UTC")
        df = df.loc[(df.index >= lo) & (df.index <= hi)]
    else:
        df = df.loc[(df.index >= WINDOW_START) & (df.index <= WINDOW_END)]
    return df.sort_index()


def _build_bias_series(df: pd.DataFrame, swing_length: int) -> tuple[pd.Series, pd.Series]:
    df_d = df.resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    df_h4 = df.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    left = right = max(2, swing_length // 2)
    d_swings = detect_swings(df_d, left=left, right=right)
    h_swings = detect_swings(df_h4, left=left, right=right)
    d_struct = detect_structure(df_d, d_swings)
    h_struct = detect_structure(df_h4, h_swings)
    bias_d = compute_bias_series(d_struct).reindex(df.index, method="ffill")
    bias_h4 = compute_bias_series(h_struct).reindex(df.index, method="ffill")
    return bias_d, bias_h4


def _decide_trade_dir(
    b_d, b_h4, bias_mode, htf_daily_enabled, htf_h4_enabled,
) -> str | None:
    if not htf_daily_enabled and not htf_h4_enabled:
        if b_d == "bull" or b_h4 == "bull":
            return "long"
        if b_d == "bear" or b_h4 == "bear":
            return "short"
        return None
    if bias_mode == "h4_only":
        if b_d == "bear" and b_h4 == "bull":
            return None
        if b_d == "bull" and b_h4 == "bear":
            return None
        if b_h4 == "bull":
            return "long"
        if b_h4 == "bear":
            return "short"
        return None
    if bias_mode == "any":
        if b_d == "bull" or b_h4 == "bull":
            return "long"
        if b_d == "bear" or b_h4 == "bear":
            return "short"
        return None
    if b_d == "bull" and b_h4 == "bull":
        return "long"
    if b_d == "bear" and b_h4 == "bear":
        return "short"
    return None


def _find_ob_for_bar(order_blocks_full, ts: pd.Timestamp, target: str):
    for ob in order_blocks_full.events:
        if ob.direction != target:
            continue
        if not ob.is_active_at(ts):
            continue
        if ob.first_touch_timestamp is not None and ts > ob.first_touch_timestamp:
            continue
        return ob
    return None


def _exit_trade(
    trade: SimTrade, future_bars: pd.DataFrame, lot: float,
) -> tuple[float, pd.Timestamp | None, str, float]:
    """Run ScaleInExit, return (realized_r, exit_ts, exit_reason, commission_usd)."""
    pos = ScaleInExit(
        entry=trade.entry, sl=trade.sl, side=trade.side,
        scale_in_r=2.0, final_tp_r=4.0, leg2_lot=0.5, leg2_tp1_r=None,
    )
    exit_ts = None
    exit_reason = ""
    total_commission = 0.0
    # ScaleInExit phases: phase1 close 50% at 2R, then close leg2 at 4R (or SL cascade).
    # Each close pays commission_per_side × lot × fraction closed.
    # We pay commission on entry-side too ($2.50/lot at open).
    total_commission += COMMISSION_PER_SIDE_USD * lot
    leg1_closed_partial = False
    leg2_closed_partial = False
    for ts, row in future_bars.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        sl_hit_phase1 = (
            (trade.side == "long" and low <= trade.sl + 1e-9)
            or (trade.side == "short" and high >= trade.sl - 1e-9)
        )
        prev_state = pos.state
        actions = pos.update(close)
        if sl_hit_phase1 and not pos.closed and pos.state == "phase1":
            actions = pos.update(trade.sl)
        # Detect state transitions to charge commission on each leg close.
        for a in actions:
            if a[0] == "close_pct" and not leg1_closed_partial:
                # First partial close of leg1 (50%).
                frac = float(a[1])
                total_commission += COMMISSION_PER_SIDE_USD * lot * frac
                leg1_closed_partial = True
            if a[0] == "open_leg2":
                # Opening leg2 pays commission for the new lot size.
                leg2_lot = float(a[1])
                total_commission += COMMISSION_PER_SIDE_USD * leg2_lot
            if a[0] == "close_leg2" and not leg2_closed_partial:
                # Closing leg2 (full or partial).
                leg2_remaining = pos.leg2_remaining
                total_commission += COMMISSION_PER_SIDE_USD * lot * leg2_remaining
                leg2_closed_partial = True
            if a[0] == "closed":
                exit_reason = a[1] if len(a) > 1 else "?"
                exit_ts = ts
        if pos.closed:
            break
    if not pos.closed:
        exit_reason = "open_at_eod"
        exit_ts = future_bars.index[-1] if len(future_bars) else trade.entry_time
        # Force-close any residual leg and pay commission.
        if pos.leg1_remaining > 0:
            total_commission += COMMISSION_PER_SIDE_USD * lot * pos.leg1_remaining
        if pos.leg2_remaining > 0:
            total_commission += COMMISSION_PER_SIDE_USD * lot * pos.leg2_remaining
    return float(pos.r_multiple), exit_ts, exit_reason, total_commission


def run(window=None, **kwargs):
    df = _load_data(window)
    # Tunable params — defaults match the LOOSENED config.yaml (2026-09-03).
    swing_length = kwargs.get("swing_length", 10)
    htf_daily_enabled = kwargs.get("htf_daily_enabled", False)
    htf_h4_enabled = kwargs.get("htf_h4_enabled", False)
    bias_mode = kwargs.get("bias_mode", "h4_only")
    displacement_atr_mult = kwargs.get("displacement_atr_mult", 1.2)
    min_confluence_score = kwargs.get("min_confluence_score", 3)
    sl_atr_buffer = kwargs.get("sl_atr_buffer", 0.2)
    min_sl_atr = kwargs.get("min_sl_atr", 0.3)
    max_sl_atr = kwargs.get("max_sl_atr", 5.0)
    min_sl_pips = kwargs.get("min_sl_pips", MIN_SL_PIPS_EURUSD)
    entry_proximity_atr = kwargs.get("entry_proximity_atr", 2.0)
    apply_costs = kwargs.get("apply_costs", True)

    # Slippage RNG (deterministic seed for reproducibility).
    slip_rng = np.random.default_rng(SLIPPAGE_SEED)

    t0 = time.perf_counter()
    swings = detect_swings(df, left=swing_length // 2, right=swing_length // 2)
    atr = calculate_atr(df)
    try:
        structure = detect_structure(df, swings, atr=atr)
    except TypeError:
        structure = detect_structure(df, swings)
    expansion = detect_range_expansion(df, atr, multiplier=displacement_atr_mult)
    context = compute_dealing_range_context(df, structure)
    pd_zone_series = context.zone.reindex(df.index).fillna("neutral")
    bias_d_series, bias_h4_series = _build_bias_series(df, swing_length)
    order_blocks_full = detect_order_blocks(df, structure, expansion)
    print(f"engine build: {time.perf_counter()-t0:.1f}s; OB events: {len(order_blocks_full.events)}")

    trades: list[SimTrade] = []
    equity_pts: list[EquityPoint] = []
    equity = ACCOUNT_SIZE
    open_pos = None
    sl_pips_rejects = 0
    start_bar = swing_length + 20

    for i in range(start_bar, len(df)):
        ts = df.index[i]
        bar_close = float(df["close"].iloc[i])
        if pd.isna(bar_close):
            continue
        atr_now = float(atr.iloc[i]) if i < len(atr) else 0.0

        # Manage open position.
        if open_pos is not None:
            pos = open_pos["exit_obj"]
            actions = pos.update(bar_close)
            trade = open_pos["trade"]
            for action in actions:
                tag = action[0]
                if tag == "closed":
                    trade.exit_time = ts
                    trade.exit_reason = action[1] if len(action) > 1 else "?"
            if pos.closed:
                realized_r = pos.r_multiple
                trade.r_multiple = round(float(realized_r), 6)
                risk_amount = open_pos["risk_amount"]
                gross_pnl = float(realized_r) * risk_amount
                commission = open_pos["commission_pending"]
                net_pnl = gross_pnl - commission
                trade.commission_paid = round(commission, 2)
                trade.pnl_dollar = round(net_pnl, 2)
                equity += net_pnl
                equity_pts.append(EquityPoint(ts=ts, equity=round(equity, 2)))
                trades.append(trade)
                open_pos = None
            continue

        b_d = bias_d_series.iloc[i] if i < len(bias_d_series) else None
        b_h4 = bias_h4_series.iloc[i] if i < len(bias_h4_series) else None
        trade_dir = _decide_trade_dir(
            b_d, b_h4, bias_mode, htf_daily_enabled, htf_h4_enabled,
        )
        if trade_dir is None:
            continue
        target = "bullish" if trade_dir == "long" else "bearish"
        ob = _find_ob_for_bar(order_blocks_full, ts, target)
        if ob is None:
            continue
        disp = bool(expansion.qualified.iloc[i]) if i < len(expansion.qualified) else False
        if not disp:
            continue
        in_pd = is_in_pd_zone(str(pd_zone_series.iloc[i]), trade_dir)
        score, _reasons, entry_allowed = bot_score_setup({
            "displacement": disp,
            "bias_aligned": True,
            "sweep_clean": disp,
            "in_pd_zone": in_pd,
            "first_test": True,
            "pd_zone": str(pd_zone_series.iloc[i]),
        }, min_score=min_confluence_score)
        if not entry_allowed:
            continue

        top = float(ob.top)
        bottom = float(ob.bottom)
        entry = top if trade_dir == "long" else bottom
        buf = sl_atr_buffer * atr_now
        sl = (bottom - buf) if trade_dir == "long" else (top + buf)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        sl_atr = risk / atr_now
        if sl_atr < min_sl_atr or sl_atr > max_sl_atr:
            continue
        # ABSOLUTE PIP FLOOR — EURUSD live requires >= 17 pips.
        sl_pips = risk / PIP_SIZE
        if min_sl_pips > 0 and sl_pips < min_sl_pips:
            sl_pips_rejects += 1
            continue
        if abs(bar_close - entry) > entry_proximity_atr * atr_now:
            continue

        # --- Execution costs at entry ---
        # Apply spread + slippage to entry price (worse for trader).
        slip_pips = 0.0
        if apply_costs:
            slip_pips = max(0.0, float(slip_rng.normal(
                SLIPPAGE_MEAN_PIPS, SLIPPAGE_STD_PIPS,
            )))
            half_spread = SPREAD_PIPS_EURUSD / 2.0
            total_entry_pips = half_spread + slip_pips
            price_offset = total_entry_pips * PIP_SIZE
            if trade_dir == "long":
                entry = entry + price_offset
                # SL hit harder — push SL further from entry by slip_pips.
                sl = sl - slip_pips * PIP_SIZE
            else:  # short
                entry = entry - price_offset
                sl = sl + slip_pips * PIP_SIZE
            # Recompute risk in case entry/SL moved (sl_atr check still holds).
            risk = abs(entry - sl)
            sl_atr = risk / atr_now
            if sl_atr < min_sl_atr or sl_atr > max_sl_atr:
                continue
            sl_pips = risk / PIP_SIZE
            if min_sl_pips > 0 and sl_pips < min_sl_pips:
                sl_pips_rejects += 1
                continue

        sig_id = f"{int(ts.timestamp())}_{trade_dir}_{ob.id}"
        trade = SimTrade(
            signal_id=sig_id, symbol=PAIR, side=trade_dir,
            entry_time=ts, entry=entry, sl=sl, sl_pips=round(sl_pips, 2),
        )
        # Lot sizing: risk_pct * equity / (sl_pips * pip_value)
        # For EURUSD 1 pip = $10 per standard lot. Use pip value $10.
        pip_value_usd = 10.0
        risk_amount = ACCOUNT_SIZE * RISK_PCT  # fixed position sizing for live realism
        lot = max(0.01, risk_amount / (sl_pips * pip_value_usd))

        pos = ScaleInExit(
            entry=entry, sl=sl, side=trade_dir,
            scale_in_r=2.0, final_tp_r=4.0, leg2_lot=0.5, leg2_tp1_r=None,
        )
        # Estimate commission cost up-front (refined in _exit_trade).
        est_commission = (
            COMMISSION_PER_SIDE_USD * lot  # entry side
            + COMMISSION_PER_SIDE_USD * lot * 0.5  # phase1 partial close
            + COMMISSION_PER_SIDE_USD * lot * 0.5  # leg2 open
            + COMMISSION_PER_SIDE_USD * lot * 0.5  # leg2 close
        ) if apply_costs else 0.0
        open_pos = {
            "trade": trade, "exit_obj": pos, "risk_amount": risk_amount,
            "lot": lot, "commission_pending": est_commission,
        }

    # Force-close any remaining open at end of data.
    if open_pos is not None:
        trade = open_pos["trade"]
        lot = open_pos["lot"]
        future = df.loc[df.index > trade.entry_time]
        if not future.empty:
            realized_r, exit_ts, exit_reason, commission = _exit_trade(
                trade, future, lot,
            )
        else:
            realized_r, exit_ts, exit_reason, commission = 0.0, df.index[-1], "no_future", 0.0
        trade.r_multiple = round(float(realized_r), 6)
        risk_amount = open_pos["risk_amount"]
        gross_pnl = float(realized_r) * risk_amount
        # Replace estimated with actual if _exit_trade computed one.
        if commission > 0:
            commission = commission
        net_pnl = gross_pnl - commission
        trade.commission_paid = round(commission, 2)
        trade.pnl_dollar = round(net_pnl, 2)
        trade.exit_time = exit_ts
        trade.exit_reason = exit_reason
        equity += net_pnl
        equity_pts.append(EquityPoint(ts=exit_ts, equity=round(equity, 2)))
        trades.append(trade)

    return trades, equity_pts, time.perf_counter() - t0, sl_pips_rejects


def _compute_metrics(trades: list[SimTrade], equity: list[EquityPoint]) -> dict:
    if not trades:
        return {"trades": 0}
    n = len(trades)
    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]
    wr = len(wins) / n * 100.0
    avg_r = sum(t.r_multiple for t in trades) / n
    total_r = sum(t.r_multiple for t in trades)
    gross_win = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    eq_vals = pd.Series([e.equity for e in equity], index=[e.ts for e in equity])
    dd = (eq_vals / eq_vals.cummax() - 1.0) * 100.0
    total_commission = sum(t.commission_paid for t in trades)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "winrate_pct": round(wr, 2),
        "avg_r": round(avg_r, 4),
        "total_r": round(total_r, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "max_dd_pct": round(float(dd.min()), 2),
        "final_equity": round(float(eq_vals.iloc[-1]), 2),
        "roi_pct": round((eq_vals.iloc[-1] / ACCOUNT_SIZE - 1.0) * 100.0, 2),
        "total_commission_usd": round(total_commission, 2),
    }


def _parse_args():
    p = argparse.ArgumentParser(
        description="EURUSD backtest via SignalEngine + ScaleInExit (with execution costs)",
    )
    p.add_argument("--displacement-atr-mult", type=float, default=None)
    p.add_argument("--sl-atr-buffer", type=float, default=None)
    p.add_argument("--min-sl-atr", type=float, default=None)
    p.add_argument("--max-sl-atr", type=float, default=None)
    p.add_argument("--min-confluence-score", type=int, default=None)
    p.add_argument("--entry-proximity-atr", type=float, default=None)
    p.add_argument("--swing-length", type=int, default=None)
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--label", type=str, default=None)
    p.add_argument("--no-costs", action="store_true",
                   help="Disable spread + slippage + commission (legacy behavior)")
    args = p.parse_args()
    overrides = {k: v for k, v in vars(args).items()
                 if v is not None and k not in ("label", "no_costs")}
    if args.no_costs:
        overrides["apply_costs"] = False
    return overrides, args.label


def main() -> int:
    overrides, label = _parse_args()
    suffix = f"_{label}" if label else ""
    out_dir = ROOT / "output" / f"backtest_signal_engine_full_eurusd{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    start = overrides.pop("start", None)
    end = overrides.pop("end", None)
    window = None
    if start or end:
        window = (start or "2016-01-01", end or "2026-08-21")
    print("=" * 72)
    print("SIGNAL-ENGINE BACKTEST (per-bar + ScaleInExit + FTMO exec costs)")
    print("=" * 72)
    win_str = (f"{window[0]} → {window[1]}" if window
               else f"{WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Pair: {PAIR}   window: {win_str}")
    print(f"min_sl_pips: {MIN_SL_PIPS_EURUSD} (EURUSD live floor)")
    if overrides:
        print(f"Overrides: {overrides}")
    print(f"Execution costs: spread={SPREAD_PIPS_EURUSD} pip, "
          f"slippage=N({SLIPPAGE_MEAN_PIPS},{SLIPPAGE_STD_PIPS}) pip, "
          f"commission=${COMMISSION_PER_SIDE_USD}/side/lot")
    print(f"Output: {out_dir}")

    trades, equity_pts, elapsed, sl_rejects = run(window=window, **overrides)
    metrics = _compute_metrics(trades, equity_pts)

    print(f"\nElapsed: {elapsed:.1f}s")
    print(f"Entries rejected by SL 17-pip floor: {sl_rejects}")
    print(json.dumps(metrics, indent=2))

    if trades:
        years = Counter(t.entry_time.year for t in trades)
        print("\nTrades per year:")
        for y in sorted(years):
            print(f"  {y}: {years[y]:>4d}")
        pip_stats = [t.sl_pips for t in trades]
        print(f"\nSL pip distribution:")
        print(f"  min={min(pip_stats):.1f}  max={max(pip_stats):.1f}  "
              f"mean={sum(pip_stats)/len(pip_stats):.1f}")
        below = [p for p in pip_stats if p < MIN_SL_PIPS_EURUSD]
        print(f"  trades with sl_pips < {MIN_SL_PIPS_EURUSD}: {len(below)} (must be 0)")

    reasons = Counter(t.exit_reason for t in trades)
    print(f"\nExit reasons: {dict(reasons)}")

    summary = {
        "config": {
            "pair": PAIR,
            "window": win_str,
            "min_sl_pips": MIN_SL_PIPS_EURUSD,
            "pip_size": PIP_SIZE,
            "risk_pct": RISK_PCT,
            "account_size": ACCOUNT_SIZE,
            "execution_costs": {
                "spread_pips": SPREAD_PIPS_EURUSD,
                "slippage_mean_pips": SLIPPAGE_MEAN_PIPS,
                "slippage_std_pips": SLIPPAGE_STD_PIPS,
                "commission_per_side_usd": COMMISSION_PER_SIDE_USD,
            },
            **overrides,
        },
        "metrics": metrics,
        "exit_reasons": dict(reasons),
        "sl_pips_rejects_count": sl_rejects,
        "year_breakdown": (
            dict(Counter(t.entry_time.year for t in trades)) if trades else {}
        ),
        "elapsed_s": round(elapsed, 2),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    if trades:
        trades_df = pd.DataFrame([{
            "signal_id": t.signal_id, "symbol": t.symbol, "side": t.side,
            "entry_time": t.entry_time.isoformat(), "entry": t.entry,
            "sl": t.sl, "sl_pips": t.sl_pips,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "exit_reason": t.exit_reason, "r_multiple": t.r_multiple,
            "pnl_dollar": t.pnl_dollar, "commission_paid": t.commission_paid,
        } for t in trades])
        trades_df.to_csv(out_dir / "trades.csv", index=False)
    if equity_pts:
        eq_df = pd.DataFrame([
            {"ts": e.ts.isoformat(), "equity": e.equity} for e in equity_pts
        ])
        eq_df.to_csv(out_dir / "equity.csv", index=False)
    print(f"\nArtifacts: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
