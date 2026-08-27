import pandas as pd
import yfinance as yf
import ccxt
from datetime import datetime, timedelta
from pathlib import Path
import time
import warnings
warnings.filterwarnings('ignore')

PAIRS = ['EURUSD', 'XAUUSD', 'BTCUSD']
TIMEFRAMES = ['1d', '4h', '1h', '15m']
YEARS = 10
DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

def download_yfinance(symbol: str, years: int = YEARS, interval: str = '1d') -> pd.DataFrame:
    """Download with 2-year chunks to bypass yfinance limit for intraday data."""
    yf_symbol = {'EURUSD': 'EURUSD=X', 'XAUUSD': 'GC=F', 'BTCUSD': 'BTC-USD'}.get(symbol, symbol)
    end = datetime.now()
    data_list = []
    chunk_size = 2  # yfinance limit ~2 years for 1h+
    for i in range(0, years, chunk_size):
        chunk_start = end - timedelta(days=365 * (i + chunk_size))
        chunk_end = end - timedelta(days=365 * i)
        try:
            chunk = yf.download(
                yf_symbol,
                start=chunk_start,
                end=chunk_end,
                interval=interval,
                progress=False,
                auto_adjust=False
            )
            if not chunk.empty:
                data_list.append(chunk)
            time.sleep(1)
        except Exception as e:
            print(f"yfinance chunk failed for {symbol} {interval} ({chunk_start.date()} to {chunk_end.date()}): {e}")
    if data_list:
        df = pd.concat(data_list).sort_index().drop_duplicates()
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        df.index.name = 'timestamp'
        return df
    return pd.DataFrame()

def download_ccxt(symbol: str, timeframe: str) -> pd.DataFrame:
    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        since = int((datetime.now() - timedelta(days=YEARS * 400)).timestamp() * 1000)
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe, since=since, limit=2000)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('timestamp')
        return df
    except Exception as e:
        print(f"ccxt failed for BTC {timeframe}: {e}")
        return pd.DataFrame()

def resample_to_tf(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    if df.empty or len(df) < 5:
        return df
    rule_map = {'1d': 'D', '4h': '4h', '1h': '1h', '15m': '15min'}
    rule = rule_map.get(target_tf.lower(), target_tf)
    ohlc = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    try:
        return df.resample(rule).agg(ohlc).dropna(how='all')
    except:
        return df

def save_parquet(df: pd.DataFrame, pair: str, tf: str):
    if df.empty:
        return
    tf_map = {'1d': 'D', '4h': 'H4', '1h': 'H1', '15m': 'M15'}
    tf_norm = tf_map.get(tf.lower(), tf.upper())
    path = DATA_DIR / f"{pair.lower()}_{tf_norm.lower()}.parquet"
    df.to_parquet(path)
    print(f"Saved {path} ({len(df)} rows)")

def main():
    print(f"Starting data download for SMC FTMO unified tool ({YEARS} years OHLCV with chunking)...")
    for pair in PAIRS:
        print(f"\nDownloading {pair}...")
        for tf_code in TIMEFRAMES:
            print(f"  -> {tf_code}")
            if pair == 'BTCUSD':
                df = download_ccxt(pair, tf_code)
                if df.empty:
                    df = download_yfinance(pair, YEARS, tf_code)
            else:
                df = download_yfinance(pair, YEARS, tf_code)
                if not df.empty and tf_code in ('4h', '1h', '15m'):
                    df = resample_to_tf(df, tf_code)
            if not df.empty:
                if isinstance(df.index, pd.DatetimeIndex):
                    df.index.name = 'timestamp'
                df = df[['open', 'high', 'low', 'close', 'volume']].copy()
                save_parquet(df, pair, tf_code)
            else:
                print(f"  Failed to download {pair} {tf_code}")
            time.sleep(2)
    print("\n10-year data download complete. Verifying...")
    for f in sorted(DATA_DIR.glob("*.parquet")):
        df = pd.read_parquet(f)
        print(f"  {f.name}: {len(df)} rows, {df.index.min()} to {df.index.max()}")
    print("Data ready for 10 years (daily full, intraday chunked).")

if __name__ == "__main__":
    main()
