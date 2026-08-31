"""Fetch BTCUSDT M1 klines from Binance public API → HistData-style CSV.

Output format (matches scripts/format_histdata.py input):
    YYYYMMDD HHMMSS;OPEN;HIGH;LOW;CLOSE;VOL

Binance kline schema (each row is a list):
    [open_time, o, h, l, c, volume, close_time, quote_volume, trades,
     taker_buy_base, taker_buy_quote, ignore]

We use `volume` (base asset = BTC) and drop sub-minute precision via integer
truncation of timestamps → M1 boundaries aligned to Binance bar open time.

Usage:
    python scripts/fetch_binance_btc_m1.py                          # 2017→2026 (today)
    python scripts/fetch_binance_btc_m1.py --start 2017 --end 2026
    python scripts/fetch_binance_btc_m1.py --symbol BTCUSDT --out histdata

Resumable: writes one CSV per year; skips a year file if it already exists
and is non-empty unless --force is passed.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


BINANCE_BASE = "https://api.binance.com"
KLINE_URL = f"{BINANCE_BASE}/api/v3/klines"
RATE_SLEEP_S = 0.05  # 20 req/s — Binance allows 1200/min weight, M1 is 1/req
MAX_LIMIT = 1000
HTTP_TIMEOUT = 30


def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> list[list]:
    """Paginate Binance klines from start_ms (inclusive) up to end_ms (exclusive).

    Each request returns up to 1000 M1 bars (~16.6h). We paginate by stepping
    forward to last bar's openTime + 60_000 ms until we hit end_ms.
    """
    rows: list[list] = []
    cursor = start_ms
    session = requests.Session()
    session.headers.update({"User-Agent": "smc-ftmo/1.0"})
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": MAX_LIMIT,
            "startTime": cursor,
            "endTime": end_ms,
        }
        try:
            resp = session.get(KLINE_URL, params=params, timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            print(f"    network error: {type(e).__name__} → retry in 3s", file=sys.stderr)
            time.sleep(3)
            continue
        if resp.status_code == 429 or resp.status_code == 418:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"    HTTP {resp.status_code} → sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if not resp.ok:
            print(f"    HTTP {resp.status_code}: {resp.text[:200]} → retry in 3s", file=sys.stderr)
            time.sleep(3)
            continue
        payload = resp.json()
        if not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        next_cursor = last_open + 60_000
        if next_cursor == cursor:
            # Defensive: avoid infinite loop if server repeats last bar.
            break
        cursor = next_cursor
        time.sleep(RATE_SLEEP_S)
    return rows


def klines_to_histdata_csv(rows: list[list], year: int) -> list[str]:
    """Convert Binance rows → list of HistData-format CSV lines for `year`."""
    lines: list[str] = []
    for r in rows:
        open_ms = int(r[0])
        ts = datetime.fromtimestamp(open_ms / 1000, tz=timezone.utc)
        if ts.year != year:
            continue
        o, h, l, c, v = (float(r[i]) for i in (1, 2, 3, 4, 5))
        # HistData uses 6-decimal precision like EURUSD, but BTC only needs 2.
        # We keep 6 to be safe (no precision loss; format_histdata reads as float).
        lines.append(
            f"{ts.strftime('%Y%m%d %H%M%S')};{o:.6f};{h:.6f};{l:.6f};{c:.6f};{v:.6f}"
        )
    return lines


def year_window_ms(year: int) -> tuple[int, int]:
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch BTCUSDT M1 from Binance")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", type=int, default=2017)
    parser.add_argument("--end", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("histdata"))
    parser.add_argument("--force", action="store_true", help="refetch even if file exists")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    grand_total = 0

    for year in range(args.start, args.end + 1):
        out_path = args.out / f"DAT_ASCII_BTCUSD_M1_{year:04d}.csv"
        if out_path.exists() and out_path.stat().st_size > 0 and not args.force:
            existing = sum(1 for _ in out_path.open(encoding="utf-8"))
            print(f"  {out_path.name}: skip ({existing:,} rows already on disk)")
            grand_total += existing
            continue

        start_ms, end_ms = year_window_ms(year)
        t0 = time.perf_counter()
        print(f"  {year}: fetching {args.symbol} 1m klines...")
        rows = fetch_klines(args.symbol, start_ms, end_ms)
        lines = klines_to_histdata_csv(rows, year)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elapsed = time.perf_counter() - t0
        print(f"    → {out_path.name}: {len(lines):,} rows in {elapsed:.1f}s")
        grand_total += len(lines)

    print(f"\nDone: {grand_total:,} total rows across {args.end - args.start + 1} years")
    print(f"Output dir: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
