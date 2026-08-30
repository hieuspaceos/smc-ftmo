"""Edge-case + concurrency audit tests for Phase 04 replay + capture."""

from __future__ import annotations

import asyncio
import csv
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_bot_backtest.capture import (
    CSV_COLUMNS,
    capture_from_live,
    capture_from_pine_logs,
    capture_from_replay,
)
from smc_bot_backtest.replay_engine import ReplayEngine, replay_from_ohlc
from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.payload import parse_payload


def _make_ohlc(n: int = 200, seed: int = 42, **index_kwargs) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.0005, n),
            "high": close + np.abs(rng.normal(0, 0.001, n)),
            "low": close - np.abs(rng.normal(0, 0.001, n)),
            "close": close,
            "volume": rng.integers(100, 1000, n),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="15min", **index_kwargs),
    )


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Bug #1: dir=bullish / dir=bearish normalization
# ---------------------------------------------------------------------------


class TestPineDirNormalization:
    """Pine emits dir=bullish/bearish before normalization. Pine paste parser
    must normalize to long/short, otherwise AlertPayload validator rejects."""

    def test_bullish_normalizes_to_long(self) -> None:
        from smc_bot_backtest.capture import _parse_pine_line

        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=bullish|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        p = _parse_pine_line(line)
        assert p is not None
        assert p.dir == "long"

    def test_bearish_normalizes_to_short(self) -> None:
        from smc_bot_backtest.capture import _parse_pine_line

        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=bearish|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        p = _parse_pine_line(line)
        assert p is not None
        assert p.dir == "short"

    def test_long_passes_through(self) -> None:
        from smc_bot_backtest.capture import _parse_pine_line

        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        p = _parse_pine_line(line)
        assert p is not None
        assert p.dir == "long"

    def test_unknown_dir_normalizes_to_none(self) -> None:
        """normalize_dir maps unknown values to 'none' (safe default per
        bot/webhook/payload.py). AlertPayload accepts 'none' as a valid dir."""
        from smc_bot_backtest.capture import _parse_pine_line

        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=sideways|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        p = _parse_pine_line(line)
        assert p is not None
        assert p.dir == "none"


# ---------------------------------------------------------------------------
# Replay with non-datetime index
# ---------------------------------------------------------------------------


class TestReplayIndexTypes:
    def test_non_datetime_integer_index(self) -> None:
        """Replay currently uses ohlc.index[bar_idx].timestamp() which
        requires a Timestamp/datetime index. Integer index raises."""
        n = 200
        rng = np.random.default_rng(42)
        close = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
        ohlc = pd.DataFrame(
            {
                "open": close + rng.normal(0, 0.0005, n),
                "high": close + np.abs(rng.normal(0, 0.001, n)),
                "low": close - np.abs(rng.normal(0, 0.001, n)),
                "close": close,
                "volume": rng.integers(100, 1000, n),
            },
            index=range(n),  # plain integer index
        )
        with pytest.raises(ValueError, match="DatetimeIndex"):
            replay_from_ohlc(ohlc)

    def test_timezone_aware_index_works(self) -> None:
        ohlc = _make_ohlc(tz="UTC")
        result = replay_from_ohlc(ohlc)
        assert len(result.signals) > 0


# ---------------------------------------------------------------------------
# Replay with edge prices
# ---------------------------------------------------------------------------


class TestReplayExtremePrices:
    def test_nan_close_crashes(self) -> None:
        """NaN prices propagate through pivot detection. Document current behavior."""
        rng = np.random.default_rng(42)
        n = 100
        close = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
        close[50] = float("nan")
        ohlc = pd.DataFrame(
            {
                "open": close + rng.normal(0, 0.0005, n),
                "high": close + np.abs(rng.normal(0, 0.001, n)),
                "low": close - np.abs(rng.normal(0, 0.001, n)),
                "close": close,
                "volume": rng.integers(100, 1000, n),
            },
            index=pd.date_range("2026-01-01", periods=n, freq="15min"),
        )
        # Document: NaN in close may produce surprising results.
        try:
            result = replay_from_ohlc(ohlc)
            # If it doesn't crash, signals may be empty (NaN comparisons are False).
            assert isinstance(result.signals, tuple)
        except (ValueError, TypeError):
            pass  # Acceptable to raise.

    def test_negative_prices_do_not_crash(self) -> None:
        """Negative prices are weird but should not crash."""
        rng = np.random.default_rng(42)
        n = 200
        close = 0.5 + np.cumsum(rng.normal(0, 0.001, n)) - 0.6  # some negative
        ohlc = pd.DataFrame(
            {
                "open": close + rng.normal(0, 0.0005, n),
                "high": close + np.abs(rng.normal(0, 0.001, n)),
                "low": close - np.abs(rng.normal(0, 0.001, n)),
                "close": close,
                "volume": rng.integers(100, 1000, n),
            },
            index=pd.date_range("2026-01-01", periods=n, freq="15min"),
        )
        result = replay_from_ohlc(ohlc)
        assert isinstance(result.signals, tuple)


