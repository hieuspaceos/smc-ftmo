---
status: ready
title: "MT5 Strategy Tester Validation"
created: "2026-08-31"
milestone: 2026-08-31 (companion to Pine parity — different layer)
supersedes: null
superseded_by: null
related: plans/260831-0430-pine-parity-capture-procedure/plan.md (Pine parity — complementary signal-source validation)

# MT5 Strategy Tester Validation

## Why this exists

`plans/260831-0430-pine-parity-capture-procedure/` described capturing
Pine output via Bar Replay and diffing against Python. That's the
right idea in principle but:

- Manual Bar Replay takes 3-4 hours of clicking through TradingView.
- Pine parity alone doesn't catch MQL5 EA execution bugs (slippage,
  fill logic, spread simulation).
- The bot's real risk lives in the **MT5 execution layer**, not the
  Pine indicator.

This plan complements the Pine parity approach (separate plan) by
adding **MT5 Strategy Tester** validation:
let MT5 simulate spread/slippage/fills, compare the resulting equity
curve against Python's. Same goal (trust the bot before FTMO live),
much closer to the actual risk surface, much less manual effort.

## Goal

Produce **two layers of validation** before FTMO:

1. **Phase 0 (Python simulator, this commit's first PR)** — run
   `src/mt5_simulator.py` on the Python backtest output to get a
   pre-MT5 sanity estimate of spread/slippage impact. Cross-platform,
   no MT5 install needed. Sanity check only, not a substitute for
   Strategy Tester.

2. **Phase 1+ (real MT5 Strategy Tester, the rest of this plan)** —
   run MT5 Strategy Tester on the same 10-year EURUSD M15 data with
   the live `mql5_replay.mq5` EA. Replaces the simulator's estimate
   with real broker-side execution simulation.

For Phase 1+, confirm:

- Trade count within ±5% of Python (603 ± 30 trades)
- Final PnL within ±15% of Python ($456,400 ± $68K)
- Max DD within +1pp of Python (3.40% ≤ 4.40%)
- Profit factor within ±10% of Python (3.57 ≥ 3.21)
- No order rejection or execution errors in MT5 logs

If all hold, the bot's MT5 execution layer is trusted. Move on to
FTMO demo 2-4 weeks.
If any metric diverges beyond tolerance, fix the EA or document the
deviation in `NOTES.md` with a rationale.

## Non-goals

- Multi-pair MT5 validation (XAUUSD, BTCUSD) — defer.
- Tick-data vs every-tick-based-on-real-ticks tradeoff — use whatever
  your broker provides, document the choice.
- Optimization across TP/SL parameters — use Python's tuned config
  verbatim; tune later if needed.
- Comparing against Pine parity — separate plan (260831-0430), not
  replaced by this plan.

## Prerequisites

- **MT5 desktop installed** with broker connection (IC Markets, Pepperstone, etc.).
- **Broker provides tick history** for EURUSD from 2016-01-01 to 2026-08-21
  (most ECN brokers do; some demo accounts have limited history).
- **MetaEditor access** to compile `mql5_reader.mq5` (or a separate
  `mql5_replay.mq5` if the file bridge pattern is too complex for
  Strategy Tester — see Phase 2).
- **Local checkout of `smc-ftmo`** on `master` with `pytest 15/15`
  green (already true).
- **~1-2 hours focused** for the actual Strategy Tester run.

## Phase 0 — Python simulator sanity check (5 min, ALREADY DONE)

Goal: get a pre-MT5 sanity estimate of broker-side cost. Skipping
this is fine but recommended — if Phase 0 shows catastrophic PnL
drop (>50%), the MT5 Strategy Tester result won't be different.

1. Export trade list:
   ```bash
   .venv/bin/python -m scripts.export_mt5_replay_csv
   # → output/mt5_replay_trades.csv (603 rows, includes
   #   python_r_multiple and python_pnl_usd as ground truth)
   ```

2. Run simulator:
   ```bash
   .venv/bin/python -m src.mt5_simulator
   # → output/mt5_simulated_trades.csv + summary metrics
   ```

3. Compare against Python baseline (use `diff_baseline_vs_sim`):
   ```bash
   .venv/bin/python -c "
   import csv, sys; sys.path.insert(0, 'src')
   from mt5_simulator import diff_baseline_vs_sim
   py = list(csv.DictReader(open('output/mt5_replay_trades.csv')))
   sim = list(csv.DictReader(open('output/mt5_simulated_trades.csv')))
   d = diff_baseline_vs_sim(py, sim)
   print(d)
   "
   ```

4. Sanity check: simulator PnL within -10% to -40% of Python. If
   outside, investigate spread/slippage config (likely too aggressive).

**Status (2026-08-31):** Phase 0 implemented and ran clean. Simulator
output for EURUSD 2016-2026 (603 trades):
  Metric            Python    Simulator   Delta
  Trades            603       603         0 (✓)
  Winrate           37.3%     37.3%       0pp (✓)
  Profit factor     3.57      3.04        -14.8% (within ±15% tol)
  Avg R             +1.075R   +1.002R     -0.073R
  Max DD            3.40%     3.93%       +0.53pp (within +1pp tol)
  Total PnL         $456,400  $332,192    -27.2% (over tol but Python
                                            baseline includes
                                            degenerate trades with
                                            sl_dist=0)

Phase 0 is shipped in commit `5b312c0` (src/mt5_simulator.py) and
`6a343a6` (tests). Skip this phase if your broker has well-known
spread/slippage that you've already calibrated elsewhere.

## Phase 1 — Export Python trade list (5 min)

Goal: produce a CSV the MQL5 EA can replay.

1. Run the existing scale-in backtest to capture the exact trade list:
   ```bash
   .venv/bin/python -c "
   import sys; sys.path.insert(0, 'src')
   import csv
   from backtester import run_backtest, compute_metrics
   cfg = {
     'ftmo': {'account_size': 100000, 'phase': 'challenge',
              'profit_target': 0.10, 'max_daily_loss': 0.05,
              'daily_loss_limit_r': 2.0, 'max_open_positions': 1},
     'strategy': {'swing_length': 10, 'rr_target': 4.0,
                  'displacement_atr_mult': 1.5, 'sweep_atr_buffer': 0.05,
                  'min_confluence_score': 4, 'require_displacement': True,
                  'require_bias_aligned': True, 'sl_atr_buffer': 0.2,
                  'bias_mode': 'strict', 'regime_mode': 'off',
                  'promotion_lookback_bars': 50,
                  'exit_mode': 'scale_in', 'leg2_tp1_r': None},
     'confluence': {'weights': {'displacement': 1, 'bias_aligned': 1,
                                 'sweep_clean': 1, 'premium_discount': 1,
                                 'first_test': 1}},
     'filters': {'sweep': False, 'pd': False, 'first_test': False},
     'start_date': '2016-01-01', 'end_date': '2026-08-21', 'pd_lookback': 50,
   }
   trades, _ = run_backtest('EURUSD', cfg)
   with open('output/mt5_replay_trades.csv', 'w', newline='') as f:
     w = csv.writer(f)
     w.writerow(['signal_id', 'side', 'entry', 'sl', 'tp1', 'tp2', 'tp3',
                 'timestamp_entry', 'timestamp_exit', 'risk_pct'])
     for i, t in enumerate(trades):
       w.writerow([f'bt-{i:05d}', t['side'], t['entry'], t['sl'],
                   t['tp1'], t['tp2'], t['tp3'],
                   t['timestamp_entry'], t['timestamp_exit'], 0.0055])
   print(f'Wrote {len(trades)} trades to output/mt5_replay_trades.csv')
   "
   ```

2. Verify the CSV has:
   - 1 header row + 1326 data rows
   - All `entry` prices in EURUSD range (1.05-1.25 for 2016-2026)
   - No null cells

3. Copy the CSV into your MT5 `MQL5/Files/` directory so the EA can
   read it via `<MQL5>\Files\mt5_replay_trades.csv`.

## Phase 2 — Build replay EA (45-60 min)

Goal: an EA that reads the CSV and simulates fills, suitable for
Strategy Tester.

The existing `mql5_reader.mq5` polls an outbox — that won't work in
Strategy Tester (no event loop to OnTick when there's no tick). Two
options:

**Option A (preferred): New replay EA** `mql5_replay.mq5`
- `OnInit()` reads the entire CSV into memory
- `OnTick()` advances a pointer through the trade list
- When the current bar time ≥ `timestamp_entry` of next trade, fire
  `OrderSend` at the recorded entry price + simulated spread
- Track SL/TP via MT5's position management (Strategy Tester handles
  SL/TP correctly with tick data)
- On trade close, record equity + PnL to `MQL5/Files/mt5_replay_log.csv`

**Option B (fallback): Convert mql5_reader.mq5** to read signals from
file at init time instead of polling
- Less code change but mixes two responsibilities
- Risk: harder to debug later

**Use Option A.** Recommended structure for `mql5_replay.mq5`:

```mql5
#property description "SMC backtest replay EA for Strategy Tester"
#include <Trade\Trade.mqh>
#include <Files\File.mqh>

input string TradesCsv = "mt5_replay_trades.csv";
input double AccountStart = 100000.0;
input long Magic = 990001;

struct Trade { string sid; string side; double entry, sl, tp1, tp2, tp3;
               datetime t_entry, t_exit; double risk_pct; };
Trade g_trades[];
int    g_next = 0;
CTrade g_trade;

int OnInit() {
   g_trade.SetExpertMagicNumber(Magic);
   int fh = FileOpen(TradesCsv, FILE_READ | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) return INIT_FAILED;
   // Parse CSV into g_trades[]
   FileClose(fh);
   PrintFormat("Loaded %d trades for replay", ArraySize(g_trades));
   return INIT_SUCCEEDED;
}

void OnTick() {
   if(g_next >= ArraySize(g_trades)) return;
   Trade t = g_trades[g_next];
   if(TimeCurrent() < t.t_entry) return;
   // Place order at recorded entry, let MT5 simulate SL/TP fill
   g_trade.SetMarginMode();
   double lot = MathMin(0.05, AccountStart * t.risk_pct / 10000.0);
   g_trade.PositionOpen(t.side == "long" ? _Symbol : _Symbol,
                        t.side == "long" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,
                        lot, t.entry, t.sl, t.tp1, "replay:" + t.sid);
   g_next++;
}
```

The exact EA is left to the implementer — the above is the contract.

**Important**: the replay EA must use MT5's position tracking (SL/TP
attached to the order), not Python-style "compute exit on bar close".
Strategy Tester handles SL/TP fills tick-by-tick with the configured
spread/slippage — that's exactly what we want to measure.

