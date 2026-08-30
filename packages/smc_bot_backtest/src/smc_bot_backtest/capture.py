"""Signal CSV capture from 3 sources.

Writes a unified CSV with columns (plan §Signal CSV schema):

    source, run_id, signal_id, event, symbol, tf, side, level, entry, sl,
    tp1, tp2, tp3, bar_time, ob_id, bos_id, state, reason, score,
    gate_status, decision, decision_at, execution_status

Three capture functions:
- capture_from_live(db, output_path): joins alert_log + signal_events
  from the live bot DB.
- capture_from_replay(engine, ohlc, output_path): runs ReplayEngine and
  writes the signals.
- capture_from_pine_logs(paste_text, output_path): parses manual Pine
  Logs paste (one signal per line, pipe-delimited) and writes rows.

The CSV is a stable schema — downstream parity / audit / dashboard tools
read it directly.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from smc_bot_backtest.replay_engine import ReplayEngine, ReplayResult
from smc_bot_core.db import BotDB
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("bot.backtest")


CSV_COLUMNS: tuple[str, ...] = (
    "source",
    "run_id",
    "signal_id",
    "event",
    "symbol",
    "tf",
    "side",
    "level",
    "entry",
    "sl",
    "tp1",
    "tp2",
    "tp3",
    "bar_time",
    "ob_id",
    "bos_id",
    "state",
    "reason",
    "score",
    "gate_status",
    "decision",
    "decision_at",
    "execution_status",
)


# Pine Logs paste format (one signal per line). Lines that don't parse
# are skipped with a warning.
_PINE_LINE_RE = re.compile(
    r"event=(?P<event>[^\|]+)\|.*?"
    r"symbol=(?P<symbol>[^\|]+)\|.*?"
    r"tf=(?P<tf>[^\|]+)\|.*?"
    r"dir=(?P<dir>[^\|]+)\|.*?"
    r"level=(?P<level>[^\|]+)\|.*?"
    r"bar_time=(?P<bar_time>[^\|]+)"
)


def _signal_row(source: str, run_id: str, payload: AlertPayload) -> dict[str, str]:
    """Build one CSV row from an AlertPayload."""
    return {
        "source": source,
        "run_id": run_id,
        "signal_id": payload.signal_id,
        "event": payload.event,
        "symbol": payload.symbol,
        "tf": payload.tf,
        "side": payload.dir,
        "level": f"{payload.level:.5f}",
        "entry": f"{payload.level:.5f}",
        "sl": "",
        "tp1": "",
        "tp2": "",
        "tp3": "",
        "bar_time": str(payload.bar_time),
        "ob_id": str(payload.ob_id),
        "bos_id": str(payload.bos_id),
        "state": payload.state,
        "reason": payload.reason,
        "score": "0",
        "gate_status": "",
        "decision": "",
        "decision_at": "",
        "execution_status": "",
    }


def _write_rows(output_path: Path, rows: Iterable[dict[str, str]]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), dialect="excel")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            n += 1
    return n


# ---------------------------------------------------------------------------
# Source 1: live (from alert_log + signal_events)
# ---------------------------------------------------------------------------


def capture_from_live(
    db: BotDB,
    output_path: Path,
    *,
    run_id: str = "live",
    limit: int | None = None,
) -> int:
    """Join alert_log + signal_events and write CSV.

    Each row uses the most recent accept/reject decision for that signal.
    """
    from smc_bot_webhook.payload import parse_payload

    alerts = db.list_recent_events(limit=limit or 10_000)
    by_sig: dict[str, list[dict[str, Any]]] = {}
    for e in alerts:
        by_sig.setdefault(e["signal_id"], []).append(e)

    rows: list[dict[str, str]] = []
    for sig_id, evs in by_sig.items():
        alert = db.get_alert_by_signal_id(sig_id)
        if alert is None:
            continue
        try:
            payload = parse_payload(alert["raw_payload"])
        except Exception:  # noqa: BLE001
            continue
        row = _signal_row("live", run_id, payload)
        for ev in evs:
            if ev["event_type"] in ("accept", "reject"):
                row["decision"] = ev["event_type"]
                row["decision_at"] = ev["created_at"]
                break
        rows.append(row)
    return _write_rows(output_path, rows)


# ---------------------------------------------------------------------------
# Source 2: Python replay output
# ---------------------------------------------------------------------------


def capture_from_replay(
    engine_or_result: ReplayEngine | ReplayResult,
    ohlc_or_path: Any = None,
    output_path: Path | None = None,
) -> int:
    """Run replay (or accept a pre-computed ReplayResult) and write CSV.

    Signatures:
    - capture_from_replay(engine, ohlc, output_path)
    - capture_from_replay(result, output_path=output_path)
    - capture_from_replay(result, output_path_path)  # positional path
    """
    if isinstance(engine_or_result, ReplayResult):
        if output_path is None:
            if ohlc_or_path is None:
                raise ValueError("output_path is required when passing ReplayResult")
            output_path = ohlc_or_path
        result = engine_or_result
    else:
        if ohlc_or_path is None or output_path is None:
            raise ValueError("ohlc and output_path required when passing ReplayEngine")
        result = engine_or_result.run(ohlc_or_path)

    rows = [
        _signal_row("replay", result.run.run_id, sig)
        for sig in result.signals
    ]
    return _write_rows(output_path, rows)


# ---------------------------------------------------------------------------
# Source 3: manual Pine Logs paste
# ---------------------------------------------------------------------------


def _parse_pine_line(line: str) -> AlertPayload | None:
    """Parse one Pine Logs line into an AlertPayload. Returns None on failure.

    Uses ``[^\|]+`` (not ``\\S+``) to anchor token capture at the next pipe,
    so e.g. ``state=watch|reason=t1`` correctly yields state='watch' (not
    'watch|reason=t1').
    """
    m = _PINE_LINE_RE.search(line)
    if not m:
        return None
    try:
        from smc_bot_webhook.payload import normalize_dir, normalize_tf
        tf_canonical = normalize_tf(m.group("tf"))
        dir_normalized = normalize_dir(m.group("dir"))

        ob_id = -1
        bos_id = -1
        state = "watch"
        reason = "manual_pine"
        ob_match = re.search(r"ob_id=([^\|]+)", line)
        if ob_match:
            ob_id = int(ob_match.group(1))
        bos_match = re.search(r"bos_id=([^\|]+)", line)
        if bos_match:
            bos_id = int(bos_match.group(1))
        st_match = re.search(r"state=([^\|]+)", line)
        if st_match:
            state = st_match.group(1)
        rsn_match = re.search(r"reason=([^\|]+)", line)
        if rsn_match:
            reason = rsn_match.group(1)

        return AlertPayload(
            prefix="SMC",
            version="v1",
            event=m.group("event"),
            symbol=m.group("symbol"),
            tf=tf_canonical,
            dir=dir_normalized,
            level=float(m.group("level")),
            bar_time=int(m.group("bar_time")),
            ob_id=ob_id,
            bos_id=bos_id,
            state=state,
            reason=reason,
            received_at=datetime.now(timezone.utc),
            raw_payload=line.strip(),
        )
    except (ValueError, KeyError):
        return None


def capture_from_pine_logs(paste_text: str, output_path: Path) -> int:
    """Parse a Pine Logs paste (one signal per line) and write CSV.

    Lines that don't match the regex are skipped with an info log.
    """
    rows: list[dict[str, str]] = []
    skipped = 0
    for line in paste_text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = _parse_pine_line(line)
        if payload is None:
            skipped += 1
            continue
        rows.append(_signal_row("pine_logs", "manual", payload))
    if skipped:
        logger.info("pine logs capture: skipped %d unparseable lines", skipped)
    return _write_rows(output_path, rows)