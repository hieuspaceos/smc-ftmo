---
status: active
title: "SMC Engine Overview"
created: "2026-08-29"
updated: "2026-08-29"
---

# SMC Engine Overview

## Purpose

`src/smc_engine/` is the project's in-house causal ICT/SMC engine.
It replaced the old third-party `smartmoneyconcepts` dependency in Phase 12.

VN note:

- **causal** = nhân quả, không nhìn tương lai
- **immutable events** = event đã sinh ra thì không bị sửa lại
- **as-of-time query** = hỏi trạng thái tại đúng thời điểm lịch sử đó

The engine does **not** predict price. It does one job well:

- take raw OHLC bars
- derive structure events causally
- expose immutable event objects and as-of-time lifecycle queries
- feed those events into the backtester and Streamlit overlays

## Design Goals

1. **No lookahead** — events only appear after the confirming bar closes.  
   *VN note: không có chuyện đang ở bar hiện tại mà engine “biết trước” 2 bar sau.*
2. **Determinism** — same input frame => same events => same smoke checksum.  
   *VN note: cùng dữ liệu đầu vào thì phải ra đúng cùng kết quả, không được hên xui.*
3. **Typed contracts** — each layer returns explicit dataclasses / typed results.  
   *VN note: mỗi bước trả ra object có field rõ ràng, không phải dict mơ hồ.*
4. **As-of-time state** — zones can be queried at historical timestamps safely.  
   *VN note: hỏi “lúc đó zone còn sống không?” phải trả lời đúng theo thời điểm đó.*
5. **Composable extensions** — breaker blocks, body-only OB zones, and regime
   switching are layered on top without mutating the base OB engine.  
   *VN note: extension là lớp gắn thêm, không được phá máy OB gốc.*

## Directory Map

| Path | Role |
|---|---|
| `src/smc_engine/events.py` | Shared immutable event contracts |
| `src/smc_engine/swings.py` | Confirmed Williams/fractal swings |
| `src/smc_engine/displacement.py` | ATR + range-expansion metrics |
| `src/smc_engine/structure.py` | BOS/CHoCH state machine |
| `src/smc_engine/sweeps.py` | Liquidity sweep detection |
| `src/smc_engine/order_blocks.py` | BOS-activated OB lifecycle |
| `src/smc_engine/fvg.py` | Three-candle FVG lifecycle |
| `src/smc_engine/context.py` | Bias + premium/discount context |
| `src/smc_engine/breaker_blocks.py` | Breaker promotion layer |
| `src/smc_engine/ob_body_mode.py` | Body-only OB geometry layer |
| `src/smc_engine/regime.py` | Regime heuristic (off / on / auto) |

## Read Next

### Đọc nhanh bằng tiếng Việt trước

- [SMC Engine Giải Thích Bằng Tiếng Việt](./smc-engine-vietnamese-guide.md)
- [SMC Engine Usage Guide](./smc-engine-usage-guide.md)

### Tài liệu kỹ thuật chi tiết

- [SMC Engine Event Pipeline](./smc-engine-event-pipeline.md)
- [SMC Engine Module Reference](./smc-engine-module-reference.md)
- [SMC Engine Extensions](./smc-engine-extensions.md)
- [SMC Engine Verification](./smc-engine-verification.md)