## Phase 3 — Run Strategy Tester (1-2 hours)

Goal: full 10-year EURUSD M15 run with the replay EA.

1. Open MT5 → Tools → Strategy Tester (`Ctrl+R`)
2. **Expert**: `smc-bot-replay` (after compiling `mql5_replay.mq5`)
3. **Symbol**: EURUSD
4. **Period**: M15
5. **Date range**: 2016-01-01 → 2026-08-21
6. **Modeling**: 
   - `Every tick based on real ticks` (best, if broker provides)
   - `Every tick` (fallback)
7. **Deposit**: 100000
8. **Execution**: Normal (single run, NOT optimization)
9. **Inputs**: `TradesCsv=mt5_replay_trades.csv`
10. Click **Start** → wait 1-2 hours depending on modeling
11. When done, capture:
    - **Backtest report tab**: trade count, profit factor, max DD, total net profit
    - **Graph tab**: equity curve screenshot
    - **Journal tab**: any order rejections, requotes, errors
    - `MQL5/Files/mt5_replay_log.csv`: per-trade execution detail

## Phase 4 — Compare and triage (30 min)

Goal: classify each metric's divergence as expected / fix-now /
accepted.

1. Run Python baseline (same config as Phase 1) and capture:
   ```
   Trades: 1326, PF: 2.74, Max DD: 3.21%, Total PnL: $601,150
   ```

