# Master Plan — SMC FTMO Tool

## Mục tiêu tổng thể

Xây dựng **1 web app thống nhất** (Streamlit + Plotly) chạy trên máy local, dùng để:
- Học và áp dụng phương pháp SMC (Smart Money Concepts)
- Backtest chiến lược trên 3 cặp EURUSD, XAUUSD, BTCUSD
- Ghi nhật ký trade, lọc, phân tích để cải tiến chiến lược
- Phase sau: kết nối MT5 để trade live trên FTMO

## Nguyên tắc thiết kế

1. **Một chỗ duy nhất** — không nhảy qua nhiều tool
2. **Visual trên chart** — vẽ tự động OB, FVG, BOS, sweep, không vẽ tay
3. **Thay đổi thông số đầu vào** — slider, checkbox, dropdown, mỗi lần đổi chạy lại được
4. **Tự ghi nhật ký** — mỗi backtest auto-log vào SQLite, xem lại và lọc được trong app
5. **Khớp với quy tắc SMC của bạn** — 12 mục đã chốt ở đầu chat

## Quy tắc trade áp dụng (tóm tắt)

1. Bias đa khung: Daily → H4 → H1 → M15. Chỉ trade thuận bias D+H4.
2. Cấu trúc: BOS cùng chiều, CHoCH đổi chiều. Phải có displacement + đóng cửa rõ.
3. Thanh khoản: sweep sạch = râu quét + đóng cửa ngược + displacement.
4. Premium/Discount: tăng vào Discount, giảm vào Premium.
5. Order Block: phải có displacement mạnh sau nến ngược chiều.
6. Breaker Block: OB bị phá mạnh + đổi vai trò, có CHoCH.
7. Thứ tự setup: Bias → Liquidity → Sweep → BOS/CHoCH → OB/Breaker → Test → Entry.
8. Confluence: 4/5 tiêu chí, bắt buộc có Displacement + Bias aligned.
9. Risk: 0.55%/lệnh, partial TP 40/30/30, BE khi hit 2R, daily stop -2R.
10. Đứng ngoài: sideway lớn, chưa BOS/CHoCH, OB yếu, mất 2R.
11. Đánh giá theo N lệnh, không phải 1–2 lệnh.
12. Lộ trình: chỉ thuận bias trước, có số liệu rồi tính lợi nhuận.

## Cấu trúc file

```
smc-ftmo/
├── app.py                       Entry point — chạy cái này
├── config.yaml                  FTMO rules, pairs, risk params
├── requirements.txt             pip dependencies
├── README.md                    Hướng dẫn cài + chạy
├── .gitignore                   Ignore data/, output/, __pycache__
├── data/                        Parquet OHLCV (auto download)
├── plans/                       Plan files (file này nằm đây)
├── src/
│   ├── download_data.py         Tải EURUSD/XAU/BTC
│   ├── data_loader.py           Đọc parquet, multi-TF
│   ├── smc_signals.py           BOS, OB, FVG, sweep, displacement
│   ├── bias_detector.py         Bias đa khung
│   ├── premium_discount.py      Vùng P/D
│   ├── confluence.py            Score 5 tiêu chí
│   ├── strategy.py              Entry/exit + partial TP
│   ├── risk_manager.py          Lot size + FTMO guard
│   ├── backtester.py            Loop bar, P&L
│   ├── journal.py               SQLite + filter
│   └── mt5_connector.py         Phase 2
└── output/
    ├── trades.db                SQLite journal
    ├── trades.csv               Export
    └── reports/                 HTML reports
```

## Tech stack cố định

| Layer | Công cụ |
|---|---|
| UI | Streamlit |
| Chart | Plotly (trong Streamlit) |
| Signal | smartmoneyconcepts (pip) |
| Data | pandas + numpy + pyarrow (parquet) |
| Storage | SQLite |
| Download | ccxt, yfinance |
| Live (Phase 2) | MetaTrader5 Python |

## Danh sách phase

| Phase | Tên | Mục tiêu | File plan |
|---|---|---|---|
| 0 | Setup môi trường | Project skeleton, deps, README | [01-phase-setup.md](01-phase-setup.md) |
| 1 | Download data | Có đủ 12 file parquet | [02-phase-data.md](02-phase-data.md) |
| 2 | Chart + SMC signals | Vẽ OB/FVG/BOS/sweep | [03-phase-chart-signal.md](03-phase-chart-signal.md) |
| 3 | Đa khung + Bias | Mini chart D/H4/H1/M15 + bias panel | [04-phase-multiframe-bias.md](04-phase-multiframe-bias.md) |
| 4 | Premium/Discount + Confluence | Score 5 tiêu chí | [05-phase-confluence.md](05-phase-confluence.md) |
| 5 | Strategy + Risk | Entry rules, partial TP, FTMO guard | [06-phase-strategy-risk.md](06-phase-strategy-risk.md) |
| 6 | Backtester | Loop bar, equity curve, metrics | [07-phase-backtester.md](07-phase-backtester.md) |
| 7 | Journal SQLite | Lưu + query + filter | [08-phase-journal.md](08-phase-journal.md) |
| 8 | App ghép UI | Sidebar + main + journal | [09-phase-app-ui.md](09-phase-app-ui.md) |
| 9 | Test + polish | Fix bug, verify kết quả | [10-phase-test-polish.md](10-phase-test-polish.md) |
| 10 | Live MT5 (sau) | Connect + auto-execute | [11-phase-live-mt5.md](11-phase-live-mt5.md) |

## Tổng thời gian

- Phase 0–9 (backtest/review): ~2 tuần
- Phase 10 (live): ~2 tuần sau khi Phase 9 xong
