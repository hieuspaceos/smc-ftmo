"""Backtest driven by smc_bot_signal.SignalEngine — same engine the live
Mac-mini bot uses to detect entries.

Replay approach:
  - Sliding window over ``data/eurusd_m15.parquet`` (2016-01-03 → 2026-08-21).
  - Every STEP_BARS, call ``Watcher._tick_symbol`` against ``InMemoryFeed``
    which returns ``df.iloc[:i].tail(history_bars)`` so ``SignalEngine.scan``
    sees the same context the live bot would at that timestamp.
  - Each new (un-deduped) ``AlertPayload`` opens a position simulated by
    ``ScaleInExit`` (Design A — 2R/4R) walked bar-by-bar until ``closed``.
  - Trades + equity curve + metrics dumped to JSON/CSV.

This is NOT identical to ``scripts/btest_scale_in.py``:
  - Bot uses swing_left/right=5/5; baseline uses swing_length=10.
  - Bot emits only ``chart_qualified``; baseline scans every BOS event.
  - Bot always allows first_test + pd_zone but not sweep; baseline honors
    ``filters.sweep``/``pd``/``first_test`` config.
  - Replay window: every STEP_BARS (default 100 = ~25h M15) — entries
    within the window may be missed.

Window: 2016-01-01 → 2026-08-21 (same as baseline scripts).

Run from repo root:
    PYTHONPATH=src:packages/smc_engine/src:packages/smc_bot_core/src:\
packages/smc_bot_webhook/src:packages/smc_bot_signal/src \
    python -m scripts.btest_signal_engine
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

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

from smc_bot_signal.config import SignalBotConfig  # noqa: E402
from smc_bot_signal.data_feed import InMemoryFeed  # noqa: E402
from smc_bot_signal.notify import LoggingNotifier  # noqa: E402
from smc_bot_signal.signal_engine import SignalEngine  # noqa: E402
from smc_bot_signal.state import SignalStateStore  # noqa: E402
from smc_bot_signal.watcher import Watcher  # noqa: E402

# --- Config — match the LOOSENED values from config.yaml (2026-09-03) ------
PAIR = "EURUSD"
PIP_SIZE = 0.0001
WINDOW_START = pd.Timestamp("2016-01-01", tz="UTC")
WINDOW_END = pd.Timestamp("2026-08-21 23:59:59", tz="UTC")
STEP_BARS = 100             # ~25h M15 between engine scans
HISTORY_BARS = 500          # bot default
RISK_PCT = 0.0055           # FTMO default 0.55%
ACCOUNT_SIZE = 100_000.0

OUT_DIR = ROOT / "output" / "backtest_signal_engine_eurusd"


# --- Helpers ----------------------------------------------------------------

@dataclass
class SimTrade:
    signal_id: str
    symbol: str
    side: str
    entry_time: pd.Timestamp
    entry: float
    sl: float
    tp_at_2r: float
    tp_at_4r: float
    exit_time: pd.Timestamp | None = None
    exit_reason: str = ""
    r_multiple: float = 0.0
    pnl_dollar: float = 0.0


@dataclass
class EquityPoint:
    ts: pd.Timestamp
    equity: float


@dataclass
class BacktestResult:
    trades: list[SimTrade] = field(default_factory=list)
    equity: list[EquityPoint] = field(default_factory=list)
    elapsed_s: float = 0.0


def _compute_metrics(trades: list[SimTrade], equity: list[EquityPoint]) -> dict:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate_pct": 0.0,
            "avg_r": 0.0,
            "total_r": 0.0,
            "profit_factor": 0.0,
            "max_dd_pct": 0.0,
            "final_equity": ACCOUNT_SIZE,
        }
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
    }


def _exit_trade(
    trade: SimTrade, future_bars: pd.DataFrame, start_equity: float,
) -> float:
    """Walk ScaleInExit across future bars; return realized R and update trade.

    Returns the realized R so caller can compound equity.
    """
    pos = ScaleInExit(
        entry=trade.entry, sl=trade.sl, side=trade.side,
        scale_in_r=2.0, final_tp_r=4.0, leg2_lot=0.5,
        leg2_tp1_r=None,  # Design A
    )
    realized_r = 0.0
    exit_ts: pd.Timestamp | None = None
    exit_reason = ""
    for ts, row in future_bars.iterrows():
        # Use bar high/low extremes before close — pessimistic for SL, optimistic for TP.
        # Per ScaleInExit spec: SL hit triggers immediately on low/high touch.
        high = float(row["high"])
        low = float(row["low"])
        # Check SL first on the adverse extreme.
        sl_hit = (
            (trade.side == "long" and low <= trade.sl + 1e-9)
            or (trade.side == "short" and high >= trade.sl - 1e-9)
        )
        # Use close for progression (matches ScaleInExit.update(current_price)).
        close = float(row["close"])
        actions = pos.update(close)
        if sl_hit and not pos.closed and pos.state == "phase1":
            actions = pos.update(trade.sl)  # force SL hit on phase 1
        for a in actions:
            if a[0] == "closed":
                exit_reason = a[1]
                exit_ts = ts
        if pos.closed:
            break
    if not pos.closed:
        # Mark-to-market at end of future window.
        realized_r = pos.r_multiple
        exit_reason = "open_at_eod"
        exit_ts = future_bars.index[-1]
    else:
        realized_r = pos.r_multiple
    trade.exit_time = exit_ts
    trade.exit_reason = exit_reason
    trade.r_multiple = round(float(realized_r), 6)
    risk_dollar = start_equity * RISK_PCT
    trade.pnl_dollar = round(float(realized_r) * risk_dollar, 2)
    return float(realized_r)


def run() -> BacktestResult:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_parquet(ROOT / "data" / f"{PAIR.lower()}_m15.parquet")
    df = raw.copy()
    # Parquet has naive index; force UTC for SignalEngine resample logic.
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df = df.loc[(df.index >= WINDOW_START) & (df.index <= WINDOW_END)]
    df = df.sort_index()
    if len(df) < HISTORY_BARS + STEP_BARS:
        raise RuntimeError(
            f"Not enough bars in window ({len(df)}) for HISTORY_BARS={HISTORY_BARS}"
        )

    # Bot config — match the LOOSENED params from config.yaml.
    cfg = SignalBotConfig(
        symbols=(PAIR,),
        timeframe="M15",
        history_bars=HISTORY_BARS,
        feed_mode="memory",
        poll_interval_seconds=60,
        dry_run=True,
        swing_left=5,
        swing_right=5,
        htf_swing_length=10,
        displacement_atr_mult=1.2,   # loosened from 1.5
        min_confluence_score=3,      # loosened from 4
        require_displacement=True,
        require_bias_aligned=True,
        bias_mode="h4_only",
        sl_atr_buffer=0.2,
        min_sl_atr=0.3,
        max_sl_atr=5.0,
        min_sl_pips=17.0,
        entry_proximity_atr=2.0,
        tp1_r=2.0, tp2_r=3.0, tp3_r=4.0,
        state_db_path=OUT_DIR / "signal_state.db",
        dedup_window_minutes=0,      # replay dedups by signal_id (deterministic)
    )

    notifier = LoggingNotifier()
    state = SignalStateStore(cfg.state_db_path, cfg.dedup_window_minutes)
    feed = InMemoryFeed({PAIR: df.iloc[:HISTORY_BARS].copy()})
    engine = SignalEngine(cfg)
    watcher = Watcher(
        cfg=cfg, feed=feed, engine=engine, state=state, notifier=notifier,
    )

    trades: list[SimTrade] = []
    equity_pts: list[EquityPoint] = []
    equity = ACCOUNT_SIZE
    bar_cursor = HISTORY_BARS

    t0 = time.perf_counter()
    while bar_cursor < len(df):
        # Grow feed to current bar.
        watcher.feed = InMemoryFeed({PAIR: df.iloc[: bar_cursor + 1].copy()})
        # Reset last_seen so watcher reprocesses this bar.
        watcher.last_seen = {}
        try:
            watcher.run_once()
        except Exception as exc:  # engine failure on a slice — log + continue
            print(f"  [warn] engine failed at bar {bar_cursor}: {exc}",
                  file=sys.stderr)
        # Drain notifier: emit any new payloads as SimTrade.
        for payload in list(notifier.sent):
            entry_ts = pd.Timestamp(payload.bar_time, unit="s", tz="UTC")
            trade = SimTrade(
                signal_id=payload.signal_id,
                symbol=payload.symbol,
                side=payload.dir,
                entry_time=entry_ts,
                entry=float(payload.entry),
                sl=float(payload.sl),
                tp_at_2r=float(payload.tp1),
                tp_at_4r=float(payload.tp3),
            )
            future = df.loc[df.index > entry_ts]
            if future.empty:
                break
            realized_r = _exit_trade(trade, future, equity)
            trades.append(trade)
            equity += trade.pnl_dollar
            equity_pts.append(EquityPoint(ts=trade.exit_time or entry_ts,
                                          equity=round(equity, 2)))
        notifier.sent.clear()
        bar_cursor += STEP_BARS
        if bar_cursor % (STEP_BARS * 25) == 0:
            print(
                f"  ... bar {bar_cursor}/{len(df)}  "
                f"trades={len(trades)}  equity=${equity:,.0f}",
                flush=True,
            )

    elapsed = time.perf_counter() - t0
    return BacktestResult(trades=trades, equity=equity_pts, elapsed_s=elapsed)


def main() -> int:
    print("=" * 72)
    print("SIGNAL-ENGINE BACKTEST (smc_bot_signal.SignalEngine + ScaleInExit)")
    print("=" * 72)
    print(f"Pair: {PAIR}   window: {WINDOW_START.date()} → {WINDOW_END.date()}")
    print(f"Step: {STEP_BARS} bars   history: {HISTORY_BARS} bars")
    print(f"Output: {OUT_DIR}")
    print()

    result = run()
    metrics = _compute_metrics(result.trades, result.equity)

    print()
    print(f"Elapsed: {result.elapsed_s:.1f}s")
    print(json.dumps(metrics, indent=2))

    # Year breakdown
    if result.trades:
        years = Counter(t.entry_time.year for t in result.trades)
        print("\nTrades per year:")
        for y in sorted(years):
            print(f"  {y}: {years[y]:>4d}")

    # Exit-reason breakdown
    reasons = Counter(t.exit_reason for t in result.trades)
    print(f"\nExit reasons: {dict(reasons)}")

    # Persist artifacts
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "config": {
            "pair": PAIR,
            "window": [str(WINDOW_START.date()), str(WINDOW_END.date())],
            "step_bars": STEP_BARS,
            "history_bars": HISTORY_BARS,
            "risk_pct": RISK_PCT,
            "account_size": ACCOUNT_SIZE,
            "pip_size": PIP_SIZE,
            "bot_config": {
                "swing_left": 5, "swing_right": 5,
                "htf_swing_length": 10,
                "displacement_atr_mult": 1.2,
                "min_confluence_score": 3,
                "bias_mode": "h4_only",
                "sl_atr_buffer": 0.2,
                "min_sl_pips": 17.0,
                "entry_proximity_atr": 2.0,
            },
        },
        "metrics": metrics,
        "exit_reasons": dict(reasons),
        "year_breakdown": (
            dict(Counter(t.entry_time.year for t in result.trades))
            if result.trades else {}
        ),
        "elapsed_s": round(result.elapsed_s, 2),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    if result.trades:
        trades_df = pd.DataFrame([{
            "signal_id": t.signal_id, "symbol": t.symbol, "side": t.side,
            "entry_time": t.entry_time.isoformat(), "entry": t.entry,
            "sl": t.sl, "tp2r": t.tp_at_2r, "tp4r": t.tp_at_4r,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "exit_reason": t.exit_reason, "r_multiple": t.r_multiple,
            "pnl_dollar": t.pnl_dollar,
        } for t in result.trades])
        trades_df.to_csv(OUT_DIR / "trades.csv", index=False)
    if result.equity:
        eq_df = pd.DataFrame([
            {"ts": e.ts.isoformat(), "equity": e.equity} for e in result.equity
        ])
        eq_df.to_csv(OUT_DIR / "equity.csv", index=False)
    print(f"\nArtifacts written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
