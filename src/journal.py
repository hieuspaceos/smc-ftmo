"""SQLite journal for FTMO backtester. Logs every simulated trade.

Schema tracks all 12-rule confluence factors (displacement, bias, sweep,
premium/discount, first-test) plus partial-TP state and session attribution.
Used by app.py to filter, render trade table, and compute stats.
"""
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

DB_PATH = Path("output/trades.db")

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
    r_multiple REAL,                  -- R-multiple at exit
    pnl_usd REAL,                     -- realized P&L USD
    risk_usd REAL,                    -- risk amount USD
    setup_type TEXT,                  -- 'OB' | 'Breaker' | 'FVG' | 'Combined'
    confluence_score INTEGER,         -- 1-5
    bias_d TEXT,                      -- 'bull' | 'bear' | 'null'
    bias_h4 TEXT,
    displacement INTEGER,             -- 0/1
    sweep_clean INTEGER,              -- 0/1
    premium_discount TEXT,            -- 'premium' | 'discount' | 'neutral'
    first_test INTEGER,               -- 0/1
    session TEXT,                     -- 'london' | 'ny' | 'asia' | 'overlap' | 'other'
    is_partial INTEGER DEFAULT 0,     -- any partial TP hit?
    exit_reason TEXT,                 -- 'tp1' | 'tp2' | 'tp3' | 'sl' | 'be' | 'time'
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pair ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_timestamp ON trades(timestamp_entry);
CREATE INDEX IF NOT EXISTS idx_score ON trades(confluence_score);
CREATE INDEX IF NOT EXISTS idx_r ON trades(r_multiple);
"""

_INSERT_SQL = """
INSERT INTO trades (
    timestamp_entry, timestamp_exit, pair, side, entry, sl, tp1, tp2, tp3,
    exit_price, r_multiple, pnl_usd, risk_usd, setup_type,
    confluence_score, bias_d, bias_h4, displacement, sweep_clean,
    premium_discount, first_test, session, is_partial, exit_reason, note
) VALUES (
    :timestamp_entry, :timestamp_exit, :pair, :side, :entry, :sl, :tp1, :tp2, :tp3,
    :exit_price, :r_multiple, :pnl_usd, :risk_usd, :setup_type,
    :confluence_score, :bias_d, :bias_h4, :displacement, :sweep_clean,
    :premium_discount, :first_test, :session, :is_partial, :exit_reason, :note
)
"""

_BOOL_COLS = ("displacement", "sweep_clean", "first_test", "is_partial")


def _normalize_trade(trade: dict) -> dict:
    """Coerce trade dict into the exact shape SQLite expects."""
    out = dict(trade)
    defaults = {
        "timestamp_entry": None,
        "timestamp_exit": None,
        "pair": "EURUSD",
        "side": "long",
        "entry": 0.0,
        "sl": 0.0,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "exit_price": None,
        "r_multiple": 0.0,
        "pnl_usd": 0.0,
        "risk_usd": 0.0,
        "setup_type": "OB",
        "confluence_score": 0,
        "bias_d": None,
        "bias_h4": None,
        "displacement": 0,
        "sweep_clean": 0,
        "premium_discount": "neutral",
        "first_test": 0,
        "session": "london",
        "is_partial": 0,
        "exit_reason": None,
        "note": None,
    }
    for k, v in defaults.items():
        out.setdefault(k, v)
    for key in _BOOL_COLS:
        out[key] = 1 if out.get(key) else 0
    for ts_key in ("timestamp_entry", "timestamp_exit"):
        v = out.get(ts_key)
        if v is None:
            out[ts_key] = None
        elif hasattr(v, "isoformat"):
            out[ts_key] = v.isoformat()
        else:
            out[ts_key] = str(v)
    return out


class Journal:
    """Thin SQLite wrapper. Single writer (Streamlit session)."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def insert_trade(self, trade: dict) -> int:
        row = _normalize_trade(trade)
        with self._connect() as conn:
            cur = conn.execute(_INSERT_SQL, row)
            return cur.lastrowid

    def insert_many(self, trades: Iterable[dict]) -> int:
        rows = [_normalize_trade(t) for t in trades]
        if not rows:
            return 0
        with self._connect() as conn:
            cur = conn.executemany(_INSERT_SQL, rows)
            return cur.rowcount

    def clear(self, pair: Optional[str] = None) -> int:
        """Delete trades. If ``pair`` given, only that pair is removed.
        Returns number of rows deleted."""
        with self._connect() as conn:
            if pair:
                cur = conn.execute("DELETE FROM trades WHERE pair = ?", (pair,))
            else:
                cur = conn.execute("DELETE FROM trades")
            return cur.rowcount

    def query(
        self,
        pair: Optional[str] = None,
        pairs: Optional[list] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_score: Optional[int] = None,
        max_score: Optional[int] = None,
        win_only: bool = False,
        lose_only: bool = False,
        session: Optional[str] = None,
        setup_type: Optional[str] = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if pair:
            sql += " AND pair = ?"
            params.append(pair)
        elif pairs:
            placeholders = ",".join("?" for _ in pairs)
            sql += f" AND pair IN ({placeholders})"
            params.extend(pairs)
        if date_from:
            sql += " AND timestamp_entry >= ?"
            params.append(str(date_from))
        if date_to:
            sql += " AND timestamp_entry <= ?"
            params.append(str(date_to))
        if min_score is not None:
            sql += " AND confluence_score >= ?"
            params.append(min_score)
        if max_score is not None:
            sql += " AND confluence_score <= ?"
            params.append(max_score)
        if win_only:
            sql += " AND r_multiple > 0"
        if lose_only:
            sql += " AND r_multiple < 0"
        if session:
            sql += " AND session = ?"
            params.append(session)
        if setup_type:
            sql += " AND setup_type = ?"
            params.append(setup_type)
        sql += " ORDER BY timestamp_entry DESC"
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def stats_by_setup(self) -> pd.DataFrame:
        """Winrate and avg R per setup_type and confluence_score."""
        sql = """
            SELECT
                setup_type,
                confluence_score,
                COUNT(*) AS n_trades,
                AVG(r_multiple) AS avg_r,
                SUM(CASE WHEN r_multiple > 0 THEN 1 ELSE 0 END) * 1.0
                    / NULLIF(COUNT(*), 0) AS winrate,
                SUM(CASE WHEN r_multiple > 0 THEN r_multiple ELSE 0 END) AS gross_profit_r,
                SUM(CASE WHEN r_multiple < 0 THEN r_multiple ELSE 0 END) AS gross_loss_r
            FROM trades
            GROUP BY setup_type, confluence_score
            ORDER BY n_trades DESC
        """
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn)

    def aggregate(self) -> dict:
        """Portfolio-level metrics: winrate, PF, total R, trade count."""
        with self._connect() as conn:
            df = pd.read_sql_query(
                "SELECT r_multiple, pnl_usd FROM trades WHERE r_multiple IS NOT NULL",
                conn,
            )
        if df.empty:
            return {
                "n_trades": 0, "winrate": 0.0, "profit_factor": 0.0,
                "avg_r": 0.0, "total_r": 0.0, "total_pnl_usd": 0.0,
            }
        wins = df[df["r_multiple"] > 0]["r_multiple"].sum()
        losses = df[df["r_multiple"] < 0]["r_multiple"].sum()
        pf = float(wins / abs(losses)) if losses < 0 else 0.0
        return {
            "n_trades": int(len(df)),
            "winrate": float((df["r_multiple"] > 0).mean()),
            "profit_factor": pf,
            "avg_r": float(df["r_multiple"].mean()),
            "total_r": float(df["r_multiple"].sum()),
            "total_pnl_usd": float(df["pnl_usd"].fillna(0).sum()),
        }

    def export_csv(self, path: Path) -> None:
        df = self.query()


        df.to_csv(path, index=False)

    # ---- backwards-compatible aliases (consumed by tests) ----
    def insert_trades(self, trades: Iterable[dict]) -> int:
        return self.insert_many(trades)

    def get_trades(self, **kwargs) -> pd.DataFrame:
        return self.query(**kwargs)

    def filter_trades(self, **kwargs) -> pd.DataFrame:
        return self.query(**kwargs)


if __name__ == "__main__":
    print("Testing journal module...")
    j = Journal(db_path=Path("output/test_trades.db"))
    j.clear()
    sample = {
        "timestamp_entry": "2024-01-02T10:15:00",
        "timestamp_exit": "2024-01-02T12:30:00",
        "pair": "EURUSD", "side": "long",
        "entry": 1.1010, "sl": 1.0990, "tp1": 1.1050, "tp2": 1.1070, "tp3": 1.1090,
        "exit_price": 1.1070, "r_multiple": 3.0, "pnl_usd": 330.0, "risk_usd": 110.0,
        "setup_type": "OB", "confluence_score": 4,
        "bias_d": "bull", "bias_h4": "bull",
        "displacement": True, "sweep_clean": False,
        "premium_discount": "discount", "first_test": True,
        "session": "london", "is_partial": True,
        "exit_reason": "tp2", "note": "",
    }
    j.insert_trade(sample)
    j.insert_many([sample, sample])
    df = j.query(pair="EURUSD")
    print(df)
    print("stats:", j.stats_by_setup())
    print("aggregate:", j.aggregate())
    print("journal verified.")
