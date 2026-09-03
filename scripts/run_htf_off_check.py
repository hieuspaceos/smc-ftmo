"""Run backtest with HTF OFF (matches Pine when user unchecks both flags)."""
import sys
import os

sys.path.insert(0, "src")
sys.path.insert(0, "packages/smc_engine/src")

from src.backtester import run_backtest
import pandas as pd


cfg = {
    "ftmo": {"account_size": 100000, "phase": "challenge",
             "profit_target": 0.10, "max_daily_loss": 0.05,
             "daily_loss_limit_r": 2.0, "max_open_positions": 1},
    "strategy": {
        "swing_length": 10, "rr_target": 4.0,
        "displacement_atr_mult": 1.5, "sweep_atr_buffer": 0.05,
        "min_confluence_score": 4, "require_displacement": True,
        "require_bias_aligned": True, "sl_atr_buffer": 0.2,
        "min_sl_atr": 0.3, "max_sl_atr": 4.0,
        "rulebook_entry_proximity_atr": 1.5,
        "bias_mode": "strict", "regime_mode": "off",
        "promotion_lookback_bars": 50,
        "exit_mode": "scale_in", "leg2_tp1_r": None,
        # HTF off (match Pine when user unchecks both)
        "htf_daily_enabled": False,
        "htf_h4_enabled": False,
    },
    "confluence": {"weights": {"displacement": 1, "bias_aligned": 1,
                                "sweep_clean": 1, "premium_discount": 1,
                                "first_test": 1}},
    "filters": {"sweep": False, "pd": False, "first_test": False},
    "start_date": "2016-01-01", "end_date": "2026-08-21",
    "pd_lookback": 50,
    "execution": {
        "spread_pips": {"EURUSD": 0.5},
        "commission_per_lot_per_side": 2.50,
        "slippage_pips": {"mean": 0.1, "std": 0.3, "seed": 42},
    },
}


print("Running EURUSD scale_in 2R/4R 10y with HTF OFF (Pine parity)...")
trades, equity = run_backtest("EURUSD", cfg)
print(f"  Trades: {len(trades)}")

if trades:
    n_win = sum(1 for t in trades if t.get("r_multiple", 0) > 0)
    wr = n_win / len(trades) * 100
    total_r = sum(t.get("r_multiple", 0) for t in trades)
    avg_r = total_r / len(trades)
    eq = pd.DataFrame(equity, columns=["ts", "eq"]).set_index("ts")["eq"]
    dd = (eq / eq.cummax() - 1) * 100
    max_dd = dd.min()
    final = float(eq.iloc[-1])
    net = final - 100000
    roi = net / 100000 * 100
    gross_win = sum(t.get("r_multiple", 0) for t in trades if t.get("r_multiple", 0) > 0)
    gross_loss = abs(sum(t.get("r_multiple", 0) for t in trades if t.get("r_multiple", 0) < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    print(f"  Winrate: {wr:.1f}% ({n_win}W / {len(trades)-n_win}L)")
    print(f"  TotalR:  {total_r:+.1f}, AvgR: {avg_r:+.3f}")
    print(f"  MaxDD:   {max_dd:.2f}%, Final: ${final:,.0f}, Net: ${net:+,.0f} ({roi:+.1f}%)")
    print(f"  PF:      {pf:.2f}")
