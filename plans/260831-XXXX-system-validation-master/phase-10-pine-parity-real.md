# Phase 10 — Pine Parity (Real Capture)

## Context

Phase 08 + 09 đã validate backtest logic. Nhưng **live bot nhận signal từ
TradingView Pine indicator**, không phải Python engine. Nếu Pine diverge
khỏi Python → bot trade strategy khác với backtest → mọi validation vô
nghĩa.

Hiện tại:
- Pine↔Python parity **tooling đã complete** (`scripts/capture-frozen-feed.py`,
  `scripts/compare-pine-parity.py`, `scripts/export-pine-parity-fixtures.py`)
- Test pass 15/15 trên **synthetic data**
- **CHƯA có real Pine capture** trong `tests/fixtures/pine-parity/`
- Label hiện tại: `parity-tooling-complete` (đã demote từ `parity-achieved`)

Plan `260831-0430-pine-parity-capture-procedure/` đã viết chi tiết procedure
nhưng chưa execute.

## Goal

Có **1 real Pine capture** cho `FXPRO:EURUSD` M15, diff clean với Python,
fix hoặc document mọi mismatch, upgrade label từ `parity-tooling-complete`
lên `parity-achieved`.

## Steps

Plan đã có sẵn ở `plans/260831-0430-pine-parity-capture-procedure/plan.md`.
Mình không duplicate spec ở đây — chỉ outline + acceptance:

### Step 1 — Pick frozen window (15 min)

Theo plan gốc, Phase 1: pick 200-500 bar window trong `data/eurusd_m15.parquet`
có ≥1 BOS, ≥1 CHoCH, ≥1 OB activation, ≥1 sweep, ≥1 FVG, ≥1 displacement.

**Recommendation:** Window đầu tháng 2024 (post-COVID, normal volatility).

### Step 2 — Generate Python reference (5 min)

Theo plan gốc, Phase 2: chạy `capture-frozen-feed.py` với window đã chọn.
Output 4 files trong `tests/fixtures/pine-parity/<run-id>/`.

**Verify:**
- `metadata.json` có `python_event_count > 0`
- `python_reference.csv` có 51 columns đầy đủ
- `pine_output.csv` là placeholder (sẽ fill ở Step 3)

### Step 3 — Capture Pine via Bar Replay (60-90 min)

**Prerequisites:**
- TradingView Premium account (Bar Replay gated)
- `tradingview/smc-engine-indicator.pine` loaded với Rulebook 8W profile
- Browser pointed at `FXPRO:EURUSD` M15

**Process:**
1. Open Bar Replay, set start = window start
2. Step through every bar (hoặc max replay speed)
3. Capture mỗi Pine `alertcondition` event (BOS/CHoCH/OB-activated/
   sweep/pool/chart-qualified/watch/blocked) vào Pine Logs
4. Parse logs → fill `pine_output.csv` với same 51 columns

**Time budget:** 200 bars × ~10s/bar (variable) = 30-60 min, +30 min parse.

### Step 4 — Diff and triage (30 min)

Run `compare-pine-parity.py`:
- `matches=True` → done, jump to Step 6
- `matches=False` → categorize mismatches:
  - Missing rows (Pine didn't fire) → fix-now
  - Extra rows (Pine fired extra) → fix-now
  - Value mismatch (float drift) → document if 1-2 ULP

Document mỗi mismatch trong `NOTES.md`:
- Category + count
- Root cause hypothesis (line number Pine hoặc Python)
- Fix action: commit fix / accept with rationale

### Step 5 — Fix or accept (60-90 min, nếu có mismatch)

For each mismatch:
1. Reproduce in isolation (dùng synthetic fixture)
2. Diagnose (compare implementations side-by-side)
3. Fix smallest change
4. Add regression test in `tests/test_pine_parity_tools.py`
5. Re-run Step 4

**Time budget:** Nếu > 90 min vẫn còn mismatch → ship what you have với
documented accepted deviations.

### Step 6 — Commit + bump parity status (15 min)

1. Commit bundle vào `tests/fixtures/pine-parity/<run-id>/`
2. Edit `docs/smc-engine-verification.md`:
   - `pine-status: parity-tooling-complete` → `pine-status: parity-achieved`
   - Honest note về actual capture
3. Re-run `pytest -q` to verify no regression

## Files involved

- `tests/fixtures/pine-parity/<run-id>/<dataset>-ohlc.csv` — new
- `tests/fixtures/pine-parity/<run-id>/<dataset>-python-reference.csv` — new
- `tests/fixtures/pine-parity/<run-id>/<dataset>-pine-output.csv` — new
- `tests/fixtures/pine-parity/<run-id>/<dataset>-metadata.json` — new
- `tests/fixtures/pine-parity/<run-id>/NOTES.md` — new
- `docs/smc-engine-verification.md` — bump label v1.3 → v1.4
- `tradingview/smc-engine-indicator.pine` — only if fix-now required
- `packages/smc_engine/src/smc_engine/*.py` — only if fix-now required

## Todo

- [ ] Pick frozen window (Step 1)
- [ ] Generate Python reference (Step 2)
- [ ] Capture Pine via Bar Replay (Step 3) — **manual, 60-90 min focused**
- [ ] Diff + triage (Step 4)
- [ ] Fix or accept mismatches (Step 5)
- [ ] Commit + bump parity status (Step 6)
- [ ] Update master plan status

## Success criteria

- `tests/fixtures/pine-parity/<run-id>/` exists với 5 files (4 data + NOTES.md)
- `compare-pine-parity.py` returns `matches=True` OR NOTES.md documents
  mọi mismatch với rationale
- `docs/smc-engine-verification.md` shows `pine-status: parity-achieved`
  (hoặc `parity-achieved-with-N-deviations`)
- Full pytest suite green

## Risk

- **Bar Replay takes long** — 60-90 min focused. Mitigation: pick smallest
  window that exercises all event types.
- **Pine Logs format drift** — TradingView có thể thay đổi format.
  Mitigation: parser script có fallback manual entry.
- **Float tolerance creep** — không bump `--abs-tol` để silence real bugs.
  Document per-column tolerances trong NOTES.md.
- **No Pine fix possible** — nếu root cause là Pine semantic không map được
  sang Python (vd `barstate.isconfirmed` khác `confirmed_bar_only`), accept
  với rationale + add regression test chỉ trên Python side.

## Out of scope

- Multi-pair parity (XAUUSD, BTCUSD) — defer
- Multi-timeframe parity (H1, H4, D) — defer
- Automated nightly parity diff — future plan

## Next steps

Phase 11 — Multi-pair + Regime.
