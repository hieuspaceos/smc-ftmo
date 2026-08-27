# SMC FTMO Unified Tool

Web app local (Streamlit + Plotly) để học, backtest và cải tiến chiến lược SMC theo đúng 12 quy tắc bạn đưa ra. Tất cả trong 1 giao diện.

## Tính năng
- Multi-timeframe chart (D, H4, H1, M15) với SMC overlays tự động (OB, FVG, BOS/CHoCH, sweep, displacement, P/D zones).
- Bias panel tự động (aligned long/short/stand-aside).
- Backtest với slider chỉnh params (swing length, min confluence, displacement mult, risk 0.55%, partial TP 40/30/30 + BE at 2R, daily -2R guard).
- Journal SQLite tự động log mọi trade, filter (pair, score, win/lose, session), stats, equity curve.
- Test pass: 147 trades, winrate 53.7%, PF 2.04, Max DD 3.71%.
- Dễ mở rộng rules và data.

## Cài đặt (Mac/Windows/Linux)

### 1. Clone repo
```bash
git clone https://github.com/hieuspaceos/smc-ftmo.git
cd smc-ftmo
```

### 2. Cài dependencies
```bash
pip install -r requirements.txt
```

### 3. Data (10 năm)
- Data M1 từ HistData.com (tải 10 năm EURUSD M1, giải nén vào `data/histdata/`).
- Chạy `run.bat` (Windows) hoặc `./run.sh` (Mac/Linux) để tự động xử lý CSV → parquet.

Hoặc dùng data sẵn trong `data/` (2-10 năm tùy TF).

### 4. Chạy app
- **Windows**: Double-click `run.bat`
- **Mac/Linux**: `./run.sh` hoặc `PYTHONPATH=src streamlit run app.py`

Mở browser: **http://localhost:8501**

## Sử dụng
- Sidebar: chỉnh params (Min score, displacement ATR, risk...).
- Chọn pair, timeframe, period.
- Bấm **Run Backtest** → xem equity curve, metrics, journal.
- Filter journal bằng slider score, side, session, win/lose.
- Tooltip giải thích 12 quy tắc SMC.

## Cấu trúc dự án
```
smc-ftmo/
├── app.py                    # Giao diện Streamlit
├── run.bat / run.sh          # Chạy nhanh (tự xóa cache)
├── config.yaml               # Rules, risk, params
├── requirements.txt
├── data/                     # Parquet (tự sinh từ HistData CSV)
├── data/histdata/            # CSV M1 từ HistData (10 năm)
├── src/
│   ├── download_data.py
│   ├── data_loader.py
│   ├── smc_signals.py        # Custom sweep, displacement
│   ├── bias_detector.py
│   ├── premium_discount.py
│   ├── confluence.py
│   ├── strategy.py           # Partial TP 40/30/30 + BE
│   ├── risk_manager.py       # FTMO Guard
│   ├── backtester.py
│   ├── journal.py
│   └── mt5_connector.py      # Phase 2
├── tests/test_backtest.py    # 10 tests pass
├── docs/                     # Tài liệu
│   ├── system-architecture.md
│   ├── project-roadmap.md
│   ├── code-standards.md
│   ├── deployment-guide.md
│   └── ...
└── plans/                    # Kế hoạch chi tiết từng phase
```

## Docs
- [system-architecture.md](docs/system-architecture.md)
- [project-roadmap.md](docs/project-roadmap.md)
- [code-standards.md](docs/code-standards.md)
- [deployment-guide.md](docs/deployment-guide.md)

## Troubleshooting
- **Port 8501 bận**: `streamlit run app.py --server.port=8502`
- **Lỗi import**: Chạy với `PYTHONPATH=src` hoặc dùng `run.bat`/`run.sh`.
- **Ít lệnh**: Tải thêm data HistData M1 nhiều năm hơn vào `data/histdata/`.
- **Lỗi Unicode**: Đã fix bằng encoding='utf-8' trong config.
- **Yfinance limit**: Dùng HistData cho full 10 năm M15.

## Roadmap
- Phase 1-9: Backtest + Journal (DONE)
- Phase 10: Kết nối MT5 live (đang làm)
- Phase 11: Tối ưu rules dựa trên journal stats

**Disclaimer**: Chỉ dùng cho mục đích học và nghiên cứu. Backtest không đảm bảo lợi nhuận tương lai. Luôn test trên demo trước khi dùng tiền thật.

---
Cập nhật: 27/8/2026
```

**Docs folder** đã được tạo với các file chính (system-architecture, roadmap, code-standards, deployment-guide, codebase-summary). Tôi đã viết đầy đủ nội dung dựa trên project hiện tại.

Bạn mở folder `docs/` để xem chi tiết. Nếu muốn chỉnh hoặc thêm file nào, nói tôi.

Repo trên GitHub cũng đã cập nhật README mới này.

Bạn xem ổn không? Muốn tôi chỉnh gì thêm trong docs hay README?