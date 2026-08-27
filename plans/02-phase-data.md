# Phase 1 — Download data

## Mục tiêu

Có đủ 12 file parquet (3 pairs × 4 khung) để chạy signal + backtest.

## Task

### File: `src/download_data.py`

Hàm chính:
- `download_pair(symbol, timeframe, years=2)` → DataFrame OHLCV → parquet
- `download_all()` → loop 3 pairs × 4 khung

### Nguồn data

| Pair | Nguồn chính | Fallback |
|---|---|---|
| EURUSD | Dukascopy tick → 1m bar | yfinance `EURUSD=X` |
| XAUUSD | HistData.com (free) | yfinance `GC=F` |
| BTCUSD | Binance API qua ccxt | yfinance `BTC-USD` |

### Timeframes cần

| TF | Dùng cho |
|---|---|
| D | Bias Daily |
| H4 | Bias H4 |
| H1 | Tham khảo |
| M15 | Entry trigger |

### Output

```
data/
├── EURUSD_M15.parquet   (~50MB, 2 năm)
├── EURUSD_H1.parquet    (~8MB)
├── EURUSD_H4.parquet    (~2MB)
├── EURUSD_D.parquet     (~0.5MB)
├── XAUUSD_M15.parquet
├── XAUUSD_H1.parquet
├── XAUUSD_H4.parquet
├── XAUUSD_D.parquet
├── BTCUSD_M15.parquet
├── BTCUSD_H1.parquet
├── BTCUSD_H4.parquet
└── BTCUSD_D.parquet
```

### Schema parquet

| Column | Type | Mô tả |
|---|---|---|
| timestamp | datetime64 | index |
| open | float64 | |
| high | float64 | |
| low | float64 | |
| close | float64 | |
| volume | float64 | |

Volume cho forex có thể là tick volume (Dukascopy) hoặc NaN.

## Acceptance criteria

- [ ] Chạy `python src/download_data.py` không lỗi
- [ ] 12 file parquet được tạo
- [ ] Mỗi file có ≥ 1 năm data, ideal 2 năm
- [ ] Data không có NaN ngoài 5 dòng đầu (warmup indicator)
- [ ] Spot check: giá EURUSD 2 năm trước vs giá file — hợp lý
