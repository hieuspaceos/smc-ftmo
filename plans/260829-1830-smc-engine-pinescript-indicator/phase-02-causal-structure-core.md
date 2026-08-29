# Phase 02: Causal Baseline Parity + Pools

## Context

- [Plan](./plan.md)
- Depends on [Phase 01](./phase-01-parity-specification-and-fixtures.md)

## Goal

Implement the causal baseline core first, then add liquidity-pool parity after
the seven baseline modules are exact.

## Requirements

- Manual True Range and SMA ATR(14); do not use `ta.atr()`.
- Earliest-equal fixed-window pivot policy matching Python.
- Pivot activates at `pivot + right`; break eligibility starts next bar.
- Strict close-through; equality and wick-only crossing do not break.
- One active high/low source, one-shot consumption, invariant and dual-break suppression.
- BOS/CHoCH transition table matches neutral/bull/bear Python states.
- Confirmed bars only for final signals.
- Use the current-app profile: `swing_length=10` -> effective `left=right=5`, displacement `> 1.5`, sweep overlay buffer `0.05`.
- Keep `regime_mode=off`; use full-wick OB geometry. Breaker and body-mode transforms are out of Pine Rulebook v1.
- Port all seven Gate A modules: swings, displacement, structure, sweeps, base
  order blocks, FVG, and structure context/bias.
- Port Gate B liquidity pools only after Gate A is exact.

## Files

- Create `tradingview/smc-engine-indicator.pine`.

## Architecture

Use clear module-like sections in one script:

1. inputs, constants, and event/state UDTs
2. ATR and expansion
3. swing confirmation and structure state
4. sweep state
5. OB and FVG chronological lifecycle state
6. structure context and bias
7. liquidity-pool extension state
8. parity/debug output and minimal plots

Avoid one loop scanning all historical bars on every bar. Use current-bar state
updates and bounded collections only.

## Implementation Steps

1. Implement ATR warmup and expansion metrics.
2. Implement exact pivot tie behavior without relying blindly on built-in pivot tie semantics.
3. Register confirmed swing levels after structure evaluation on each bar.
4. Implement trend transition, replacement/consumption, invariant suppression, and diagnostics.
5. Implement exact sweep inequalities and one-shot/dual-sided consumption with core buffer `0.05`.
6. Implement base OB origin and lifecycle: BOS-only, linked displacement on BOS or previous bar, lookback `20`, doji exclusion, next-bar lifecycle, close invalidation, first touch, expiry `200`, and cap `128` per direction.
7. Implement strict three-candle FVG origin/activation, equality behavior, touch/fill ordering, expiry `200`, and cap `128` per direction.
8. Implement chart-timeframe structure context/bias for Gate A.
9. Compare every Gate A output and diagnostic against Phase 01 fixtures.
10. Add pool membership, second-member activation, later-member updates without backpainting, and causal sweep for Gate B.
11. Expose event/state fields through Data Window or a compact table; raw debug labels remain opt-in.

## Validation

- Pine compiler passes.
- Synthetic per-bar state, all seven baseline event families, lifecycles, and diagnostics match exactly.
- Bar Replay and reload leave finalized events unchanged.
- Boundary case `range == 1.5 * ATR` remains unqualified.
- OB/FVG activation, touch, invalidation/fill, expiry, and cap precedence match the fixtures.
- Liquidity-pool activation and sweep match the frozen fixture after baseline parity is stable.

## Completion Checklist

- [ ] ATR values match fixture after warmup.
- [ ] Swing pivot and activation positions match.
- [ ] BOS/CHoCH timestamp, direction, and broken level match.
- [ ] Consumed levels cannot emit duplicate events.
- [ ] Sweep, OB, FVG, context, and lifecycle diagnostics match Gate A fixtures.
- [ ] Default view is limited to structure and the selected fresh OB; debug data is opt-in.
- [ ] Liquidity-pool parity is exact after baseline parity is locked.

## Risks and Rollback

- Pine `bool` has no `na` behavior equivalent to old examples; use explicit history guards.
- Built-in ATR or pivot helpers may differ subtly; retain manual implementations where parity demands it.
- Roll back individual module sections while keeping the last compiling core.

## Unresolved Questions

- Exact clean-sweep recency window relative to BOS or OB touch.
- Legal and reproducible storage method for frozen FXPRO OHLC.
- Whether session means fixed EST or `America/New_York` with DST.
