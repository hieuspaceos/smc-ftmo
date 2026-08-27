import pandas as pd
from pathlib import Path
import glob

print("=== SMC FTMO HistData Processor ===")
print("This script reads all M1 CSV from HistData and generates clean parquet for M15, H1, H4, Daily.")

hist_dir = Path("histdata")
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

csv_files = sorted(glob.glob(str(hist_dir / "DAT_ASCII_EURUSD_M1_*.csv")))
if not csv_files:
    print("No CSV files found in histdata/ folder!")
    print("Please download M1 EURUSD data from HistData.com for multiple years and unzip to histdata/")
    exit(1)

print(f"Found {len(csv_files)} CSV files. Processing...")

all_dfs = []
for csv_path in csv_files:
    print(f"Reading {Path(csv_path).name}...")
    df = pd.read_csv(
        csv_path,
        sep=";",
        header=None,
        names=["datetime", "open", "high", "low", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["datetime"], format="%Y%m%d %H%M%S")
    df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
    all_dfs.append(df)

df_full = pd.concat(all_dfs).sort_index().drop_duplicates()
df_full = df_full.astype(float)

print(f"Total M1 bars: {len(df_full):,} from {df_full.index.min()} to {df_full.index.max()}")

# Resample to all timeframes
for tf_name, rule in [("M15", "15min"), ("H1", "1h"), ("H4", "4h"), ("D", "1D")]:
    print(f"Resampling to {tf_name}...")
    resampled = df_full.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    output_path = data_dir / f"eurusd_{tf_name.lower()}.parquet"
    resampled.to_parquet(output_path)
    print(f"→ Saved {output_path} with {len(resampled):,} rows")

print("\n=== DONE ===")
print("All parquet files generated in data/ folder.")
print("You can now run the app with run.bat or streamlit run app.py")
print("Backtest should now have many more trades with full history.")
