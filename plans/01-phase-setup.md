# Phase 0 — Setup môi trường

## Mục tiêu

Dựng project skeleton, cài dependencies, viết README và config để chạy được `streamlit hello`.

## Task

### Tạo file gốc

- `requirements.txt` — pin version các thư viện
- `README.md` — hướng dẫn cài đặt, chạy, troubleshoot
- `config.yaml` — FTMO rules, pairs, risk params
- `.gitignore` — ignore data, output, cache

### requirements.txt

```
streamlit>=1.30
plotly>=5.18
pandas>=2.0
numpy>=1.24
pyarrow>=14.0
smartmoneyconcepts>=0.0.27
ccxt>=4.0
yfinance>=0.2.30
ta>=0.11
pyyaml>=6.0
```

### config.yaml

```yaml
# FTMO 2-Step rules
ftmo:
  account_size: 100000
  phase: challenge           # challenge | verification | funded
  profit_target: 0.10
  max_daily_loss: 0.05
  max_total_loss: 0.10
  timezone: "Europe/Paris"   # FTMO dùng CE(S)T

# Risk
risk:
  per_trade_pct: 0.0055      # 0.55%
  max_trades_per_day: 3
  daily_loss_limit_r: 2.0    # mất 2R → dừng

# Strategy
strategy:
  swing_length: 20
  rr_target: 2.5
  displacement_atr_mult: 1.5
  sweep_atr_buffer: 0.05
  min_confluence_score: 4
  partial_tp:
    - {pct: 0.40, r: 2.0}
    - {pct: 0.30, r: 3.0}
    - {pct: 0.30, r: 4.0}
  sl_atr_buffer: 0.2

# Pairs
pairs:
  - EURUSD
  - XAUUSD
  - BTCUSD

# Timeframes
timeframes:
  - D
  - H4
  - H1
  - M15

# Sessions (NY time)
sessions:
  london: {start: "02:00", end: "05:00"}
  ny: {start: "07:00", end: "10:00"}
  overlap: {start: "08:00", end: "10:00"}
```

### README.md

Hướng dẫn từng bước:
1. Cài Python 3.10+
2. Clone/extract project
3. `pip install -r requirements.txt`
4. (Phase 1) `python src/download_data.py`
5. `streamlit run app.py`
6. Mở browser `http://localhost:8501`

Troubleshoot:
- Lỗi `Microsoft Visual C++ 14.0` khi cài `ta`: bỏ qua, không quan trọng
- Lỗi `ccxt` không connect Binance: dùng yfinance fallback cho BTC
- Lỗi port 8501 bận: `streamlit run app.py --server.port 8502`

### .gitignore

```
data/
output/
__pycache__/
*.pyc
.streamlit/secrets.toml
.venv/
venv/
.env
```

## Output Phase 0

- File `requirements.txt`, `README.md`, `config.yaml`, `.gitignore` đầy đủ
- Bạn chạy `pip install -r requirements.txt` thành công
- `streamlit hello` chạy được
- Sẵn sàng cho Phase 1

## Acceptance criteria

- [ ] `pip install -r requirements.txt` không lỗi
- [ ] `streamlit hello` mở được trang demo
- [ ] `config.yaml` đọc được bằng yaml.safe_load
- [ ] `README.md` đủ rõ cho người mới cài lần đầu
