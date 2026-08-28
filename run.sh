#!/usr/bin/env bash
# SMC FTMO launcher — macOS/Linux
# Auto-creates venv on first run, installs deps, processes data, starts Streamlit.
set -e

cd "$(dirname "$0")"

# Pick Python
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Error: python3 not found. Install Python 3.10+ from https://python.org"
  exit 1
fi

# Venv
if [ ! -d ".venv" ]; then
  echo "[setup] creating virtualenv .venv ..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Deps (idempotent)
echo "[setup] installing dependencies ..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pytest >/dev/null 2>&1 || true

# Data: build parquet nếu thiếu
need_data=0
for tf in m15 h1 h4 d; do
  [ -f "data/eurusd_${tf}.parquet" ] || need_data=1
done
if [ "$need_data" = "1" ]; then
  if ls histdata/DAT_ASCII_EURUSD_M1_*.csv >/dev/null 2>&1; then
    echo "[setup] processing histdata CSVs -> parquet ..."
    python src/process_histdata.py
  else
    echo "[warn] no histdata CSVs found; backtest sẽ rỗng."
    echo "       Tải M1 EURUSD từ histdata.com vào histdata/ rồi chạy lại."
  fi
else
  echo "[setup] parquet data OK, skip processing."
fi

# Clear bytecode cache như run.bat
rm -rf src/__pycache__ __pycache__ 2>/dev/null || true

# Run
export PYTHONPATH=src
PORT="${PORT:-8501}"
echo "[run] starting Streamlit on http://localhost:${PORT}"
exec streamlit run app.py --server.port="$PORT"
