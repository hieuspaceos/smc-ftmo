---
status: active
title: "Code Standards"
created: "2026-08-29"
updated: "2026-08-29"
---

# Code Standards

## Scope

This repo is an engine-first SMC tool. Code changes should keep the causal
core stable and keep the UI/backtester contracts compatible unless a change is
explicitly scoped to a contract update.

## Rules

1. Preserve causality. No lookahead, no future leakage, no bar-level state that
   depends on incomplete higher-timeframe candles.
2. Keep the base engine additive. Extension layers belong in separate modules
   and should not mutate canonical OB / FVG / structure lifecycles.
3. Keep public adapter shapes stable. `src/smc_signals.py`, `src/backtester.py`,
   and `app.py` are compatibility surfaces.
4. Prefer deterministic helpers and typed results over ad hoc dict plumbing.
5. Use characterization tests for economic metrics. Correctness should be proven
   with deterministic or causal oracles first.
6. Update docs when user-visible behavior, setup, or public contracts change.
7. Keep edits scoped. Do not refactor unrelated modules while fixing one rule.

## File Conventions

- Engine modules live under `src/smc_engine/`.
- Tests mirror behavior and contracts under `tests/`.
- Plans and execution reports live under `plans/`.
- Historical docs stay in `docs/`.

## Verification

- Run the narrowest useful test first.
- Broaden to the full suite when shared contracts change.
- Do not ship doc claims that contradict the actual smoke report or test run.