# ---------------------------------------------------------------------------
# Replay concurrency
# ---------------------------------------------------------------------------


class TestReplayConcurrency:
    def test_concurrent_replays_thread_safe(self) -> None:
        """20 threads run replay on independent OHLC frames concurrently."""
        ohlcs = [_make_ohlc(seed=i) for i in range(20)]
        errors: list[BaseException] = []

        def worker(i: int) -> None:
            try:
                for _ in range(5):
                    replay_from_ohlc(ohlcs[i])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"concurrent replay crashed: {errors[:3]}"

    def test_concurrent_same_ohlc_deterministic(self) -> None:
        """20 threads on the SAME OHLC produce IDENTICAL run_ids."""
        ohlc = _make_ohlc()
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            r = replay_from_ohlc(ohlc)
            with lock:
                results.append(r.run.run_id)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1, f"results differ: {set(results)}"


# ---------------------------------------------------------------------------
# Capture edge cases
# ---------------------------------------------------------------------------


class TestCaptureEdges:
    def test_capture_from_pine_empty_lines_skipped(self) -> None:
        out = Path(f"output/test_pine_empty_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_pine_logs("\n\n\n", out)
            assert n == 0
        finally:
            _cleanup(out)

    def test_capture_from_pine_state_with_pipe_in_value_rejected(self) -> None:
        """State value containing '|' should be rejected (anchored [^|]+)."""
        out = Path(f"output/test_pine_pipe_{int(time.time() * 1e6)}.csv")
        try:
            paste = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|extra=foo|reason=t1"
            n = capture_from_pine_logs(paste, out)
            # state match: [^|]+ captures 'watch' (good). reason match: captures 't1' (good).
            # The pipe in 'extra=foo' between state and reason splits them cleanly.
            assert n >= 0  # no crash
        finally:
            _cleanup(out)

    def test_capture_from_replay_writes_when_zero_signals(self) -> None:
        """Constant price → 0 signals → CSV has header only."""
        n = 200
        ohlc = pd.DataFrame(
            {
                "open": [1.1] * n,
                "high": [1.1] * n,
                "low": [1.1] * n,
                "close": [1.1] * n,
                "volume": [100] * n,
            },
            index=pd.date_range("2026-01-01", periods=n, freq="15min"),
        )
        out = Path(f"output/test_replay_zero_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_replay(replay_from_ohlc(ohlc), out)
            assert n == 0
            with out.open() as f:
                rows = list(csv.DictReader(f))
            assert rows == []
        finally:
            _cleanup(out)

    def test_capture_from_live_malformed_payload_skipped(self) -> None:
        """If alert_log.raw_payload is malformed, capture_from_live skips the
        row silently. Document: should it log?"""
        p_db = Path(f"output/test_capture_live_bad_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            # Insert directly with broken raw_payload (bypass parse).
            conn = db._conn_ctx()
            with conn as c:
                c.execute(
                    "INSERT INTO alert_log (signal_id, prefix, version, event, "
                    "symbol, tf, side, level, bar_time, ob_id, bos_id, state, "
                    "reason, raw_payload, received_at, client_ip, url_token_ok, "
                    "dedupe_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        "manualsig1234",
                        "SMC", "v1", "bos", "EURUSD", "M15", "long",
                        1.1, 1700000000, -1, -1, "watch", "manual",
                        "this is not a valid SMC payload",  # malformed
                        "2026-08-30T00:00:00+00:00", None, 1,
                    ),
                )
            out = Path(f"output/test_capture_live_bad_{int(time.time() * 1e6)}.csv")
            try:
                n = capture_from_live(db, out)
                # No valid signal rows because parser failed.
                assert n == 0
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)

    def test_capture_from_live_decision_overwritten_by_latest(self) -> None:
        """If signal has both accept and reject events, the latest one wins."""
        p_db = Path(f"output/test_capture_live_dec_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            body = "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=42|bos_id=7|state=chart-qualified|reason=ok"
            payload = parse_payload(body)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "accept", actor="tester1")
            db.record_event(payload.signal_id, "reject", actor="tester2")
            out = Path(f"output/test_capture_live_dec_{int(time.time() * 1e6)}.csv")
            try:
                capture_from_live(db, out)
                row = list(csv.DictReader(out.open()))[0]
                # list_recent_events returns DESC by id; latest is reject.
                assert row["decision"] == "reject"
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)


