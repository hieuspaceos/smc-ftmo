# SMC FTMO Trading System — Production-Readiness Audit

**Audit date:** 2026-08-31
**Auditor:** FrequentSpoonbill (Staff Engineer role)
**Scope:** Read-only audit of `C:/Users/hieuspace/Documents/CODE/trading/smc-ftmo` against pro-trader / quant standards for a "complete trading system."

---

## 1. TL;DR

**Verdict: research-grade system, NOT production-ready for FTMO live deployment.**

The repo contains a coherent, well-tested Python SMC engine (`packages/smc_engine`, `src/smc_signals.py`) and a high-quality event-driven bar-by-bar backtester (`src/backtester.py`) with full partial-TP / scale-in state machines, FTMO daily guards, and per-trade SQLite journaling. The Pine↔Python parity tooling is mature (capture + comparator scripts, 15+ unit tests) and the FTMO live-bot pipeline (webhook → 11 gates → MT5 file-bridge executor) is hardening-tracked under `plans/260831-1036-bot-audit-fixes/`. WHAT IS MISSING for a complete trading system is the standard production-readiness layer that turns a profitable backtest into a deployable system:

- **No walk-forward / parameter-sensitivity / Monte-Carlo validation pipelines** (`grep` of `src/`, `scripts/`, `tests/` finds zero hits for walk_forward, monte_carlo, sensitivity, OOS, param-sweep, bootstrap, t_stat, sharpe, sortino, expectancy).
- **Backtester is single-pass with no OOS / time-split capability**; CLI is two `start_date` / `end_date` scalars (`src/backtester.py:262-276`) — no rolling in-sample/out-of-sample.
- **No spread / slippage / commission / swap model in the core backtester.** `src/mt5_simulator.py` is a *post-hoc* R-penalty wrapper over already-computed Python trades (`src/mt5_simulator.py:97-130`) — it does not re-walk OHLCV.
- **No session or news filter in the backtest.** Every trade is hardcoded to `"session": "london"` (`src/backtester.py:626`, `:723`) regardless of actual bar time; the `config.yaml` `sessions` / `active_sessions` block is dead.
- **No regime-tagged metrics, no day-of-week split, no correlation guard, no whitelist enforcement at backtest time** — all referenced in `config.yaml` but absent from `run_backtest`.
- **Manual trade journal templates are skeleton placeholders** (`journal/manual_trades_2026.md`, `journal/replay_samples_2026.md` — every field is `_______`, no adherence metric, no baseline-vs-actual scoring).
- **Pine↔Python parity has not yet been validated against real TradingView output** (`docs/smc-engine-verification.md` was demoted to `parity-tooling-complete`; `tests/fixtures/pine-parity/` contains only synthetic data — 4 files, no real capture).

In short: the **signal-generation layer** is production-shaped (causal, tested, linted), but the **research-methodology layer** (walk-forward, OOS, MC, sensitivity, regime tagging) and the **execution-realism layer** (spread/slippage/session/news within the backtest itself) are policy-only declarations in `config.yaml` and rules files.

---

## 2. Implementation Evidence Map