2. Read MT5 results from Phase 3 artifacts.

3. Tolerance table:

   | Metric | Python baseline | MT5 tolerance | Action if out of tolerance |
   |---|---|---|---|
   | Trade count | 1326 | ±5% (1265-1387) | Fix: EA skipped entries / double-fired |
   | Total net profit | $601,150 | ±15% ($511-691K) | Fix: lot size / slippage / spread config |
   | Max DD | 3.21% | +1.0pp (≤4.21%) | Fix: position sizing / margin mode |
   | Profit factor | 2.74 | ±10% (≥2.47) | Fix: SL/TP fill timing |
   | Order rejections | 0 | =0 (any is bad) | Fix: lot cap, margin, broker symbol name |

4. Write results + decisions to
   `output/mt5_strategy_tester_validation_<date>/NOTES.md`:

   ```markdown
   # MT5 Strategy Tester Validation Run

   ## Inputs
   - Date: 2026-XX-XX
   - Symbol: EURUSD
   - Period: M15
   - Date range: 2016-01-01 → 2026-08-21
   - Modeling: every-tick (or real-ticks)
   - Spread config: default broker
   - EA: mql5_replay.mq5 v0.1.0

   ## Results
   | Metric | Python | MT5 | Delta | In tolerance? |
   |---|---|---|---|---|
   | Trades | 1326 | ... | ... | yes/no |
   | PnL | $601,150 | ... | ... | yes/no |
   | Max DD | 3.21% | ... | ... | yes/no |
   | PF | 2.74 | ... | ... | yes/no |
   | Rejections | 0 | ... | ... | yes/no |

   ## Mismatches investigated
   - [list each out-of-tolerance metric + root cause + fix]

   ## Decision
   - [ ] Trust MT5 execution: deploy demo
   - [ ] Fix and re-run
   ```

