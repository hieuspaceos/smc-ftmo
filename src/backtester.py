"""M15 bar-by-bar backtester with full SMC pipeline.

Loads EURUSD (or other pair) OHLCV across D/H4/H1/M15, iterates every
M15 bar without look-ahead, opens trades only when confluence score >= 4
AND displacement + bias aligned, manages partial TP / BE via
PartialTPExit, enforces FTMOGuard daily limits, and returns a list of
closed-trade dicts plus an equity curve.

Public API (consumed by tests/test_backtest.py and app.py):
    run_backtest(pair: str, config: dict) -> (trades: list[dict], equity_curve: list[tuple])
    compute_metrics(trades, equity_curve) -> dict
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

_SRC = Path(__file__).parent
sys.path.insert(0, str(_SRC))

from bias_detector import detect_bias, align_bias
from confluence import score_setup
from data_loader import load_multi_tf_data
from premium_discount import pd_series
from risk_manager import FTMOGuard, calculate_lot
from smc_signals import SMCSignals, calculate_atr
from strategy import PartialTPExit, check_entry, pip_value_for_pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample_h4_from_h1(df_h1: pd.DataFrame) -> pd.DataFrame:
    """Resample H1 → H4 when the H4 parquet is missing."""
    if df_h1.empty:
        return pd.DataFrame()
    df = df_h1.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def _ensure_h4(data: Dict[str, pd.DataFrame]) -> None:
    """Patch missing H4 from H1 in-place."""
    if "H4" not in data or data["H4"].empty:
        if "H1" in data and not data["H1"].empty:
            data["H4"] = _resample_h4_from_h1(data["H1"])


def _precompute_bias_per_day(
    df_target: pd.DataFrame, swing_length: int
) -> Dict[str, str]:
    """Precompute bias string per calendar day for O(1) M15-loop lookup.

    Bias uses all bars of df_target up through day-end (no future look-ahead).
    That gives BOS/CHoCH enough history while staying causal.
    """
    if df_target.empty:
        return {}
    result: Dict[str, str] = {}
    tz = df_target.index.tz
    prev_bias = "neutral"
    min_bars = max(swing_length * 2 + 5, 50)

    for day in sorted(set(df_target.index.date)):
        day_end_naive = pd.Timestamp(day) + pd.Timedelta(days=1)
        if tz is not None:
            day_end = day_end_naive.tz_localize(tz)
        else:
            day_end = day_end_naive

        day_end_idx = int(df_target.index.searchsorted(day_end, side="left"))
        if day_end_idx < min_bars:
            result[str(day)] = prev_bias
            continue

        slice_ = df_target.iloc[:day_end_idx]
        bias = detect_bias(slice_, swing_length=swing_length)
        if bias is None:
            bias = prev_bias
        result[str(day)] = bias
        prev_bias = bias

    return result

def run_backtest(
    pair: str = "EURUSD",
    config: dict | None = None,
) -> Tuple[List[dict], List[Tuple[pd.Timestamp, float]]]:
    """Run bar-by-bar backtest on M15 data.

    Returns (trades, equity_curve)."""
    if config is None:
        config = {}

    swing_length = config.get("swing_length", 20)
    account_size = float(config.get("account_size", 100_000.0))
    risk_per_trade = float(config.get("risk_per_trade", 0.0055))
    max_trades_per_day = int(config.get("max_trades_per_day", 3))
    max_daily_loss_r = float(config.get("max_daily_loss_r", 2.0))
    sl_atr_buffer = float(config.get("sl_atr_buffer", 0.2))
    min_confluence = int(config.get("min_confluence_score", 4))
    pip_value = pip_value_for_pair(pair)

    # Load data
    data = load_multi_tf_data(pair)
    _ensure_h4(data)

    df_m15 = data.get("M15", pd.DataFrame())
    df_d = data.get("D", pd.DataFrame())
    df_h4 = data.get("H4", pd.DataFrame())

    if df_m15.empty:
        return [], []

    # Pre-compute signals once
    detector = SMCSignals(
        swing_length=swing_length,
        displacement_atr_mult=config.get("displacement_atr_mult", 1.5),
        sweep_atr_buffer=config.get("sweep_atr_buffer", 0.05),
    )
    signals_full = detector.get_signals(df_m15, skip_mitigation=True)

    # Displacement / sweep as Series
    disp_series = pd.Series(False, index=df_m15.index, dtype=bool)
    for sig in signals_full.get("displacement", []):
        if sig.timestamp in df_m15.index:
            disp_series.loc[sig.timestamp] = True

    sweep_bull_series = pd.Series(False, index=df_m15.index, dtype=bool)
    sweep_bear_series = pd.Series(False, index=df_m15.index, dtype=bool)
    for sig in signals_full.get("sweep", []):
        if sig.timestamp in df_m15.index:
            if sig.direction == "bullish":
                sweep_bull_series.loc[sig.timestamp] = True
            else:
                sweep_bear_series.loc[sig.timestamp] = True

    # Pre-compute ATR and P/D zone for every bar
    atr_all = calculate_atr(df_m15)
    pd_zones = pd_series(df_m15, lookback=swing_length * 2 + 10)

    # Pre-compute bias per day for D and H4.
    # D parquet often ends before M15 range — synthesize D from H1 when needed.
    df_d_bias = df_d
    if not df_m15.empty and (df_d.empty or df_d.index.max() < df_m15.index.min()):
        df_h1 = data.get("H1", pd.DataFrame())
        if not df_h1.empty:
            df_d_bias = df_h1.resample("1D").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
    elif not df_d.empty and not df_m15.empty and df_d.index.max() < df_m15.index.max():
        # Extend D with H1-daily beyond D's last date
        df_h1 = data.get("H1", pd.DataFrame())
        if not df_h1.empty:
            h1_d = df_h1.resample("1D").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
            extra = h1_d[h1_d.index > df_d.index.max()]
            if not extra.empty:
                df_d_bias = pd.concat([df_d, extra]).sort_index()
                df_d_bias = df_d_bias[~df_d_bias.index.duplicated(keep="last")]

    daily_bias_d = _precompute_bias_per_day(df_d_bias, swing_length) if not df_d_bias.empty else {}
    daily_bias_h4 = _precompute_bias_per_day(df_h4, swing_length) if not df_h4.empty else {}

    # Forward-fill bias onto every M15 calendar day so missing keys don't force stand_aside
    def _ffill_bias(bias_map: Dict[str, str], m15_index: pd.DatetimeIndex) -> Dict[str, str]:
        out: Dict[str, str] = {}
        last = "neutral"
        for day in sorted({str(t.date()) for t in m15_index}):
            if day in bias_map and bias_map[day] not in (None, "neutral"):
                last = bias_map[day]
            elif day in bias_map and bias_map[day] is not None:
                last = bias_map[day]
            out[day] = last
        return out

    daily_bias_d = _ffill_bias(daily_bias_d, df_m15.index)
    daily_bias_h4 = _ffill_bias(daily_bias_h4, df_m15.index)

    # Guard
    guard = FTMOGuard(
        account_size=account_size,
        max_daily_loss_pct=0.05,
        max_trades_per_day=max_trades_per_day,
        max_daily_loss_r=max_daily_loss_r,
    )

    equity = account_size
    equity_curve: List[Tuple[pd.Timestamp, float]] = []
    open_pos: dict | None = None
    trades: List[dict] = []

    start_bar = swing_length + 20

    for i in range(start_bar, len(df_m15)):
        ts = df_m15.index[i]
        bar_close = float(df_m15["close"].iloc[i])
        if pd.isna(bar_close):
            equity_curve.append((ts, equity))
            continue
        current_date = ts.date()

        # Daily guard reset
        if guard.last_reset_date is None or guard.last_reset_date != current_date:
            guard.reset_daily(day=current_date)

        # O(1) daily bias lookup
        bias_d = daily_bias_d.get(str(current_date), "neutral")
        bias_h4 = daily_bias_h4.get(str(current_date), "neutral")
        bias_by_tf = {"D": bias_d, "H4": bias_h4}
        aligned_bias = align_bias(bias_by_tf)

        # Snapshot components (all O(1))
        displacement = bool(disp_series.iloc[i])
        sweep_bull = bool(sweep_bull_series.iloc[i])
        sweep_bear = bool(sweep_bear_series.iloc[i])
        sweep_clean = sweep_bull or sweep_bear or displacement
        pd_zone_now = str(pd_zones.iloc[i]) if i < len(pd_zones) else "neutral"
        atr_now = float(atr_all.iloc[i]) if i < len(atr_all) else 0.0

        trade_dir = (
            "long" if aligned_bias == "aligned_long"
            else ("short" if aligned_bias == "aligned_short" else None)
        )
        bias_aligned = aligned_bias in ("aligned_long", "aligned_short")
        in_pd_zone = (
            (pd_zone_now == "discount" and trade_dir == "long")
            or (pd_zone_now == "premium" and trade_dir == "short")
        )

        # Score
        score, reasons, entry_allowed = score_setup(
            {
                "displacement": displacement,
                "bias_aligned": bias_aligned,
                "sweep_clean": sweep_clean,
                "in_pd_zone": in_pd_zone,
                "first_test": True,
                "pd_zone": pd_zone_now,
            },
            min_score=min_confluence,
        )

        # OB: pick the most recent unmitigated OB matching trade direction; use
        # top/bottom fields so SL width reflects the actual OB range, not a
        # single price level.
        ob_top: float | None = None
        ob_bottom: float | None = None
        target_dir = "bullish" if trade_dir == "long" else (
            "bearish" if trade_dir == "short" else None
        )
        if target_dir is not None:
            for sig in reversed(signals_full.get("ob", [])):
                if sig.mitigated or sig.direction != target_dir:
                    continue
                t = getattr(sig, "top", None)
                b = getattr(sig, "bottom", None)
                if t is None or b is None:
                    continue
                if sig.timestamp > ts:
                    continue
                ob_top = float(t)
                ob_bottom = float(b)
                break

        snapshot = {
            "side_request": trade_dir,
            "score": score,
            "entry_allowed": entry_allowed,
            "displacement": displacement,
            "bias_aligned": bias_aligned,
            "sweep_clean": sweep_clean,
            "in_pd_zone": in_pd_zone,
            "first_test": True,
            "pd_zone": pd_zone_now,
            "ob_top": ob_top,
            "ob_bottom": ob_bottom,
            "atr": atr_now,
            "close": bar_close,
            "bias_d": bias_d,
            "bias_h4": bias_h4,
            "reasons": reasons,
            "pair": pair,
            "sl_atr_buffer": sl_atr_buffer,
        }

        # ── Update open position ─────────────────────────────────────────────
        if open_pos is not None:
            exit_obj = open_pos["exit_obj"]
            risk_amount = open_pos["risk_amount"]
            pos_rem = open_pos.get("pos_remaining", 1.0)

            actions = exit_obj.update(bar_close)
            for action in actions:
                tag, val = action[0], action[1]
                if tag == "close_pct":
                    orig_frac = float(val) * pos_rem
                    r_now = exit_obj.r_multiple
                    equity += orig_frac * r_now * risk_amount
                    pos_rem *= max(0.0, 1.0 - float(val))
                    open_pos["pos_remaining"] = pos_rem
                    open_pos["realized_r"] = open_pos.get("realized_r", 0.0) + orig_frac * r_now
                elif tag == "move_sl":
                    open_pos["sl"] = float(val)
                elif tag == "closed":
                    r_final = open_pos.get("realized_r", exit_obj.r_multiple)
                    pnl = r_final * risk_amount
                    trades.append({
                        "pair": pair,
                        "side": open_pos["side"],
                        "entry": open_pos["entry"],
                        "exit_price": bar_close,
                        "sl": open_pos["sl"],
                        "tp1": open_pos["tp1"],
                        "tp2": open_pos["tp2"],
                        "tp3": open_pos["tp3"],
                        "r_multiple": r_final,
                        "pnl_usd": pnl,
                        "risk_usd": risk_amount,
                        "confluence_score": open_pos.get("score", 0),
                        "bias_d": open_pos.get("bias_d"),
                        "bias_h4": open_pos.get("bias_h4"),
                        "displacement": int(open_pos.get("displacement", 0)),
                        "sweep_clean": int(open_pos.get("sweep_clean", 0)),
                        "premium_discount": open_pos.get("pd_zone", "neutral"),
                        "first_test": int(open_pos.get("first_test", 0)),
                        "exit_reason": val,
                        "session": "london",
                        "timestamp_entry": open_pos.get("timestamp_entry"),
                        "timestamp_exit": str(ts),
                        "setup_type": "OB",
                    })
                    guard.record_trade(r_final)
                    open_pos = None
                    break

        # ── Entry logic ─────────────────────────────────────────────────────
        if open_pos is None:
            can_trade, _ = guard.can_trade(equity)
            if can_trade and entry_allowed:
                entry_info = check_entry(snapshot)
                if entry_info is not None:
                    # Risk fixed off initial account to keep DD bounded (FTMO style)
                    risk_amount = account_size * risk_per_trade
                    sl_dist = abs(entry_info["entry"] - entry_info["sl"])
                    if sl_dist <= 0:
                        continue
                    lot = calculate_lot(account_size, risk_per_trade, sl_dist, pip_value)
                    exit_obj = PartialTPExit(
                        entry=entry_info["entry"],
                        sl=entry_info["sl"],
                        side=entry_info["side"],
                        atr_buffer=sl_atr_buffer,
                    )
                    open_pos = {
                        **entry_info,
                        "lot": lot,
                        "risk_amount": risk_amount,
                        "exit_obj": exit_obj,
                        "timestamp_entry": str(ts),
                        "score": score,
                        "bias_d": bias_d,
                        "bias_h4": bias_h4,
                        "displacement": int(displacement),
                        "sweep_clean": int(sweep_clean),
                        "pd_zone": pd_zone_now,
                        "first_test": 1,
                        "pos_remaining": 1.0,
                        "realized_r": 0.0,
                    }

        equity_curve.append((ts, equity))

    # Close open position at end
    if open_pos is not None:
        last_ts = df_m15.index[-1]
        last_close = float(df_m15["close"].iloc[-1])
        exit_obj: PartialTPExit = open_pos["exit_obj"]
        actions = exit_obj.update(last_close)
        for action in actions:
            if action[0] == "closed":
                r_final = exit_obj.r_multiple
                pnl = r_final * open_pos["risk_amount"]
                equity += pnl
                trades.append({
                    "pair": pair,
                    "side": open_pos["side"],
                    "entry": open_pos["entry"],
                    "exit_price": last_close,
                    "sl": open_pos["sl"],
                    "tp1": open_pos["tp1"],
                    "tp2": open_pos["tp2"],
                    "tp3": open_pos["tp3"],
                    "r_multiple": r_final,
                    "pnl_usd": pnl,
                    "risk_usd": open_pos["risk_amount"],
                    "confluence_score": open_pos.get("score", 0),
                    "bias_d": open_pos.get("bias_d"),
                    "bias_h4": open_pos.get("bias_h4"),
                    "displacement": int(open_pos.get("displacement", 0)),
                    "sweep_clean": int(open_pos.get("sweep_clean", 0)),
                    "premium_discount": open_pos.get("pd_zone", "neutral"),
                    "first_test": int(open_pos.get("first_test", 0)),
                    "exit_reason": "time",
                    "session": "london",
                    "timestamp_entry": open_pos.get("timestamp_entry"),
                    "timestamp_exit": str(last_ts),
                    "setup_type": "OB",
                })
                guard.record_trade(r_final)

    return trades, equity_curve


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(
    trades: List[dict],
    equity_curve: List[Tuple[pd.Timestamp, float]],
) -> dict:
    """Compute summary statistics from closed trades and equity curve."""
    if not trades:
        return {
            "total_trades": 0, "winrate": 0.0, "profit_factor": 0.0,
            "avg_r": 0.0, "max_dd": 0.0, "max_dd_pct": 0.0,
            "total_r": 0.0, "final_equity": 0.0,
            "longest_win_streak": 0, "longest_loss_streak": 0,
        }

    df = pd.DataFrame(trades)
    wins = df[df["r_multiple"] > 0]
    losses = df[df["r_multiple"] <= 0]

    gross_profit = float(wins["r_multiple"].sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses["r_multiple"].sum())) if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else float("inf")

    eq = pd.Series([e for _, e in equity_curve])
    running_max = eq.cummax()
    drawdown = (eq - running_max) / running_max
    max_dd = float(drawdown.min())

    return {
        "total_trades": len(trades),
        "winrate": float(len(wins) / len(trades)),
        "profit_factor": float(profit_factor),
        "avg_r": float(df["r_multiple"].mean()),
        "max_dd": abs(max_dd),
        "max_dd_pct": abs(max_dd) * 100,
        "total_r": float(df["r_multiple"].sum()),
        "final_equity": float(equity_curve[-1][1]) if equity_curve else 0.0,
        "longest_win_streak": _streak(list(df["r_multiple"] > 0), True),
        "longest_loss_streak": _streak(list(df["r_multiple"] <= 0), False),
    }


def _streak(bools: List[bool], target: bool) -> int:
    best = cur = 0
    for b in bools:
        cur = (cur + 1) if b == target else 0
        best = max(best, cur)
    return best


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running backtest smoke test on EURUSD (Aug 2024–present)…")
    config = {
        "swing_length": 20, "risk_per_trade": 0.0055,
        "max_trades_per_day": 3, "max_daily_loss_r": 2.0,
        "min_confluence_score": 4, "account_size": 100_000.0,
        "sl_atr_buffer": 0.2, "displacement_atr_mult": 1.5,
        "sweep_atr_buffer": 0.05, "pair": "EURUSD",
    }
    trades, curve = run_backtest("EURUSD", config)
    metrics = compute_metrics(trades, curve)
    print(f"Trades: {metrics['total_trades']}, Winrate: {metrics['winrate']:.1%}, "
          f"PF: {metrics['profit_factor']:.2f}, MaxDD: {metrics['max_dd_pct']:.2f}%, "
          f"AvgR: {metrics['avg_r']:.2f}")
    print("Backtester smoke test done.")
