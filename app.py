"""SMC FTMO Backtester — Streamlit UI.

Sidebar with all SMC params, 4 mini bias panel + bias verdict, main Plotly chart
with overlays (OB blue, FVG yellow, BOS green/red, sweep markers, displacement
highlights, P/D zones). Run Backtest button triggers full pipeline, persists to
SQLite journal, renders metrics, equity curve, journal table with filters.

Tooltips reference the 12-rule set the strategy implements. Warning banner
fires when winrate<45% or max DD>4% (FTMO 5% daily buffer).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

from src.data_loader import get_available_pairs, load_multi_tf_data
from src.bias_detector import (
    align_bias,
    detect_bias_multi_tf,
    is_bias_aligned,
    trade_direction,
)
from src.confluence import build_setup_dict, reasons_to_text, score_setup
from src.journal import Journal
from src.smc_engine.liquidity_pools import detect_liquidity_pools
from src.smc_engine.swings import detect_swings
from src.smc_signals import SMCSignals, calculate_atr, get_smc_overlays
from src.backtester import compute_metrics, run_backtest
from src.smc_engine.regime import detect_regime
from src.premium_discount import detect_premium_discount


CONFIG_PATH = Path("config.yaml")
RULE_TOOLTIPS = {
    "swing_length": "Rule 1 — Swing length for BOS/CHoCH structure (default 20).",
    "rr_target": "Rule 7 — Risk:Reward for full TP target (partial TP rules below).",
    "displacement_thr": "Rule 2 — Displacement: candle range > N×ATR (default 1.5).",
    "sweep_buf": "Rule 3 — Sweep sạch: price exceeds swing by N×ATR then closes back.",
    "min_score": "Rule 8 — Min confluence score to enter (default 4/5).",
    "risk_pct": "Rule 9 — Risk per trade: 0.55% FTMO default.",
    "max_trades": "Rule 9 — Max trades per day (FTMO default 3).",
    "daily_limit_r": "Rule 9 — Daily loss limit in R (FTMO default 2R).",
    "sl_buffer": "Rule 6 — SL placed below OB minus 0.2×ATR buffer.",
}


@st.cache_data(ttl=3600)
def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_multi_tf(pair: str) -> dict:
    return load_multi_tf_data(pair)


@st.cache_data(ttl=3600, show_spinner=False)
def _compute_overlays(
    pair: str, timeframe: str, start_iso: str, end_iso: str,
    swing_length: int, disp_atr: float, sweep_buf: float,
) -> dict:
    """Compute SMC overlays for the active chart slice. Cached by params."""
    data = load_multi_tf_data(pair)
    if not data or timeframe not in data:
        return {"bos": [], "choch": [], "fvg": [], "ob": [],
                "sweep": [], "displacement": []}
    df = data[timeframe]
    start_ts = pd.Timestamp(start_iso) if start_iso else df.index[0]
    end_ts = pd.Timestamp(end_iso) if end_iso else df.index[-1]

    # Fix tz mismatch (df.index is tz-aware e.g. Europe/London, start_ts from date_input is naive)
    tz = getattr(df.index, 'tz', None)
    if tz is not None:
        if getattr(start_ts, 'tzinfo', None) is None:
            start_ts = start_ts.tz_localize(tz)
        if getattr(end_ts, 'tzinfo', None) is None:
            end_ts = end_ts.tz_localize(tz)

    df_view = df[(df.index >= start_ts) & (df.index <= end_ts)].copy()
    det = SMCSignals(
        swing_length=swing_length,
        displacement_atr_mult=disp_atr,
        sweep_atr_buffer=sweep_buf,
    )
    return det.get_signals(df_view)


@st.cache_data(ttl=3600, show_spinner=False)
def _compute_liquidity_pools(
    pair: str,
    start_iso: str,
    end_iso: str,
    swing_length: int,
):
    data = load_multi_tf_data(pair)
    df = data.get("M15", pd.DataFrame())
    if df.empty:
        return {"pools": [], "levels": []}
    start_ts = pd.Timestamp(start_iso) if start_iso else df.index[0]
    end_ts = pd.Timestamp(end_iso) if end_iso else df.index[-1]
    tz = getattr(df.index, "tz", None)
    if tz is not None:
        if getattr(start_ts, "tzinfo", None) is None:
            start_ts = start_ts.tz_localize(tz)
        if getattr(end_ts, "tzinfo", None) is None:
            end_ts = end_ts.tz_localize(tz)
    df_view = df[(df.index >= start_ts) & (df.index <= end_ts)].copy()
    if df_view.empty:
        return {"pools": [], "levels": []}
    left = right = max(2, int(swing_length) // 2)
    atr = calculate_atr(df_view)
    swings = detect_swings(df_view, left=left, right=right)
    pools = detect_liquidity_pools(df_view, swings, atr)
    serialized_pools = [
        {
            "id": ev.id,
            "side": ev.side,
            "activation_ts": ev.activation_timestamp,
            "level_mean": ev.level_mean,
            "level_min": ev.level_min,
            "level_max": ev.level_max,
            "swept": ev.swept,
            "sweep_ts": ev.sweep_timestamp,
        }
        for ev in pools.events
    ]
    return {"pools": serialized_pools}


@st.cache_data(ttl=3600, show_spinner=False)
def _compute_regime_state(
    pair: str,
    start_iso: str,
    end_iso: str,
    swing_length: int,
    disp_atr: float,
    sweep_buf: float,
):
    data = load_multi_tf_data(pair)
    df = data.get("M15", pd.DataFrame())
    if df.empty:
        return None
    start_ts = pd.Timestamp(start_iso) if start_iso else df.index[0]
    end_ts = pd.Timestamp(end_iso) if end_iso else df.index[-1]
    tz = getattr(df.index, "tz", None)
    if tz is not None:
        if getattr(start_ts, "tzinfo", None) is None:
            start_ts = start_ts.tz_localize(tz)
        if getattr(end_ts, "tzinfo", None) is None:
            end_ts = end_ts.tz_localize(tz)
    df_view = df[(df.index >= start_ts) & (df.index <= end_ts)].copy()
    if df_view.empty:
        return None
    left = right = max(2, int(swing_length) // 2)
    return detect_regime(
        df_view,
        swing_left=left,
        swing_right=right,
        sweep_atr_buffer=float(sweep_buf),
        displacement_atr_mult=float(disp_atr),
    )
    return {"pools": serialized_pools}


def _mini_chart(df: pd.DataFrame, tf: str, pair: str) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title=f"{pair} {tf} — no data", height=220)
        return fig
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=tf,
        )
    )
    fig.update_layout(title=f"{pair} {tf}", height=220, margin=dict(l=10, r=10, b=10, t=30))
    return fig
def _mini_chart(df: pd.DataFrame, tf: str, pair: str) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title=f"{pair} {tf} — no data", height=220)
        return fig
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=tf,
        )
    )
    fig.update_layout(
        title=f"{pair} {tf}", height=220, margin=dict(l=0, r=0, t=30, b=0),
        xaxis_rangeslider_visible=False, showlegend=False,
    )
    return fig


def _bias_emoji(bias: str | None) -> str:
    return {"bull": "🟢", "bear": "🔴"}.get(bias or "", "⚪")


def _bias_label(bias: str | None) -> str:
    return {"bull": "Bull", "bear": "Bear"}.get(bias or "", "—")

def build_main_chart(
    df: pd.DataFrame, signals: dict, params: dict, pair: str, timeframe: str,
    liquidity: dict | None = None,
    pool_cap: int = 40,
) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title=f"{pair} {timeframe} — no data", height=600)
        return fig
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=pair,
        )
    )
    # --- Premium / Discount zones ---
    pd_state = detect_premium_discount(df, lookback=params.get("pd_lookback", 50))
    eq = pd_state["equilibrium"]
    fig.add_hline(y=eq, line=dict(color="orange", width=1, dash="dash"),
                  annotation_text="Equilibrium", annotation_position="right")
    fig.add_hrect(
        y0=pd_state["range_low"], y1=eq,
        fillcolor="rgba(0,200,0,0.04)", line_width=0, layer="below",
        annotation_text="Discount", annotation_position="top left",
    )
    fig.add_hrect(
        y0=eq, y1=pd_state["range_high"],
        fillcolor="rgba(200,0,0,0.04)", line_width=0, layer="below",
        annotation_text="Premium", annotation_position="top left",
    )
    OB_CAP, FVG_CAP, BOS_CAP, CHOCH_CAP, DISP_CAP = 60, 200, 100, 50, 200

    # Cap overlay counts to keep Plotly responsive. The engine can produce
    # thousands of FVGs / displacements on a 15 895-bar dataset, but the
    # visual chart only needs the most recent ones to convey structure.
    # The full signal set still drives run_backtest via _compute_overlays,
    # so this cap is purely cosmetic — it does NOT alter trade selection.
    view_start = df.index[0]
    view_end = df.index[-1]
    in_view = lambda sig: view_start <= getattr(sig, "timestamp", view_start) <= view_end
    active_obs = [o for o in signals.get("ob", []) if in_view(o) and not getattr(o, "mitigated", False)]
    for ob in active_obs[-OB_CAP:]:
        fig.add_shape(
            type="rect", x0=ob.timestamp, x1=df.index[-1],
            y0=ob.price * 0.999, y1=ob.price * 1.001,
            line=dict(color="rgba(0, 80, 255, 0.0)"),
            fillcolor="rgba(0, 80, 255, 0.25)", layer="below",
        )

    # --- Fair Value Gaps (yellow rectangles at actual price range) ---
    # Use the top/bottom prices of each FVG so candles aren't squashed by a
    # constant y=1.0 bar trace.
    active_fvgs = [f for f in signals.get("fvg", []) if in_view(f) and not getattr(f, "mitigated", False)]
    for fvg in active_fvgs[-FVG_CAP:]:
        top = getattr(fvg, "top", None)
        bottom = getattr(fvg, "bottom", None)
        if top is None or bottom is None:
            continue
        fig.add_shape(
            type="rect",
            x0=fvg.timestamp, x1=df.index[-1],
            y0=float(bottom), y1=float(top),
            line=dict(color="rgba(255, 215, 0, 0.0)"),
            fillcolor="rgba(255, 215, 0, 0.30)",
            layer="below",
        )
    # Single dummy trace so FVG still shows up in the legend with a swatch.
    if active_fvgs:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=12, symbol="square", color="rgba(255,215,0,0.6)"),
            name="FVG", showlegend=True, hoverinfo="skip",
        ))
    # --- BOS / CHoCH (vectorized scatter+text, no per-event add_annotation) ---
    bos_sigs = [s for s in signals.get("bos", []) if in_view(s)][-BOS_CAP:]
    bos_bull = [(s.timestamp, s.price) for s in bos_sigs if s.direction == "bullish"]
    bos_bear = [(s.timestamp, s.price) for s in bos_sigs if s.direction != "bullish"]
    if bos_bull:
        fig.add_trace(go.Scatter(
            x=[t for t, _ in bos_bull], y=[p for _, p in bos_bull],
            mode="markers+text", text=["▲"] * len(bos_bull),
            textposition="top center", textfont=dict(color="green", size=14),
            marker=dict(symbol="triangle-up", color="green", size=10),
            name="BOS ↑", showlegend=True, hoverinfo="skip",
        ))
    if bos_bear:
        fig.add_trace(go.Scatter(
            x=[t for t, _ in bos_bear], y=[p for _, p in bos_bear],
            mode="markers+text", text=["▼"] * len(bos_bear),
            textposition="bottom center", textfont=dict(color="red", size=14),
            marker=dict(symbol="triangle-down", color="red", size=10),
            name="BOS ↓", showlegend=True, hoverinfo="skip",
        ))
    choch_sigs = [s for s in signals.get("choch", []) if in_view(s)][-CHOCH_CAP:]
    ch_bull = [(s.timestamp, s.price) for s in choch_sigs if s.direction == "bullish"]
    ch_bear = [(s.timestamp, s.price) for s in choch_sigs if s.direction != "bullish"]
    if ch_bull:
        fig.add_trace(go.Scatter(
            x=[t for t, _ in ch_bull], y=[p for _, p in ch_bull],
            mode="text", text=["CH"] * len(ch_bull),
            textposition="top center", textfont=dict(color="lime", size=10),
            name="CHoCH ↑", showlegend=True, hoverinfo="skip",
        ))
    if ch_bear:
        fig.add_trace(go.Scatter(
            x=[t for t, _ in ch_bear], y=[p for _, p in ch_bear],
            mode="text", text=["CH"] * len(ch_bear),
            textposition="bottom center", textfont=dict(color="orangered", size=10),
            name="CHoCH ↓", showlegend=True, hoverinfo="skip",
        ))
    # Sweep markers: bull / bear into two Scatter traces (was 754 traces).
    sweep_bull_x, sweep_bull_y, sweep_bear_x, sweep_bear_y = [], [], [], []
    for sig in signals.get("sweep", []):
        if in_view(sig):
            if sig.direction == "bullish":
                sweep_bull_x.append(sig.timestamp); sweep_bull_y.append(sig.price)
            else:
                sweep_bear_x.append(sig.timestamp); sweep_bear_y.append(sig.price)
    if sweep_bull_x:
        fig.add_trace(go.Scatter(
            x=sweep_bull_x, y=sweep_bull_y, mode="markers",
            marker=dict(symbol="x", color="cyan", size=11),
            name="Sweep ↑", showlegend=True,
            hovertemplate="Sweep bull @ %{x}<br>price=%{y:.5f}<extra></extra>",
        ))
    if sweep_bear_x:
        fig.add_trace(go.Scatter(
            x=sweep_bear_x, y=sweep_bear_y, mode="markers",
            marker=dict(symbol="x", color="magenta", size=11),
            name="Sweep ↓", showlegend=True,
            hovertemplate="Sweep bear @ %{x}<br>price=%{y:.5f}<extra></extra>",
        ))
    # Displacement highlights: add a dummy trace so the legend still has the
    # "Displacement" swatch without forcing a fake y=1.0 bar that would
    # squash the candle y-axis.
    if signals.get("displacement"):
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(
                size=14, symbol="square",
                color="rgba(120,180,120,0.45)",
            ),
            name="Displacement", showlegend=True, hoverinfo="skip",
        ))
    # --- Premium / Discount zones ---
    pd_state = detect_premium_discount(df, lookback=params.get("pd_lookback", 50))
    eq = pd_state["equilibrium"]
    fig.add_hline(y=eq, line=dict(color="orange", width=1, dash="dash"),
                  annotation_text="Equilibrium", annotation_position="right")
    fig.add_hrect(
        y0=pd_state["range_low"], y1=eq,
        fillcolor="rgba(0,200,0,0.04)", line_width=0, layer="below",
        annotation_text="Discount", annotation_position="top left",
    )
    fig.add_hrect(
        y0=eq, y1=pd_state["range_high"],
        fillcolor="rgba(200,0,0,0.04)", line_width=0, layer="below",
        annotation_text="Premium", annotation_position="top left",
    )

    # --- Liquidity Pools (EQH / EQL) ---------------------------------------
    # Cap the visible pool count so the chart stays responsive on the
    # full dataset. The backtester and regime engine still see the full
    # pool list; this only affects the visual overlay.
    pool_cap = max(0, int(params.get("pool_cap", 40)))
    pools = (liquidity or {}).get("pools", []) if liquidity else []
    pools = pools[-pool_cap:] if pool_cap and pools else []
    last_ts = df.index[-1]
    if pools:
        for pool in pools:
            activation_ts = pool["activation_ts"]
            side = pool["side"]
            level_low = pool["level_min"]
            level_high = pool["level_max"]
            color = (
                "rgba(0, 200, 200, 0.20)" if side == "high"
                else "rgba(200, 0, 200, 0.20)"
            )
            edge = (
                "rgba(0, 200, 200, 0.85)" if side == "high"
                else "rgba(200, 0, 200, 0.85)"
            )
            fig.add_shape(
                type="rect",
                x0=activation_ts, x1=last_ts,
                y0=level_low, y1=level_high,
                fillcolor=color, line=dict(color=edge, width=1),
                layer="below",
            )
        sweep_bull_x, sweep_bull_y, sweep_bear_x, sweep_bear_y = [], [], [], []
        for pool in pools:
            if not pool["swept"] or pool["sweep_ts"] is None:
                continue
            ts = pool["sweep_ts"]
            price = pool["level_mean"]
            if pool["side"] == "high":
                sweep_bull_x.append(ts); sweep_bull_y.append(price)
            else:
                sweep_bear_x.append(ts); sweep_bear_y.append(price)
        if sweep_bull_x:
            fig.add_trace(go.Scatter(
                x=sweep_bull_x, y=sweep_bull_y, mode="markers",
                marker=dict(symbol="diamond", color="teal", size=10),
                name="EQH Pool swept", showlegend=True,
                hovertemplate="EQH sweep @ %{x}<br>level=%{y:.5f}<extra></extra>",
            ))
        if sweep_bear_x:
            fig.add_trace(go.Scatter(
                x=sweep_bear_x, y=sweep_bear_y, mode="markers",
                marker=dict(symbol="diamond", color="purple", size=10),
                name="EQL Pool swept", showlegend=True,
                hovertemplate="EQL sweep @ %{x}<br>level=%{y:.5f}<extra></extra>",
            ))

    fig.update_layout(
        title=f"{pair} {timeframe} — SMC overlays",
        xaxis_rangeslider_visible=False, height=1000,
        autosize=True,
        legend=dict(
            orientation="h",
            bordercolor="rgba(0,0,0,0.1)",
            borderwidth=1,
            itemclick="toggle",
            itemdoubleclick="toggleothers",
            groupclick="toggleitem",
            tracegroupgap=4,
        ),
        margin=dict(l=60, r=40, t=80, b=60),
        hovermode="closest",
        modebar=dict(
            orientation="h",
            bgcolor="rgba(255,255,255,0.7)",
            color="#444",
            activecolor="#007bff",
            add=["zoom2d", "pan2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d"],
        ),
    )
    fig.update_xaxes(fixedrange=False)
    fig.update_yaxes(fixedrange=False)
    return fig


def _plot_equity(equity_curve: list) -> go.Figure:
    if not equity_curve:
        return go.Figure().update_layout(title="Equity curve (no data)", height=300)
    ts, eq = zip(*equity_curve)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(ts), y=list(eq), mode="lines", name="Equity"))
    fig.update_layout(title="Equity Curve", height=300, xaxis_title="Time", yaxis_title="USD")
    return fig

def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%" if x <= 1.5 else f"{x:.1f}%"


# ============================================================================
#                              STREAMLIT APP
# ============================================================================

st.set_page_config(layout="wide", page_title="SMC FTMO Backtester")
CONFIG = _load_config()
risk_cfg = CONFIG.get("risk", {})
strat_cfg = CONFIG.get("strategy", {})

# -------------------- SIDEBAR --------------------
# Pair + timeframe need to be picked before loading data, so they live in a
# compact sidebar block at the top. The remaining widgets (SMC params,
# filters, risk, period, Run Backtest) render after data is loaded so they
# can drive defaults from the selected timeframe's parquet range.
with st.sidebar:
    st.header("Settings")
    pairs = get_available_pairs()
    pair = st.selectbox("Pair", pairs, help="Symbol under test (EURUSD default).")
    timeframes = ["D", "H4", "H1", "M15"]
    timeframe = st.selectbox("Timeframe", timeframes, index=3,
                             help="Chart timeframe for the main panel.")

# -------------------- LOAD DATA --------------------
data = _cached_multi_tf(pair)
if not data:
    st.error(f"No data files for {pair}. Run download_data first.")
    st.stop()

if timeframe not in data:
    timeframe = "M15" if "M15" in data else next(iter(data.keys()))

data_range = data[timeframe].index
data_start = data_range.min().date()
data_end = data_range.max().date()

# -------------------- SIDEBAR (remaining widgets) --------------------

# Pair / timeframe were picked above; rest of widgets live here so they
# can use data_start / data_end from the loaded parquet range.
with st.sidebar:
    st.subheader("SMC Params")
    swing_length = st.slider("Swing length", 5, 50,
                             strat_cfg.get("swing_length", 10),
                             help=RULE_TOOLTIPS["swing_length"])
    # TP profile replaces the legacy single rr_target slider. The ladder
    # maps each preset to (r_multiple, close_pct_of_remaining) tuples,
    # passed via run_cfg["strategy"]["partial_tp"] into backtester.
    tp_profiles = {
        "Conservative (2R/3R/4R)": (
            {"pct": 0.40, "r": 2.0},
            {"pct": 0.50, "r": 3.0},
            {"pct": 1.00, "r": 4.0},
        ),
        "Balanced (3R/5R/8R)": (
            {"pct": 0.40, "r": 3.0},
            {"pct": 0.50, "r": 5.0},
            {"pct": 1.00, "r": 8.0},
        ),
    }
    tp_profile = st.selectbox("TP profile", list(tp_profiles.keys()), index=0)
    partial_tp = list(tp_profiles[tp_profile])

    displacement_thr = st.slider("Displacement ATR mult", 1.0, 3.0,
                                 float(strat_cfg.get("displacement_atr_mult", 1.5)),
                                 help=RULE_TOOLTIPS["displacement_thr"])
    sweep_buf = st.slider("Sweep ATR buffer", 0.0, 0.30, 0.05, 0.01,
                          help=RULE_TOOLTIPS["sweep_buf"])
    pd_lookback = st.slider("P/D lookback", 20, 200, 50,
                            help="Swing lookback for premium/discount equilibrium.")

    st.subheader("Confluence")
    min_score = st.slider("Min confluence score", 1, 5,
                          int(strat_cfg.get("min_confluence_score", 4)),
                          help=RULE_TOOLTIPS["min_score"])
    bias_mode = st.selectbox(
        "Bias mode",
        ["strict (D+H4)", "h4_only", "any"],
        index=0,
        help=(
            "strict = D+H4 cùng chiều (Rule 1 truyền thống). "
            "h4_only = theo H4 khi D neutral; chặn counter-trend. "
            "any = trade theo bất kỳ TF nào (nới lỏng)."
        ),
    )
    # Auto regime is structure-aware: recent BOS/CHoCH/sweep densities decide
    # whether breakers are trusted. Mixed stays conservative and keeps OB-classic.
    regime_mode = st.selectbox(
        "Regime mode (breakers)",
        ["off", "on", "auto"],
        index=0,
        help=(
            "off = baseline OB-classic only. on = always layer breaker "
            "zones. auto = use recent BOS/CHoCH/sweep structure to decide "
            "whether breakers should participate."
        ),
    )
    promotion_lookback = st.slider(
        "Breaker promotion lookback",
        10, 200, 50, 5,
        help="Max bars between OB origin and CHoCH for breaker promotion.",
    )
    # Filters removed: sweep_clean, in_PD_zone, first_test are redundant or
    # anti-edge on EURUSD M15 (verified empirically). Confluence score and
    # OB lifecycle already enforce the underlying logic.
    sweep_filter = False
    pd_filter = False
    first_test_filter = False
    bias_filter = bias_mode in ("strict (D+H4)", "h4_only")
    st.subheader("Risk (FTMO)")
    risk_pct = st.slider("Risk % per trade", 0.1, 2.0,
                         float(risk_cfg.get("per_trade_pct", 0.0055)) * 100, 0.05,
                         help=RULE_TOOLTIPS["risk_pct"]) / 100.0
    max_trades = st.number_input("Max trades/day", 1, 10,
                                 int(risk_cfg.get("max_trades_per_day", 3)),
                                 help=RULE_TOOLTIPS["max_trades"])
    daily_limit_r = st.number_input("Daily loss limit (R)", 1.0, 5.0,
                                    float(risk_cfg.get("daily_loss_limit_r", 2.0)), 0.5,
                                    help=RULE_TOOLTIPS["daily_limit_r"])
    sl_buffer = st.slider("SL ATR buffer below OB", 0.0, 1.0, 0.2, 0.05,
                          help=RULE_TOOLTIPS["sl_buffer"])

    st.subheader("Period")
    col_a, col_b = st.columns(2)
    start_date = col_a.date_input("Start", value=data_start,
                                  min_value=data_start, max_value=data_end,
                                  help="Inclusive start date for the backtest window.")
    end_date = col_b.date_input("End", value=data_end,
                                min_value=data_start, max_value=data_end,
                                help="Inclusive end date for the backtest window.")

    run_btn = st.button("Run Backtest", type="primary",
                        help="Run full pipeline on selected pair/timeframe.")
# -------------------- TOP: 4 mini charts + bias panel --------------------
st.subheader("Multi-Timeframe Bias")
biases = detect_bias_multi_tf(data, swing_length=swing_length)
cols = st.columns(4)
for col, tf in zip(cols, ["D", "H4", "H1", "M15"]):
    with col:
        b = biases.get(tf)
        st.metric(tf, f"{_bias_emoji(b)} {_bias_label(b)}")

verdict = align_bias(biases)
direction = trade_direction(biases)
if verdict == "aligned_long":
    st.success(f"✅ Trade direction: LONG only (D+H4 aligned bull)")
elif verdict == "aligned_short":
    st.error(f"✅ Trade direction: SHORT only (D+H4 aligned bear)")
else:
    st.warning("⚠️ D và H4 không aligned → ĐỨNG NGOÀI (stand aside)")

regime_state = _compute_regime_state(
    pair,
    str(start_date) if start_date else "",
    str(end_date) if end_date else "",
    swing_length,
    displacement_thr,
    sweep_buf,
)

if regime_state is None:
    st.info("Regime auto: unavailable for the selected window.")
else:
    regime_cols = st.columns(4)
    regime_cols[0].metric("Regime auto", regime_state.regime)
    regime_cols[1].metric("Continuation", f"{regime_state.trend_strength:.2f}")
    regime_cols[2].metric("Range pressure", f"{regime_state.choppiness:.2f}")
    regime_cols[3].metric("Breaker weight", f"{regime_state.breaker_weight:.0%}")
    st.caption(regime_state.explanation)

# 4 mini charts in a row
mini_cols = st.columns(4)
for col, tf in zip(mini_cols, ["D", "H4", "H1", "M15"]):
    with col:
        tf_df = data.get(tf, pd.DataFrame())
        st.plotly_chart(_mini_chart(tf_df.tail(120), tf, pair),
                        use_container_width=True, key=f"mini_{tf}_{pair}")
# -------------------- MAIN CHART --------------------

with st.expander("Chart tips & shortcuts (Plotly)", expanded=False):
    st.markdown(
        """
        - **Drag**: Box zoom — draw a rectangle to zoom in.
        - **Pan / Move**: click the **Pan** button on the toolbar, then drag.
        - **Zoom in / out**: scroll wheel on the chart.
        - **Auto-fit axes**: click **Reset Axes** in the toolbar, or double-click.
        - **Toggle overlays**: single-click an item in the legend to hide it; double-click to isolate it.
        - **Save view**: right-click the chart → *Download plot as PNG*.
        """
    )
_CHART_MAX_BARS_DEFAULT = 400
main_df = data[timeframe]
if start_date and end_date:
    try:
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        main_df_view = main_df[(main_df.index >= start_ts) & (main_df.index < end_ts)]
    except Exception:
        main_df_view = main_df.tail(500)
else:
    main_df_view = main_df.tail(500)
col_pool, col_bars = st.columns(2)
with col_pool:
    pool_cap = st.slider(
        "EQH/EQL pools visible",
        min_value=0, max_value=80, step=4, value=8,
        help="0 = hide pools, 80 = show all. Use a small value when many bars are visible.",
    )
with col_bars:
    chart_view_limit = st.number_input(
        "Visible bars per slice",
        min_value=150, max_value=3000, step=50,
        value=int(st.session_state.get("chart_max_bars", _CHART_MAX_BARS_DEFAULT)),
        key="chart_max_bars_input",
        help="Lower = zoom in. Higher = see more bars but smaller candles.",
    )
st.session_state["chart_max_bars"] = int(chart_view_limit)
CHART_MAX_BARS = int(chart_view_limit)
if len(main_df_view) > CHART_MAX_BARS:
    main_df_view = main_df_view.tail(CHART_MAX_BARS)
signals = _compute_overlays(
    pair, timeframe,
    str(start_date) if start_date else "",
    str(end_date) if end_date else "",
    swing_length, displacement_thr, sweep_buf,
)
liquidity_overlays = _compute_liquidity_pools(
    pair,
    str(start_date) if start_date else "",
    str(end_date) if end_date else "",
    swing_length,
)
main_chart_params = {"pd_lookback": int(pd_lookback), "pool_cap": int(pool_cap)}
st.plotly_chart(
    build_main_chart(main_df_view, signals, main_chart_params, pair, timeframe, liquidity_overlays, pool_cap=int(pool_cap)),
    use_container_width=True,
    key=f"main_chart_{pair}_{timeframe}_{swing_length}",
)
st.subheader("Backtest Results")
run_cfg = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": float(daily_limit_r),
             "max_open_positions": 1},
    "strategy": {
        "swing_length": int(swing_length),
        "rr_target": float(partial_tp[-1]["r"]),
        "displacement_atr_mult": float(displacement_thr),
        "sweep_atr_buffer": float(sweep_buf),
        "min_confluence_score": int(min_score),
        "require_displacement": True, "require_bias_aligned": bias_filter,
        "sl_atr_buffer": float(sl_buffer),
        "bias_mode": "strict" if bias_mode == "strict (D+H4)" else bias_mode,
        "regime_mode": regime_mode,
        "promotion_lookback_bars": int(promotion_lookback),
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": sweep_filter, "pd": pd_filter, "first_test": first_test_filter},
    "start_date": str(start_date) if start_date else "",
    "end_date": str(end_date) if end_date else "",
    "pd_lookback": int(pd_lookback),
}

if run_btn:
    with st.spinner("Running backtest..."):
        try:
            trades, equity_curve = run_backtest(pair=pair, config=run_cfg)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            trades, equity_curve = [], []

    st.session_state["last_trades"] = trades
    st.session_state["last_equity"] = equity_curve
    st.session_state["last_pair"] = pair
    if trades:
        try:
            journal = Journal()
            cleared = journal.clear(pair=pair)
            inserted = journal.insert_many(trades)
            st.success(
                f"Cleared {cleared} old {pair} trades, inserted {inserted} new trades."
            )
        except Exception as exc:
            st.warning(f"Journal write skipped: {exc}")
    else:
        try:
            cleared = Journal().clear(pair=pair)
            if cleared:
                st.info(f"No new trades — cleared {cleared} old {pair} journal entries.")
        except Exception:
            pass
trades = st.session_state.get("last_trades") or []
equity_curve = st.session_state.get("last_equity") or []
metrics = compute_metrics(trades, equity_curve)

m_cols = st.columns(6)
m_cols[0].metric("Trades", metrics.get("total_trades", 0))
m_cols[1].metric("Winrate", _fmt_pct(metrics.get("winrate", 0.0)))
m_cols[2].metric("Profit Factor", f"{metrics.get('profit_factor', 0):.2f}")
m_cols[3].metric("Avg R", f"{metrics.get('avg_r', 0):.2f}R")
m_cols[4].metric("Total R", f"{metrics.get('total_r', 0):.1f}R")
m_cols[5].metric("Max DD",
                 f"{metrics.get('max_dd_pct', metrics.get('max_dd', 0) * 100):.2f}%")

wr = metrics.get("winrate", 0.0)
max_dd_pct = metrics.get("max_dd_pct", metrics.get("max_dd", 0) * 100)
if trades and wr < 0.45:
    st.warning(f"⚠️ Winrate {wr*100:.1f}% < 45% — review rules or data quality.")
if trades and max_dd_pct > 4.0:
    st.warning(f"⚠️ Max DD {max_dd_pct:.2f}% > 4% — close to FTMO 5% daily limit.")

if equity_curve:
    st.plotly_chart(_plot_equity(equity_curve), use_container_width=True,
                    key="equity_curve")

# -------------------- JOURNAL --------------------
st.subheader("Journal — Filterable")

try:
    journal_df = Journal().query()
except Exception as exc:
    st.error(f"Journal read failed: {exc}")
    journal_df = pd.DataFrame()

if journal_df.empty:
    st.info("No trades in journal yet. Click **Run Backtest** to populate.")
else:
    f1, f2, f3, f4, f5 = st.columns(5)
    jpair = f1.multiselect("Pair", sorted(journal_df["pair"].unique()))
    jmin = f2.slider("Min score", 1, 5, 1)
    jmax = f3.slider("Max score", 1, 5, 5)
    jside = f4.selectbox("Side", ["all", "long", "short"])
    jsession = f5.selectbox("Session",
                            ["all"] + sorted(journal_df["session"].dropna().unique().tolist()))

    jwin = st.checkbox("Win only", False)
    jlose = st.checkbox("Lose only", False)

    filtered = journal_df.copy()
    if jpair:
        filtered = filtered[filtered["pair"].isin(jpair)]
    filtered = filtered[(filtered["confluence_score"] >= jmin) &
                        (filtered["confluence_score"] <= jmax)]
    if jside != "all":
        filtered = filtered[filtered["side"] == jside]
    if jsession != "all":
        filtered = filtered[filtered["session"] == jsession]
    if jwin:
        filtered = filtered[filtered["r_multiple"] > 0]
    if jlose:
        filtered = filtered[filtered["r_multiple"] < 0]

    st.dataframe(
        filtered[["timestamp_entry", "pair", "side", "entry", "sl", "exit_price",
                  "r_multiple", "pnl_usd", "confluence_score", "bias_d", "bias_h4",
                  "displacement", "sweep_clean", "premium_discount", "first_test",
                  "session", "is_partial", "exit_reason"]]
        if not filtered.empty else filtered,
        use_container_width=True, height=320,
    )

    st.markdown("##### Stats by Setup")
    try:
        st.dataframe(Journal().stats_by_setup(), use_container_width=True)
    except Exception as exc:
        st.warning(f"stats_by_setup failed: {exc}")

# -------------------- FOOTER --------------------
st.caption(
    "Rules — Required: 1) Bias mode (strict/h4_only/any) · 2) BOS/CHoCH on M15 · "
    "3) Displacement · 4) OB unmitigated (auto first-test) · "
    "5) Confluence ≥ min_score · 6) SL = OB edge ± ATR buffer · "
    "7) Partial TP per profile, BE on TP1 · "
    "8) Regime mode (off/on/auto, Plan 14) — breaker overlay when on/auto · "
    "9) Risk 0.55%/trade, max 3/day, -2R daily stop, FTMO 5%/10% guard · "
    "10) Journal every trade."
)
