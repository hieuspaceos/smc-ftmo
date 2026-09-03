"""Phase 1.5: Python SMC engine validation layer.

Re-computes Pine's chart-qualified signal via the Python ``smc_engine``
package and compares with the webhook payload. Used as defense-in-depth:
a mismatch or error does NOT block the Telegram message; it only adds a
diagnostic annotation. See plan §Phase 1.5.

Pipeline:
    1. Pine chart emits ``alert()`` with ``SMC|v1|...|entry=...|sl=...|score=...``
    2. Webhook receives payload, parses into ``AlertPayload``
    3. ``validate_pine_signal(payload)`` runs Python engine on M15 data
       (swings / structure / order blocks) and compares
    4. Result returned to webhook handler with 3-state ``matched``:
         True   \u2192 Pine + Python agree
         False  \u2192 Pine + Python disagree (diverge)
         None   \u2192 unable to validate (OB not found / timeout / error)
"""
from __future__ import annotations

import signal as _signal
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from smc_bot_webhook.payload import AlertPayload

# Lazy imports of smc_engine: pulled in only when validator runs, so the
# webhook module doesn't pay the import cost on every request.
def _import_engine():
    """Lazily import smc_engine functions; raise RuntimeError on failure."""
    try:
        from smc_engine.swings import detect_swings
        from smc_engine.structure import detect_structure
        from smc_engine.order_blocks import detect_order_blocks
        from smc_engine.displacement import calculate_atr
    except ImportError as exc:
        raise RuntimeError(
            f"smc_engine package unavailable: {exc}. "
            "Install with `pip install -e packages/smc_engine`."
        ) from exc
    return detect_swings, detect_structure, detect_order_blocks, calculate_atr


# Pip-multiplier: how many pips per 1.0 price-unit for the pair.
# FX 5-digit brokers (EURUSD, GBPUSD, USDCHF): 1 pip = 0.0001 price.
# XAUUSD 2-digit: 1 pip = 0.01 price. BTCUSD: 1 pip = 1.0 price.
_PIP_MULTIPLIER = {
    "EURUSD": 10000.0,
    "GBPUSD": 10000.0,
    "USDCHF": 10000.0,
    "XAUUSD": 100.0,
    "BTCUSD": 1.0,
}


@contextmanager
def _time_budget(seconds: float):
    """POSIX-only signal-based timeout. No-op on Windows / non-main thread."""
    import threading
    if not hasattr(_signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return
    def _handler(signum, frame):
        raise TimeoutError("smc_validator time budget exceeded")
    prev_handler = _signal.signal(_signal.SIGALRM, _handler)
    _signal.setitimer(_signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        _signal.setitimer(_signal.ITIMER_REAL, 0)
        _signal.signal(_signal.SIGALRM, prev_handler)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of Python SMC engine validation against a Pine signal."""
    matched: bool | None  # True=agree, False=diverge, None=unable to validate
    reason: str
    pine_signal: AlertPayload | None = None
    python_signal: dict[str, Any] | None = None
    diff: dict[str, Any] = field(default_factory=dict)


def validate_pine_signal(
    payload: AlertPayload,
    m15_data: pd.DataFrame | None,
    *,
    tolerance_pips: float = 5.0,
    timeout_seconds: float = 2.0,
) -> ValidationResult:
    """Run Python engine, compare with Pine payload. Always returns; never raises.

    The validator NEVER blocks the Telegram message \u2014 it only annotates.
    On timeout / error / no data, ``matched=None`` so the caller can label
    the message "validation skipped" instead of false-positive divergence.
    """
    # 1. Prerequisite: need data + entry level
    if m15_data is None or m15_data.empty:
        return ValidationResult(matched=None, reason="no M15 data",
                                 pine_signal=payload)
    if payload.entry is None or payload.ob_id is None or payload.ob_id < 0:
        return ValidationResult(matched=None, reason="payload missing entry/ob_id",
                                 pine_signal=payload)

    pip_mult = _PIP_MULTIPLIER.get(payload.symbol, 10000.0)

    try:
        with _time_budget(timeout_seconds):
            detect_swings, detect_structure, detect_order_blocks, calculate_atr = _import_engine()
            swings = detect_swings(m15_data, left=5, right=5)
            atr_series = calculate_atr(m15_data)
            # detect_structure wants an atr arg; older signatures used
            # a different name. Try the current one first, fall back if absent.
            try:
                structure = detect_structure(m15_data, swings, atr=atr_series)
            except TypeError:
                structure = detect_structure(m15_data, swings)
            obs = detect_order_blocks(m15_data, swings, structure,
                                     atr=atr_series if "atr" in _detect_ob_signature() else None)
    except TimeoutError:
        return ValidationResult(matched=None, reason="timeout",
                                 pine_signal=payload)
    except Exception as exc:
        return ValidationResult(matched=None, reason=f"error: {type(exc).__name__}: {exc}",
                                 pine_signal=payload)

    # 2. Find candidate OB matching Pine payload's ob_id + direction
    pine_dir_long = payload.dir == "long"
    candidates = [
        ob for ob in obs.events
        if ob.id == payload.ob_id
        and ((pine_dir_long and ob.direction == "bullish")
             or (not pine_dir_long and ob.direction == "bearish"))
    ]
    if not candidates:
        return ValidationResult(
            matched=None,
            reason=f"OB id={payload.ob_id} not found in Python engine",
            pine_signal=payload,
        )

    ob = candidates[0]
    py_entry = ob.top if pine_dir_long else ob.bottom
    py_dir_str = "long" if pine_dir_long else "short"
    py_side_match = (ob.direction == "bullish" and pine_dir_long) or \
                    (ob.direction == "bearish" and not pine_dir_long)
    entry_diff_pips = abs(py_entry - payload.entry) * pip_mult
    entry_match = entry_diff_pips <= tolerance_pips
    matched = py_side_match and entry_match

    py_signal = {
        "side": py_dir_str,
        "entry": py_entry,
        "ob_id": ob.id,
        "ob_top": ob.top,
        "ob_bottom": ob.bottom,
        "structure_event_id": ob.structure_event_id,
    }

    if not matched:
        reason_parts = []
        if not py_side_match:
            reason_parts.append(
                f"side mismatch (Pine={payload.dir}, Python={py_dir_str})")
        if not entry_match:
            reason_parts.append(
                f"entry differs by {entry_diff_pips:.1f} pips "
                f"(tolerance {tolerance_pips})")
        reason = "; ".join(reason_parts) if reason_parts else "diverged"
    else:
        reason = "matched"

    return ValidationResult(
        matched=matched,
        reason=reason,
        pine_signal=payload,
        python_signal=py_signal,
        diff={
            "entry_pips": entry_diff_pips,
            "side_match": py_side_match,
            "entry_match": entry_match,
        },
    )


def _detect_ob_signature() -> inspect.Signature | None:
    """Inspect detect_order_blocks to learn if it accepts atr kwarg."""
    import inspect
    try:
        from smc_engine.order_blocks import detect_order_blocks
        return inspect.signature(detect_order_blocks)
    except Exception:
        return None
