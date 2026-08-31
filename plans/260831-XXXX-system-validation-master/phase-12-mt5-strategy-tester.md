# Phase 12 — MT5 Strategy Tester (Real Run)

## Context

Phases 08-11 đã validate Python backtest + Pine parity + multi-pair + regime.
**Nhưng còn 1 layer nữa**: MT5 execution layer — broker-side spread/slippage/
fills/requotes/margin mode.

Hiện tại:
- `src/mt5_simulator.py` (Phase 0) là Python post-hoc penalty, không re-walk
  bars
- Live bot's MQL5 EA `mql5_reader.mq5` chỉ là file-bridge transport, không
  simulate execution
- **CHƯA có MT5 Strategy Tester run** với replay EA

Plan `260831-0437-mt5-strategy-tester-validation/` đã viết chi tiết procedure
(Phases 1-4) nhưng chưa execute.

## Goal

Chạy MT5 Strategy Tester trên full 10 năm EURUSD M15 với replay EA, so sánh
5 metrics với Python baseline. Nếu trong tolerance → trust MT5 execution
layer. Move on Track C.

## Steps

Plan đã có sẵn ở `plans/260831-0437-mt5-strategy-tester-validation/plan.md`.
Mình không duplicate spec — chỉ outline + acceptance:

### Step 1 — Export Python trade list (5 min)

Theo plan gốc Phase 1: chạy scale_in backtest, export trades thành
`output/mt5_replay_trades.csv` (603 rows + header).

**Verify:**
- 603 rows (matches Phase 08 baseline)
- Columns: `signal_id, side, entry, sl, tp1, tp2, tp3, timestamp_entry,
  timestamp_exit, risk_pct`
- Entry prices trong range EURUSD 2016-2026 (1.05-1.25)

### Step 2 — Build replay EA (45-60 min)

Theo plan gốc Phase 2: tạo `mql5_replay.mq5` (Option A — preferred).
Recommended structure đã có trong plan:
- `OnInit()`: đọc CSV vào memory
- `OnTick()`: advance pointer, fire `OrderSend` khi `TimeCurrent() ≥ t_entry`
- Track SL/TP qua MT5 position management

**Compile:** MetaEditor → build → verify no errors.

### Step 3 — Run Strategy Tester (1-2 hours)

Theo plan gốc Phase 3:
- Expert: `smc-bot-replay` (compiled EA)
- Symbol: EURUSD
- Period: M15
- Date range: 2016-01-01 → 2026-08-21
- Modeling: `Every tick based on real ticks` (nếu broker hỗ trợ) hoặc
  `Every tick` (fallback)
- Deposit: 100000
- Inputs: `TradesCsv=mt5_replay_trades.csv`

**Capture:**
- Backtest report tab: trade count, PF, max DD, total net profit
- Graph tab: equity curve screenshot
- Journal tab: order rejections, requotes, errors
- `MQL5/Files/mt5_replay_log.csv`: per-trade execution detail

### Step 4 — Compare and triage (30 min)

Theo plan gốc Phase 4. Tolerance table:

| Metric | Python baseline | MT5 tolerance | Action if out |
|---|---|---|---|
| Trade count | 603 | ±5% (573-633) | Fix EA skipped/double-fired |
| Total net profit | varies (Phase 08 v2) | ±15% | Fix lot size / slippage / spread config |
| Max DD | varies | +1.0pp | Fix position sizing / margin mode |
| Profit factor | varies | ±10% | Fix SL/TP fill timing |
| Order rejections | 0 | =0 | Fix lot cap / margin / symbol name |

**Acceptance:**
- All 5 metrics trong tolerance
- 0 order rejections
- Write results to
  `output/mt5_strategy_tester_validation_<date>/NOTES.md`

### Step 5 — Fix or document deviations (variable time)

If any metric out of tolerance:
1. **Fix-now:** Modify EA, recompile, re-run Strategy Tester
2. **Fix-later:** Open GitHub issue, document in NOTES.md
3. **Accept:** Document rationale (vd broker-specific spread widening
   hours, slippage profile)

### Step 6 — Commit + verdict (15 min)

1. Commit EA source + CSV + NOTES.md
2. Update `docs/mt5-bridge-setup.md` với reference tới validation run
3. Track B verdict: **MT5 execution layer trusted** OR
   **deviations documented, defer to Track C for monitoring**

## Files involved

**Create:**
- `packages/smc_bot_webhook/mql5/mql5_replay.mq5` — new EA
- `output/mt5_replay_trades.csv` — Python trade export
- `output/mt5_strategy_tester_validation_<date>/report.xml` — MT5 export
- `output/mt5_strategy_tester_validation_<date>/NOTES.md` — verdict
- `output/mt5_strategy_tester_validation_<date>/equity_curve.png` — chart

**Modify:**
- `docs/mt5-bridge-setup.md` — add reference to validation run
- `plans/260831-0437/plan.md` — update status từ `ready` → `done`

## Prerequisites

- MT5 desktop installed with broker connection
- Broker provides tick history for EURUSD 2016-01-01 → 2026-08-21
- MetaEditor access for compiling MQL5
- ~2-3 hours focused time

## Todo

- [ ] Export Python trade list (Step 1)
- [ ] Build + compile `mql5_replay.mq5` (Step 2)
- [ ] Run Strategy Tester, capture results (Step 3)
- [ ] Compare vs Python baseline, triage (Step 4)
- [ ] Fix/document deviations (Step 5)
- [ ] Commit + update docs (Step 6)
- [ ] Update master plan status

## Success criteria

- `output/mt5_strategy_tester_validation_<date>/NOTES.md` exists
- All 5 metrics trong tolerance (or documented deviations)
- 0 order rejections
- Equity curve plot saved
- `plans/260831-0437/plan.md` status updated

## Risk

- **Broker không có tick history 10 năm** — fallback `Every tick` modeling
  widening tolerance ±20%.
- **EA bugs** (lot cap, magic number, margin mode) → first run thường fail,
  iteration cần thiết.
- **Modeling choice** — `Every tick based on real ticks` mới thực sự simulate
  spread/slippage; `Every tick` thì gần như perfect fill.
- **Time** — Strategy Tester full 10 năm M15 = 1-2 giờ. Mitigation: đầu tư
  laptop riêng, không multitask.

## Out of scope

- Multi-pair MT5 validation (XAUUSD, BTCUSD) — defer
- Tick-data vs every-tick tradeoff — use whatever broker cung cấp
- Optimization across TP/SL parameters — use Python's tuned config verbatim

## Next steps

Track B done. Viết Track C plan (live validation: FTMO demo + journal +
adherence metric + go/no-go gate).
