"""Tests for Phase 06 — Outbox validation, rate-limit LRU, and admin_override.

Closes audit finding H1 (outbox path unsafe), H3 (rate limiter leak),
L5 (/healthz private attr), L6 (outbox cap missing).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from smc_bot_webhook.gates.validator import Validator
from smc_bot_webhook.mt5_bridge.executor import _validate_outbox_dir
from smc_bot_webhook.mt5_bridge.signal_writer import (
    OutboxWriter,
    SignalRecord,
    SignalAlreadyWrittenError,
)
from smc_bot_webhook.server import _RateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="test_p6_"))


def _cleanup(p: Path) -> None:
    shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------------
# H1: outbox validation
# ---------------------------------------------------------------------------


class TestValidateOutboxDir:
    def test_accepts_valid_directory(self, tmp_path: Path) -> None:
        result = _validate_outbox_dir(tmp_path)
        assert result == tmp_path.resolve()

    def test_creates_missing_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "new_outbox"
        result = _validate_outbox_dir(target)
        assert result == target.resolve()
        assert target.is_dir()

    def test_rejects_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            _validate_outbox_dir(f)


# ---------------------------------------------------------------------------
# L6: outbox max_pending cap
# ---------------------------------------------------------------------------


class TestOutboxMaxPending:
    def _seed(self, td: Path, count: int) -> None:
        outbox = OutboxWriter(td, max_pending=count + 5)
        for i in range(count):
            rec = SignalRecord(
                signal_id=f"sig{i:04d}",
                symbol="EURUSD",
                side="long",
                entry=1.10000,
                sl=1.09950,
                tp=(1.10100, 1.10200, 1.10300),
                risk_pct=0.0055,
                bar_time="2026-08-31T10:00:00Z",
                expires_at="2026-08-31T10:05:00Z",
                ob_id=1,
                bos_id=1,
                approved_by="tester",
            )
            outbox.write_atomic(f"sig{i:04d}", rec)

    def test_cap_blocks_at_max(self, tmp_path: Path) -> None:
        td = _tmp_dir()
        try:
            outbox = OutboxWriter(td / "out", max_pending=2)
            self._seed(td / "out", 2)
            rec = SignalRecord(
                signal_id="sig_new",
                symbol="EURUSD",
                side="long",
                entry=1.1,
                sl=1.0995,
                tp=(1.101,),
                risk_pct=0.0055,
                bar_time="2026-08-31T10:00:00Z",
                expires_at="2026-08-31T10:05:00Z",
                ob_id=1,
                bos_id=1,
                approved_by="tester",
            )
            with pytest.raises(SignalAlreadyWrittenError, match="at capacity"):
                outbox.write_atomic("sig_new", rec)
        finally:
            _cleanup(td)

    def test_invalid_max_pending_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_pending must be > 0"):
            OutboxWriter(tmp_path, max_pending=0)


# ---------------------------------------------------------------------------
# H3: _RateLimiter LRU eviction
# ---------------------------------------------------------------------------


class TestRateLimiterLRU:
    def test_evicts_oldest_key_when_over_max(self) -> None:
        rl = _RateLimiter(per_minute=60, max_buckets=2)
        assert rl.hit("a") is True
        assert rl.hit("b") is True
        # Third unique key should evict the oldest ('a') to make room.
        assert rl.hit("c") is True
        # Now bucket 'a' is gone — should be allowed again (fresh slot).
        assert rl.hit("a") is True
        assert len(rl._buckets) == 2

    def test_invalid_max_buckets_raises(self) -> None:
        with pytest.raises(ValueError, match="max_buckets must be > 0"):
            _RateLimiter(per_minute=10, max_buckets=0)

    def test_default_max_buckets_is_10000(self) -> None:
        rl = _RateLimiter(per_minute=10)
        assert rl._max_buckets == 10000


# ---------------------------------------------------------------------------
# L5: validator.admin_override public property
# ---------------------------------------------------------------------------


class TestValidatorAdminOverride:
    def test_admin_override_default_false(self) -> None:
        v = Validator.__new__(Validator)  # bypass __init__ for unit test
        v._admin_override = False
        assert v.admin_override is False

    def test_admin_override_true(self) -> None:
        v = Validator.__new__(Validator)
        v._admin_override = True
        assert v.admin_override is True
