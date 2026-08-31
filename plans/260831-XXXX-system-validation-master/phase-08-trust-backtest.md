# Phase 08 — Trust Backtest

## Context

Track A (`260831-1036-bot-audit-fixes`) done 2026-08-31 với tag
`v0.4.0-audit-fixed`. Bot đã operational-safe (308 webhook tests pass, 0
regressions).

Bây giờ cần **tin lại backtest** trước khi bỏ tiền thật vào FTMO challenge.
Audit (`plans/reports/260831-trading-system-audit.md`) tìm thấy **5 gap
làm backtest hiện tại không realistic + 1 critical bug confirmed**:

| Gap | Severity | Evidence (verified 2026-08-31) |
|---|---|---|
| **calculate_lot unit-conversion bug** (smoke uses pips, runtime passes price → 100× discrepancy) | 🔴 **Confirmed bug** | `src/risk_manager.py:15-31` (function) vs `src/backtester.py:652` (call site) vs `src/risk_manager.py:93` (smoke `assert calculate_lot(100000, 0.0055, 50, 10) == 1.10`). Smoke expects `sl_distance=50` = pips; runtime passes `abs(entry - sl)` = price (0.0050 for 50-pip EURUSD). **100× off — toàn bộ backtest USD figures vô nghĩa.** |
| No spread in core backtester | High | `src/backtester.py` không đọc spread config |
| No commission in core backtester | Medium | `src/backtester.py` không đọc commission config |
| Same-bar-close entry (không next-bar-open) | Medium | `src/backtester.py:642-689` |
| Session hardcoded `"london"` cho mọi trade | Critical | `src/backtester.py:626, 723` (per audit) |

## Goal

Biến backtest từ **"broker-perfect-fill assumption"** thành **"realistic
broker execution"** đủ để:
- So sánh apples-to-apples với MT5 Strategy Tester (Phase 12)
- Tin được PnL trước khi trust live (Track C)
- Confidence ≥ 80% rằng live sẽ không diverge quá 30% so với backtest

## Pre-work: re-baseline (BẮT BUỘC sau Step 1)

**Vấn đề:** Sau khi fix `calculate_lot` bug ở Step 1, tất cả backtest dollar
figures trước đó (PF 3.57, $456K, etc) sẽ thay đổi. Cần rerun tất cả
`scripts/btest_*.py` để có baseline mới.

**Action:** Tạo `output/baselines_pre_step2.md` snapshot TẤT CẢ backtest
output TRƯỚC khi touch Step 2-4. Đây là reference để so sánh "with execution
realism" vs "perfect fill assumption" ở Step 2.

```bash
mkdir -p output/baselines_pre_step2
python -m scripts.btest_10y > output/baselines_pre_step2/btest_10y.txt 2>&1
python -m scripts.btest_scale_in > output/baselines_pre_step2/btest_scale_in.txt 2>&1
# ... other btest_*.py scripts
```

## Steps

### Step 1 — Verify & fix calculate_lot bug (30 min) 🔴 CRITICAL

**Verify (already done 2026-08-31):**
- `src/risk_manager.py:15-31` defines `calculate_lot(account_equity, risk_pct,
  sl_distance, pip_value)`.
- Smoke test `src/risk_manager.py:93`: `assert calculate_lot(100000, 0.0055,
  50, 10) == 1.10` — interprets `sl_distance=50` as pips.
- Runtime call `src/backtester.py:652`: passes `sl_dist = abs(entry_info["entry"]
  - entry_info["sl"])` — which is price units (0.0050 for 50-pip EURUSD).
- → 100× discrepancy. `calculate_lot(100000, 0.0055, 0.0050, 10) = 550/(0.005*10)
  = 11,000 lots`. Backtest đang trade ở 11,000 lots thay vì 1.10 lots.

**Fix tại `src/backtester.py:648-652`:**
```python
# Before:
sl_dist = abs(entry_info["entry"] - entry_info["sl"])
if sl_dist <= 0:
    equity_curve.append((ts, equity))
    continue
lot = calculate_lot(account_size, risk_per_trade, sl_dist, pip_value)

# After (explicit pips conversion):
sl_dist_price = abs(entry_info["entry"] - entry_info["sl"])
if sl_dist_price <= 0:
    equity_curve.append((ts, equity))
    continue
sl_dist_pips = sl_dist_price / pip_size  # pip_size = 0.0001 for EURUSD
lot = calculate_lot(account_size, risk_per_trade, sl_dist_pips, pip_value)
```

**Regression test** (`tests/test_position_sizing_units.py`):
```python
from src.risk_manager import calculate_lot


def test_calculate_lot_uses_pips_not_price():
    """50-pip SL on EURUSD = 0.0050 price, should give 1.10 lots."""
    # Verify smoke value still works
    assert calculate_lot(100000, 0.0055, 50, 10) == 1.10
    # Verify price-distance value also gives 1.10 (if properly converted)
    # Caller should convert price → pips BEFORE calling calculate_lot
    price_dist = 0.0050  # 50 pips
    pip_size = 0.0001
    pips = price_dist / pip_size
    assert calculate_lot(100000, 0.0055, pips, 10) == 1.10


def test_calculate_lot_min_lot():
    """Sub-minimum risk should floor at 0.01 lot."""
    # Tiny risk amount → 0.005 lots → floor to 0.01
    result = calculate_lot(100000, 0.0001, 100, 10)
    assert result == 0.01
```

