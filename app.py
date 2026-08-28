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
from src.premium_discount import detect_premium_discount, pd_annotations
from src.smc_signals import SMCSignals, calculate_atr, get_smc_overlays
from src.backtester import compute_metrics, run_backtest


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

    # --- Order Blocks (blue rectangles, mitigation-aware) ---
    for ob in signals.get("ob", []):
        if getattr(ob, "mitigated", False):
            continue
        fig.add_shape(
            type="rect", x0=ob.timestamp, x1=df.index[-1],
            y0=ob.price * 0.999, y1=ob.price * 1.001,
            line=dict(color="rgba(0, 80, 255, 0.0)"),
            fillcolor="rgba(0, 80, 255, 0.25)", layer="below",
        )

    # --- Fair Value Gaps (yellow rectangles) ---
    for fvg in signals.get("fvg", []):
        if getattr(fvg, "mitigated", False):
            continue
        fig.add_shape(
            type="rect", x0=fvg.timestamp, x1=df.index[-1],
            y0=fvg.price * 0.9995, y1=fvg.price * 1.0005,
            line=dict(color="rgba(0,0,0,0)"),
            fillcolor="rgba(255, 215, 0, 0.30)", layer="below",
        )

    # --- BOS / CHoCH arrows ---
    for sig in signals.get("bos", []):
        col = "green" if sig.direction == "bullish" else "red"
        fig.add_annotation(
            x=sig.timestamp, y=sig.price,
            text="▲" if sig.direction == "bullish" else "▼",
            showarrow=True, arrowhead=2, arrowcolor=col, font=dict(color=col, size=14),
        )
    for sig in signals.get("choch", []):
        col = "lime" if sig.direction == "bullish" else "orangered"
        fig.add_annotation(
            x=sig.timestamp, y=sig.price, text="CH",
            showarrow=False, font=dict(color=col, size=10),
        )

    # --- Sweep markers ---
    for sig in signals.get("sweep", []):
        col = "cyan" if sig.direction == "bullish" else "magenta"
        fig.add_trace(
            go.Scatter(
                x=[sig.timestamp], y=[sig.price], mode="markers",
                marker=dict(symbol="x", color=col, size=11),
                name="Sweep", showlegend=False,
                hovertemplate="Sweep %s @ %s<br>price=%.5f<extra></extra>"
                % (sig.direction, sig.timestamp, sig.price),
            )
        )

    # --- Displacement highlights (large green/red candles outline) ---
    if signals.get("displacement"):
        disp_ts = [s.timestamp for s in signals["displacement"]]
        disp_col = [
            "rgba(0,200,0,0.10)" if s.direction == "bullish" else "rgba(200,0,0,0.10)"
            for s in signals["displacement"]
        ]
        fig.add_trace(
            go.Bar(
                x=disp_ts, y=[1] * len(disp_ts), marker_color=disp_col,
                opacity=0.25, name="Displacement", showlegend=True,
                hoverinfo="skip",
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

    fig.update_layout(
        title=f"{pair} {timeframe} — SMC overlays",
        xaxis_rangeslider_visible=False, height=620,
        legend=dict(orientation="h", y=1.02, x=0),
    )
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

st.title("SMC FTMO Backtester")

# -------------------- SIDEBAR --------------------
with st.sidebar:
    st.header("Settings")
    pairs = get_available_pairs()
    pair = st.selectbox("Pair", pairs, help="Symbol under test (EURUSD default).")
    timeframes = ["D", "H4", "H1", "M15"]
    timeframe = st.selectbox("Timeframe", timeframes, index=3,
                             help="Chart timeframe for the main panel.")

    st.subheader("SMC Params")
    swing_length = st.slider("Swing length", 5, 50,
                             strat_cfg.get("swing_length", 10),
                             help=RULE_TOOLTIPS["swing_length"])
    rr_target = st.slider("Risk:Reward", 1.0, 6.0,
                          float(strat_cfg.get("rr_target", 2.5)),
                          help=RULE_TOOLTIPS["rr_target"])
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
    bias_filter = st.checkbox("Bias aligned only", True,
                              help="Rule 1 — only trade when D+H4 agree.")
    sweep_filter = st.checkbox("Sweep clean only", False,
                               help="Rule 3 — filter setups with clean liquidity sweep.")
    pd_filter = st.checkbox("In P/D zone only", False,
                            help="Rule 4 — long only in discount, short only in premium.")
    first_test_filter = st.checkbox("First test only", False,
                                    help="Rule 5 — only enter on first touch of OB/FVG.")

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
    start_date = col_a.date_input("Start", value=pd.Timestamp("2023-01-01").date())
    end_date = col_b.date_input("End", value=pd.Timestamp("2024-12-31").date())

    run_btn = st.button("Run Backtest", type="primary",
                        help="Run full pipeline on selected pair/timeframe.")

# -------------------- LOAD DATA --------------------
data = _cached_multi_tf(pair)
if not data:
    st.error(f"No data files for {pair}. Run download_data first.")
    st.stop()

if timeframe not in data:
    timeframe = "M15" if "M15" in data else next(iter(data.keys()))

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

# 4 mini charts in a row
mini_cols = st.columns(4)
for col, tf in zip(mini_cols, ["D", "H4", "H1", "M15"]):
    with col:
        tf_df = data.get(tf, pd.DataFrame())
        st.plotly_chart(_mini_chart(tf_df.tail(120), tf, pair),
                        use_container_width=True, key=f"mini_{tf}_{pair}")

# -------------------- MAIN CHART --------------------
st.subheader(f"{pair} {timeframe} — SMC Overlays")

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

signals = _compute_overlays(
    pair, timeframe,
    str(start_date) if start_date else "",
    str(end_date) if end_date else "",
    swing_length, displacement_thr, sweep_buf,
)
fig = build_main_chart(main_df_view, signals, {"pd_lookback": pd_lookback}, pair, timeframe)
st.plotly_chart(fig, use_container_width=True, key=f"main_{pair}_{timeframe}_{swing_length}")

# -------------------- BACKTEST --------------------
st.subheader("Backtest Results")

run_cfg = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "max_total_loss": 0.10, "timezone": "Europe/Paris"},
    "risk": {"per_trade_pct": risk_pct, "max_trades_per_day": int(max_trades),
             "daily_loss_limit_r": float(daily_limit_r),
             "max_open_positions": 1},
    "strategy": {
        "swing_length": int(swing_length), "rr_target": float(rr_target),
        "displacement_atr_mult": float(displacement_thr),
        "sweep_atr_buffer": float(sweep_buf),
        "min_confluence_score": int(min_score),
        "require_displacement": True, "require_bias_aligned": bias_filter,
        "sl_atr_buffer": float(sl_buffer),
        "partial_tp": [
            {"pct": 0.40, "r": 2.0, "move_sl_to": "entry"},
            {"pct": 0.30, "r": 3.0, "move_sl_to": "entry"},
            {"pct": 0.30, "r": 4.0, "move_sl_to": "entry"},
        ],
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
    "Rules: 1) Bias from D+H4 aligned · 2) Displacement > 1.5×ATR · 3) Sweep clean · "
    "4) Premium/Discount zone · 5) First test · 6) SL = OB - 0.2×ATR · "
    "7) Entry confluence ≥ 4/5 · 8) Partial TP 40/30/30 with BE at 2R · "
    "9) Risk 0.55%, max 3 trades/day, -2R daily stop · "
    "10) FTMO 5% daily / 10% total guard · 11) Session filter (LDN/NY) · "
    "12) Journal every trade."
)