| File (line / symbol) | What it actually implements |
|---|---|
| `src/backtester.py:150-732` `run_backtest()` | Event-driven M15 bar-by-bar loop; causal (no T+1 lookahead — `_align_to_m15` uses `merge_asof(direction="backward")` at line 110; OB filter uses `ev.is_active_at(ts)` and `ts > ev.first_touch_timestamp` at lines 468-471); supports one date range via `start_date` / `end_date` (lines 252-276); no walk-forward / OOS / MC / sensitivity / session / news flags. |
| `src/backtester.py:737-773` `compute_metrics()` | Total trades, winrate, profit_factor, avg_R, max_dd_pct (from `eq.cummax()`), total_R, final_equity, longest_win_streak, longest_loss_streak. **No Sharpe, Sortino, Expectancy, Calmar, recovery factor, t-stat, bootstrap CI.** |
| `src/backtester.py:626, 723` | Every trade dict is written with `"session": "london"` — constant, **not** derived from bar timestamp. |
| `src/strategy.py:39-157` `PartialTPExit` | Stateful per-position object; `update(price)` returns action tuples (`close_pct`, `move_sl`, `closed`); 40/30/30 ladder default (`DEFAULT_STAGES = ((2.0, 0.40), (3.0, 0.50), (4.0, 1.0))` at line 67); overshoot-safe (one stage per bar; `+1e-9` epsilon on R-boundary). Tested in `strategy.py` self-test and `tests/test_scale_in_exit.py`. |
| `src/strategy.py:163-265` `check_entry(snapshot)` | Pure entry decision from a `snapshot` dict; requires `entry_allowed` + `displacement` + `bias_aligned` + valid OB + ATR > 0 + price within 1.5×ATR of OB edge. Returns `{side, entry, sl, tp1, tp2, tp3, ob_top, ob_bottom, risk_per_unit, atr, reasons}`. |
| `src/scale_in_exit.py` `ScaleInExit` | Independent module mirroring `PartialTPExit` API; state machine `phase1 → phase2 → closed`; Design A (default) and Design B (leg2_tp1_r=3.0 intermediate TP). Math invariants documented in module docstring (lines 5-58). |
| `src/mt5_simulator.py:35-81` `FillConfig` | Spread (default 0.5 pips), Gaussian slippage (mean 0.1 / std 0.5), commission-per-lot, fixed pip_size 0.0001. **Constant** spread, not session-dependent (line 33 docstring: "Spread + slippage are constant (not session-dependent)"). |
| `src/mt5_simulator.py:84-130` `simulate_trade()` | Adjusts already-computed Python `r_multiple` by `(spread + slippage) / sl_distance_pips` — does NOT re-walk bars or recompute fills. Not a true MT5 simulation; it's an additive cost penalty. |
| `src/mt5_simulator.py:236-258` `compute_sim_metrics()` | Aggregator: trades / winrate / PF / total_pnl / max_dd / avg_r. Mirrors backtester output, no extra analytics. |
| `src/risk_manager.py:14-31` `calculate_lot()` | Fixed-fractional lot sizing: `lot = (equity * risk_pct) / (sl_distance * pip_value)`, floored at 0.01. |
| `src/risk_manager.py:45-93` `FTMOGuard` | Daily reset (NY session start), -2R daily stop, max trades/day (default 3), equity-based daily loss ceiling (5%). No max-consecutive-losses, no drawdown-trailing circuit breaker. |
| `src/journal.py:18-49` `SCHEMA` | SQLite trades table: pair, side, entry/exit prices, tp1/2/3, r_multiple, pnl_usd, risk_usd, confluence_score, bias_d/h4, displacement, sweep_clean, premium_discount, first_test, session, is_partial, exit_reason. Indexed on pair, timestamp_entry, score, r. |
| `src/journal.py:151-197` `Journal.query()` | Filter by pair/pairs, date range, min_score, win/lose, session, setup_type. |
| `src/journal.py:199-216` `stats_by_setup()` | Per-setup winrate, avg_R, gross profit/loss R. **No Sharpe / t-test / bootstrap / drawdown trajectory.** |
| `src/journal.py:218-244` `aggregate()` | Portfolio-level winrate, PF, total R, total USD. |
| `src/premium_discount.py` `detect_premium_discount()` / `pd_series()` | Equilibrium = (range_high+range_low)/2 over lookback window. Discount = below, premium = above. Per-bar Series returned. Used by backtester (`src/backtester.py:300`). |
| `src/bias_detector.py` `align_bias()` | D+H4 must agree → `aligned_long` / `aligned_short` / `stand_aside`. Falls back to `bias_mode in {h4_only, any}`. |
| `src/data_loader.py:11-25` `load_multi_tf_data()` | Loads parquet from `data/`; tz_localize(None) on DatetimeIndex; sort + dedupe. Cached via `st.cache_data`. |
| `src/smc_signals.py` `SMCSignals.get_signals()` | Compatibility adapter over `packages/smc_engine` — emits Signal dataclasses for BOS/CHoCH/displacement/sweep/OB/FVG. |
| `packages/smc_engine/src/smc_engine/{swings,structure,displacement,sweeps,order_blocks,fvg,context,breaker_blocks,ob_body_mode,liquidity_pools,regime}.py` | The actual SMC engine. Pure causal one-pass functions; events are immutable dataclasses with `activation_timestamp`, `is_active_at(ts)`, `is_first_test_at(ts)` lifecycle queries. Verified by `tests/test_smc_*.py` (200+ tests). |
| `packages/smc_bot_webhook/src/smc_bot_webhook/server.py:94-136` `AppSettings` | Required env: `SMC_WEBHOOK_TOKEN` (≥16 chars), `TELEGRAM_CALLBACK_SECRET` (≥16 chars) when bot token set, optional `SMC_BOT_DB_PATH`, `SMC_TRUSTED_PROXY`. |
| `packages/smc_bot_webhook/src/smc_bot_webhook/gates/validator.py:46-59` `CHART_GATE_NAMES` (5 chart gates) + `MANUAL_GATE_NAMES` (6 manual gates from `state.py:41-44`: `no_position`, `spread_news_clean`, `judgment_clear` etc.) | 11-gate pipeline; Accept button re-runs validator; signal-specific gates expire after 10 min. |
| `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/ftmo_guard.py:121-158` `FtmoGuard.check()` | Real DB-backed guard state (Phase 02 audit fix); checks daily_pnl → trades_today → open_position in that order. |
| `packages/smc_bot_backtest/src/smc_bot_backtest/replay_engine.py` + `capture.py` | Frozen-feed replay + unified CSV schema (24 columns) for parity between live webhook, Python replay, and Pine Logs paste. Deterministic. |
| `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/mql5_reader.mq5` | MQL5 EA that polls outbox and writes results; **does NOT** do spread/slippage/session-aware execution — just a file-bridge transport. |
| `scripts/btest_10y.py`, `btest_scale_in.py`, `btest_balanced.py` | Standalone CLI backtests: hardcoded configs calling `run_backtest()`; report trades/year histogram + winrate/total_R/max_DD. No CLI flags for walk-forward / OOS / MC. |
| `scripts/capture-frozen-feed.py` + `compare-pine-parity.py` + `export-pine-parity-fixtures.py` | 3-tool chain: produce deterministic Python reference, capture TradingView Pine output, diff with configurable `abs_tol`. **Real Pine capture is NOT in `tests/fixtures/pine-parity/`** — only synthetic. |
| `scripts/export_mt5_replay_csv.py` + `src/mt5_simulator.py` | Pre-MT5 sanity estimate. **Phase 0 of MT5 Strategy Tester plan (`plans/260831-0437`) shipped**; Phase 1+ (real `mql5_replay.mq5`) is TODO. |
| `journal/rule-book.md` | Manual-trade 8-week rulebook, including the 3 freeze overlays (sweep ≥0.25×ATR + reclaim, SL >1.2×ATR → NO TRADE, 2R into HTF wall → NO TRADE). Defines exit-mode scale-in metrics (AvgR +1.075R, PF 3.57, MaxDD 3.40%). |
| `journal/manual_trades_2026.md` | Skeleton template with all fields blank `_______`. No actual trades logged yet. |
| `journal/replay_samples_2026.md` | Skeleton template for 16 replay setups (4 win-big, 4 win-small, 4 loss, 4 BE). No actual replays logged. |
| `config.yaml` | FTMO rules + risk + strategy + pairs + timeframes + sessions + pip_values + data. **No `backtest:` section declaring walk-forward / MC / sensitivity** (the user's assignment prompt suggested one but it is not present in the actual config). |

---

## 3. Pro-Trader Checklist Audit

Legend: ✅ implemented in code | ⚠️ partial | 📄 documented/policy only | ❌ missing.

| # | Item | Status | Evidence (file:line / section) |
|---|---|---|---|
| 1 | Walk-forward analysis (rolling in-sample → OOS) | ❌ missing | `grep -n "walk_forward\|oos" src/ scripts/ tests/` → no matches. `run_backtest()` (`src/backtester.py:150`) has only single-pass `start_date` / `end_date`. |
| 2 | Pure OOS split (separate dataset / time window) | ❌ missing | No OOS time-window splitter. `btest_10y.py` runs full 2016-2026 in one pass. |
| 3 | Parameter sensitivity test (perturb ±X%, PnL survives?) | ❌ missing | No `scripts/sensitivity*` or `tests/test_sensitivity*`. `grep "sensitivity\|param.?sweep" src/ scripts/` → 0. |
| 4 | Monte Carlo simulation (shuffle / max-DD / ruin probability) | ❌ missing | `grep "monte_carlo\|shuffle\|bootstrap\|t_stat"` → 0 across `src/`, `scripts/`, `tests/`. |
| 5 | Regime tagging (separate metrics per regime) | ⚠️ partial | `packages/smc_engine/regime.py` computes regime labels (trending/ranging/mixed) and `RegimeState` dataclass with `ob_weight`, `breaker_weight`, `choppiness`, etc. `RegimeV2` is consulted in backtester for breaker overlay (`src/backtester.py:341-352`). **But:** trades are NOT tagged with regime in the trades dict (`src/backtester.py:605-630`); no per-regime metrics function; `Journal.stats_by_setup` doesn't group by regime. |
| 6 | Multi-pair validation (≥2 symbols beyond original) | 📄 documented | `config.yaml` lists `EURUSD / XAUUSD / BTCUSD`. `run_backtest` accepts a `pair` arg (`src/backtester.py:151`) and `data_loader.load_multi_tf_data(pair)` (`src/data_loader.py:14`) iterates any pair. **No comparative multi-pair metrics script**; `btest_*.py` scripts run only EURUSD. |
| 7 | Realistic spread model (per session / per volatility regime) | ❌ missing in core backtester | `src/mt5_simulator.py:33` docstring: "Spread + slippage are constant (not session-dependent)". `src/backtester.py` does not consume any spread input. |
| 8 | Slippage model (market vs limit, requote, partial fill) | ⚠️ partial | `src/mt5_simulator.py:67-71` Gaussian slippage on entry+exit; no requote / partial fill simulation. Applied *after* Python computes R; not part of the walk. |
| 9 | Commission + swap modeling | ⚠️ partial | `FillConfig.commission_per_lot_per_side` field exists (`src/mt5_simulator.py:75`), CLI flag `--commission-per-lot` (`src/mt5_simulator.py:329`). Swap not modeled. Default commission is 0.0. |
| 10 | Session filter enforced in backtest AND live | ⚠️ partial | `config.yaml:60-72` defines `active_sessions: [london, new_york, overlap]`; gates `state.py:41` has `spread_news_clean` manual gate. **But:** backtester writes `"session": "london"` constant (`src/backtester.py:626`); no bar-time check against `active_sessions`. Readers of trade journals see session=london for everything. |
| 11 | News filter (NFP/FOMC/CPI blackout window) | ❌ missing | No calendar integration; no time-of-day news blackout. Manual gate `spread_news_clean` is a human ack button (`packages/smc_bot_webhook/src/smc_bot_webhook/gates/state.py:42`) — not an automated filter. |
| 12 | Position sizing rule (fixed fractional / volatility-based) | ✅ implemented | `src/risk_manager.py:14-31` `calculate_lot()` is fixed-fractional: `lot = equity * risk_pct / (sl_distance * pip_value)`. Used in `src/backtester.py:657`. No volatility-based (e.g. ATR-weighted) variant. |
| 13 | Daily drawdown brake / circuit breaker | ✅ implemented | `src/risk_manager.py:45-93` `FTMOGuard`: -2R daily stop, max 3 trades/day, 5% equity daily loss ceiling. Also enforced in live `packages/smc_bot_webhook/.../ftmo_guard.py:121-158`. **No trailing-DD circuit breaker** (e.g. -10% from peak → halt). |
| 14 | Max consecutive losses → pause rule | ❌ missing | No consecutive-loss tracking in `FTMOGuard`. `compute_metrics()` reports `longest_loss_streak` (`src/backtester.py:772`) but does not gate on it. |
| 15 | Correlation guard (no double exposure on correlated pairs) | ❌ missing | `config.yaml:55-57` lists pairs; no correlation matrix, no guard. `FtmoGuard.check()` operates per-symbol (`ftmo_guard.py:147`). |
| 16 | Symbol whitelist + max positions per symbol | ✅ implemented | `config.yaml:55-57` whitelist; `ftmo_guard.py:147-157` enforces `max_open_positions` per symbol. Backtester has `max_open_positions: 1` (`src/backtester.py:605-606` reads `risk.max_open_positions` indirectly via `FTMOGuard.can_trade`). |
| 17 | Time-stop (exit if no SL/TP hit after X bars) | ✅ implemented | Backtester forces close at last bar with `exit_reason: "time"` (`src/backtester.py:720-728`). But this is a *backtest-only* end-of-data flush, not a per-trade time-stop rule. No mid-trade max-bars-hold. |
| 18 | Forward / paper-trade validation pipeline | ⚠️ partial | Phase 6 of `plans/260831-0437-mt5-strategy-tester-validation/plan.md` describes a 2-4 week demo forward run, but the pipeline is "Run the bot on FTMO demo, journal results." No tooling (no metrics dashboard, no compare-to-backtest script, no stat-sig test). |
| 19 | Live validation journal with adherence metric | ❌ missing | `journal/manual_trades_2026.md` is a template with all fields blank; no filled entries. No adherence metric computed anywhere in the repo. `plans/260831-1036-bot-audit-fixes/plan.md:22` lists 11 gates — but these are *pre-trade* validation gates, not post-trade adherence scoring. |
| 20 | Statistical significance test (t-test / bootstrap CI on Sharpe or R) | ❌ missing | `grep -r "t_stat\|bootstrap\|scipy.stats\|ttest\|sharpe_ratio\|sortino_ratio" src/ scripts/ tests/` → 0 matches. |
| 21 | Expectancy / profit factor / Sharpe from trades | ⚠️ partial | `src/backtester.py:737-773` computes winrate, profit_factor, avg_R, max_dd, longest_win/loss_streak. **No Sharpe / Sortino / Calmar / expectancy-per-trade-as-percent / recovery-factor.** |
| 22 | Maximum consecutive losing streak tracked | ✅ implemented | `src/backtester.py:772` `longest_loss_streak` from `_streak()` helper at line 776-784. |
| 23 | Per-trade journal entry persistence | ✅ implemented | `src/journal.py:127-150` `insert_trade` / `insert_many`; full 24-column schema with all confluence factors. |
| 24 | Equity curve persistence + drawdown tracking | ⚠️ partial | `src/backtester.py:736-738` returns `equity_curve: List[(ts, equity)]`; `compute_metrics` derives max DD from cummax. **NOT** persisted to SQLite; only in-memory list. Live bot writes `execution_log` per acceptance (`ftmo_guard.py:118-159`) but no aggregate equity-curve table. |
| 25 | Pine ↔ Python parity check | ⚠️ partial | Tooling complete (`scripts/capture-frozen-feed.py`, `scripts/compare-pine-parity.py`, `scripts/export-pine-parity-fixtures.py`, `tests/test_pine_parity_tools.py` with 15+ tests). **No real Pine capture committed** — `tests/fixtures/pine-parity/` contains only synthetic OHLC (4 files). Plan `plans/260831-0430-pine-parity-capture-procedure/` is open and explicitly states parity status was demoted to `parity-tooling-complete` until a real capture exists. |

**Summary: 6 ✅, 8 ⚠️ partial, 1 📄 documented-only, 10 ❌ missing.**

---

## 4. Backtest Methodology Assessment

### 4.1 Architecture
- **Event-driven**, not vectorized. `src/backtester.py:380-731` is a single `for i in range(start_bar, len(df_m15))` loop calling `exit_obj.update(bar_close)` and the engine helpers. Engine itself (`packages/smc_engine/*.py`) does full-pass computation up-front (`src/backtester.py:317-358`) which is acceptable because outputs are indexed Series.
- **Order of operations per bar**: first check open position actions → close_pct / move_sl / closed; then evaluate entry if `open_pos is None`. This means TP/SL checks happen on the same bar as entry signals, which is *technically* look-ahead-prone on the same bar — entry at bar T's close, then SL/TP evaluated on bar T's close too. For an event-driven bar-by-bar this is the standard simplification (treat bar close as simultaneous).

### 4.2 Look-ahead bias
- **HTF bias alignment is causal.** `_align_to_m15` uses `merge_asof(direction="backward")` (`src/backtester.py:110-113`) — today's daily bias only applies after its own daily close. ✅
- **OB lifecycle is causal.** `_ob_zones_as_of` and inline check at `src/backtester.py:468-471` use `ev.is_active_at(ts)` and `ts > ev.first_touch_timestamp`. ✅
- **Engine itself is causal by design** (swing activation at `pivot_pos + right`, structure on close-only breaks, sweeps one-shot, FVG on i-2/i). Verified in `docs/system-architecture.md:32-58`.
- **No `df.shift(-1)` or T+1 references** in engine code (`grep -r "shift(-1)"` → 0 in `packages/smc_engine`).
- **Risk:** if a swing is detected at bar T using bars T-left..T+right (typical fractal), `detect_swings` activates at `pivot_pos + right` (`packages/smc_engine/src/smc_engine/swings.py:90-100`) — this means at bar T the user sees the swing, but the *activation* requires T+right bars to have already happened, so the engine output for bar T uses information from bar T+right. Within a single causal pass this is consistent (the engine's per-bar output for bar T uses only data up to bar T+right). However, in the backtester this means trade entries on bar T use a swing that was confirmed retrospectively — *that is the correct causal behavior.*

### 4.3 Entry execution
- **Same-bar close entry** (not next-bar open). `src/backtester.py:675-686`: when `entry_allowed and check_entry(snapshot) returns truthy`, an open position is created immediately at bar T's `entry_info["entry"]` price. **This is mildly optimistic** — in live execution, you fill at the next bar's open (or worse, after spread+slippage). Real-world backtests typically assume `entry = next_bar.open`.
- The TP ladder is evaluated intrabar via the `update(bar_close)` call (line 548). Since `bar_close` is the only price provided to `PartialTPExit`, this is **bar-close approximation** — the TP could be hit intrabar but the model assumes it hits at bar close. **Conservative enough for swing trades; aggressive for short timeframes.**

### 4.4 Spread / slippage
- **No spread / slippage in core backtester.** `run_backtest()` does not read any spread config. PnL is computed from raw close-vs-entry R multiples.
- `src/mt5_simulator.py` is a separate post-hoc tool that *adjusts* Python R-multiples by `(spread_pips + sampled_slippage) / sl_distance_pips`. **This is not the same as live execution**, because it does not test whether the SL/TP would have actually been hit at the assumed price after spread+slippage (a SL might get filled worse than SL price; a TP might get filled at TP price minus spread). The simulator's own `compute_sim_metrics` shows EURUSD 2016-2026 PnL dropped from $456,400 to $332,192 (-27%) with default 0.5 pip spread and Gaussian slippage — this is the only quantitative execution-cost measurement in the repo.
- **No commission** in core backtester; `FillConfig.commission_per_lot_per_side` defaults to 0.0.
- **No swap**.

### 4.5 Partial TP implementation
- **Intrabar via bar-close approximation.** `PartialTPExit.update(price)` checks SL first (`src/strategy.py:106-115`), then evaluates one TP stage per bar (line 122-138). Returns action tuples that the backtester (`src/backtester.py:549-630`) translates into PnL accounting.
- **One stage per bar** prevents double-counting but ignores intra-bar path (e.g. price spikes to 4R then settles at 2R — only TP2 fires).
- **Overshoot-safe:** R boundary uses `r + 1e-9 >= target_r` (line 122), so a bar that closes exactly at TP2 counts as a TP2 hit but doesn't also credit TP3.

### 4.6 OOS / walk-forward / MC / sensitivity / param-sweep flags
- **None.** `run_backtest()` signature is `(pair: str, config: dict) -> (trades, equity_curve)` (`src/backtester.py:150-153`). No `--walk-forward`, `--oos`, `--monte-carlo`, `--sensitivity`, `--param-sweep` flags. No command-line entry point at all — `__main__` block at line 784 is a hardcoded smoke test on EURUSD. The `btest_*.py` scripts are ad-hoc Python runners with hardcoded date ranges.
- **`scripts/btest_10y.py:11-15`** hardcodes `start_date='2016-01-01'`, `end_date='2026-08-21'`, EURUSD only.

### 4.7 Regime / session / day-of-week tagging
- **Regime awareness exists in the engine** (`packages/smc_engine/regime.py`) but **trades are NOT tagged with regime** in the trades dict (`src/backtester.py:605-630`). `premium_discount` is tagged; `bias_d`, `bias_h4`, `displacement`, `sweep_clean`, `first_test`, `confluence_score` are tagged; `setup_type` is hardcoded `"OB"` (line 629); `session` is hardcoded `"london"` (line 626).
- **No day-of-week, hour-of-day, regime, or correlation-bucket breakdowns** anywhere in `compute_metrics` or `Journal.aggregate`.

### 4.8 Forward validation
- **`plans/260831-0437-mt5-strategy-tester-validation/plan.md` Phase 6** describes a 2-4 week demo forward run, but it is a manual ops step, not a pipeline. No metrics comparison script, no statistical significance test, no go/no-go gate.

### 4.9 Critical methodology gaps
1. **Same-bar entry** (no next-bar-open assumption) inflates backtest vs live.
2. **No spread in core** — every backtest number is "broker-perfect-fill."
3. **No commission** — even FTMO-charged commissions are invisible.
4. **No session filter** — trades logged with `session="london"` regardless of bar time, so a Tuesday 14:00 UTC entry would be mis-classified.
5. **No OOS split** — every metric is in-sample.

---

## 5. Top Gaps Ranked by Impact on "Complete System" Claim

| # | Gap | Why it matters | Effort |
|---|---|---|---|
| 1 | **No walk-forward / OOS / Monte-Carlo / sensitivity pipelines.** Without these, every backtest metric is in-sample and any curve-fit is invisible. | This is the #1 reason a "profitable backtest" ≠ "production-ready." Without OOS validation the system cannot claim statistical edge. | L (2-3 weeks): implement `--walk-forward`, `--oos-split`, `--monte-carlo`, `--sensitivity` flags in `run_backtest`; add bootstrap CI on Sharpe/R. |
| 2 | **Backtester has no spread/slippage/commission/swap.** | Live PnL will always be worse than backtest PnL. From the simulator's own numbers: EURUSD scale-in PnL drops 27% with default 0.5pip spread + Gaussian slippage. The true live cost is likely higher because the simulator doesn't model fill-quality variance. | M (1 week): add spread input (per-pair or per-session) into `PartialTPExit` / `ScaleInExit`; commission per side; intrabar fill model. |
| 3 | **No session or news filter in backtest.** All trades written with hardcoded `session="london"`. | Live session filter exists (`active_sessions` config, manual `spread_news_clean` gate), but the backtest ignores bar time entirely. You cannot measure how much of the backtest PnL comes from off-session hours. | S (2-3 days): compute `ts.hour` (or use existing config `sessions` map), filter entries; tag `session` correctly per bar. |
| 4 | **Pine↔Python parity not yet validated against real TradingView output.** Only synthetic data in `tests/fixtures/pine-parity/`. | The entire signal source for the live bot is the Pine indicator. If it diverges from Python, the bot is trading a different strategy than the one backtested. Parity plan (`plans/260831-0430`) is open and not yet executed. | M (1 week once started): per Phase 2-5 of the parity plan, capture 200-500 bars, diff, triage. Plan estimates 3-4 hours of Bar Replay work + diff/fix loop. |
| 5 | **Same-bar-close entry assumption (no next-bar-open).** | Backtest fills are optimistic. In live FTMO the entry at M15 bar T will be at bar T+1's open (15 min later), often at a worse price for the trader. | S (1-2 days): shift entry to `df_m15["open"].iloc[i+1]` and verify behavior changes. |
| 6 | **Trades not tagged with regime / day-of-week / hour-of-day.** `Journal.stats_by_setup` does not break down by these. | Cannot identify which regimes or sessions produce edge. If 70% of the PnL comes from one Tuesday morning in 2022, that's a curve fit, not an edge. | S (2-3 days): compute regime at entry, tag trade dict; add `Journal.stats_by_regime()`. |
| 7 | **No statistical significance tests** (t-test, bootstrap, Sharpe CI). | "PF 3.57" is meaningless without a confidence interval. Could be sampling luck on 603 trades. | S (3-4 days): add `scipy.stats.ttest_1samp` on R-multiples; bootstrap CI on Sharpe via `numpy.random`. |
| 8 | **No max-consecutive-loss pause / no trailing-DD circuit breaker.** | FTMO account survives -10% total / -5% daily but trader psychology does not. A 5-loss streak followed by size-up revenge-trading is a classic blow-up pattern. | S (1 day): add `max_consecutive_loss` field to `FTMOGuard`, halt for N bars or end-of-day. |
| 9 | **Manual journal templates empty** + no adherence metric. `journal/manual_trades_2026.md` and `replay_samples_2026.md` are blank. | The whole point of the 8-week manual phase (per `journal/rule-book.md`) is adherence testing. Without filled journals + a numeric adherence score (e.g. % of trades that passed checklist), the bot cannot claim trader-blessed. | M (2 weeks of human time + 2-3 days of tooling): fill journals daily, add `journal/adherence_score.py`. |
| 10 | **MT5 Strategy Tester validation Phase 1+ not done.** Phase 0 (Python simulator) shipped but Phase 1+ (real `mql5_replay.mq5` EA + Strategy Tester run) is TODO per `plans/260831-0437/plan.md`. | The biggest risk surface in live FTMO is the EA / broker execution layer. Without running the EA through Strategy Tester on the same 10-year EURUSD M15 data, MQL5 bugs (lot cap, margin mode, partial fills, requote) are invisible until live. | L (1-2 weeks): build `mql5_replay.mq5`, run Strategy Tester, triage tolerances (PF ±10%, PnL ±15%, DD +1pp). |

---

## 6. Recommended Next Actions (ordered)

1. **(S) Tag trades by real session + add session filter.** Two-day fix in `src/backtester.py`. Without this, the rest of the metrics work is misleading.

2. **(S) Move entry to next-bar-open.** One-day fix; re-run `btest_10y.py` and `btest_scale_in.py` to see the cost of realism.

3. **(M) Add spread + commission to core backtester.** 1 week. Extend `PartialTPExit` / `ScaleInExit` to accept a spread-cost-per-side; verify the EURUSD scale-in backtest PnL drops from $456,400 toward the simulator's $332,192 number.

4. **(M) Execute `plans/260831-0430-pine-parity-capture-procedure` end-to-end.** 1 week. Real TradingView Bar Replay capture → diff → triage → either bump label to `parity-achieved` or document accepted deviations.

5. **(M) Execute `plans/260831-0437-mt5-strategy-tester-validation` Phase 1+.** 1-2 weeks. Build `mql5_replay.mq5`, run Strategy Tester, compare against Python baseline with the ±5%/±15%/+1pp tolerances.

6. **(L) Build walk-forward / OOS / MC / sensitivity tooling into `run_backtest`.** 2-3 weeks. Add `walk_forward(window_months=6, step_months=1, oos_months=2)`, `monte_carlo(shuffles=1000)`, `sensitivity(perturb_pct=10)`. This is the biggest gap to "complete system" status.

7. **(S) Add statistical significance.** Bootstrap CI on Sharpe, t-test on R-multiples. 3-4 days.

8. **(S) Add max-consecutive-loss guard + trailing-DD circuit breaker** to `FTMOGuard`. 1 day each.

9. **(S) Tag trades with regime + day-of-week + hour-of-day; add `Journal.stats_by_regime()`.** 2-3 days.

10. **(M) Fill `journal/manual_trades_2026.md` and `replay_samples_2026.md` during the actual 8-week manual trade phase.** Then add `journal/adherence_score.py` that scores filled entries against `rule-book.md` checklist.

11. **(S) Persist equity curve to SQLite** for the live bot (`equity_curve` table). Currently only in-memory.

12. **(S) Audit-finding closure** from `plans/260831-1036-bot-audit-fixes/`: phases 01-07 still pending (auth hardening, FTMO guard real impl, accept ordering, Telegram MarkdownV2, payload hardening, outbox/rate-limit, smoke + rollback). Each is a 1-3 day fix.

---

## 7. Verification Commands (read-only; do not run during this audit)

For when the user wants to spot-verify the claims above without re-reading source:

```bash
# Confirm no walk-forward / MC / sensitivity code anywhere
grep -r -l "walk_forward\|monte_carlo\|sensitivity\|out_of_sample\|OOS\|param_sweep\|bootstrap\|t_stat\|sharpe\|sortino" src/ scripts/ tests/ packages/ 2>/dev/null

# Confirm backtester signature has no WF/MC flags
grep -n "argparse\|--walk-forward\|--monte-carlo\|--sensitivity" src/backtester.py

# Confirm session is hardcoded in trade dict
grep -n '"session":' src/backtester.py

# Confirm no spread/slippage in core backtester
grep -n "spread\|slippage\|commission" src/backtester.py

# Confirm no real Pine capture
ls tests/fixtures/pine-parity/   # 4 synthetic files, no real capture

# Run the scale-in smoke script to verify numbers
python -m scripts.btest_scale_in   # EURUSD 603 trades, $456,400 PnL, PF 3.57

# Run the MT5 simulator to see execution-cost penalty
python -m src.mt5_simulator         # default 0.5 pip spread, Gaussian slippage

# Run unit tests for the engine layer
pytest tests/test_smc_swings.py tests/test_smc_structure.py tests/test_smc_order_blocks.py tests/test_smc_fvg_context.py tests/test_smc_sweeps.py tests/test_smc_liquidity_pools.py tests/test_smc_regime.py tests/test_smc_breaker_blocks.py tests/test_smc_ob_body_mode.py tests/test_smc_displacement.py tests/test_backtest.py tests/test_backtest_breakers.py tests/test_scale_in_backtest.py tests/test_scale_in_exit.py tests/test_mt5_simulator.py tests/test_pine_parity_tools.py tests/test_bot_dispatch.py tests/test_bot_db_concurrency.py -q

# Run unit tests for the bot webhook + gates
pytest packages/smc_bot_webhook/tests/ packages/smc_bot_core/tests/ packages/smc_bot_backtest/tests/ -q
```

---

## 8. File map of cited evidence

| Evidence | File | Line |
|---|---|---|
| Backtester loop | `src/backtester.py` | 380-731 |
| Backtester entry | `src/backtester.py` | 675-706 |
| Backtester forced time-close | `src/backtester.py` | 720-728 |
| `compute_metrics` | `src/backtester.py` | 737-773 |
| `_streak` helper | `src/backtester.py` | 776-784 |
| Session hardcoded | `src/backtester.py` | 626, 723 |
| `merge_asof` bias align | `src/backtester.py` | 91-114 |
| OB lifecycle check | `src/backtester.py` | 117-132, 468-471 |
| PartialTPExit | `src/strategy.py` | 39-157 |
| ScaleInExit | `src/scale_in_exit.py` | (whole file, 265 lines) |
| MT5 simulator penalty | `src/mt5_simulator.py` | 35-130 |
| MT5 simulator metrics | `src/mt5_simulator.py` | 236-258 |
| FTMOGuard | `src/risk_manager.py` | 45-93 |
| `calculate_lot` | `src/risk_manager.py` | 14-31 |
| Journal schema | `src/journal.py` | 18-49 |
| `Journal.aggregate` | `src/journal.py` | 218-244 |
| `Journal.stats_by_setup` | `src/journal.py` | 199-216 |
| Regime V2 | `packages/smc_engine/src/smc_engine/regime.py` | (whole file, 243 lines) |
| Engine swing activation | `packages/smc_engine/src/smc_engine/swings.py` | 90-100 |
| AppSettings env | `packages/smc_bot_webhook/src/smc_bot_webhook/server.py` | 94-136 |
| 11-gate validator | `packages/smc_bot_webhook/src/smc_bot_webhook/gates/validator.py` | 46-59 |
| Manual gates list | `packages/smc_bot_webhook/src/smc_bot_webhook/gates/state.py` | 41-44 |
| Live FTMO guard | `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/ftmo_guard.py` | 121-158 |
| Pine parity plan | `plans/260831-0430-pine-parity-capture-procedure/plan.md` | (whole file) |
| MT5 tester plan | `plans/260831-0437-mt5-strategy-tester-validation/plan.md` | (whole file) |
| Bot audit plan | `plans/260831-1036-bot-audit-fixes/plan.md` | (whole file) |
| Manual trade journal template | `journal/manual_trades_2026.md` | (skeleton) |
| Replay samples template | `journal/replay_samples_2026.md` | (skeleton) |

---

**End of report.**


---

## 9. Risk & FTMO Compliance Audit (Section 9)

> Read-only review focused on **risk-management implementation** and **FTMO-rule enforcement** across `src/backtester.py`, `src/strategy.py`, `src/scale_in_exit.py`, `src/risk_manager.py`, `src/mt5_simulator.py`, and the `smc_bot_webhook` package.

### 9.1 TL;DR

- Position-sizing math is real (`src/risk_manager.py:18-29`) and wired into the backtester (`src/backtester.py:652`).
- Two parallel FTMO guards with **inconsistent semantics**:
  - `src/risk_manager.FTMOGuard` — backtester (realized-R, `equity - account_size ≤ -5%`).
  - `packages/smc_bot_webhook.mt5_bridge.ftmo_guard.FtmoGuard` — webhook (DB-aggregated, derives threshold from `0.55% × 2R = 1.1%`).
- **Floating P&L intraday not tracked** in either guard → FTMO 5% rule not enforced to spec.
- **Session filter is explicitly documented as NOT implemented** — `journal/rule-book.md:320`: *"Bot backtester hiện không lọc session — đây là kỷ luật tay, vẫn bắt buộc."*
- **News filter does not exist** in Python code (no NFP/FOMC/CPI/economic_calendar keyword anywhere); only manual gate `spread_news_clean`.
- **Partial TP / scale-in logic fully implemented + tested in backtest**, but **`docs/mt5-bridge-setup.md:240-243` documents live MT5 only executes TP1 = +2R** — all backtest PnL beyond 2R is unrealized on live.
- **Possible unit-conversion bug at `src/backtester.py:652`** — smoke test interprets `sl_distance=50` as pips; runtime call passes price-distance (0.0050). 100× discrepancy in `calculate_lot()` invocation. Needs implementation verification before trusting backtest dollar figures.

### 9.2 Risk implementation matrix (29 items)

| # | Item | Status | Evidence (file:line) |
|---|---|---|---|
| 1 | FTMO profit target per phase | ❌ missing | `config.yaml:5` declares 0.10; **no code reads it** (grep returns only yaml + Streamlit echo). |
| 2 | Max daily loss 5% tracked at trade-level (incl. floating P&L) | ⚠️ partial | Backtester: `equity - account_size ≤ -5%` (`src/risk_manager.py:84-90`), realized only. Webhook: `execution_log.pnl` sum, open trades excluded (`db_impl.py:368-382`). |
| 3 | Max total loss 10% tracked | ❌ missing | `config.yaml:7` declares 0.10; `FTMOGuard.__init__()` ignores it. |
| 4 | Time-zone aware (Europe/Paris) | ⚠️ partial | `config.yaml:8` cosmetic; webhook uses `America/New_York` (`gates/state.py:50-65`); backtester uses dataframe native tz. |
| 5 | Phase switching (challenge → verification → funded) | 📄 documented-only | `config.yaml:4`; no code path reads it. |
| 6 | FTMO rules in single source of truth | ⚠️ partial | Two parallel classes, different semantics. `backtester.py:387-392` hardcodes 5% regardless of config; webhook derives 1.1% from per-trade × daily R. |
| 7 | Fixed fractional sizing (per_trade_pct = 0.55%) | ✅ implemented | `src/risk_manager.py:18-29`. |
| 8 | ATR-based SL (sl_atr_buffer = 0.2×ATR) | ✅ implemented | `src/strategy.py:202-207`. |
| 9 | R-multiple per trade | ✅ implemented | `src/strategy.py:91-94`, `src/scale_in_exit.py:97-101`. |
| 10 | Daily loss limit (2R) tracked | ⚠️ partial | Realized-only in both guards. Manual `daily_loss_ok` ack is not auto-revoked. |
| 11 | Max 3 trades/day enforced | ✅ backtest / ⚠️ live | Counting semantics differ (closed vs queued/sent/acked/filled/closed). |
| 12 | Max 1 open position | ⚠️ partial | Webhook `get_open_positions()` uses `state='filled'` as proxy — never-closed fills permanently counted. |
| 13 | Per-pair correlation guard | ❌ missing | No correlation logic anywhere. |
| 14 | Slippage buffer added to SL | ⚠️ partial | `mt5_simulator.py:17-25` is post-hoc; SL itself not widened. |
| 15 | Ladder TP 40/30 at 2R/3R/4R | ✅ backtest / ⚠️ live | `src/strategy.py:33-65`. Live EA only consumes TP1 per `docs/mt5-bridge-setup.md:240-243`. |
| 16 | Scale-in alternative | ✅ backtest / ❌ live | `src/scale_in_exit.py:46-260`. Live EA does NOT support scale-in. |
| 17 | Both modes tested | ✅ | `tests/test_scale_in_exit.py` (10 tests). |
| 18 | Webhook → 11-gate → MT5 | ✅ | `gates/validator.py:55-65`, `gates/state.py:36-44`, `server.py:265-289`. |
| 19 | Telegram + Discord dispatchers | ✅ | `notify/telegram.py`, `notify/discord.py`. |
| 20 | MT5 file bridge | ✅ | `mt5_bridge/executor.py:40-50`, `signal_writer.py:160-178`. |
| 21 | Idempotency / dedup | ✅ | `db_impl.py:106-153` UNIQUE(signal_id, prefix). EA `SMC_processed.csv`. |
| 22 | Replay on bot-down | ⚠️ partial | Webhook returns 200 on duplicate; no replay queue. |
| 23 | Pre-trade checklist (manual) | 📄 documented-only | Telegram `/ack <gate>`. |
| 24 | News filter (NFP/FOMC/CPI) | 📄 documented-only | Manual gate only. No calendar API. |
| 25 | Session filter — backtest | ❌ missing | `rule-book.md:320` documents as unimplemented. |
| 26 | Session filter — live | 📄 documented-only | Trader self-attest via manual gate. |
| 27 | Time-stop / max-bars-in-trade | ❌ missing | `PartialTPExit` advances indefinitely; backtester `exit_reason="time"` is last-bar flush only. |
| 28 | Trailing stop after partial TP | ❌ missing | Only `move_sl(entry)`; never advances past entry. |
| 29 | Kill switch / flatten | ⚠️ partial | `EXECUTOR_TRANSPORT=disabled` halts new orders; does not flatten existing. No `/kill` command. |

### 9.3 FTMO breach simulation

**Yes, daily-5% trip works** but on realized equity only:

1. **Trip logic** — `src/risk_manager.py:78-90`: when `current_equity - account_size ≤ -5% × account`, guard refuses.
2. **Wired** — `src/backtester.py:578-580`, `:687-688`. `equity` is realized; partial closes update it, but unrealized P&L on open position is **NOT** included.
3. **Reset** — `src/backtester.py:478-480`.
4. **Test coverage** — **No integration test** drives `run_backtest()` into the breach. Smoke at `src/risk_manager.py:113-122` only tests guard in isolation.
5. **Total loss 10% has NO enforcement** anywhere in code.

### 9.4 Position sizing verification

`src/risk_manager.py:18-29`:
```
lot = (equity × risk_pct) / (sl_distance × pip_value)
```

For 0.5 lot / 20-pip / $100k / 0.55%: 0.5 × 20 × $10 = $100 = **0.10% of $100k** — the premise is internally inconsistent. To hit 0.55% target on 20-pip SL, lot size should be **2.75 lots**.

**Possible unit-conversion bug at `src/backtester.py:652`**: smoke `calculate_lot(100000, 0.0055, 50, 10) == 1.10` interprets `sl_distance=50` as pips; runtime passes `abs(entry - sl)` which is price units (0.0050 for 50-pip EURUSD) → 550/(0.005×10) = 11,000 lots. 100× discrepancy. Treat backtest dollar figures with skepticism until verified.

**Live cap**: EA `MaxLot=0.05` (`docs/mt5-bridge-setup.md:78`) → on demo 0.05 × 20 × $10 = $10 = 0.01% of $100k, far below 0.55% target.

### 9.5 Partial TP verification

**Both modes fully implemented in backtest:**
- Ladder `PartialTPExit` — `src/strategy.py:33-150`, stages `(2.0, 0.40), (3.0, 0.50), (4.0, 1.0)`.
- Scale-in `ScaleInExit` — `src/scale_in_exit.py:46-260`, phase1→phase2 state machine, Design A/B variants.
- Branched on `exit_mode` in backtester (`src/backtester.py:653-674`).

**Live gap (critical)**: `docs/mt5-bridge-setup.md` is unambiguous — MQL5 EA only consumes TP1; no partial closes; no scale-in leg2. Live FTMO today = single-shot close at +2R. ~50% of expected backtest PnL is unrealized.

### 9.6 News + session reality check

- **News filter**: ❌ Not implemented. `state.py:42` has `spread_news_clean` manual gate. Zero code references to NFP/FOMC/CPI/economic_calendar across `src/` and `packages/`.
- **Session filter**: ❌ Not implemented. `config.yaml:67-76` declares sessions; no code reads them. `rule-book.md:320` explicitly documents as unimplemented.

### 9.7 Critical gaps ranked

| # | Gap | Severity |
|---|---|---|
| 1 | Live MT5 only executes TP1 — backtest PnL beyond 2R unrealized | Critical |
| 2 | Floating P&L not tracked → FTMO 5% daily rule not enforced to spec | Critical |
| 3 | max_total_loss 10% not enforced anywhere | Critical |
| 4 | Session filter absent (rule-book explicitly says so) | Critical |
| 5 | News filter is manual-only | High |
| 6 | Two parallel FTMO guards with inconsistent semantics | High |
| 7 | No kill switch for flattening open positions | High |
| 8 | No time-stop | Medium |
| 9 | No trailing stop after partial TP | Medium |
| 10 | No correlation guard | Medium |
| 11 | No SL slippage buffer | Medium |
| 12 | No replay queue on bot-down | Medium |
| 13 | Profit target 10% not enforced | Medium |
| 14 | Possible unit-conversion bug at `src/backtester.py:652` | High |

### 9.8 Top recommended next actions

| # | Action | Effort |
|---|---|---|
| 1 | Wire session filter into `check_entry()` + webhook | 1 day |
| 2 | Track floating P&L in both guards | 2-3 days |
| 3 | Add max_total_loss enforcement | 1 day |
| 4 | Implement MQL5 partial TP + scale-in leg2 | 1-2 weeks |
| 5 | Unify FTMOGuard into single shared class | 1-2 days |
| 6 | Economic calendar integration + blackout | 3-5 days |
| 7 | `/kill` Telegram command + EA close_all | 2-3 days |
| 8 | Max-bars-in-trade time-stop | 1 day |
| 9 | Trailing SL after partial TP | 3-5 days |
| 10 | Integration test `tests/test_ftmo_daily_breach.py` | 1 day |
| 11 | **Verify `calculate_lot()` unit-conversion at `src/backtester.py:652`** | 0.5 day |

Top-5 effort ≈ 3 weeks. Top-10 ≈ 6 weeks (incl. MQL5).
