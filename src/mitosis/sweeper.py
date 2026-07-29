"""Reservation sweeper (SPEC.md §4.4; docs/STATE_MACHINES.md §2.3).

Scoped to expired `reserved` reservations only. Resolving reservations
already in `execution_unknown` is a separate, deliberate reconciliation
flow (human/Auditor-driven per §4.4) — not something the sweeper retries
automatically, since "unknown external operations are reconciled, never
auto-released" (Charter C7) implies a considered process, not a repeated
sweep.

What an expired reservation *means* is deliberately not this module's
question: `ExternalOperationChecker` is the seam, and the caller supplies
the implementation that knows the external system. Phase 4's model gateway
supplies `gateway.GatewayOperationChecker`, which is why nothing here
imports `gateway` or mentions a model call — the dependency runs the other
way. A sweep leaves the *reservations* correct; bringing the gateway's own
`model_calls` rows back into agreement with them is
`gateway.resolve_stranded_calls`, and `mitosis sweep` runs both in order.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Protocol

from . import reservations
from .models import Reservation, ReservationStatus


class ExternalOutcome(Enum):
    NOT_HAPPENED = auto()
    HAPPENED = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class CheckResult:
    outcome: ExternalOutcome
    actual_amount: int | None = None
    destination_account_id: str | None = None


class ExternalOperationChecker(Protocol):
    def check(self, reservation: Reservation) -> CheckResult: ...


class UnknownOperationChecker:
    """Phase 1 default. No real external systems exist yet (no real LLM
    calls, no sandboxed execution — SPEC.md §28 Phase 1), so any reservation
    with an attached external_operation_id is honestly unresolvable at
    sweep time. This never guesses NOT_HAPPENED for a real
    external_operation_id — that would risk masking a real double-spend.
    """

    def check(self, reservation: Reservation) -> CheckResult:
        return CheckResult(ExternalOutcome.UNKNOWN)


def sweep(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    checker: ExternalOperationChecker | None = None,
) -> list[Reservation]:
    """Sweep expired `reserved` reservations. Returns the reservations that
    were transitioned, in their new state, in the order they were swept.
    """
    now = now or datetime.now(timezone.utc)
    checker = checker or UnknownOperationChecker()

    rows = conn.execute(
        "SELECT reservation_id FROM reservations WHERE status = ? AND expires_at <= ? "
        "ORDER BY expires_at",
        (ReservationStatus.RESERVED.value, now.astimezone(timezone.utc).isoformat()),
    ).fetchall()

    swept: list[Reservation] = []
    for row in rows:
        reservation = reservations.get_reservation(conn, row["reservation_id"])
        if reservation is None:
            continue

        if reservation.external_operation_id is None:
            # Nothing external was ever triggered; releasing is safe.
            swept.append(reservations.release(conn, reservation.reservation_id))
            continue

        result = checker.check(reservation)
        if result.outcome is ExternalOutcome.NOT_HAPPENED:
            swept.append(reservations.release(conn, reservation.reservation_id))
        elif result.outcome is ExternalOutcome.HAPPENED:
            if result.actual_amount is None or result.destination_account_id is None:
                raise ValueError(
                    "checker reported HAPPENED without actual_amount and "
                    "destination_account_id"
                )
            swept.append(
                reservations.settle(
                    conn,
                    reservation.reservation_id,
                    settled_amount=result.actual_amount,
                    destination_account_id=result.destination_account_id,
                )
            )
        else:
            swept.append(
                reservations.mark_execution_unknown(conn, reservation.reservation_id)
            )
    return swept
