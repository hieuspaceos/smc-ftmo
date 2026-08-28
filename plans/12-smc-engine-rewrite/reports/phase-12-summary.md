# Phase 12 — SMC Engine Rewrite Summary

## What changed

| Phase | Outcome |
|---|---|
| 1 — Causal Swing Events | `src/smc_engine/swings.py`, `events.py`: typed `SwingEvent`/`SwingResult`, activation at `pivot + right`, earliest-equal tie policy, O(n). |
| 2 — ATR & Range Expansion | `src/smc_engine/displacement.py`: causal NaN warmup, `ExpansionMetrics` (range/body/close-location/qualified). |
| 3 — Structure State Machine | `src/smc_engine/structure.py`: exhaustive `(prior trend × break) → bos/choch` table, consumed-level suppression, optional ATR buffer, mutex between BOS/CHoCH. |
| 4 — Liquidity Sweeps | `src/smc_engine/sweeps.py`: one-shot grabs against activated swing levels, dual-sided diagnostics. |
| 5 — Order Block Lifecycle | `src/smc_engine/order_blocks.py`: BOS-only origin vs activation split, chronological first-touch/invalidation/200-bar expiry/128-zone cap, `is_active_at` / `is_first_test_at`. |
| 6 — FVG/Bias/Context | `src/smc_engine/fvg.py`, `context.py`: three-candle strict gap with lifecycle, structure-derived bias Series, structure-dealing-range premium/discount. |
| 7 — Adapter Cutover | `src/smc_signals.py` rewritten as thin compatibility adapter preserving the legacy `SMCSignals` signature and `Signal` schema. |
| 8 — Migration & Verification | `src/bias_detector.py`, `src/backtester.py`: vocabulary fixed (`bull/bear`), HTF state uses completed-bar `merge_asof`, OB/FVG historical state via engine lifecycle methods. `tests/test_backtest.py` reframed as characterization. |
| 9 — Acceptance Cleanup | `smartmoneyconcepts` removed from `requirements.txt`. `docs/system-architecture.md` created. `scripts/smoke-phase12.py` produces deterministic report. |

## Smoke Metrics (2026 EURUSD, 15 895 M15 bars)

```
bias_multi_tf: D=bull, H4=bull, H1=bull, M15=bear
trade_total: 32 (5 long + 27 short — both sides, post-cutover)
winrate: 0.8125
profit_factor: 8.29
max_dd_pct: 1.17%
final_equity: 133 271.37
runtime_seconds: 0.93
m15_close_sha256: 4d6a95cff910bbcbe857af34d07f0289529d514177fb5c607176c38eb565cb0a
```

Full snapshot in `plans/12-smc-engine-rewrite/reports/smoke-final.json`.

## Tests

`pytest tests/ -q` reports **163 passed in 2.04 s**.

| File | Count |
|---|---|
| `tests/test_smc_swings.py` | 14 |
| `tests/test_smc_displacement.py` | 34 |
| `tests/test_smc_structure.py` | 23 |
| `tests/test_smc_sweeps.py` | 30 |
| `tests/test_smc_order_blocks.py` | 30 |
| `tests/test_smc_fvg_context.py` | 22 |
| `tests/test_backtest.py` (characterization) | 10 |

## Algorithm Lock-Ins (from Validation Session 1)

- Causal ATR with NaN warmup (no legacy backfill).
- OB / FVG: 200-bar expiry, cap 128 per direction.
- Premium/Discount: latest confirmed activated structure dealing range; rolling wrapper remains as compatibility layer.
- Breakers deferred post-cutover.
- Confirmed swing break-eligible from bar after activation.
- Entry eligible on the first-touch bar.
- Economic thresholds are characterization only; correctness relies on deterministic and causal oracles.

## Unresolved Questions

None. Optional upgrades are explicit in the plan and in the implementation gap list below.

## Known Limitations / Optional Upgrades

- ATR/deviation ZigZag or directional-change pivots (replace Williams/fractal engine).
- Volume-quality and body-quality filters for displacement.
- Breaker block classification and role-flip rendering.
- OB body-only zones; FVG midpoint-fill policies.
- Threshold tuning and economic optimization (out of MVP scope).
