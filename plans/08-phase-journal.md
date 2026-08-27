# Phase 7 — Journal SQLite

## Mục tiêu

Mỗi backtest auto-log trade vào SQLite. Query lọc theo pair/ngày/score/win-lose.

## Task

### File: `src/journal.py`

```python
import sqlite3
from pathlib import Path

DB_PATH = Path('output/trades.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_entry TEXT NOT NULL,
    timestamp_exit TEXT,
    pair TEXT NOT NULL,
    side TEXT NOT NULL,                -- 'long' | 'short'
    entry REAL NOT NULL,
    sl REAL NOT NULL,
    tp1 REAL, tp2 REAL, tp3 REAL,
    exit_price REAL,
    r_multiple REAL,                  -- kết quả R
    pnl_usd REAL,                     -- P&L bằng USD
    risk_usd REAL,                    -- risk amount USD
    setup_type TEXT,                  -- 'OB' | 'Breaker' | 'FVG' | 'Combined'
    confluence_score INTEGER,         -- 1-5
    bias_d TEXT,                      -- 'bull' | 'bear' | 'null'
    bias_h4 TEXT,
    displacement INTEGER,             -- 0/1
    sweep_clean INTEGER,              -- 0/1
    premium_discount TEXT,            -- 'premium' | 'discount' | 'neutral'
    first_test INTEGER,               -- 0/1
    session TEXT,                     -- 'london' | 'ny' | 'asia' | 'other'
    is_partial INTEGER DEFAULT 0,     -- đã chốt partial chưa
    exit_reason TEXT,                 -- 'tp1' | 'tp2' | 'tp3' | 'sl' | 'be'
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pair ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_timestamp ON trades(timestamp_entry);
CREATE INDEX IF NOT EXISTS idx_score ON trades(confluence_score);
"""

class Journal:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def insert_trade(self, trade):
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO trades (
                    timestamp_entry, timestamp_exit, pair, side, entry, sl, tp1, tp2, tp3,
                    exit_price, r_multiple, pnl_usd, risk_usd, setup_type,
                    confluence_score, bias_d, bias_h4, displacement, sweep_clean,
                    premium_discount, first_test, session, is_partial, exit_reason, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (...))
            return cursor.lastrowid

    def query(self, pair=None, date_from=None, date_to=None,
              min_score=None, win_only=False, lose_only=False):
        sql = "SELECT * FROM trades WHERE 1=1"
        params = []
        if pair:
            sql += " AND pair = ?"
            params.append(pair)
        if date_from:
            sql += " AND timestamp_entry >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND timestamp_entry <= ?"
            params.append(date_to)
        if min_score is not None:
            sql += " AND confluence_score >= ?"
            params.append(min_score)
        if win_only:
            sql += " AND r_multiple > 0"
        if lose_only:
            sql += " AND r_multiple < 0"

        sql += " ORDER BY timestamp_entry DESC"
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def stats_by_setup(self):
        """Thống kê winrate theo setup_type và score"""
        with self._connect() as conn:
            return pd.read_sql_query("""
                SELECT
                    setup_type,
                    confluence_score,
                    COUNT(*) as n_trades,
                    AVG(r_multiple) as avg_r,
                    SUM(CASE WHEN r_multiple > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as winrate
                FROM trades
                GROUP BY setup_type, confluence_score
                ORDER BY n_trades DESC
            """, conn)

    def export_csv(self, path):
        df = self.query()
        df.to_csv(path, index=False)
```

## Acceptance criteria

- [ ] Chạy backtest → file `output/trades.db` được tạo
- [ ] Bảng `trades` có đủ schema
- [ ] Query `Journal().query(pair='EURUSD')` trả về DataFrame
- [ ] Filter theo date_from, date_to hoạt động
- [ ] Filter win_only, lose_only hoạt động
- [ ] `stats_by_setup()` trả về bảng thống kê theo setup + score
- [ ] Export CSV ra file đúng format
