"""M15 bar-by-bar backtester with custom SMC pipeline.

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

from bias_detector import align_bias, detect_bias
from confluence import score_setup
from data_loader import load_multi_tf_data
from premium_discount import pd_series
from risk_manager import FTMOGuard, calculate_lot
from smc_signals import SMCSignals, calculate_atr
from strategy import PartialTPExit, check_entry, pip_size_for_pair, pip_value_for_pair
from scale_in_exit import ScaleInExit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample_h4_from_h1(df_h1: pd.DataFrame) -> pd.DataFrame:
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
    if "H4" not in data or data["H4"].empty:
        if "H1" in data and not data["H1"].empty:
            data["H4"] = _resample_h4_from_h1(data["H1"])


def _resample_h1_to_daily(df_h1: pd.DataFrame, existing_d: pd.DataFrame) -> pd.DataFrame:
    """Combine H1-daily with parquet D, filling Gaps from H1 when D ends early."""
    if df_h1.empty:
        return existing_d
    h1_d = df_h1.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    if existing_d is None or existing_d.empty:
        return h1_d
    out = pd.concat([existing_d, h1_d[h1_d.index > existing_d.index.max()]]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def _bias_series_for_tf(
    df: pd.DataFrame, swing_length: int
) -> pd.Series | None:
    """Compute per-bar bias as a Series using the custom engine."""
    if df is None or df.empty:
        return None
    from smc_engine.context import compute_bias_series
    from smc_engine.structure import detect_structure
    from smc_engine.swings import detect_swings

    left = right = max(2, swing_length // 2)
    swings = detect_swings(df, left=left, right=right)
    if len(swings.events) == 0:
        return None
    structure = detect_structure(df, swings)
    return compute_bias_series(structure)


def _align_to_m15(htf_bias: pd.Series, m15_index: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill HTF bias onto every M15 bar.

    Uses ``merge_asof`` so today's daily bias only applies after its own daily
    close timestamp; future bias never leaks into past M15 bars.
    """
    if htf_bias is None or htf_bias.empty:
        return pd.Series("neutral", index=m15_index, dtype=object)
    series = htf_bias.copy()
    if not isinstance(series.index, pd.DatetimeIndex):
        return pd.Series("neutral", index=m15_index, dtype=object)
    if series.index.tz is None and m15_index.tz is not None:
        series = series.tz_localize(m15_index.tz)
    elif series.index.tz is not None and m15_index.tz is None:
        series = series.tz_localize(None)
    s = series.reset_index()
    s.columns = ["ts", "bias"]
    s["ts"] = pd.to_datetime(s["ts"])
    target = pd.DataFrame({"ts": pd.to_datetime(m15_index)})
    merged = pd.merge_asof(
        target, s, on="ts", direction="backward", allow_exact_matches=True
    )
    merged["bias"] = merged["bias"].fillna("neutral")
    return pd.Series(merged["bias"].values, index=m15_index, dtype=object)


def _ob_zones_as_of(ob_list, ts) -> list:
    """Return OB event dicts available at timestamp ``ts`` using lifecycle state."""
    out = []
    for ev in ob_list:
        if ev.activation_timestamp > ts:
            continue
        if not ev.is_active_at(ts):
            continue
        out.append({
            "direction": ev.direction,
            "top": float(ev.top),
            "bottom": float(ev.bottom),
            "first_touch_at": ev.first_touch_timestamp,
            "activation_at": ev.activation_timestamp,
        })
    return out


def _fvg_zones_as_of(fvg_list, ts) -> list:
    out = []
    for ev in fvg_list:
        if ev.activation_timestamp > ts:
            continue
        if not ev.is_active_at(ts):
            continue
        out.append({
            "direction": ev.direction,
            "top": float(ev.top),
            "bottom": float(ev.bottom),
        })
    return out


