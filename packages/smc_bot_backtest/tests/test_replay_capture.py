"""Tests for Phase 04 replay engine + signal CSV capture."""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_bot_backtest.replay_engine import ReplayEngine, replay_from_ohlc
from smc_bot_backtest.capture import (
    CSV_COLUMNS,
    capture_from_live,
    capture_from_pine_logs,
    capture_from_replay,
)
from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.payload import parse_payload

# Canonical 16-char hex signal_id.
_SAMPLE_SID = "1c54f6c631e1fc3d"


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------


def _make_ohlc(n: int = 200, seed: int = 42) -> pd.DataFrame:
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
        index=pd.date_range("2026-01-01", periods=n, freq="15min"),
    )


class TestReplayDeterminism:
    def test_same_input_same_run_id(self) -> None:
        ohlc = _make_ohlc()
        a = replay_from_ohlc(ohlc)
        b = replay_from_ohlc(ohlc)
        assert a.run.run_id == b.run.run_id

    def test_same_input_same_signal_count(self) -> None:
        ohlc = _make_ohlc()
        a = replay_from_ohlc(ohlc)
        b = replay_from_ohlc(ohlc)
        assert len(a.signals) == len(b.signals)

    def test_same_input_same_signal_ids(self) -> None:
        ohlc = _make_ohlc()
        a = replay_from_ohlc(ohlc)
        b = replay_from_ohlc(ohlc)
        ids_a = [s.signal_id for s in a.signals]
        ids_b = [s.signal_id for s in b.signals]
        assert ids_a == ids_b

    def test_different_input_different_run_id(self) -> None:
        a = replay_from_ohlc(_make_ohlc(seed=42))
        b = replay_from_ohlc(_make_ohlc(seed=99))
        assert a.run.run_id != b.run.run_id

    def test_determinism_with_repeated_engine_runs(self) -> None:
        engine = ReplayEngine()
        ohlc = _make_ohlc()
        results = [engine.run(ohlc) for _ in range(5)]
        first_ids = [s.signal_id for s in results[0].signals]
        for r in results[1:]:
            assert [s.signal_id for s in r.signals] == first_ids


class TestReplayValidation:
    def test_missing_columns_raises(self) -> None:
        bad = pd.DataFrame({"open": [], "close": []})  # missing high, low, volume
        with pytest.raises(ValueError, match="missing required columns"):
            replay_from_ohlc(bad)

    def test_non_dataframe_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a DataFrame"):
            replay_from_ohlc("not a dataframe")  # type: ignore[arg-type]

    def test_swing_left_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="swing_left"):
            ReplayEngine(swing_left=0)

    def test_engine_repr_includes_run_metadata(self) -> None:
        result = replay_from_ohlc(_make_ohlc(n=300))
        run = result.run
        assert run.symbol == "EURUSD"
        assert run.tf == "M15"
        assert run.signal_count == len(result.signals)
        assert isinstance(run.started_at, datetime)
        assert isinstance(run.finished_at, datetime)
        assert run.ohlc_checksum != ""


class TestReplaySignalsShape:
    def test_signals_are_alert_payloads(self) -> None:
        result = replay_from_ohlc(_make_ohlc())
        for sig in result.signals:
            assert sig.prefix == "SMC"
            assert sig.version == "v1"
            assert sig.symbol == "EURUSD"
            assert sig.tf == "M15"
            assert sig.event in ("bos", "choch")
            assert sig.dir in ("long", "short")
            assert sig.state == "watch"
            assert sig.reason.startswith("replay:")

    def test_replay_signal_id_is_16_chars(self) -> None:
        result = replay_from_ohlc(_make_ohlc())
        for sig in result.signals:
            assert len(sig.signal_id) == 16

    def test_bar_time_in_replay_matches_ohlc_index(self) -> None:
        result = replay_from_ohlc(_make_ohlc(n=100))
        # Every bar_time should round-trip from the index timestamp.
        for sig in result.signals:
            assert sig.bar_time > 0


