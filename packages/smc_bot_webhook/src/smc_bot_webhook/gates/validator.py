"""11-gate rulebook validator.

Combines:
- 5 chart gates derived from ``AlertPayload`` (Pine state, symbol, tf, etc.)
- 6 manual gates persisted in ``gate_ack`` (trader ack via Telegram)

Returns a ``Decision`` enum that the dispatcher / Telegram handlers use to
decide whether to enable Accept/Reject buttons, run a re-check on Accept,
or mark the signal ``expired`` / ``blocked``.

Re-check semantics
------------------
``Accept`` button messages are presentation only — Phase 03 re-runs the
validator on every Accept callback. If any gate has gone stale since the
Telegram message was sent (e.g. the trader changed no_position via a
different flow, or 5 minutes elapsed), the Accept is refused and the
Telegram message is edited to show ``BLOCKED — reason: ...``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from smc_bot_webhook.gates.state import (
    MANUAL_GATE_NAMES,
    SIGNAL_GATE_WINDOW_MINUTES,
    SIGNAL_SPECIFIC_GATE_NAMES,
    GateState,
    GateStateStore,
    GateStatus,
)
from smc_bot_webhook.payload import AlertPayload


class Decision(str, Enum):
    """Validator output — drives dispatch + Accept-revalidation flow."""

    NOTIFY_ONLY = "notify_only"          # chart ok; not yet ready (manual gates stale)
    NEEDS_MANUAL_ACK = "needs_manual_ack"  # chart ok; some manual gates missing
    BLOCKED = "blocked"                  # at least one chart gate failed
    ACCEPTED_READY = "accepted_ready"    # all 11 gates pass; Accept enabled
    EXPIRED = "expired"                  # signal-specific gates stale


# Five chart gates — pure functions of AlertPayload.
CHART_GATE_NAMES: tuple[str, ...] = (
    "symbol_eurusd",     # gate 1: symbol allowlist
    "tf_m15",            # gate 2: timeframe
    "pine_state_ok",     # gate 3: chart-qualified or watch
    "direction_exists",  # gate 4: dir in {long, short}
    "ob_bos_provenance", # gate 5: ob_id or bos_id present for trade event
)


@dataclass(frozen=True)
class GateResult:
    """One gate check outcome."""

    name: str
    passed: bool
    reason: str = ""  # human-readable for Telegram message


@dataclass(frozen=True)
class ValidationOutcome:
    """Full validator output."""

    decision: Decision
    chart_results: tuple[GateResult, ...]
    manual_results: tuple[GateResult, ...]
    missing_manual: tuple[str, ...]  # subset of MANUAL_GATE_NAMES that need ack

    @property
    def passed(self) -> bool:
        return self.decision is Decision.ACCEPTED_READY

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.chart_results + self.manual_results)

    def blocking_reasons(self) -> tuple[str, ...]:
        """Human-readable reasons for any non-passing gate."""
        reasons: list[str] = []
        for r in self.chart_results + self.manual_results:
            if not r.passed:
                tag = "chart" if r.name in CHART_GATE_NAMES else "manual"
                reasons.append(f"[{tag}] {r.name}: {r.reason}")
        return tuple(reasons)


# ---------------------------------------------------------------------------
# Chart gates (pure)
# ---------------------------------------------------------------------------


def _check_symbol(payload: AlertPayload) -> GateResult:
    return GateResult(
        name="symbol_eurusd",
        passed=payload.symbol == "EURUSD",
        reason="" if payload.symbol == "EURUSD" else f"symbol is {payload.symbol}, expected EURUSD",
    )


def _check_tf(payload: AlertPayload) -> GateResult:
    return GateResult(
        name="tf_m15",
        passed=payload.tf == "M15",
        reason="" if payload.tf == "M15" else f"tf is {payload.tf}, expected M15",
    )


def _check_pine_state(payload: AlertPayload) -> GateResult:
    ok = payload.state in ("chart-qualified", "watch")
    return GateResult(
        name="pine_state_ok",
        passed=ok,
        reason="" if ok else f"pine state is {payload.state!r}, expected chart-qualified or watch",
    )


def _check_direction(payload: AlertPayload) -> GateResult:
    ok = payload.dir in ("long", "short")
    return GateResult(
        name="direction_exists",
        passed=ok,
        reason="" if ok else f"direction is {payload.dir!r}, expected long or short",
    )


def _check_ob_bos(payload: AlertPayload) -> GateResult:
    # For trade events (chart_qualified), require either ob_id or bos_id.
    # For watch events, accept missing — they're not yet a candidate.
    if payload.event in ("ob_activated", "chart_qualified"):
        ok = payload.ob_id >= 0 or payload.bos_id >= 0
        reason = "" if ok else f"event={payload.event} has no ob_id or bos_id provenance"
    else:
        ok = True
        reason = ""
    return GateResult(name="ob_bos_provenance", passed=ok, reason=reason)


_CHART_FUNCS = (
    _check_symbol,
    _check_tf,
    _check_pine_state,
    _check_direction,
    _check_ob_bos,
)


def evaluate_chart_gates(payload: AlertPayload) -> tuple[GateResult, ...]:
    """Run all 5 chart gates against the payload."""
    return tuple(fn(payload) for fn in _CHART_FUNCS)


# ---------------------------------------------------------------------------
# Manual gates
# ---------------------------------------------------------------------------


def evaluate_manual_gates(state: GateState) -> tuple[GateResult, ...]:
    """Run all 6 manual gates against the persisted gate_ack snapshot."""
    results: list[GateResult] = []
    for name in MANUAL_GATE_NAMES:
        s = state.statuses.get(name)
        if s is None or s.value is None:
            results.append(GateResult(name=name, passed=False, reason=f"{name} not acked"))
            continue
        if s.expired:
            results.append(GateResult(name=name, passed=False, reason=f"{name} ack expired"))
            continue
        if not s.fresh:
            results.append(GateResult(name=name, passed=False, reason=f"{name} ack stale"))
            continue
        results.append(GateResult(name=name, passed=True, reason=""))
    return tuple(results)


def missing_manual_gates(state: GateState) -> tuple[str, ...]:
    """Names of manual gates that are not acked (or are expired)."""
    missing: list[str] = []
    for name in MANUAL_GATE_NAMES:
        s = state.statuses.get(name)
        if s is None or s.value is None or s.expired:
            missing.append(name)
    return tuple(missing)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class Validator:
    """Combines chart + manual gates + admin override + expiry logic."""

    def __init__(
        self,
        state_store: GateStateStore,
        *,
        admin_override: bool = False,
        signal_window_minutes: int = SIGNAL_GATE_WINDOW_MINUTES,
    ) -> None:
        self._store = state_store
        self._admin_override = admin_override
        self._signal_window = signal_window_minutes

    def validate(self, payload: AlertPayload, *, now: Any = None) -> ValidationOutcome:
        """Evaluate all 11 gates. Pure orchestration — no I/O besides the store."""
        chart = evaluate_chart_gates(payload)
        snapshot = self._store.snapshot(now=now)
        manual = evaluate_manual_gates(snapshot)
        missing = missing_manual_gates(snapshot)

        # Chart gates that fail → BLOCKED (chart gates can't be fixed by manual ack).
        chart_pass = all(r.passed for r in chart)
        if not chart_pass:
            return ValidationOutcome(
                decision=Decision.BLOCKED,
                chart_results=chart,
                manual_results=manual,
                missing_manual=missing,
            )

        # Chart OK. Admin override skips manual checks.
        if self._admin_override:
            return ValidationOutcome(
                decision=Decision.ACCEPTED_READY,
                chart_results=chart,
                manual_results=manual,
                missing_manual=missing,
            )

        # Manual gates all fresh → ACCEPTED_READY.
        if all(r.passed for r in manual):
            return ValidationOutcome(
                decision=Decision.ACCEPTED_READY,
                chart_results=chart,
                manual_results=manual,
                missing_manual=missing,
            )

        # Some manual gates missing or expired. Distinguish signal-specific expiry
        # vs session-wide daily gates: if a signal-specific gate is expired, the
        # signal is too old → EXPIRED. Otherwise, just need manual ack.
        has_signal_expired = any(
            s.name in SIGNAL_SPECIFIC_GATE_NAMES
            and s.value is not None
            and s.expired
            for s in snapshot.statuses.values()
        )
        if has_signal_expired:
            return ValidationOutcome(
                decision=Decision.EXPIRED,
                chart_results=chart,
                manual_results=manual,
                missing_manual=missing,
            )
        if missing:
            return ValidationOutcome(
                decision=Decision.NEEDS_MANUAL_ACK,
                chart_results=chart,
                manual_results=manual,
                missing_manual=missing,
            )
        # All acked but at least one failed (e.g., daily_loss_ok=False from trader).
        return ValidationOutcome(
            decision=Decision.NOTIFY_ONLY,
            chart_results=chart,
            manual_results=manual,
            missing_manual=missing,
        )