**Commit:**
```
fix(backtest): convert sl_distance to pips before calculate_lot call

Bug: src/backtester.py:648 passes price-distance (0.0050 for 50-pip SL)
directly to calculate_lot(), but the function expects pips. Result: lot
sized 100× larger than intended (e.g. 11000 lots vs 1.10 lots on EURUSD
50-pip SL). Toàn bộ backtest USD figures vô nghĩa.

Fix: divide price-distance by pip_size (0.0001 EURUSD) before calling.

Add tests/test_position_sizing_units.py with 2 regression cases.
```

### Step 2 — Add spread + commission to core backtester (2-3 ngày)

**Config additions** (`config.yaml`):
```yaml
execution:
  spread_pips:
    EURUSD: 0.5
    XAUUSD: 2.0
    BTCUSD: 5.0
  commission_per_lot_per_side: 3.5  # FTMO standard
  slippage_pips:
    mean: 0.1
    std: 0.3
```

**Code changes:**

1. `src/backtester.py`:
   - `run_backtest(pair, config)` đọc `config['execution']`
   - Trừ spread khỏi entry price (long: entry = ask = mid + spread/2;
     short: entry = bid = mid - spread/2)
   - Cộng slippage vào SL price (long: SL fill tệ hơn = SL + slippage;
     short: tương tự)
   - Trừ commission từ realized PnL mỗi khi đóng vị thế
2. `src/strategy.py` (`PartialTPExit`):
   - Stage hits phải tính từ raw price → trừ spread trước khi compare R
3. `src/scale_in_exit.py` (`ScaleInExit`):
   - Same — R calc phải account for spread at each TP level

**Tests** (`tests/test_execution_realism.py`):
- Spread 0.5 pip EURUSD → long entry thực tế = entry + 0.00005
- Commission $3.5/lot/side → PnL giảm $7 cho 1 lot round-trip
- Slippage 0.3 pip Gaussian → 100 trades, average slippage ~0.3 pip
- Partial TP: stage 2 hit at +2R → realized price = tp_price - spread

**Verification:**
1. Run `btest_10y.py` với execution realism ON
2. So sánh với `output/baselines_pre_step2/btest_10y.txt`:
   - Trade count: giữ nguyên (signal logic không đổi)
   - Winrate: giữ nguyên (spread/slippage ăn cả win lẫn loss)
   - Total R: giảm ~5-10% (cost)
   - Total USD: giảm ~25-35% (commission + spread hit hard)
   - Max DD: tăng ~0.5-1pp
3. Nếu PnL âm → investigate (spread/commission quá aggressive hoặc
   position sizing sai)

### Step 3 — Move entry to next-bar-open (1 ngày)

**Code change** tại `src/backtester.py:642-689`:

```python
# Before (same-bar-close):
if can_trade and entry_allowed:
    entry_info = check_entry(snapshot)
    if entry_info is not None:
        ... open position at entry_info["entry"] ...

# After (next-bar-open):
if can_trade and entry_allowed:
    entry_info = check_entry(snapshot)
    if entry_info is not None:
        # Defer entry to next bar's open price
        if i + 1 < len(df_m15):
            next_open = df_m15["open"].iloc[i + 1]
            entry_price = next_open + (spread_pips / 2) * pip_size  # long
        else:
            # Last bar — skip
            equity_curve.append((ts, equity))
            continue
        ... open position at entry_price ...
```

**Edge case:** Nếu bar i+1 không tồn tại → skip entry.

**Test** (`tests/test_next_bar_open_entry.py`):
- Signal tại bar i → entry thực tế = open của bar i+1 + spread/2
- Nếu bar i+1 không tồn tại → entry = None (skip)

**Verification:** Total trades giảm nhẹ (~1-2%) vì một số signals sẽ
không fill được ở bar tiếp theo.

### Step 4 — Tag trades by real session (2-3 ngày)

**Code changes:**

1. Tạo `src/session_filter.py` (NEW):
   ```python
   def get_session(ts_utc: pd.Timestamp, sessions_cfg: dict) -> str:
       h = ts_utc.hour
       for name, window in sessions_cfg.items():
           if window["start_utc"] <= h < window["end_utc"]:
               return name
       return "off_session"
   ```

2. `src/backtester.py`:
   - Tính session từ `ts.hour` (UTC) theo config
   - Trong `check_entry()`: skip nếu `session not in config['active_sessions']`
   - Trade dict: dùng `session` thật thay vì hardcoded `"london"`

