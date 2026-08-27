# SMC FTMO Backtester

Web app thống nhất để học và áp dụng phương pháp SMC (Smart Money Concepts), backtest chiến lược trên 3 cặp EURUSD, XAUUSD, BTCUSD, ghi nhật ký và cải tiến chiến lược — tất cả trong 1 giao diện trên browser.

## Tính năng

- Đa khung Daily → H4 → H1 → M15 với bias panel tự động
- Vẽ tự động Order Block, Fair Value Gap, BOS/CHoCH, sweep, displacement trên chart
- Backtest với slider chỉnh thông số (swing length, RR, score tối thiểu, session filter)
- Confluence score 5 tiêu chí theo quy tắc SMC
- Risk 0.55%/lệnh, partial TP 40/30/30, breakeven khi hit 2R
- Daily guard: mất 2R trong ngày → dừng (theo quy tắc)
- Journal SQLite với filter pair/ngày/score/win-lose
- Phase sau: kết nối MT5 để trade live

## Cài đặt

### 1. Yêu cầu

- Python 3.10 trở lên
- Windows / macOS / Linux
- ~2GB disk cho data

### 2. Cài dependencies

```bash
cd smc-ftmo
pip install -r requirements.txt
```

Nếu lỗi khi cài `ta`:

```bash
pip install ta --no-deps
```

### 3. Download data (chỉ làm 1 lần)

```bash
python src/download_data.py
```

Output: 12 file parquet trong `data/` (3 pairs × 4 khung).

### 4. Chạy app

```bash
streamlit run app.py
```

Mở browser tại `http://localhost:8501`.

## Cấu trúc thư mục

```
smc-ftmo/
├── app.py                       Entry point
├── config.yaml                  FTMO rules + risk params
├── requirements.txt
├── README.md
├── data/                        OHLCV parquet (auto download)
├── plans/                       Kế hoạch chi tiết từng phase
├── src/
│   ├── download_data.py
│   ├── data_loader.py
│   ├── smc_signals.py
│   ├── bias_detector.py
│   ├── premium_discount.py
│   ├── confluence.py
│   ├── strategy.py
│   ├── risk_manager.py
│   ├── backtester.py
│   ├── journal.py
│   └── mt5_connector.py         (Phase 2)
└── output/
    ├── trades.db                SQLite journal
    └── reports/                 HTML reports
```

## Quy tắc trade áp dụng

Đầy đủ ở `plans/00-master-plan.md`. Tóm tắt:

1. Bias đa khung Daily → H4 → H1 → M15, chỉ trade thuận D+H4
2. Cấu trúc: BOS cùng chiều, CHoCH đổi chiều, có displacement + close rõ
3. Thanh khoản: sweep sạch = râu quét + close ngược + displacement
4. Premium/Discount: tăng vào Discount, giảm vào Premium
5. Order Block phải có displacement mạnh
6. Breaker Block: OB bị phá mạnh + đổi vai trò + CHoCH
7. Thứ tự setup: Bias → Liquidity → Sweep → BOS/CHoCH → OB/Breaker → Test → Entry
8. Confluence: 4/5 tiêu chí, bắt buộc Displacement + Bias aligned
9. Risk 0.55%/lệnh, partial TP 40/30/30, BE khi hit 2R, daily stop -2R
10. Đứng ngoài khi sideway lớn, chưa BOS/CHoCH, OB yếu, mất 2R

## Kế hoạch phát triển

Xem `plans/`:
- `00-master-plan.md` — tổng quan
- `01-phase-setup.md` — Phase 0: setup môi trường
- `02-phase-data.md` — Phase 1: download data
- `03-phase-chart-signal.md` — Phase 2: chart + signals
- `04-phase-multiframe-bias.md` — Phase 3: đa khung + bias
- `05-phase-confluence.md` — Phase 4: confluence score
- `06-phase-strategy-risk.md` — Phase 5: strategy + risk
- `07-phase-backtester.md` — Phase 6: backtester
- `08-phase-journal.md` — Phase 7: journal SQLite
- `09-phase-app-ui.md` — Phase 8: UI ghép
- `10-phase-test-polish.md` — Phase 9: test + polish
- `11-phase-live-mt5.md` — Phase 10: live MT5

## Troubleshooting

**Lỗi `Microsoft Visual C++ 14.0` khi cài `ta`**
→ Không quan trọng cho SMC, bỏ qua.

**Lỗi kết nối Binance (ccxt)**
→ Tự động fallback sang yfinance.

**Lỗi port 8501 bận**
→ `streamlit run app.py --server.port 8502`

**Không có trade nào trong backtest**
→ Giảm `Min Confluence Score` xuống 3, hoặc giảm `Swing Length` xuống 10.

**Equity curve bằng phẳng**
→ Check pip_value đúng cho từng pair trong `config.yaml`.

## Disclaimer

Công cụ này chỉ phục vụ mục đích học tập và nghiên cứu. Không phải lời khuyên đầu tư. Backtest kết quả tốt không đảm bảo lợi nhuận tương lai. Luôn forward test trên demo trước khi dùng tiền thật.
