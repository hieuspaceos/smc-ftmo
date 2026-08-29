---
title: "SMC Market Comparison and Pine Feasibility"
status: complete
created: "2026-08-29T18:30:00+07:00"
updated: "2026-08-29T18:30:00+07:00"
---

# SMC Market Comparison and Pine Feasibility

## Summary

The defensible difference is not that this engine draws BOS, CHoCH, OB, FVG,
sweeps, EQH/EQL, or premium/discount. Mature TradingView indicators already
bundle those concepts. The difference is stricter semantics, deterministic
selection, and verifiable parity:

- explicit pivot time versus activation time
- next-bar eligibility after swing confirmation
- strict close-only breaks and one-shot consumed levels
- deterministic BOS/CHoCH state transitions
- base OBs from BOS only, gated by range displacement
- chronological first-touch, invalidation, and expiry state
- immutable-as-of-time Python event contracts
- prefix invariance, synthetic tests, and stable replay expectations

That is a reliability and traceability advantage, not proof of superior profitability.

## Current Engine Map

| Layer | Status | Notes |
|---|---|---|
| Events contract | Separate | Shared immutable swing contract |
| Baseline modules | 7 | `swings`, `displacement`, `structure`, `sweeps`, `order_blocks`, `fvg`, `context` |
| Extension modules | 4 | `liquidity_pools`, `breaker_blocks`, `ob_body_mode`, `regime` |
| Adapters | Not engine components | `SMCSignals`, app, and backtester wrappers |

The current app profile is the parity target, not the `SMCSignals` constructor
default:

- `config.yaml` sets `swing_length: 10`
- the app passes that value through
- effective left/right swing window is `5 / 5`
- ATR is `SMA(True Range, 14)`
- displacement is strict `> 1.5`
- sweep overlay buffer is `0.05`
- OB lookback is `20`
- OB expiry is `200`
- OB cap is `128`
- OB geometry is full wick
- FVG expiry is `200`
- FVG cap is `128`

## Method

- Conducted: 2026-08-29, Asia/Ho_Chi_Minh
- Local sources: engine code, engine docs, rule book, tests
- External sources: current TradingView public indicator pages and official Pine docs
- Comparison boundary: publicly described behavior; closed or protected code is not treated as verified internals
- Local verification on 2026-08-29: `191` focused SMC tests and `209` full-suite tests passed via `.venv/bin/pytest`

## Market Comparison

| Area | Current engine | Typical/public examples | Actual distinction |
|---|---|---|---|
| Feature breadth | BOS/CHoCH, OB, FVG, sweep, EQH/EQL, P/D, breaker, regime | LuxAlgo, AlphaX, SMC Analytics Pro, and Quantitative SMC expose similar or broader visual sets | Not unique |
| Swing logic | Fixed confirmed Williams/fractal window; earliest-equal tie rule; activation at pivot + right | Fixed pivots, ZigZag, or adaptive ATR retracement are common | Exact tie and activation semantics are unusually explicit |
| Structure break | Strict close beyond active level; activated level eligible from next bar; consume once | Close-confirmed BOS/CHoCH is common, but eligibility and consume details are often undocumented | Deterministic lifecycle is stronger than feature claims |
| Displacement | Full candle range `> 1.5 * SMA(TR,14)`; NaN warmup | Public scripts use body/ATR, average body, strong-candle rules, volume, or adaptive filters | Formula differs materially; TradingView built-in ATR is not equivalent |
| OB trigger | BOS only; displacement on BOS or previous bar | Several scripts create OB after BOS or CHoCH; others use engulfing or volume filters | BOS-only plus exact gate is a meaningful rule difference |
| OB origin | Last opposite candle within bounded lookback | Last opposite, most extreme, engulfed, or volume-filtered candle | Deterministic but not inherently more profitable |
| OB lifecycle | Active at BOS; touch and invalidation begin next bar; close invalidation; first-test and expiry | Touch or mitigation removal is common; wick or close options are common | Ordering and historical as-of query are more rigorous |
| Sweep | Confirmed swing, ATR wick buffer, reclaim close, one-shot; dual-sided suppressed | Pivot sweeps and reclaim are common; thresholds and cooldowns vary | One-shot source consumption and diagnostics are explicit |
| FVG | Strict three-candle gap with chronological touch, fill, and expiry | Standard market feature | Not unique; lifecycle verification is the advantage |
| Liquidity pools | ATR-relative `0.15` tolerance, second-swing activation, causal sweep | EQH/EQL common | Explicit causal extension policy is stronger than generic plotting |
| Regime | Structure, sweep, and pool density select conservative OB vs breaker weights | Dashboards and trend filters are common; this density model is not commonly documented | Distinct extension, but not suitable for Pine v1 |
| MTF | Completed HTF bars only | Many tools offer MTF; anti-repaint quality varies | Must reproduce with confirmed `request.security()` semantics |
| Verification | Typed immutable events, as-of lifecycle, unit, golden, and prefix tests | Public pages emphasize visuals and no-repaint claims; test evidence is usually unavailable | Strongest real differentiation |