3. Update `config.yaml` sessions với UTC bounds:
   ```yaml
   sessions:
     asia:     {start_utc: 0,  end_utc: 7}    # ~Asia session
     london:   {start_utc: 7,  end_utc: 12}   # ~London
     new_york: {start_utc: 12, end_utc: 17}   # ~NY
     overlap:  {start_utc: 13, end_utc: 17}   # London+NY overlap
   active_sessions: [london, new_york, overlap]
   ```

**Tests** (`tests/test_session_filter.py`):
- 03:00 UTC → 'asia'
- 08:00 UTC → 'london'
- 14:00 UTC → 'overlap' (matches both NY and overlap, prefer overlap)
- 22:00 UTC → 'off_session'
- Backtest với `active_sessions=[london, new_york, overlap]` → giảm ~40%
  trades (asia + off_session bị filter)

**Verification:**
- Trade count giảm ~40% (asia + off_session bị filter)
- PnL giảm ít hơn 40% (asia có winrate thấp hơn → filter bỏ trades xấu)
- Per-session breakdown trong output CSV: london/NY/overlap chiếm 100% trades

### Step 5 — Run full regression + commit (2-3 giờ)

1. **Run full pytest** (must pass):
   ```bash
   pytest packages/smc_bot_webhook/tests/ -q  # 308 tests — Track A regression check
   pytest tests/ -q                            # all backtest tests
   pytest packages/ -q                         # full suite
   ```
2. **Re-run all btest scripts** → save vào `output/btest_v2_realistic/`
3. **Comparison report** (`output/btest_v1_vs_v2_diff.md`):
   - Trade count, winrate, PF, total R, total USD, max DD — side-by-side
   - Verdict: "realistic backtest within acceptable range" OR
     "investigate further"
4. **Commit từng step riêng:**
   - `fix(backtest): convert sl_distance to pips before calculate_lot call`
   - `feat(backtest): add spread + commission + slippage to core`
   - `feat(backtest): entry at next-bar-open`
   - `feat(backtest): session filter + per-bar session tag`
5. Update `docs/project-roadmap.md`:
   - Add Track B section với Phase 08 status
6. Update `CHANGELOG.md` (if exists) hoặc tạo mới
7. Tag: `v0.5.0-realistic-backtest` (suggested)

## Files to modify

**Core backtester:**
- `src/backtester.py` — entry logic, spread/commission, session tag, fix sl_dist
- `src/risk_manager.py` — verify `calculate_lot` signature (no change)
- `src/strategy.py` — `PartialTPExit` R calc with spread
- `src/scale_in_exit.py` — `ScaleInExit` R calc with spread

**New files:**
- `src/session_filter.py` — session classification helper
- `tests/test_position_sizing_units.py`
- `tests/test_execution_realism.py`
- `tests/test_next_bar_open_entry.py`
- `tests/test_session_filter.py`

**Config:**
- `config.yaml` — `execution:` block, session UTC bounds

**Docs:**
- `docs/project-roadmap.md` — Track B status
- `output/baselines_pre_step2/` — pre-fix backtest snapshots
- `output/btest_v2_realistic/` — post-fix backtest outputs
- `output/btest_v1_vs_v2_diff.md` — comparison report

## Todo

- [ ] Snapshot baselines pre-Step 2
- [ ] Step 1: verify + fix calculate_lot unit-conversion + regression test
- [ ] Step 2: add spread + commission + slippage to core backtester
- [ ] Step 3: move entry to next-bar-open
- [ ] Step 4: implement session filter + tag trades by real session
- [ ] Step 5: full regression + commit + tag v0.5.0
- [ ] Update roadmap + changelog

## Success criteria

- All Track A tests pass (308 webhook tests — zero regression)
- 4 new test files pass
- `btest_10y` v2 numbers:
  - Trade count: giảm 35-45% (do session filter + next-bar-open)
  - Total R: giảm 5-15% (do execution costs)
  - Total USD: giảm 25-40% (commission hit hard)
  - Max DD: tăng < 1pp
- Per-session breakdown: chỉ london/new_york/overlap xuất hiện
- Backtest dollar figures now meaningful (Step 1 fix verified)

## Risk

- **Numbers sụp mạnh** nếu spread/commission quá aggressive. Mitigation:
  start với spread=0.5pip, commission=$3.5/lot/side (FTMO standard), verify
  PnL không âm.
- **Session filter loại trades tốt** nếu config active_sessions sai.
  Mitigation: chạy với filter ON/OFF, compare, document edge cases.
- **Next-bar-open thay đổi trade timing** → có thể break existing test
  assumptions. Mitigation: chạy full pytest, fix từng test riêng.
- **Track A regression**: Phase 08-12 touch core backtest + strategy code,
  có thể break Track A's webhook flow nếu coupling không clean. Mitigation:
  chạy 308 webhook tests sau mỗi step.
- **Re-baseline mất time**: rerun all `btest_*.py` scripts sau Step 1 để
  có baseline mới = 4-6 giờ.

## Next steps

Phase 09 — Statistical Validation (walk-forward, OOS, MC, sensitivity) trên
backtest realistic mới.