def run_backtest(
    pair: str = "EURUSD",
    config: dict | None = None,
) -> Tuple[List[dict], List[Tuple[pd.Timestamp, float]]]:
    if config is None:
        config = {}

    swing_length = int(config.get("swing_length", 20))
    account_size = float(config.get("account_size", 100_000.0))

    risk_cfg = config.get("risk", {}) if isinstance(config.get("risk"), dict) else {}
    risk_per_trade = float(
        risk_cfg.get("per_trade_pct", config.get("risk_per_trade", 0.0055))
    )
    max_trades_per_day = int(
        risk_cfg.get("max_trades_per_day", config.get("max_trades_per_day", 3))
    )
    max_daily_loss_r = float(
        risk_cfg.get("daily_loss_limit_r", config.get("max_daily_loss_r", 2.0))
    )

    strat_cfg = config.get("strategy", {}) if isinstance(config.get("strategy"), dict) else {}
    rr_target = float(strat_cfg.get("rr_target", config.get("rr_target", 2.5)))
    sl_atr_buffer = float(strat_cfg.get("sl_atr_buffer", config.get("sl_atr_buffer", 0.2)))
    min_sl_atr = float(strat_cfg.get("min_sl_atr", config.get("min_sl_atr", 0.0)))
    max_sl_atr = float(strat_cfg.get("max_sl_atr", config.get("max_sl_atr", 99.0)))
    min_sl_pips = strat_cfg.get("min_sl_pips", config.get("min_sl_pips", 0))
    rulebook_entry_proximity_atr = float(
        strat_cfg.get("rulebook_entry_proximity_atr", config.get("rulebook_entry_proximity_atr", 1.5)))
    displacement_atr_mult = float(
        strat_cfg.get("displacement_atr_mult", config.get("displacement_atr_mult", 1.5))
    )
    sweep_atr_buffer = float(
        strat_cfg.get("sweep_atr_buffer", config.get("sweep_atr_buffer", 0.05))
    )
    min_confluence = int(
        strat_cfg.get("min_confluence_score", config.get("min_confluence_score", 4))
    )
    require_bias_aligned = bool(
        strat_cfg.get("require_bias_aligned", config.get("require_bias_aligned", True))
    )
    # Pine parity: HTF enable flags. Default True (Pine default). User can
    # disable to match Pine when 'Use Daily HTF' / 'Use H4 HTF' are unchecked.
    htf_daily_enabled = bool(
        strat_cfg.get("htf_daily_enabled", config.get("htf_daily_enabled", True))
    )
    htf_h4_enabled = bool(
        strat_cfg.get("htf_h4_enabled", config.get("htf_h4_enabled", True)))
    # Plan 14 regime-aware strategy:
    #   regime_mode="off"  -> breaker overlay disabled (legacy baseline).
    #   regime_mode="on"   -> breaker overlay always enabled.
    #   regime_mode="auto" -> regime detection picks weights from data.
    regime_mode = str(
        strat_cfg.get("regime_mode", config.get("regime_mode", "off"))
    )
    if regime_mode not in ("off", "on", "auto"):
        raise ValueError(
            f"regime_mode must be off|on|auto, got {regime_mode!r}"
        )
    promotion_lookback_bars = int(
        strat_cfg.get(
            "promotion_lookback_bars",
            config.get("promotion_lookback_bars", 50),
        )
    )
    # Bias mode controls how strictly daily+H4 must agree:
    #   'strict'     -> D+H4 must agree (legacy); require_bias_aligned must be True.
    #   'h4_only'    -> trade by H4 alone; D neutral is allowed, D counter-trend is blocked.
    #   'any'        -> trade if any single TF has a bias; require_bias_aligned must be False.
    # Falls back to legacy 'strict' when absent.
    bias_mode = strat_cfg.get("bias_mode", config.get("bias_mode", "strict"))
    if bias_mode not in ("strict", "h4_only", "any"):
        bias_mode = "strict"
    raw_tp_stages = strat_cfg.get("partial_tp") or config.get("partial_tp")
    if isinstance(raw_tp_stages, list) and raw_tp_stages:
        try:
            tp_stages = tuple(
                (float(stage["r"]), float(stage["pct"])) for stage in raw_tp_stages
            )
        except (KeyError, TypeError, ValueError):
            tp_stages = PartialTPExit.DEFAULT_STAGES
    elif isinstance(raw_tp_stages, tuple) and raw_tp_stages:
        tp_stages = raw_tp_stages
    else:
        tp_stages = PartialTPExit.DEFAULT_STAGES

    # Exit mode: 'ladder' (default PartialTPExit) or 'scale_in' (ScaleInExit).
    # Backward-compatible: existing configs default to 'ladder' (unchanged behavior).
    # Exit mode: 'ladder' (default PartialTPExit), 'scale_in' (leg2 @ 2R peak,
    # 0.5 vol), 'scale_in_middle' (leg2 @ 1R retrace, 0.5 vol), or
    # 'scale_in_middle_1r' (leg2 @ 1R retrace, 1.0 vol).
    exit_mode = strat_cfg.get("exit_mode", config.get("exit_mode", "ladder"))
    if exit_mode not in ("ladder", "scale_in",
                         "scale_in_middle", "scale_in_middle_1r"):
        exit_mode = "ladder"



    filters = config.get("filters", {}) if isinstance(config.get("filters"), dict) else {}
    sweep_filter = bool(filters.get("sweep", False))
    pd_filter = bool(filters.get("pd", False))
    first_test_filter = bool(filters.get("first_test", False))

    pd_lookback = int(config.get("pd_lookback", swing_length * 2 + 10))

    start_iso = config.get("start_date")
    end_iso = config.get("end_date")

    pip_value = pip_value_for_pair(pair)
    # Execution costs (Phase 08 Step 2 — 2026-08-31).
    # Reads optional 'execution' block from config. If absent, defaults to
    # zero spread / zero commission / zero slippage (legacy behavior).
    _exec_raw = config.get("execution")
    execution_cfg = _exec_raw if isinstance(_exec_raw, dict) else {}
    _spread_raw = execution_cfg.get("spread_pips")
    spread_table = _spread_raw if isinstance(_spread_raw, dict) else {}
    spread_pips = float(spread_table.get(pair, 0.0))
    commission_per_side = float(
        execution_cfg.get("commission_per_lot_per_side", 0.0)
    )
    _slip_raw = execution_cfg.get("slippage_pips")
    slip_cfg = _slip_raw if isinstance(_slip_raw, dict) else {}
    slippage_mean = float(slip_cfg.get("mean", 0.0))
    slippage_std = float(slip_cfg.get("std", 0.0))
    import numpy as _np
    slippage_rng = _np.random.default_rng(
        execution_cfg.get("slippage_seed", 42)
    )

    data = load_multi_tf_data(pair)
    _ensure_h4(data)
    df_m15 = data.get("M15", pd.DataFrame())
    df_d = data.get("D", pd.DataFrame())
    df_h4 = data.get("H4", pd.DataFrame())
    df_h1 = data.get("H1", pd.DataFrame())

    if start_iso or end_iso:
        try:
            lo = pd.Timestamp(start_iso) if start_iso else df_m15.index[0]
            hi = pd.Timestamp(end_iso) if end_iso else df_m15.index[-1]
            tz = getattr(df_m15.index, "tz", None)
            if tz is not None:
                if getattr(lo, "tzinfo", None) is None:
                    lo = lo.tz_localize(tz)
                if getattr(hi, "tzinfo", None) is None:
                    hi = hi.tz_localize(tz)
            def _clip(d):
                if d is None or d.empty:
                    return d
                if tz is not None and getattr(d.index, "tz", None) is None:
                    d = d.tz_localize(tz)
                return d[(d.index >= lo) & (d.index <= hi)]
            df_m15 = _clip(df_m15)
            df_d = _clip(df_d)
            df_h4 = _clip(df_h4)
        except Exception:
            pass

    if df_m15.empty:
        return [], []

    # Compute HTF daily + extend D from H1 when D ends early.
    if not df_d.empty and not df_h1.empty and df_d.index.max() < df_m15.index.max():
        df_d_bias_src = _resample_h1_to_daily(df_h1, df_d)
    elif df_d.empty and not df_h1.empty:
        df_d_bias_src = _resample_h1_to_daily(df_h1, df_d)
    else:
        df_d_bias_src = df_d

    bias_series_d = _bias_series_for_tf(df_d_bias_src, swing_length)
    bias_series_h4 = _bias_series_for_tf(df_h4, swing_length)

    m15_bias_d = _align_to_m15(bias_series_d, df_m15.index)
    m15_bias_h4 = _align_to_m15(bias_series_h4, df_m15.index)

    # Pine parity (bug #10): HTF H4 range wall. 16-bar rolling high/low on H4.
    # Mirrors Pine "ta.highest(high, 16)" / "ta.lowest(low, 16)".
    # Used to skip trades whose TP1 would hit the H4 range wall.
    if not df_h4.empty:
        h4_high_16 = df_h4['high'].rolling(16).max().shift(1)
        h4_low_16  = df_h4['low'].rolling(16).min().shift(1)
        h4_high_s  = h4_high_16.reindex(df_m15.index, method='ffill')
        h4_low_s   = h4_low_16.reindex(df_m15.index, method='ffill')
    else:
        h4_high_s  = pd.Series(float('nan'), index=df_m15.index)
        h4_low_s   = pd.Series(float('nan'), index=df_m15.index)

    # ATR + P/D zone for every M15 bar
    atr_all = calculate_atr(df_m15)
    pd_zones = pd_series(df_m15, lookback=pd_lookback)

    # Build all engine outputs once for the full M15 frame.
    detector = SMCSignals(
        swing_length=swing_length,
        displacement_atr_mult=displacement_atr_mult,
        sweep_atr_buffer=sweep_atr_buffer,
    )
    signals_full = detector.get_signals(df_m15, skip_mitigation=True)

    # Displacement / sweep as Series.
    disp_series = pd.Series(False, index=df_m15.index, dtype=bool)
    for sig in signals_full.get("displacement", []):
        ts = pd.Timestamp(sig.timestamp)
        if ts in df_m15.index:
            disp_series.loc[ts] = True

    sweep_bull_series = pd.Series(False, index=df_m15.index, dtype=bool)
    sweep_bear_series = pd.Series(False, index=df_m15.index, dtype=bool)
    for sig in signals_full.get("sweep", []):
        ts = pd.Timestamp(sig.timestamp)
        if ts in df_m15.index:
            if sig.direction == "bullish":
                sweep_bull_series.loc[ts] = True
            else:
                sweep_bear_series.loc[ts] = True
    pool_bull_near_series = pd.Series(0, index=df_m15.index, dtype=int)
    pool_bear_near_series = pd.Series(0, index=df_m15.index, dtype=int)
    from smc_engine.context import compute_dealing_range_context, is_in_pd_zone as _pd_is_in
    from smc_engine.displacement import detect_range_expansion
    from smc_engine.fvg import detect_fvgs
    from smc_engine.liquidity_pools import detect_liquidity_pools
    from smc_engine.order_blocks import detect_order_blocks
    from smc_engine.regime import detect_regime
    from smc_engine.structure import detect_structure
    from smc_engine.sweeps import detect_sweeps
    from smc_engine.swings import detect_swings

    left = right = max(2, swing_length // 2)
    swings_m15 = detect_swings(df_m15, left=left, right=right)
    expansion_m15 = detect_range_expansion(df_m15, atr_all, multiplier=displacement_atr_mult)
    structure_m15 = detect_structure(df_m15, swings_m15, atr=atr_all)
    sweeps_m15 = detect_sweeps(
        df_m15,
        swings_m15,
        atr_all,
        atr_buffer=sweep_atr_buffer,
        range_expansion_mult=displacement_atr_mult,
    )
    order_blocks_full = detect_order_blocks(df_m15, structure_m15, expansion_m15)
    fvgs_full = detect_fvgs(df_m15)
    allow_breakers = regime_mode == "on"
    if regime_mode == "auto":
        regime = detect_regime(
            df_m15,
            structure=structure_m15,
            sweeps=sweeps_m15,
            swing_left=left,
            swing_right=right,
            sweep_atr_buffer=sweep_atr_buffer,
            displacement_atr_mult=displacement_atr_mult,
        )
        allow_breakers = regime.breaker_weight > 0.0
    liquidity_pools = detect_liquidity_pools(df_m15, swings_m15, atr_all)
    for pool in liquidity_pools.events:
        if pool.activation_pos >= len(df_m15):
            continue
        start = max(pool.activation_pos, 0)
        if pool.side == "high":
            pool_bull_near_series.iloc[start:] += 1
        else:
            pool_bear_near_series.iloc[start:] += 1
    breakers_list: list = []
    if regime_mode != "off" and allow_breakers:
        from smc_engine.breaker_blocks import promote_breakers_with_events
        breakers_list, _breaker_diags = promote_breakers_with_events(
            order_blocks_full,
            structure_m15,
            df_m15.index,
            promotion_lookback_bars=promotion_lookback_bars,
        )
    context_m15 = compute_dealing_range_context(df_m15, structure_m15)
    pd_zone_engine_series = context_m15.zone.reindex(df_m15.index).fillna("neutral")
    liquidity_pools = detect_liquidity_pools(df_m15, swings_m15, atr_all)
    for pool in liquidity_pools.events:
        if pool.activation_pos >= len(df_m15):
            continue
        start = max(pool.activation_pos, 0)
        if pool.side == "high":
            pool_bull_near_series.iloc[start:] += 1
        else:
            pool_bear_near_series.iloc[start:] += 1

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

        if guard.last_reset_date is None or guard.last_reset_date != current_date:
            guard.reset_daily(day=current_date)

        bias_d = m15_bias_d.iloc[i] if i < len(m15_bias_d) else "neutral"
        bias_h4 = m15_bias_h4.iloc[i] if i < len(m15_bias_h4) else "neutral"
        bias_by_tf = {"D": bias_d, "H4": bias_h4}
        # Pine parity: respect htf_daily_enabled / htf_h4_enabled flags.
        # When both HTFs are disabled, fall back to 'any' mode logic below.
        if not htf_daily_enabled and not htf_h4_enabled:
            aligned_bias = "any_long_short"  # both HTFs off: take any direction
        else:
            aligned_bias = align_bias(bias_by_tf)

        displacement = bool(disp_series.iloc[i]) if i < len(disp_series) else False
        sweep_bull = bool(sweep_bull_series.iloc[i]) if i < len(sweep_bull_series) else False
        sweep_bear = bool(sweep_bear_series.iloc[i]) if i < len(sweep_bear_series) else False
        sweep_clean = sweep_bull or sweep_bear or displacement
        pool_bull_near = int(pool_bull_near_series.iloc[i]) if i < len(pool_bull_near_series) else 0
        pool_bear_near = int(pool_bear_near_series.iloc[i]) if i < len(pool_bear_near_series) else 0
        near_high_pool = pool_bull_near > 0
        near_low_pool = pool_bear_near > 0
        near_pool = near_high_pool or near_low_pool

        pd_zone_now = pd_zone_engine_series.iloc[i] if i < len(pd_zone_engine_series) else "neutral"
        atr_now = float(atr_all.iloc[i]) if i < len(atr_all) else 0.0
        # Direction. Engine bias enum: bull/bear/neutral.
        # bias_mode:
        #   strict  -> legacy: aligned_bias from D+H4 must agree.
        #   h4_only -> trade on H4 direction when D is neutral; block counter-trend.
        #   any     -> trade on any single TF bias (legacy require_bias_aligned=False branch).
        if aligned_bias == "aligned_long":
            trade_dir = "long"
        elif aligned_bias == "aligned_short":
            trade_dir = "short"
        elif aligned_bias == "any_long_short":
            # Pine parity: both HTF flags disabled. Fire on any bias (D or H4).
            if bias_d == "bull" or bias_h4 == "bull":
                trade_dir = "long"
            elif bias_d == "bear" or bias_h4 == "bear":
                trade_dir = "short"
            else:
                trade_dir = None
        elif bias_mode == "h4_only":
            # Trade on H4 alone, but only when D is not counter-trend.
            if bias_d == "bear" and bias_h4 == "bull":
                trade_dir = None  # D counter-trend vs H4 -> skip
            elif bias_d == "bull" and bias_h4 == "bear":
                trade_dir = None  # D counter-trend vs H4 -> skip
            elif bias_h4 == "bull":
                trade_dir = "long"
            elif bias_h4 == "bear":
                trade_dir = "short"
            else:
                trade_dir = None
        elif not require_bias_aligned:
            if bias_d == "bull" or bias_h4 == "bull":
                trade_dir = "long"
            elif bias_d == "bear" or bias_h4 == "bear":
                trade_dir = "short"
            else:
                trade_dir = None
        else:
            trade_dir = None
        bias_aligned = trade_dir is not None
        in_pd_zone = _pd_is_in(str(pd_zone_now), trade_dir or "long")
        target = None
        ob_zones_now = []
        if trade_dir in ("long", "short"):
            target = "bullish" if trade_dir == "long" else "bearish"
            for ev in order_blocks_full.events:
                if ev.direction != target:
                    continue
                if not ev.is_active_at(ts):
                    continue
                if ev.first_touch_timestamp is not None and ts > ev.first_touch_timestamp:
                    continue
                ob_zones_now.append({
                    "direction": ev.direction,
                    "top": float(ev.top),
                    "bottom": float(ev.bottom),
                })
            # EQH/EQL proximity check: longs require a nearby low-side pool,
            # shorts require a nearby high-side pool. Falls back to permissive
            # when no pools are nearby so the baseline count is unchanged.
            if (
                (trade_dir == "long" and not near_low_pool)
                or (trade_dir == "short" and not near_high_pool)
            ):
                entry_allowed = False
            # Auto mode is regime-gated, not hash-sampled: breakers only
            # participate when the recent structure is clearly ranging.
            if breakers_list:
                for br in breakers_list:
                    if br.direction != target:
                        continue
                    if ts < br.role_flip_timestamp:
                        continue
                    ob_zones_now.append({
                        "direction": br.direction,
                        "top": float(br.top),
                        "bottom": float(br.bottom),
                    })
        ob_top: float | None = ob_zones_now[-1]["top"] if ob_zones_now else None
        ob_bottom: float | None = ob_zones_now[-1]["bottom"] if ob_zones_now else None

        first_test = ob_top is not None and ob_bottom is not None

        score, reasons, entry_allowed = score_setup(
            {
                "displacement": displacement,
                "bias_aligned": bias_aligned,
                "sweep_clean": sweep_clean,
                "in_pd_zone": in_pd_zone,
                "first_test": first_test,
                "pd_zone": pd_zone_now,
            },
            min_score=min_confluence,
        )

        if sweep_filter and not sweep_clean:
            entry_allowed = False
        if pd_filter and not in_pd_zone:
            entry_allowed = False
        # (rr_target cap removed: TP ladder now comes from tp_stages in config)
        snapshot = {
            "side_request": trade_dir,
            "score": score,
            "entry_allowed": entry_allowed,
            "displacement": displacement,
            "bias_aligned": bias_aligned,
            "sweep_clean": sweep_clean,
            "in_pd_zone": in_pd_zone,
            "first_test": first_test,
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
            "min_sl_atr": min_sl_atr,
            "max_sl_atr": max_sl_atr,
            "min_sl_pips": min_sl_pips,
            "rulebook_entry_proximity_atr": rulebook_entry_proximity_atr,
            "tp_stages": tp_stages,
            # Pine parity: rulebookEntryProximityAtr (default 1.5).
            # Mirrors Pine "rulebookEntryProximityAtr" input.
            # Pine parity (bug #10): HTF H4 range wall.
            "htf_h4_range_high": float(h4_high_s.iloc[i]) if pd.notna(h4_high_s.iloc[i]) else None,
            "htf_h4_range_low":  float(h4_low_s.iloc[i])  if pd.notna(h4_low_s.iloc[i])  else None,
        }

        # Update open position
        if open_pos is not None:
            exit_obj = open_pos["exit_obj"]
            risk_amount = open_pos["risk_amount"]
            pos_rem = open_pos.get("pos_remaining", 1.0)

            actions = exit_obj.update(bar_close)
            for action in actions:
                tag = action[0]
                # Actions vary in length: ('close_leg2',) is 1-tuple,
                # ('close_pct', frac) is 2-tuple,
                # ('open_leg2', lot, sl, tp) is 4-tuple.
                # Read payload fields only when the branch needs them.
                r_now_price = (bar_close - open_pos["entry"]) / max(1e-12, abs(open_pos["entry"] - open_pos["sl"]))
                if open_pos["side"] == "short":
                    r_now_price = -r_now_price
                if tag == "close_pct":
                    val = action[1]
                    orig_frac = float(val) * pos_rem
                    r_now = exit_obj.r_multiple
                    if exit_mode == "ladder":
                        # Ladder mode: backtester tracks realized_r mid-trade.
                        equity += orig_frac * r_now * risk_amount
                        # Commission (Phase 08 Step 2): each side pays per-lot fee.
                        # Closing a partial chunk incurs commission on that chunk.
                        if commission_per_side > 0:
                            equity -= commission_per_side * lot * float(val)
                        pos_rem *= max(0.0, 1.0 - float(val))
                        open_pos["pos_remaining"] = pos_rem
                        open_pos["realized_r"] = open_pos.get("realized_r", 0.0) + orig_frac * r_now
                    # scale_in / scale_in_middle: exit_obj tracks realized_r
                    # internally; equity is updated only on full close via
                    # the 'closed' branch below.
                    # scale_in mode: ScaleInExit tracks realized_r internally;
                    # equity is updated only on full close via the 'closed' branch below.
                elif tag == "move_sl":
                    # Preserve the original sl for journal accuracy — the BE rule
                    # overwrites it to entry, but downstream consumers (trade journal,
                    # journal.py stats_by_setup) need to know what SL the trade was
                    # actually opened with.
                    if "original_sl" not in open_pos:
                        open_pos["original_sl"] = float(open_pos["sl"])
                    open_pos["sl"] = float(action[1])
                elif tag == "open_leg2":
                    # Scale-in: register leg2 with given lot/sl/tp; no equity change.
                    # Action shape is ("open_leg2", lot, sl, tp) — a 4-tuple, so the
                    # extra fields live at action[1:].
                    leg2_lot, leg2_sl, leg2_tp = action[1], action[2], action[3]
                    open_pos["leg2"] = {
                        "lot": float(leg2_lot),
                        "sl": float(leg2_sl),
                        "tp": float(leg2_tp),
                        "entry_price": float(bar_close),
                    }
                elif tag == "close_leg2":
                    # Scale-in leg2 closure: realized_r already tracked inside exit_obj,
                    # so this tag is a no-op accounting-wise; PnL flows through close_pct
                    # and the existing 'closed' handler.
                    pass
                elif tag == "close_leg2_partial":
                    # Design B: 50% leg2 closed at TP1. realized_r already
                    # credited inside exit_obj; this just records the partial
                    # in the position dict for inspection.
                    open_pos["leg2_partial_closed"] = float(action[1])
                elif tag == "move_leg2_sl":
                    # Design B: move remaining leg2 SL up to lock profit.
                    if "leg2" in open_pos:
                        open_pos["leg2"]["sl"] = float(action[1])
                elif tag == "leg2_tp1":
                    # Design B: TP1 marker (informational; no accounting change).
                    open_pos["leg2_tp1_hit"] = True
                elif tag == "closed":
                    r_final = (
                        exit_obj.r_multiple
                    if exit_mode != "ladder"
                        else open_pos.get("realized_r", exit_obj.r_multiple)
                    )
                    pnl = r_final * risk_amount
                    trades.append({
                        "side": open_pos["side"],
                        "entry": open_pos["entry"],
                        "exit_price": bar_close,
                        "sl": open_pos.get("original_sl", open_pos["sl"]),
                        "lot": open_pos.get("lot"),
                        "sl_after_tp1": open_pos["sl"] if "original_sl" in open_pos else None,
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
                        "exit_reason": action[1] if len(action) > 1 else "",
                        "session": "london",
                        "timestamp_entry": open_pos.get("timestamp_entry"),
                        "timestamp_exit": str(ts),
                        "setup_type": "OB",
                    })
                    guard.record_trade(r_final)
                    # Apply final PnL to equity. Ladder mode already credited
                    # partial closes in the 'close_pct' branch above, so we add
                    # only the residual (r_final - open_pos.realized_r). The two
                    # scale_in* modes credit nothing during the trade, so we add
                    # the full r_final here.
                    prior_realized = (
                        open_pos.get("realized_r", 0.0)
                        if exit_mode == "ladder"
                        else 0.0
                    )
                    equity += (r_final - prior_realized) * risk_amount
                    # Commission on remaining position (Phase 08 Step 2).
                    # Partial closes already paid commission on closed chunks;
                    # this covers the final residual lot.
                    if commission_per_side > 0:
                        residual_frac = open_pos.get("pos_remaining", 1.0)
                        equity -= commission_per_side * lot * residual_frac
                    open_pos = None
                    break

        if open_pos is None:
            can_trade, _ = guard.can_trade(equity)
            if can_trade and entry_allowed:
                entry_info = check_entry(snapshot)
                if entry_info is not None:
                    risk_amount = account_size * risk_per_trade
                    sl_dist_price = abs(entry_info["entry"] - entry_info["sl"])
                    if sl_dist_price <= 0:
                        equity_curve.append((ts, equity))
                        continue
                    # calculate_lot expects sl_distance in PIPS, not price units.
                    # Without this conversion, lot is sized 10000x off for EURUSD
                    # (1 pip = 0.0001 price, smoke test passes 50 for 50-pip SL but
                    # runtime was passing 0.0050 = 50 pips in price = 50 / 0.0001 =
                    # 500 pips, causing lot to balloon from 1.10 to 11000).
                    sl_dist_pips = sl_dist_price / pip_size_for_pair(pair)
                    lot = calculate_lot(account_size, risk_per_trade, sl_dist_pips, pip_value)
                    # Execution costs (Phase 08 Step 2 — 2026-08-31).
                    # Spread applied to entry: long pays ask (mid+spread/2),
                    # short receives bid (mid-spread/2). Slippage applied
                    # as Gaussian pips added against the trader on both
                    # entry and exit (modeled on entry only here; SL/TP
                    # exits use bar_close which already approximates real fill).
                    if spread_pips > 0 or slippage_std > 0:
                        slip_pips = 0.0
                        if slippage_std > 0:
                            slip_pips = max(0.0, slippage_rng.normal(
                                slippage_mean, slippage_std
                            ))
                        total_pips = (spread_pips / 2.0) + slip_pips
                        price_offset = total_pips * pip_size_for_pair(pair)
                        if entry_info["side"] == "long":
                            entry_info = dict(entry_info)
                            entry_info["entry"] = entry_info["entry"] + price_offset
                            # SL hit harder when slippage pushes it
                            entry_info["sl"] = entry_info["sl"] - slip_pips * pip_size_for_pair(pair)
                        else:
                            entry_info = dict(entry_info)
                            entry_info["entry"] = entry_info["entry"] - price_offset
                            entry_info["sl"] = entry_info["sl"] + slip_pips * pip_size_for_pair(pair)
                    if exit_mode == "scale_in":
                        from scale_in_exit import ScaleInExit
                        leg2_tp1_r = strat_cfg.get("leg2_tp1_r", config.get("leg2_tp1_r"))
                        exit_obj = ScaleInExit(
                            entry=entry_info["entry"],
                            sl=entry_info["sl"],
                            side=entry_info["side"],
                            leg2_tp1_r=leg2_tp1_r,
                        )
                    elif exit_mode == "scale_in_middle":
                        from scale_in_middle_exit import ScaleInMiddleExit
                        exit_obj = ScaleInMiddleExit(
                            entry=entry_info["entry"],
                            sl=entry_info["sl"],
                            side=entry_info["side"],
                        )
                    elif exit_mode == "scale_in_middle_1r":
                        from scale_in_middle_1r_exit import ScaleInMiddle1RExit
                        exit_obj = ScaleInMiddle1RExit(
                            entry=entry_info["entry"],
                            sl=entry_info["sl"],
                            side=entry_info["side"],
                        )
                    else:
                        exit_obj = PartialTPExit(
                            entry=entry_info["entry"],
                            sl=entry_info["sl"],
                            side=entry_info["side"],
                            atr_buffer=sl_atr_buffer,
                            tp_stages=tp_stages,
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

    if open_pos is not None:
        last_ts = df_m15.index[-1]
        last_close = float(df_m15["close"].iloc[-1])
        exit_obj: PartialTPExit = open_pos["exit_obj"]
        actions = exit_obj.update(last_close)
        for action in actions:
            if action[0] == "closed":
                r_final = exit_obj.r_multiple
                pnl = r_final * open_pos["risk_amount"]
                # Commission (Phase 08 Step 2): time-close at end of data
                # closes any remaining position. pay commission on full lot
                # (no partial closes were tracked in this path).
                if commission_per_side > 0:
                    pnl = pnl - commission_per_side * open_pos.get("lot", 0.0)
                equity += pnl
                trades.append({
                    "pair": pair,
                    "side": open_pos["side"],
                    "entry": open_pos["entry"],
                    "exit_price": last_close,
                    "sl": open_pos.get("original_sl", open_pos["sl"]),
                    "lot": open_pos.get("lot"),
                    "sl_after_tp1": open_pos["sl"] if "original_sl" in open_pos else None,
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


if __name__ == "__main__":
    print("Running backtest smoke test on EURUSD …")
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
