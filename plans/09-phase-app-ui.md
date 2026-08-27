# Phase 8 — App UI ghép tất cả

## Mục tiêu

Mở `streamlit run app.py` thấy đầy đủ:
- Sidebar controls (pair, TF, params, filters)
- Top: 4 mini chart đa khung + bias panel
- Main: chart M15 với đầy đủ signal
- Bottom: results (metrics), equity curve, journal table với filter

## Task

### File: `app.py` hoàn chỉnh

```python
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import yaml

from src.data_loader import load_pair, load_multi_tf
from src.smc_signals import detect_all_signals
from src.bias_detector import detect_bias
from src.premium_discount import detect_premium_discount
from src.confluence import score_setup
from src.strategy import check_entry
from src.risk_manager import FTMOGuard, calculate_lot
from src.backtester import run_backtest, compute_metrics
from src.journal import Journal

# Load config
with open('config.yaml') as f:
    CONFIG = yaml.safe_load(f)

# Page config
st.set_page_config(layout="wide", page_title="SMC FTMO Backtester")

# === SIDEBAR ===
with st.sidebar:
    st.header("Settings")

    pair = st.selectbox("Pair", CONFIG['pairs'])
    timeframe = st.selectbox("Timeframe", CONFIG['timeframes'], index=3)

    st.subheader("SMC Params")
    swing_length = st.slider("Swing Length", 5, 50, CONFIG['strategy']['swing_length'])
    rr_target = st.slider("Risk:Reward", 1.0, 5.0, CONFIG['strategy']['rr_target'])
    displacement_thr = st.slider("Displacement ATR Mult", 1.0, 3.0, CONFIG['strategy']['displacement_atr_mult'])

    st.subheader("Filters")
    min_score = st.slider("Min Confluence Score", 1, 5, CONFIG['strategy']['min_confluence_score'])
    bias_filter = st.checkbox("Bias aligned only", True)
    sweep_filter = st.checkbox("Sweep clean only", False)
    pd_filter = st.checkbox("In P/D zone only", False)
    first_test_filter = st.checkbox("First test only", False)

    st.subheader("Risk")
    risk_pct = st.slider("Risk % per trade", 0.1, 2.0, CONFIG['risk']['per_trade_pct'] * 100) / 100
    max_trades = st.number_input("Max trades/day", 1, 10, CONFIG['risk']['max_trades_per_day'])
    daily_limit_r = st.number_input("Daily loss limit (R)", 1.0, 5.0, CONFIG['risk']['daily_loss_limit_r'])

    st.subheader("Backtest Period")
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start", datetime(2023, 1, 1))
    end_date = col2.date_input("End", datetime(2024, 12, 31))

    run_btn = st.button("Run Backtest", type="primary")

# === MAIN ===
st.title(f"SMC FTMO Backtester — {pair}")

# Load data
data = load_multi_tf(pair, ['D', 'H4', 'H1', 'M15'])

# === TOP: Multi-timeframe bias ===
st.subheader("Multi-Timeframe Bias")
cols = st.columns(4)
biases = {}
for col, tf in zip(cols, ['D', 'H4', 'H1', 'M15']):
    biases[tf] = detect_bias(data[tf], swing_length)
    with col:
        emoji = "🟢" if biases[tf] == 'bull' else "🔴" if biases[tf] == 'bear' else "⚪"
        st.metric(tf, f"{emoji} {biases[tf] or 'sideway'}")

can_trade = biases['D'] == biases['H4'] and biases['D'] is not None
if can_trade:
    st.success(f"✅ Trade direction: {biases['D'].upper()} only")
else:
    st.warning("⚠️ D và H4 không aligned → ĐỨNG NGOÀI")

# === MAIN CHART ===
st.subheader(f"{pair} {timeframe} with SMC Signals")

# Detect signals
signals = detect_all_signals(data[timeframe], swing_length, displacement_thr)

# Vẽ chart
fig = build_chart(data[timeframe], signals, pair)
st.plotly_chart(fig, use_container_width=True)

# === RESULTS (sau khi Run) ===
if run_btn:
    with st.spinner("Running backtest..."):
        trades, equity_curve = run_backtest(
            data['M15'], data['H4'], data['D'],
            swing_length, rr_target, displacement_thr,
            min_score, bias_filter, sweep_filter, pd_filter, first_test_filter,
            risk_pct, max_trades, daily_limit_r,
            start_date, end_date
        )

        metrics = compute_metrics(trades, equity_curve)

        # Save to journal
        journal = Journal()
        for t in trades:
            journal.insert_trade(t)

    # Display metrics
    st.subheader("Backtest Results")
    cols = st.columns(5)
    cols[0].metric("Trades", metrics['total_trades'])
    cols[1].metric("Winrate", f"{metrics['winrate']:.1f}%")
    cols[2].metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
    cols[3].metric("Max DD", f"{metrics['max_dd']:.1f}%")
    cols[4].metric("Expectancy", f"{metrics['avg_r']:.2f}R")

    # Equity curve
    st.plotly_chart(plot_equity(equity_curve), use_container_width=True)

# === JOURNAL TABLE ===
st.subheader("Journal (filterable)")
journal = Journal()

col1, col2, col3, col4 = st.columns(4)
filter_pair = col1.multiselect("Pair", CONFIG['pairs'])
filter_score = col2.slider("Min score", 1, 5, 1)
filter_win = col3.checkbox("Win only", False)
filter_lose = col4.checkbox("Lose only", False)

if st.button("Apply filter"):
    df = journal.query(
        pair=filter_pair[0] if filter_pair else None,
        min_score=filter_score,
        win_only=filter_win,
        lose_only=filter_lose,
    )
    st.dataframe(df, use_container_width=True)

    # Stats by setup
    st.subheader("Stats by Setup")
    st.dataframe(journal.stats_by_setup())
```

## Acceptance criteria

- [ ] Mở browser thấy đủ 4 mini chart + bias panel
- [ ] Chọn EURUSD → chart chính vẽ đúng
- [ ] Đổi swing_length slider → chart re-render nhanh (< 2s)
- [ ] Click Run Backtest → ra metrics + equity curve
- [ ] Filter journal theo pair/score/win/lose hoạt động
- [ ] Stats by setup hiển thị winrate theo từng setup + score
- [ ] Không có exception trên console
- [ ] UI responsive khi thu nhỏ/mở rộng browser