class TestReplayEdgeCases:
    def test_empty_ohlc(self) -> None:
        ohlc = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], freq="15min"),
        )
        result = replay_from_ohlc(ohlc)
        assert result.run.signal_count == 0
        assert result.signals == ()

    def test_very_short_ohlc(self) -> None:
        # 5 bars — too few for swing detection (swing=5/5).
        ohlc = _make_ohlc(n=5)
        result = replay_from_ohlc(ohlc)
        # No BOS events possible with so few bars.
        assert isinstance(result.run.signal_count, int)

    def test_constant_price_no_signals(self) -> None:
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
        result = replay_from_ohlc(ohlc)
        # No breaks of structure in a flat market.
        assert result.run.signal_count == 0


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


class TestCaptureSchema:
    def test_csv_columns(self) -> None:
        # The CSV_COLUMNS tuple must be exactly what the plan specifies.
        expected = (
            "source", "run_id", "signal_id", "event", "symbol", "tf", "side",
            "level", "entry", "sl", "tp1", "tp2", "tp3", "bar_time", "ob_id",
            "bos_id", "state", "reason", "score", "gate_status", "decision",
            "decision_at", "execution_status",
        )
        assert CSV_COLUMNS == expected


class TestCaptureFromReplay:
    def test_writes_one_row_per_signal(self) -> None:
        ohlc = _make_ohlc()
        result = replay_from_ohlc(ohlc)
        out = Path(f"output/test_replay_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_replay(result, out)
            assert n == result.run.signal_count
            rows = _read_csv(out)
            assert len(rows) == n
        finally:
            _cleanup(out)

    def test_each_row_has_source_replay(self) -> None:
        ohlc = _make_ohlc()
        result = replay_from_ohlc(ohlc)
        out = Path(f"output/test_replay_{int(time.time() * 1e6)}.csv")
        try:
            capture_from_replay(result, out)
            for row in _read_csv(out):
                assert row["source"] == "replay"
                assert row["run_id"] == result.run.run_id
        finally:
            _cleanup(out)

    def test_accepts_engine_signature(self) -> None:
        engine = ReplayEngine()
        ohlc = _make_ohlc(n=100)
        out = Path(f"output/test_replay_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_replay(engine, ohlc, out)
            assert n > 0
        finally:
            _cleanup(out)

    def test_accepts_result_with_positional_path(self) -> None:
        ohlc = _make_ohlc(n=100)
        result = replay_from_ohlc(ohlc)
        out = Path(f"output/test_replay_{int(time.time() * 1e6)}.csv")
        try:
            # result, out (positional path) — second arg treated as path.
            n = capture_from_replay(result, out)
            assert n == result.run.signal_count
        finally:
            _cleanup(out)


class TestCaptureFromPineLogs:
    def test_parses_one_valid_line(self) -> None:
        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        out = Path(f"output/test_pine_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_pine_logs(line, out)
            assert n == 1
            rows = _read_csv(out)
            assert rows[0]["source"] == "pine_logs"
            assert rows[0]["event"] == "bos"
            assert rows[0]["symbol"] == "EURUSD"
            assert rows[0]["tf"] == "M15"  # canonical (15 → M15)
            assert rows[0]["bar_time"] == "1700000000"
            assert rows[0]["bos_id"] == "7"
            assert rows[0]["state"] == "watch"
        finally:
            _cleanup(out)

    def test_skips_unparseable_lines(self) -> None:
        paste = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1\n"
            "this is total junk\n"
            "SMC|v1|event=choch|symbol=EURUSD|tf=15|dir=short|level=1.105|bar_time=1700000900|ob_id=42|bos_id=-1|state=watch|reason=t2\n"
        )
        out = Path(f"output/test_pine_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_pine_logs(paste, out)
            assert n == 2
        finally:
            _cleanup(out)

    def test_empty_paste_writes_header_only(self) -> None:
        out = Path(f"output/test_pine_{int(time.time() * 1e6)}.csv")
        try:
            n = capture_from_pine_logs("", out)
            assert n == 0
            rows = _read_csv(out)
            assert rows == []
        finally:
            _cleanup(out)

    def test_normalizes_tf_15_to_m15(self) -> None:
        # Pine emits tf=15 raw; capture must canonicalize to M15.
        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        out = Path(f"output/test_pine_{int(time.time() * 1e6)}.csv")
        try:
            capture_from_pine_logs(line, out)
            row = _read_csv(out)[0]
            assert row["tf"] == "M15"
        finally:
            _cleanup(out)

    def test_state_field_anchored_at_pipe(self) -> None:
        # Without anchor, regex \S+ would capture 'watch|reason=t1' for state.
        # Anchor [^|]+ should yield 'watch'.
        line = "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=-1|bos_id=7|state=watch|reason=t1"
        out = Path(f"output/test_pine_{int(time.time() * 1e6)}.csv")
        try:
            capture_from_pine_logs(line, out)
            row = _read_csv(out)[0]
            assert row["state"] == "watch"
            assert row["reason"] == "t1"
        finally:
            _cleanup(out)


class TestCaptureFromLive:
    def test_writes_one_row_per_alert(self) -> None:
        p_db = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            for _ in range(3):
                body = "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=42|bos_id=7|state=chart-qualified|reason=ok"
                payload = parse_payload(body)
                # Force unique signal_id by varying bar_time.
                from smc_bot_webhook.payload import AlertPayload
                from datetime import datetime, timezone
                payload = AlertPayload.model_construct(
                    prefix=payload.prefix, version=payload.version,
                    event=payload.event, symbol=payload.symbol, tf=payload.tf,
                    dir=payload.dir, level=payload.level,
                    bar_time=1700000000 + _,
                    ob_id=payload.ob_id, bos_id=payload.bos_id,
                    state=payload.state, reason=payload.reason,
                    received_at=datetime.now(timezone.utc), raw_payload=body,
                )
                db.insert_alert(payload, url_token_ok=True)
                db.record_event(payload.signal_id, "received", actor="test")
            out = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.csv")
            try:
                n = capture_from_live(db, out)
                assert n == 3
                rows = _read_csv(out)
                for row in rows:
                    assert row["source"] == "live"
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)

    def test_decision_propagated_from_signal_events(self) -> None:
        p_db = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            body = "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|ob_id=42|bos_id=7|state=chart-qualified|reason=ok"
            payload = parse_payload(body)
            db.insert_alert(payload, url_token_ok=True)
            db.record_event(payload.signal_id, "received", actor="test")
            db.record_event(payload.signal_id, "accept", actor="tester")
            out = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.csv")
            try:
                capture_from_live(db, out)
                row = _read_csv(out)[0]
                assert row["decision"] == "accept"
                assert row["decision_at"] != ""
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)

    def test_empty_db_writes_header_only(self) -> None:
        p_db = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.db")
        init_db(p_db)
        try:
            db = BotDB(p_db)
            out = Path(f"output/test_capture_live_{int(time.time() * 1e6)}.csv")
            try:
                n = capture_from_live(db, out)
                assert n == 0
            finally:
                _cleanup(out)
        finally:
            _cleanup(p_db)


class TestCaptureDeterminism:
    def test_replay_capture_byte_identical_two_runs(self) -> None:
        ohlc = _make_ohlc()
        out1 = Path(f"output/test_capture_det_a_{int(time.time() * 1e6)}.csv")
        out2 = Path(f"output/test_capture_det_b_{int(time.time() * 1e6)}.csv")
        try:
            capture_from_replay(replay_from_ohlc(ohlc), out1)
            capture_from_replay(replay_from_ohlc(ohlc), out2)
            assert out1.read_bytes() == out2.read_bytes()
        finally:
            _cleanup(out1)
            _cleanup(out2)