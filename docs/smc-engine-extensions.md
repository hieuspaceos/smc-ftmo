---
status: active
title: "SMC Engine Extensions"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Extensions

## Why Extensions Exist

The base OB engine is intentionally conservative and stable. Extensions are
kept outside `order_blocks.py` so the core engine stays deterministic and all
pre-existing tests continue to pass verbatim.

VN note:

- **extension** = lớp mở rộng gắn thêm, không phá lõi
- **non-invasive** = không đụng vào máy OB gốc
- mục tiêu là thử ý tưởng mới nhưng vẫn giữ baseline nguyên vẹn

That split matters because the extensions are more experimental than the core.
## Extension 1 — Breaker Blocks

`src/smc_engine/breaker_blocks.py`

### Definition

A breaker is an invalidated OB that is promoted into the opposite direction by
a later CHoCH.

### Promotion rules

1. start from an `OrderBlockEvent` whose `invalidation_timestamp` is not `None`
2. wait for a `StructureEvent` of type `choch`
3. require `invalidation_timestamp < choch_activation_timestamp`
4. require `choch_pos - ob.origin_pos <= promotion_lookback_bars`
5. apply single-flip rule: an OB can become a breaker once only

VN note:

- bước 3 là rule chống lookahead: OB phải chết trước, CHoCH tới sau
- bước 4 là chống stale zone: OB quá cũ thì không promote nữa
- bước 5 là chống double-count: 1 OB chỉ được lật vai 1 lần

### Why CHoCH and not BOS

- BOS = continuation *(VN: tiếp diễn trend)*
- CHoCH = reversal *(VN: đảo chiều cấu trúc)*

A breaker is specifically a role-reversal concept, so CHoCH is the right
promotion event.

### Lifecycle

```mermaid
flowchart LR
    A[BOS creates OB] --> B[OB active]
    B --> C[close through opposite edge]
    C --> D[OB invalidated]
    D --> E[later CHoCH]
    E --> F[breaker promoted]
    F --> G[pullback test in opposite direction]
```

### Current empirical note

On the shipped EURUSD M15 2026 dataset:

- breaker overlays are causal and deterministic
- 59 breakers are detected
- forcing them into entries reduces edge vs baseline OB-classic entries

So breakers are implemented and visible, but **not currently better** than
baseline on that specific dataset.

## Extension 2 — OB Body Mode

`src/smc_engine/ob_body_mode.py`

### Purpose

Change only the geometry of the OB zone, not the event itself.

### Modes

| Mode | Zone |
|---|---|
| `full` | `high-low` of origin candle |
| `body` | `max(open, close)` to `min(open, close)` |

### What changes / what does not

Changes:

- zone width
- likely fill frequency
- likely hit rate

Does not change:

- origin candle
- activation timestamp
- invalidation timestamp
- expiry timestamp
- structure provenance

## Extension 3 — Regime Detection

`src/smc_engine/regime.py`

### Purpose

Choose when to prefer classic OB entries vs breaker overlays.

### Modes in the backtester/UI

| Mode | Meaning |
|---|---|
| `off` | baseline OB-classic only |
| `on` | always include breakers |
| `auto` | derive breaker weight from regime metrics |

### Current heuristic

- `trend_strength = |net move| / sum(|moves|)`
- `choppiness = reversal fraction`

### Current caveat

The heuristic classifies EURUSD M15 2026 as `ranging` because the path is
choppy, even though the higher-timeframe bias is broadly bullish. So
`auto` currently behaves like `on` there.

That means the regime layer is implemented and tested, but still heuristic,
not authoritative.

## Why Not Put Everything Into `order_blocks.py`

Because the engine needs a stable center.

If breaker logic, geometry transforms, and regime heuristics all live in the
same file as OB lifecycle, then every experiment risks changing the baseline.

The current split keeps responsibilities clean:

- `order_blocks.py` = canonical OB lifecycle
- `breaker_blocks.py` = role-reversal layer
- `ob_body_mode.py` = geometry transform
- `regime.py` = strategy-selection heuristic

That is easier to test, easier to rollback, and easier to explain.
