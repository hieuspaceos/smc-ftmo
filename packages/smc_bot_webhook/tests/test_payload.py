"""Unit tests for SMC|v1 payload parser (Phase 01 acceptance)."""

from __future__ import annotations

import pytest

from smc_bot_webhook.payload import (
    AlertPayload,
    PayloadParseError,
    compute_signal_id,
    normalize_dir,
    normalize_state,
    normalize_symbol,
    normalize_tf,
    parse_payload,
)


VALID_PIPE = (
    "SMC|v1|event=chart_qualified|symbol=EURUSD|tf=15|dir=long"
    "|level=1.10000|bar_time=1700000000|ob_id=42|bos_id=7"
    "|state=chart-qualified|reason=ok"
)


class TestNormalizers:
    def test_normalize_symbol_strips_broker_prefix(self) -> None:
        assert normalize_symbol("OANDA:EURUSD") == "EURUSD"
        assert normalize_symbol("eurusd") == "EURUSD"
        assert normalize_symbol("FX:EURUSD") == "EURUSD"

    def test_normalize_tf_pine_period(self) -> None:
        assert normalize_tf("15") == "M15"
        assert normalize_tf("60") == "H1"
        assert normalize_tf("240") == "H4"
        assert normalize_tf("D") == "D"

    def test_normalize_tf_already_canonical(self) -> None:
        assert normalize_tf("M15") == "M15"
        assert normalize_tf("H1") == "H1"

    def test_normalize_dir(self) -> None:
        assert normalize_dir("long") == "long"
        assert normalize_dir("bullish") == "long"
        assert normalize_dir("short") == "short"
        assert normalize_dir("bearish") == "short"
        assert normalize_dir("none") == "none"
        assert normalize_dir("garbage") == "none"

    def test_normalize_state(self) -> None:
        assert normalize_state("chart-qualified") == "chart-qualified"
        assert normalize_state("CHART-QUALIFIED") == "chart-qualified"


class TestComputeSignalId:
    def test_deterministic(self) -> None:
        a = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        b = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        assert a == b
        assert len(a) == 16

    def test_changes_with_event(self) -> None:
        a = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        b = compute_signal_id("choch", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        assert a != b

    def test_changes_with_bar_time(self) -> None:
        a = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        b = compute_signal_id("bos", "EURUSD", "M15", "long", 1.1, 1700000001, -1, -1)
        assert a != b

    def test_changes_with_ob_id(self) -> None:
        a = compute_signal_id("ob_activated", "EURUSD", "M15", "long", 1.1, 1700000000, -1, -1)
        b = compute_signal_id("ob_activated", "EURUSD", "M15", "long", 1.1, 1700000000, 42, -1)
        assert a != b


class TestParsePayload:
    def test_pipe_round_trip(self) -> None:
        p = parse_payload(VALID_PIPE)
        assert isinstance(p, AlertPayload)
        assert p.prefix == "SMC"
        assert p.version == "v1"
        assert p.event == "chart_qualified"
        assert p.symbol == "EURUSD"
        assert p.tf == "M15"
        assert p.dir == "long"
        assert p.level == pytest.approx(1.1)
        assert p.bar_time == 1700000000
        assert p.ob_id == 42
        assert p.bos_id == 7
        assert p.state == "chart-qualified"
        assert p.reason == "ok"
        assert len(p.signal_id) == 16
        assert p.raw_payload == VALID_PIPE

    def test_pine_tf_normalized_to_canonical(self) -> None:
        # Pine timeframe.period = "15" must become canonical "M15".
        p = parse_payload(VALID_PIPE)
        assert p.tf == "M15"

    def test_ob_id_default_minus_one(self) -> None:
        body = (
            "SMC|v1|event=sweep|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=watch|reason=sweep"
        )
        p = parse_payload(body)
        assert p.ob_id == -1
        assert p.bos_id == -1

    def test_bullish_dir_normalized_to_long(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=bullish"
            "|level=1.10000|bar_time=1700000000"
            "|state=chart-qualified|reason=ok"
        )
        p = parse_payload(body)
        assert p.dir == "long"

    def test_bearish_dir_normalized_to_short(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=bearish"
            "|level=1.10000|bar_time=1700000000"
            "|state=chart-qualified|reason=ok"
        )
        p = parse_payload(body)
        assert p.dir == "short"

    def test_symbol_broker_prefix_stripped(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=OANDA:EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=chart-qualified|reason=ok"
        )
        p = parse_payload(body)
        assert p.symbol == "EURUSD"

    def test_state_phase01_accepts_watch_and_blocked(self) -> None:
        # Plan phase-01 §P0 nhận cả 3 states.
        for state in ("chart-qualified", "watch", "blocked", "no-signal"):
            body = (
                f"SMC|v1|event=watch|symbol=EURUSD|tf=15|dir=long"
                f"|level=1.10000|bar_time=1700000000"
                f"|state={state}|reason=ok"
            )
            p = parse_payload(body)
            assert p.state == state

    def test_json_content_type(self) -> None:
        obj = {
            "prefix": "SMC",
            "version": "v1",
            "event": "bos",
            "symbol": "EURUSD",
            "tf": "15",
            "dir": "long",
            "level": 1.1,
            "bar_time": 1700000000,
            "ob_id": -1,
            "bos_id": -1,
            "state": "chart-qualified",
            "reason": "ok",
        }
        p = parse_payload(str(obj).replace("'", '"'), content_type="application/json")
        assert p.event == "bos"
        assert p.tf == "M15"

    def test_idempotency_signal_id_stable_across_parses(self) -> None:
        p1 = parse_payload(VALID_PIPE)
        p2 = parse_payload(VALID_PIPE)
        assert p1.signal_id == p2.signal_id

    # ---- reject paths ----

    def test_rejects_wrong_prefix(self) -> None:
        body = "WRONG|v1|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|state=watch|reason=ok"
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_wrong_version(self) -> None:
        body = "SMC|v2|event=bos|symbol=EURUSD|tf=15|dir=long|level=1.1|bar_time=1700000000|state=watch|reason=ok"
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_unknown_symbol(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=GBPUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=chart-qualified|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_unknown_state(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=invalid|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_unknown_event(self) -> None:
        body = (
            "SMC|v1|event=unknown_event|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=watch|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_unknown_tf(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=M5|dir=long"
            "|level=1.10000|bar_time=1700000000"
            "|state=watch|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_zero_bar_time(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=0"
            "|state=watch|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)

    def test_rejects_empty_body(self) -> None:
        with pytest.raises(PayloadParseError):
            parse_payload("")

    def test_rejects_missing_required_fields(self) -> None:
        with pytest.raises(PayloadParseError):
            parse_payload("SMC|v1|event=bos")  # missing symbol/tf/dir/level/bar_time/state

    def test_rejects_ob_id_less_than_minus_one(self) -> None:
        body = (
            "SMC|v1|event=bos|symbol=EURUSD|tf=15|dir=long"
            "|level=1.10000|bar_time=1700000000|ob_id=-5"
            "|state=watch|reason=ok"
        )
        with pytest.raises(PayloadParseError):
            parse_payload(body)