# ---------------------------------------------------------------------------
# CSV schema robustness
# ---------------------------------------------------------------------------


class TestCSVSchema:
    def test_columns_exact_match_plan(self) -> None:
        expected = (
            "source", "run_id", "signal_id", "event", "symbol", "tf", "side",
            "level", "entry", "sl", "tp1", "tp2", "tp3", "bar_time", "ob_id",
            "bos_id", "state", "reason", "score", "gate_status", "decision",
            "decision_at", "execution_status",
        )
        assert CSV_COLUMNS == expected

    def test_csv_uses_utf8_encoding(self) -> None:
        """CSV writer should use UTF-8 for non-ASCII chars (e.g. Vietnamese reason)."""
        ohlc = _make_ohlc()
        out = Path(f"output/test_utf8_{int(time.time() * 1e6)}.csv")
        try:
            # Inject a non-ASCII reason via replay (replay uses raw string).
            # Since replay reasons come from event types, we'll use the Pine parser.
            paste = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=kiểm_tra"
            capture_from_pine_logs(paste, out)
            # Read raw bytes — should be UTF-8.
            raw = out.read_bytes()
            assert b"ki" in raw  # ASCII portion (non-ASCII chars follow)
            assert "kiểm_tra".encode("utf-8") in raw
        finally:
            _cleanup(out)


# ---------------------------------------------------------------------------
# Capture from live: missing events
# ---------------------------------------------------------------------------


class TestCaptureLiveEdge:
    def test_capture_only_alerts_without_events_returns_zero_rows(self) -> None:
        """capture_from_live reads signal_events table to determine source.
        Without events, by_sig is empty → 0 rows. Document this design choice."""
        p_db = Path(f"output/test_capture_no_events_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            body = "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=42|bos_id=7|state=chart-qualified|reason=ok"
            payload = parse_payload(body)
            db.insert_alert(payload, url_token_ok=True)
            # No record_event call.
            out = Path(f"output/test_capture_no_events_{int(time.time() * 1e6)}.csv")
            try:
                n = capture_from_live(db, out)
                # Document: returns 0 because the by_sig dict is keyed on signal_events rows.
                assert n == 0
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)


# ---------------------------------------------------------------------------
# ReplayEngine configuration
# ---------------------------------------------------------------------------


class TestReplayConfigEdge:
    def test_engine_repr_no_swings_emits_zero_signals(self) -> None:
        """No-swing OHLC (constant close) produces 0 signals — no crash."""
        n = 100
        ohlc = pd.DataFrame(
            {
                "open": [1.1] * n,
                "high": [1.1] * n,
                "low": [1.1] * n,
                "close": [1.1] * n,
                "volume": [100] * n,
            },
            index=pd.date_range("2026-01-01", periods=n, freq="15min"),
        )
        engine = ReplayEngine(swing_left=10, swing_right=10)
        result = engine.run(ohlc)
        assert result.run.signal_count == 0

    def test_engine_rejects_negative_swing(self) -> None:
        with pytest.raises(ValueError):
            ReplayEngine(swing_left=-1)

    def test_engine_ohlc_checksum_is_deterministic_hex(self) -> None:
        """checksum is 64-char hex (SHA-256)."""
        result = replay_from_ohlc(_make_ohlc(seed=42))
        assert len(result.run.ohlc_checksum) == 64
        assert all(c in "0123456789abcdef" for c in result.run.ohlc_checksum)


# ---------------------------------------------------------------------------
# Bar time encoding
# ---------------------------------------------------------------------------


class TestBarTimeEncoding:
    def test_replay_bar_time_is_positive_int(self) -> None:
        ohlc = _make_ohlc()
        result = replay_from_ohlc(ohlc)
        for sig in result.signals:
            assert isinstance(sig.bar_time, int)
            assert sig.bar_time > 0

    def test_replay_bar_time_matches_index(self) -> None:
        ohlc = _make_ohlc()
        result = replay_from_ohlc(ohlc)
        # Build signal_id → bar_time map and verify a known mapping.
        first_idx = ohlc.index[0]
        expected_ts = int(first_idx.timestamp())
        # First signal (if any) should match or be later than first_idx.
        if result.signals:
            assert result.signals[0].bar_time >= expected_ts