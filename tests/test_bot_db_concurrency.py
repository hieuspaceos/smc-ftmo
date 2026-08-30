"""Edge-case + concurrency tests for bot storage and rate limiter.

Run separately from main suite: ``pytest tests/test_bot_db_concurrency.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path
import time

import pytest

from bot.storage.db import BotDB, init_db
from bot.webhook.payload import AlertPayload, parse_payload
from bot.webhook.server import _RateLimiter


VALID = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


def _make_db() -> tuple[BotDB, Path]:
    p = Path(f"output/test_conc_{int(time.time() * 1000000)}.db")
    init_db(p)
    return BotDB(p), p


def _cleanup(p: Path) -> None:
    try:
        p.unlink()
    except FileNotFoundError:
        pass


class TestInsertAlertConcurrency:
    def test_concurrent_inserts_same_signal_id(self) -> None:
        """20 threads racing to insert the same signal_id must produce exactly 1 row,
        dedupe_count == 20, no exceptions."""
        db, path = _make_db()
        try:
            payload = parse_payload(VALID)
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    db.insert_alert(payload, client_ip="52.89.214.238", url_token_ok=True)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"unexpected exceptions: {errors!r}"
            assert db.count_alerts() == 1, "must have exactly one row for same signal_id"
            stored = db.get_alert_by_signal_id(payload.signal_id)
            assert stored is not None
            assert stored["dedupe_count"] == 20
        finally:
            _cleanup(path)

    def test_concurrent_inserts_distinct_signal_ids(self) -> None:
        """20 threads inserting different signal_ids must produce 20 distinct rows."""
        db, path = _make_db()
        try:
            errors: list[BaseException] = []

            def worker(i: int) -> None:
                try:
                    body = (
                        "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
                        f"|level=1.10000|bar_time={1700000000 + i}"
                        "|state=chart-qualified|reason=ok"
                    )
                    db.insert_alert(parse_payload(body))
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert errors == [], f"unexpected exceptions: {errors!r}"
            assert db.count_alerts() == 20
        finally:
            _cleanup(path)

    def test_dedupe_count_increments_across_sequential_dups(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID)
            for expected in (1, 2, 3, 4, 5):
                _id, is_new = db.insert_alert(payload)
                if expected == 1:
                    assert is_new is True
                else:
                    assert is_new is False
                stored = db.get_alert_by_signal_id(payload.signal_id)
                assert stored["dedupe_count"] == expected
        finally:
            _cleanup(path)


class TestRateLimiterThreadSafety:
    def test_concurrent_hits_under_limit_all_allowed(self) -> None:
        rl = _RateLimiter(per_minute=1000)
        allowed = []
        lock = threading.Lock()

        def hit() -> None:
            ok = rl.hit("test-key")
            with lock:
                allowed.append(ok)

        threads = [threading.Thread(target=hit) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(allowed) == 50

    def test_concurrent_hits_at_limit_respects_cap(self) -> None:
        rl = _RateLimiter(per_minute=10)
        allowed = []
        lock = threading.Lock()

        def hit() -> None:
            ok = rl.hit("test-key")
            with lock:
                allowed.append(ok)

        threads = [threading.Thread(target=hit) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(allowed) == 10

    def test_distinct_keys_have_independent_buckets(self) -> None:
        rl = _RateLimiter(per_minute=2)
        assert rl.hit("a") is True
        assert rl.hit("a") is True
        assert rl.hit("a") is False
        # Different key still has fresh quota.
        assert rl.hit("b") is True
        assert rl.hit("b") is True
        assert rl.hit("b") is False


class TestEdgeCases:
    def test_empty_client_ip_persisted_as_none(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID)
            alert_id, is_new = db.insert_alert(payload, client_ip=None)
            assert is_new is True
            stored = db.get_alert(alert_id)
            assert stored["client_ip"] is None
        finally:
            _cleanup(path)

    def test_url_token_ok_false_persisted_as_0(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID)
            alert_id, is_new = db.insert_alert(payload, url_token_ok=False)
            stored = db.get_alert(alert_id)
            assert stored["url_token_ok"] == 0
        finally:
            _cleanup(path)

class TestLogThrottling:
    def test_throttled_logger_emits_first_then_suppresses(self) -> None:
        from bot.webhook.server import _ThrottledLogger
        import logging as _logging

        # Capture log records.
        records: list[_logging.LogRecord] = []
        handler = _logging.Handler()
        handler.emit = records.append  # type: ignore[method-assign]
        logger_under_test = _logging.getLogger("bot.webhook")
        logger_under_test.addHandler(handler)
        prev_level = logger_under_test.level
        logger_under_test.setLevel(_logging.DEBUG)
        try:
            tl = _ThrottledLogger(window_seconds=60.0)
            tl.log(_logging.WARNING, "k", "msg %s", "a")
            tl.log(_logging.WARNING, "k", "msg %s", "b")
            tl.log(_logging.WARNING, "k2", "msg %s", "c")  # different key — emit
        finally:
            logger_under_test.removeHandler(handler)
            logger_under_test.setLevel(prev_level)
        assert len(records) == 2  # first "k" + "k2", second "k" suppressed
        assert records[0].getMessage() == "msg a"
        assert records[1].getMessage() == "msg c"


class TestAppSettingsValidation:
    def test_short_secret_rejected(self) -> None:
        import os
        os.environ["SMC_WEBHOOK_TOKEN"] = "short"
        os.environ["SMC_TRUSTED_PROXY"] = "0"
        from bot.webhook.server import AppSettings
        with pytest.raises(RuntimeError, match="too short"):
            AppSettings.from_env()

    def test_empty_secret_rejected(self) -> None:
        import os
        os.environ["SMC_WEBHOOK_TOKEN"] = ""
        from bot.webhook.server import AppSettings
        with pytest.raises(RuntimeError, match="required"):
            AppSettings.from_env()


    def test_raw_payload_preserved_verbatim(self) -> None:
        db, path = _make_db()
        try:
            payload = parse_payload(VALID)
            _id, _ = db.insert_alert(payload)
            stored = db.get_alert_by_signal_id(payload.signal_id)
            assert stored["raw_payload"] == VALID
        finally:
            _cleanup(path)

    def test_init_db_idempotent(self) -> None:
        path = Path(f"output/test_init_{int(time.time() * 1000000)}.db")
        try:
            init_db(path)
            init_db(path)  # second call must not error
            # Schema still valid
            db = BotDB(path)
            assert db.count_alerts() == 0
        finally:
            _cleanup(path)


class TestPayloadIdempotencyEdgeCases:
    def test_level_precision_difference_same_signal_id(self) -> None:
        """Different floating-point representations of same price must hash to same signal_id."""
        from bot.webhook.payload import compute_signal_id

        sig1 = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        sig2 = compute_signal_id("bos", "EURUSD", "M15", "long", 1.10000000, 1700000000, -1, -1)
        assert sig1 == sig2

    def test_signal_id_distinguishes_zero_vs_negative_one(self) -> None:
        """ob_id=0 (valid) vs ob_id=-1 (N/A) must produce different signal_ids."""
        from bot.webhook.payload import compute_signal_id

        sig_zero = compute_signal_id("ob_activated", "EURUSD", "M15", "long", 1.1, 1700000000, 0, -1)
        sig_neg = compute_signal_id("ob_activated", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        assert sig_zero != sig_neg

    def test_signal_id_changes_with_dir_normalization(self) -> None:
        """Bullish vs bearish (which normalize to long/short) — verify after normalization they differ."""
        from bot.webhook.payload import compute_signal_id

        sig_long = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        sig_short = compute_signal_id("bos", "EURUSD", "M15", "short", 1.1, 1700000000, -1, -1)
        assert sig_long != sig_short