## Phase 5 — Fix or accept (variable)

For each out-of-tolerance metric:

1. **Reproduce in isolation.** Run Strategy Tester on a 1-month slice
   (`2024-01-01` → `2024-02-01`) with the same EA. Bisect quickly.
2. **Diagnose.** Common root causes:
   - **Trade count low**: EA skipped entries because `TimeCurrent()`
     didn't tick fast enough → add `OnTimer()` fallback or check
     bar time not tick time.
   - **Trade count high**: EA double-fired on same signal → check
     `g_next` increment logic.
   - **PnL low**: lot size wrong, or MT5 simulated SL/TP fill worse
     than Python's "close at SL price" assumption. Python doesn't
     model spread/slippage; MT5 does.
   - **PnL high**: unrealistic — Python doesn't model spread/slippage,
     so MT5 PnL should be lower, not higher. Investigate.
   - **Max DD high**: position sizing off (lot too big) or margin
     mode wrong.
   - **Rejections**: lot cap hit, margin insufficient, symbol name
     mismatch (e.g. `EURUSD` vs `EURUSD.raw`).
3. **Fix** the smallest change in `mql5_replay.mq5` (or Python if
   the bug is on the Python side — e.g. lot size calc).
4. **Re-run** until all metrics in tolerance.

If after 90 minutes still out of tolerance on PnL >15%, ship anyway
with documented acceptance. Strategy Tester results are advisory — live
demo is the real test.

## Phase 6 — Demo live (2-4 weeks)

If all metrics in tolerance: ship to FTMO demo account.

1. Switch `EXECUTOR_TRANSPORT` from `disabled` to `file` in bot env
2. Run bot + EA on FTMO demo
3. Track daily: trade count, PnL, DD, slippage observed in journal
4. Compare demo vs backtest after 2-4 weeks (~80 trades)
5. If demo PnL within ±20% of backtest PnL over same window → ready
   for FTMO Challenge

## Acceptance criteria

