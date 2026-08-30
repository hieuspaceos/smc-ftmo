-- Bot storage schema (P0 → P2)
-- Additive: does NOT touch existing output/trades.db.

PRAGMA foreign_keys = ON;

-- Phase 01: every incoming webhook payload lands here.
-- dedupe_count tracks how many times the same signal_id has been received.
CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id        TEXT NOT NULL,
    prefix           TEXT NOT NULL,
    version          TEXT NOT NULL,
    event            TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    tf               TEXT NOT NULL,
    side             TEXT NOT NULL,
    level            REAL NOT NULL,
    bar_time         INTEGER NOT NULL,
    ob_id            INTEGER NOT NULL DEFAULT -1,
    bos_id           INTEGER NOT NULL DEFAULT -1,
    state            TEXT NOT NULL,
    reason           TEXT NOT NULL DEFAULT '',
    raw_payload      TEXT NOT NULL,
    received_at      TEXT NOT NULL,
    client_ip        TEXT,
    url_token_ok     INTEGER NOT NULL DEFAULT 0,
    dedupe_count     INTEGER NOT NULL DEFAULT 1,
    UNIQUE(signal_id, prefix)
);

CREATE INDEX IF NOT EXISTS idx_alert_log_received_at ON alert_log(received_at);
CREATE INDEX IF NOT EXISTS idx_alert_log_symbol_tf    ON alert_log(symbol, tf);

-- Phase 02: per-signal lifecycle (received → notified → accepted/rejected → expired).
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id     TEXT NOT NULL,
    event_type    TEXT NOT NULL,  -- 'received'|'notified'|'accepted'|'rejected'|'expired'|'notified_failed'
    payload       TEXT,
    actor         TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_events_signal ON signal_events(signal_id, created_at);

-- Phase 02-03: daily manual gate acks (six gates × trade_date).
CREATE TABLE IF NOT EXISTS gate_ack (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date     TEXT NOT NULL,
    gate_name      TEXT NOT NULL,
    value          INTEGER NOT NULL,
    expires_at     TEXT NOT NULL,
    acknowledged_by TEXT,
    acknowledged_at TEXT NOT NULL,
    UNIQUE(trade_date, gate_name)
);

CREATE INDEX IF NOT EXISTS idx_gate_ack_date ON gate_ack(trade_date);

-- Phase 06: demo MT5 execution audit.
CREATE TABLE IF NOT EXISTS execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id      TEXT NOT NULL,
    transport      TEXT NOT NULL,  -- 'file'|'metaapi'|'disabled'
    state          TEXT NOT NULL,  -- 'queued'|'sent'|'acked'|'failed'|'rejected'
    payload        TEXT,
    mt5_ticket     TEXT,
    fill_price     REAL,
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE(signal_id, transport)
);

CREATE INDEX IF NOT EXISTS idx_execution_log_state ON execution_log(state, created_at);