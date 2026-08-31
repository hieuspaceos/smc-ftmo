"""Tests for Phase 05 — Payload hardening.

Closes audit finding H4 (signal_id float precision), H6 (received_at
overwritten on reconstruct), M2 (parse_ack accepts empty id), M3
(frozen payload), M4 (record_event truncation log).
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from smc_bot_core.db import BotDB, init_db
from smc_bot_webhook.notify.telegram import TelegramDispatcher
from smc_bot_webhook.payload import (
    AlertPayload,
    compute_signal_id,
    parse_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_db() -> tuple[Path, Path]:
    """Return (tmp_dir, db_path). Caller is responsible for cleanup."""
    td = Path(tempfile.mkdtemp(prefix="test_p5_"))
    return td, td / "bot.db"


def _cleanup(td: Path) -> None:
    shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# H4: signal_id precision (level rounding)
# ---------------------------------------------------------------------------


class TestSignalIdPrecision:
    def test_same_level_within_tick_produces_same_id(self) -> None:
        """Two Pine runs emitting 1.10000 and 1.10000001 for the same
        OB must produce the same signal_id (after round to 5 digits)."""
        sid1 = compute_signal_id(
            "chart_qualified", "EURUSD", "15", "long",
            1.10000, 1700000000, 42, 7,
        )
        sid2 = compute_signal_id(
            "chart_qualified", "EURUSD", "15", "long",
            1.10000001, 1700000000, 42, 7,
        )
        assert sid1 == sid2

    def test_levels_differing_by_one_tick_produce_different_ids(self) -> None:
        sid1 = compute_signal_id(
            "chart_qualified", "EURUSD", "15", "long",
            1.10000, 1700000000, 42, 7,
        )
        sid2 = compute_signal_id(
            "chart_qualified", "EURUSD", "15", "long",
            1.10001, 1700000000, 42, 7,
        )
        assert sid1 != sid2

    def test_signal_id_is_16_hex_chars(self) -> None:
        sid = compute_signal_id(
            "chart_qualified", "EURUSD", "15", "long",
            1.1, 1700000000, 42, 7,
        )
        assert len(sid) == 16
        assert all(c in "0123456789abcdef" for c in sid)


# ---------------------------------------------------------------------------
# M3: AlertPayload is frozen
# ---------------------------------------------------------------------------


class TestAlertPayloadFrozen:
    def test_payload_is_frozen_after_parse(self) -> None:
        p = parse_payload(
            "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
            "|state=chart-qualified|reason=ok"
        )
        with pytest.raises((AttributeError, TypeError, ValueError)):
            p.level = 1.2  # type: ignore[misc]

    def test_model_construct_auto_fills_signal_id_when_empty(self) -> None:
        """Re-hydrating from the DB may omit signal_id; the override
        re-computes the canonical hash so audit lookup still works."""
        p = AlertPayload.model_construct(
            prefix="SMC",
            version="v1",
            event="chart_qualified",
            symbol="EURUSD",
            tf="15",
            dir="long",
            level=1.10000,
            bar_time=1700000000,
            ob_id=42,
            bos_id=7,
            state="chart-qualified",
            reason="ok",
            signal_id="",  # empty → auto-fill
        )
        assert p.signal_id != ""
        assert len(p.signal_id) == 16


# ---------------------------------------------------------------------------
# M2: parse_ack_callback length check
# ---------------------------------------------------------------------------


class TestParseAckCallbackLength:
    def test_rejects_empty_signal_id(self) -> None:
        result = TelegramDispatcher.parse_ack_callback("ack:risk_ok:")
        assert result is None

    def test_rejects_short_signal_id(self) -> None:
        result = TelegramDispatcher.parse_ack_callback("ack:risk_ok:abc")
        assert result is None

    def test_rejects_long_signal_id(self) -> None:
        result = TelegramDispatcher.parse_ack_callback(
            "ack:risk_ok:0123456789abcdef00"
        )
        assert result is None

    def test_accepts_exactly_16_hex_chars(self) -> None:
        result = TelegramDispatcher.parse_ack_callback(
            "ack:risk_ok:0123456789abcdef"
        )
        assert result == ("risk_ok", "0123456789abcdef")

    def test_rejects_non_hex_chars(self) -> None:
        # Length is 16 but contains a non-hex char ('z').
        result = TelegramDispatcher.parse_ack_callback(
            "ack:risk_ok:0123456789abcdez"
        )
        assert result is None


# ---------------------------------------------------------------------------
# H6: received_at preserved on reconstruct
# ---------------------------------------------------------------------------


class TestReceivedAtPreserved:
    def test_parse_payload_records_received_at(self) -> None:
        p = parse_payload(
            "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
            "|state=chart-qualified|reason=ok"
        )
        assert p.received_at is not None

    def test_received_at_preserved_in_model_construct(self) -> None:
        original_ts = "2026-08-31T10:30:00+00:00"
        p = AlertPayload.model_construct(
            prefix="SMC",
            version="v1",
            event="chart_qualified",
            symbol="EURUSD",
            tf="15",
            dir="long",
            level=1.10000,
            bar_time=1700000000,
            ob_id=42,
            bos_id=7,
            state="chart-qualified",
            reason="ok",
            received_at=datetime.fromisoformat(original_ts),
        )
        assert p.received_at.isoformat() == original_ts


# ---------------------------------------------------------------------------
# M4: record_event truncation log
# ---------------------------------------------------------------------------


class TestRecordEventTruncationLog:
    def test_truncation_logged_with_size_and_cap(self, caplog) -> None:
        """When the payload exceeds the cap, the warning should
        include the original size, the cap, and the signal_id."""
        td, db_path = _tmp_db()
        try:
            init_db(db_path)
            db = BotDB(db_path)
            huge = "X" * (40 * 1024)  # 40 KB > 32 KB cap
            with caplog.at_level(logging.WARNING, logger="bot.storage"):
                db.record_event(
                    "test_sig_123", "received",
                    payload=huge, actor="webhook:test",
                )
            matching = [
                r for r in caplog.records
                if "truncating oversized signal_events payload" in r.message
            ]
            assert len(matching) == 1
            msg = matching[0].message
            assert "test_sig_123" in msg
            assert "size=40960" in msg
            assert "cap=32768" in msg
        finally:
            _cleanup(td)

    def test_payload_below_cap_unchanged(self) -> None:
        td, db_path = _tmp_db()
        try:
            init_db(db_path)
            db = BotDB(db_path)
            small = "Y" * 100
            eid = db.record_event(
                "small_sig", "received",
                payload=small, actor="webhook:test",
            )
            assert eid > 0
        finally:
            _cleanup(td)