## Pine Feasibility

### Can port closely

- causal SMA True Range ATR and NaN warmup
- fixed left/right swing confirmation and tie policy
- pivot and activation positions
- next-bar active-level registration
- BOS/CHoCH trend state and level consumption
- displacement-gated BOS-to-OB creation
- bounded OB/FVG/sweep/pool lifecycle arrays using Pine UDTs
- clean labels, lines, boxes, and alerts
- confirmed chart-bar processing

### Can port with explicit constraints

- historical OB/FVG lifecycle: retain bounded recent objects, not unlimited event history
- MTF D/H4 bias: use confirmed HTF requests and accept one completed-bar delay semantics
- event export: use Data Window, table, alerts, or manual CSV comparison; Pine cannot write repo fixture files
- parity: requires identical OHLC feed, timezone, session, symbol, timeframe, and date span
- regime: feasible computationally, but should be deferred until core runtime is profiled

### Cannot port literally into one indicator

- Python dataclass immutability and arbitrary `is_active_at(timestamp)` API
- SQLite journal and local backtester integration
- all-history objects beyond TradingView drawing and history limits
- broker-independent equality when TradingView OHLC differs from local HistData
- unrestricted lower-timeframe reconstruction

Official constraints relevant to the design:

- scripts permit at most 64 plot counts and up to 500 line, box, and label IDs per type; default drawing retention is approximately 50 when caps are not raised: [writing limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/)
- explicit deletion and bounded drawing cleanup are required; assigning `na` does not release an ID: [lines and boxes](https://www.tradingview.com/pine-script-docs/visuals/lines-and-boxes/)
- `request.*()` calls and intrabar retrieval are limited by plan and runtime: [writing limitations](https://www.tradingview.com/pine-script-docs/writing/limitations/)
- confirmed HTF requests need offset values with `lookahead_on` to prevent repainting: [repainting](https://www.tradingview.com/pine-script-docs/concepts/repainting/)
- Pine arrays and UDTs can model bounded event lifecycles: [arrays](https://www.tradingview.com/pine-script-docs/language/arrays/)
- Pine Profiler should validate loop-heavy lifecycle scans: [profiling and optimization](https://www.tradingview.com/pine-script-docs/writing/profiling-and-optimization/)

## Recommendation

Build one private indicator, internally separate it into module-like sections,
and ship progressively. Default visualization should show gated structure and
fresh zones, not every raw event. Keep Python as the reference implementation
and generate golden fixtures from it before writing Pine logic.

Do not copy public script source. Public indicators are benchmarks for usability
and feature vocabulary only.

V1 should use frozen `FXPRO:EURUSD` as the parity feed. The implementation must
avoid pip-specific constants so later XAUUSD and BTCUSD validation can reuse
the same engine. Those markets require separate feed metadata, fixtures, and
performance characterization; matching EURUSD does not prove cross-market parity.

If a single Pine script later fails profiler limits, the fallback is a private
Pine library plus two thin frontends. That fallback preserves the one-core,
two-profile decision without splitting the product into independent indicators.

Pine v1 targets exact parity for all seven baseline behavior modules plus the
liquidity-pool extension: `8/11`, or `72.7%`, of current behavior modules when
the events contract is excluded. Breaker, body mode, and regime are already
implemented Python extensions but are intentionally deferred. Rulebook OB
selection is a separate policy layer and must pass its own fixtures; module
coverage is not evidence of setup quality or profitability.

## Next Steps

1. Freeze event schema and export synthetic and EURUSD fixtures.
2. Port swings, ATR/displacement, and structure before any boxes.
3. Prove core parity, then add OB, FVG, sweep, and pool lifecycle.
4. Add Rulebook selector, display pruning, and alerts.
5. Add confirmed D/H4 bias only after chart-timeframe parity.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