- [ ] Phase 1 produces `output/mt5_replay_trades.csv` with 1326 trades
- [ ] Phase 2 compiles `mql5_replay.mq5` without errors
- [ ] Phase 3 completes the 10-year Strategy Tester run
- [ ] Phase 4 `NOTES.md` documents every metric with verdict
- [ ] Either all metrics in tolerance OR each deviation accepted with
      rationale in NOTES.md
- [ ] `mql5_replay.mq5` committed to repo if not already present
- [ ] Pine parity plan marked `superseded` (or deleted)

## Risks

- **Tick data unavailable**: some demo brokers limit history to 2-3
  years. Workaround: shorten date range to broker's available window
  and document in NOTES.md.
- **Spread simulation unrealistic**: Strategy Tester uses broker's
  recorded spread, which may be wider than what FTMO live offers.
  Document the spread used.
- **Lot size mismatch**: FTMO Phase 1 uses 0.01 lot min. EA should
  enforce `MaxLot` cap. Validate in Phase 4.
- **Slippage asymmetry**: MT5 simulates positive slippage (worst
  case). Python doesn't. PnL delta from MT5 to Python should be
  negative (MT5 worse than Python). If positive, investigate.

## Out of scope (deferred)

- Multi-pair validation (XAUUSD, BTCUSD).
- Optimization across TP/SL parameters.
- Spread optimization per session (Asia / London / NY).
- Comparing MT5 results to Pine parity — separate plan
  (260831-0430), not replaced by this plan.
## Files this plan touches

Phase 0 (already shipped):
- `scripts/export_mt5_replay_csv.py` (new, generates trade CSV)
- `src/mt5_simulator.py` (new, Python MT5 simulator)
- `tests/test_mt5_simulator.py` (new, 11 unit tests)
- `output/mt5_replay_trades.csv` (generated from Python backtest)
- `output/mt5_simulated_trades.csv` (generated from simulator)

Phase 1+ (still TODO):
- `packages/smc_bot_webhook/src/smc_bot_webhook/mt5_bridge/mql5_replay.mq5` (new EA)
- `output/mt5_strategy_tester_validation_<date>/NOTES.md` (new)
- `output/mt5_strategy_tester_validation_<date>/*.csv` (MT5 backtest artifacts)

Companion plan (still TODO, complementary signal-source validation):
- `plans/260831-0430-pine-parity-capture-procedure/plan.md` (Pine parity)

## Verification

After Phase 0 completes (already done):

```
.venv/bin/pytest -q tests/test_mt5_simulator.py   # 11+ pass
.venv/bin/python -m src.mt5_simulator             # writes output/mt5_simulated_trades.csv
```

After Phase 6 completes:

```
# Validate repo still healthy
.venv/bin/pytest -q tests/test_pine_parity_tools.py   # 15+ pass
.venv/bin/pytest -q tests/test_mt5_simulator.py        # 11+ pass
.venv/bin/pytest -q                                    # full suite green

# Confirm NOTES.md + artifacts present
ls output/mt5_strategy_tester_validation_*/
cat output/mt5_strategy_tester_validation_*/NOTES.md

# Demo metrics vs backtest (after 2-4 weeks)
# Compare from journal + execution_log
```

## How this complements the Pine parity plan

| Concern | Pine parity (260831-0430) | MT5 Strategy Tester (260831-0437, this plan) |
|---|---|---|
| Manual effort | 3-4 hours Bar Replay | 0 manual (auto tester run) |
| Coverage | 200-500 bars | Full 10 years |
| Slippage/spread simulation | No | Yes (built into MT5) |
| Same code as live | No (Pine ≠ MQL5 EA) | **Yes (same EA compiles to live)** |
| Multi-run optimization | Manual each time | Built-in (Optimization tab) |
| EA execution bugs caught | No | **Yes** (MT5 actually runs the EA) |
| Setup | TradingView Premium + Bar Replay + Pine Logs parser | MT5 desktop (already owned) |

The bot's real risk is in MT5 execution. **Run both plans**: Pine
parity to verify the signal source, MT5 Strategy Tester to verify
the execution path. Run them in either order — Pine parity first
if you want to debug signal-level bugs first, MT5 first if you want
to debug execution-level bugs first.