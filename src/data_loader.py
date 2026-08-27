import pandas as pd
from pathlib import Path
from functools import lru_cache
import streamlit as st
from typing import Dict

DATA_DIR = Path('data')

@st.cache_data(ttl=3600)
def load_multi_tf_data(pair: str = 'EURUSD') -> Dict[str, pd.DataFrame]:
    """Load parquet files for all timeframes into dict. Normalizes schema."""
    tfs = ['D', 'H4', 'H1', 'M15']
    data = {}
    for tf in tfs:
        file = DATA_DIR / f"{pair.lower()}_{tf.lower()}.parquet"
        if file.exists():
            df = pd.read_parquet(file)
            if isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df.index.name = 'timestamp'
            df = df[['open', 'high', 'low', 'close', 'volume']].copy()
            df = df.sort_index().drop_duplicates(keep='last')  # fix non-monotonic and duplicates
            data[tf] = df
            print(f"Loaded {tf} for {pair}: {df.shape}")
        else:
            print(f"Missing data file: {file}")
    return data

@lru_cache(maxsize=32)
def get_tf_data(pair: str, tf: str) -> pd.DataFrame:
    """Cached single TF loader."""
    data = load_multi_tf_data(pair)
    return data.get(tf, pd.DataFrame())

def get_available_pairs() -> list:
    """Discover available pairs from parquet files."""
    if not DATA_DIR.exists():
        return ['EURUSD']
    files = list(DATA_DIR.glob("*.parquet"))
    pairs = set()
    for f in files:
        name = f.stem.split('_')[0]
        pairs.add(name.upper())
    return sorted(list(pairs)) or ['EURUSD', 'XAUUSD', 'BTCUSD']

if __name__ == "__main__":
    # Verification
    print("Testing data_loader...")
    pairs = get_available_pairs()
    print("Available pairs:", pairs)
    for p in pairs[:1]:  # test first pair
        data = load_multi_tf_data(p)
        print(f"For {p}: loaded TFs = {list(data.keys())}")
        if data:
            sample = next(iter(data.values()))
            print("Sample schema OK:", sample.index.name, list(sample.columns))
    print("Data loader verified.")
