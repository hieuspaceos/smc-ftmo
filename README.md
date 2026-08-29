# SMC FTMO Unified Tool

Web app local với `Streamlit` + `Plotly` để học, backtest, và cải tiến chiến lược SMC trong một giao diện.

## Tình trạng hiện tại

- Core engine causal đã thay thế dependency `smartmoneyconcepts`.
- Regime V2 + liquidity pools đã được ship dưới dạng extension không phá baseline.
- Phase 13 breaker/body upgrade đang ở trạng thái pending trong `plans/`.
- Full suite hiện tại: `209 passed`.
- Smoke baseline hiện tại: `32 trades`, `WR 81.25%`, `PF 8.29`, `Max DD 1.17%`.

## Tính năng

- Multi-timeframe chart `D / H4 / H1 / M15` với overlays SMC tự động.
- Bias panel tự động với `aligned long / short / stand-aside`.
- Backtest với slider chỉnh params, risk, TP profile, và FTMO guard.
- Journal SQLite log trade, filter theo pair / score / win-lose / session.
- Overlay toggles cho `Candles`, `OB`, `FVG`, `BOS`, `CHoCH`, `Sweep`, `Displacement`, `EQH swept`, `EQL swept`, `P/D zones`.

## Cài đặt

### 1. Clone repo
```bash
git clone https://github.com/hieuspaceos/smc-ftmo.git
cd smc-ftmo
```

### 2. Cài dependencies
```bash
pip install -r requirements.txt
```

### 3. Data
- Data M1 từ HistData.com có thể đặt vào `data/histdata/`.
- Chạy `run.bat` trên Windows hoặc `./run.sh` trên Mac/Linux để xử lý CSV -> parquet.
- Có thể dùng data có sẵn trong `data/` nếu không cần full 10 năm.

### 4. Chạy app
- Windows: double-click `run.bat`
- Mac/Linux: `./run.sh` hoặc `PYTHONPATH=src streamlit run app.py`

Mở browser: `http://localhost:8501`

## Sử dụng

- Sidebar để chỉnh params như `min score`, `displacement ATR`, `risk`, `bias mode`, `regime mode`.
- Chọn pair, timeframe, và period.
- Bấm `Run Backtest` để xem equity curve, metrics, và journal.
- Dùng overlay toggles để bật/tắt trace trên chart.

## Tài liệu

- [System Architecture](docs/system-architecture.md)
- [SMC Engine Overview](docs/smc-engine-overview.md)
- [SMC Engine Event Pipeline](docs/smc-engine-event-pipeline.md)
- [SMC Engine Module Reference](docs/smc-engine-module-reference.md)
- [SMC Engine Extensions](docs/smc-engine-extensions.md)
- [SMC Engine Usage Guide](docs/smc-engine-usage-guide.md)
- [SMC Engine Verification](docs/smc-engine-verification.md)
- [SMC Engine Vietnamese Guide](docs/smc-engine-vietnamese-guide.md)
- [Checklist Trade Tay SMC](docs/smc-manual-trade-checklist.md)
- [Rule Book Trade Tay](journal/rule-book.md)
- [Project Roadmap](docs/project-roadmap.md)
- [Code Standards](docs/code-standards.md)

## Roadmap ngắn

- Phase 12: custom SMC engine rewrite - done.
- Phase 13: breaker block + OB body toggle - pending.
- Signal-quality refinement (Regime V2 + liquidity pools) - done.

## Troubleshooting

- Port `8501` bận: `streamlit run app.py --server.port=8502`
- Lỗi import: chạy với `PYTHONPATH=src` hoặc dùng `run.bat` / `run.sh`
- Dữ liệu ít: tải thêm CSV HistData M1 vào `data/histdata/`
- Unicode issue: repo đã dùng encoding UTF-8 cho config và docs

**Disclaimer**: Chỉ dùng cho học tập và nghiên cứu. Backtest không đảm bảo lợi nhuận tương lai. Luôn test demo trước khi dùng tiền thật.
