"""Model gateway (SPEC.md §24; §5; §2.4; Amendment A6; Charter C4/C5/C14).

This is the module that spends real money. Everything before it in the kernel
moved synthetic or internal balances; `call_model` is the first code path in
MITOSIS whose successful execution produces an external charge.

The shape of one call, in order:

    1. Price the worst case      pricing.py + a conservative token estimate
    2. RESERVE (USD_REAL)        reservations.request(provider=...)
                                   -> Charter C5 global caps + §5.1 per-provider cap
                                   -> Charter C4 the Cell's own balance
    3. RESERVE (RESOURCE)        the A6 link for token metering
    4. EXECUTE                   provider.complete() — the external call
    5. SETTLE (USD_REAL)         at the provider's *reported* usage, not the
                                   estimate, to `external_expense`
    6. METER (RESOURCE)          record_usage per token type, then settle
    7. MIRROR (USD_SIM)          §2.4 independent synthetic expense

Reserve-before-execute is the whole point: a Cell cannot make a paid call it
has not already been authorised for, and the caps are checked inside the
reservation's write lock, so concurrent calls cannot collectively exceed a
limit that each individually respects (§5.3).

**Failure is where the money is.** A provider call that raises after the
request left the machine may or may not have been billed. Releasing the
reservation in that case would silently lose real money; this module marks
the reservation `execution_unknown` instead (§4.4, Charter C7) and leaves the
funds committed until a human or a future reconciliation resolves it. Only a
provider rejection that is definitely unbilled (a 400/401/403/404) releases.

**Steps 5-7 are one transaction, and so are their failure-path
equivalents.** Charter C7 makes each individual reservation transition
crash-atomic, but one paid call resolves *two* reservations plus metering,
the mirror and the `model_calls` row. Performed separately, a crash
mid-sequence would leave real money spent against a call still recorded as
in flight, with nothing able to say which steps had run. `_handle_success`
and `_handle_failure` therefore each hold a single `BEGIN IMMEDIATE` and
compose the `_*_locked` cores of reservations.py, resource_metering.py and
ledger.py — the same split those modules already used for `audit.record`
and `ledger._write_transaction`. A crash rolls back to the pre-call state,
which `GatewayOperationChecker` + `resolve_stranded_calls` resolve; see the
crash-recovery section below for why that state is honest rather than
complete. Steps 1-3 stay separate on purpose: the reservation must be
durably committed *before* the external call, which is what makes
reserve-before-execute mean anything.

**Charter C14** is upheld by `providers.py`, not here: no credential is ever
an argument to, a field of, or a return value from anything in this module,
and provider error text is redacted before it is persisted.

Deliberately out of scope for this slice:

- **Routing** (§24.3's task-type -> model policy). The caller names the model.
  Routing needs a task taxonomy the kernel does not have.
- **Retries** (§24's "retries controlled failures"). A retry after an
  `execution_unknown` failure risks double-billing, and deciding that needs
  the reconciliation this kernel cannot do yet.
- **Structured-output validation** and **model competition** (§24) — both
  need Cells that can actually consume a response, which is Phase 5.
- **Provider drift as a regime change** (§24.2). `resolved_model` and
  `api_version` are recorded on every call, so the drift is *visible*;
  nothing yet reacts to it, because §8.4 regime changes don't exist.
- **Reconciled cost** (§24.1). `reconciled_micro_usd` is always None: there
  is no provider invoice to reconcile against.
- **Forward recovery** of a crashed call (ADR-022's deferred alternative).
  The single transaction below guarantees no money is left half-moved, but
  a rollback also discards the provider's reported usage — the one thing a
  crash cannot reconstruct. Recording that response durably first, under a
  `settling` status, would let recovery finish the settlement automatically
  instead of parking it in `execution_unknown` for a human. It needs the
  same plumbing as §24.1 reconciliation and is deferred to land with it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import (
    audit,
    ids,
    ledger,
    network_seal,
    pricing,
    providers,
    reservations,
    resource_metering,
    sweeper,
    tracing,
)
from .accounts import cell_cash
from .models import (
    Book,
    EntrySpec,
    ModelCall,
    ModelCallStatus,
    Reservation,
    ReservationStatus,
    ResourceType,
)
from .providers import ModelProvider, ModelRequest

DEFAULT_RESERVATION_TTL = timedelta(minutes=15)

# §2.4: model-call cost may be mirrored into USD_SIM as an independent
# synthetic experiment charge. 1.0 mirrors the real cost 1:1. This is a
# *mirror*, never a transfer — the USD_SIM posting is funded from the Cell's
# own synthetic cash and no value crosses between books.
DEFAULT_MIRROR_MULTIPLIER = 1.0

_EXTERNAL_EXPENSE = "external_expense"
_INFRASTRUCTURE_RESERVE = "infrastructure_reserve"


class GatewayError(Exception):
    pass


class InsufficientRealBudgetError(GatewayError):
    pass


def call_model(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    provider: ModelProvider,
    request: ModelRequest,
    idempotency_key: str,
    resource_budget: int | None = None,
    experiment_id: str | None = None,
    mirror_multiplier: float = DEFAULT_MIRROR_MULTIPLIER,
    ttl: timedelta = DEFAULT_RESERVATION_TTL,
) -> ModelCall:
    """Execute one model call through the gateway. Idempotent on
    `idempotency_key`: replaying a key returns the existing call rather than
    making (and paying for) a second one.

    `resource_budget` caps the call's RESOURCE-book consumption in micro-USD
    of shadow price; it defaults to the same worst-case figure used for the
    USD_REAL reservation, which is the natural pairing — a call cannot burn
    more shadow-priced resource than it can cost in real money.
    """
    existing = get_model_call_by_idempotency_key(conn, idempotency_key)
    if existing is not None:
        return existing

    if request.max_tokens <= 0:
        raise GatewayError("max_tokens must be positive")
    if mirror_multiplier < 0:
        raise GatewayError("mirror_multiplier must be non-negative")

    # Fails closed on an un-priced model *before* any reservation or call:
    # billing a model we cannot price is worse than refusing to call it.
    worst_case_micro = _worst_case_micro_usd(provider.name, request)
    worst_case_minor = pricing.micro_usd_to_minor_units(worst_case_micro)
    if worst_case_minor <= 0:
        # A zero-priced model (the mock provider) still needs a reservation so
        # the same code path is exercised end to end; reserve the minimum.
        worst_case_minor = 1
    # Floored at 2 so a zero-priced model (the mock provider) can still record
    # one input-token and one output-token usage row: resource_metering
    # requires a positive minor_units per row, so a budget of 0 — or of 1 —
    # would silently drop the metering that Amendment A6 requires of every
    # call, regardless of what that call cost.
    resource_budget = (
        resource_budget if resource_budget is not None else max(worst_case_micro, 2)
    )

    model_call_id = ids.new_id()
    now = datetime.now(timezone.utc)
    expires_at = now + ttl

    real_reservation = reservations.request(
        conn,
        cell_id=cell_id,
        book=Book.USD_REAL,
        currency="USD",
        maximum_amount=worst_case_minor,
        expires_at=expires_at,
        idempotency_key=f"model_call_real:{model_call_id}",
        experiment_id=experiment_id,
        external_operation_type="model_call",
        external_operation_id=model_call_id,
        provider=provider.name,
    )
    try:
        resource_reservation = reservations.request(
            conn,
            cell_id=cell_id,
            book=Book.RESOURCE,
            currency="RESOURCE",
            maximum_amount=resource_budget,
            expires_at=expires_at,
            idempotency_key=f"model_call_resource:{model_call_id}",
            experiment_id=experiment_id,
            external_operation_type="model_call",
            external_operation_id=model_call_id,
        )
    except Exception:
        # The RESOURCE side failed, so no call will be made — give the real
        # money straight back rather than leaving it committed.
        reservations.release(conn, real_reservation.reservation_id)
        raise

    _insert_model_call(
        conn,
        model_call_id=model_call_id,
        cell_id=cell_id,
        experiment_id=experiment_id,
        provider=provider.name,
        request=request,
        cost_estimate_micro_usd=worst_case_micro,
        real_reservation_id=real_reservation.reservation_id,
        resource_reservation_id=resource_reservation.reservation_id,
        created_at_utc=now,
        idempotency_key=idempotency_key,
    )

    try:
        # A view for an opted-in operator, never the record (ADR-104): the
        # row inserted above is. Opened after the reservation commits, which
        # is why `tracing.span` swallows its own faults and never ours.
        with tracing.span(
            "model_call",
            run_type="llm",
            inputs={"messages": list(request.messages)},
            metadata={
                "ls_provider": provider.name,
                "ls_model_name": request.model,
                "ls_max_tokens": request.max_tokens,
                "ls_temperature": request.temperature,
                "model_call_id": model_call_id,
                "cell_id": cell_id,
                "idempotency_key": idempotency_key,
            },
        ) as span:
            response = provider.complete(request)
            span.finish({
                "text": response.text,
                "resolved_model": response.resolved_model,
                "usage_metadata": {
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "total_tokens": response.input_tokens + response.output_tokens,
                },
            })
    except (providers.ProviderError, network_seal.NetworkSealed) as exc:
        if isinstance(exc, network_seal.NetworkSealed):
            # Refused by the interpreter before a byte left the process
            # (ADR-085), so this is the one failure known with certainty to be
            # unbilled — whatever provider was wired in, and whether or not it
            # caught the refusal itself. Uncaught, it would escape this
            # function with both reservations committed and strand them until
            # the sweeper guessed at an outcome that is not in doubt.
            exc = providers.ProviderCallError(str(exc), execution_unknown=False)
        _handle_failure(
            conn,
            model_call_id=model_call_id,
            cell_id=cell_id,
            real_reservation_id=real_reservation.reservation_id,
            resource_reservation_id=resource_reservation.reservation_id,
            exc=exc,
        )
        result = get_model_call(conn, model_call_id)
        assert result is not None
        return result

    _handle_success(
        conn,
        model_call_id=model_call_id,
        cell_id=cell_id,
        provider_name=provider.name,
        request=request,
        response=response,
        real_reservation_id=real_reservation.reservation_id,
        resource_reservation_id=resource_reservation.reservation_id,
        mirror_multiplier=mirror_multiplier,
    )
    result = get_model_call(conn, model_call_id)
    assert result is not None
    return result


def call_failure(call: ModelCall) -> str | None:
    """Why this call returned no reply — or `None` when it returned one to read.

    **The question every caller of `call_model` has to ask and one did not.**
    A provider failure does not raise out of `call_model`: it is classified
    (`failed` when the request is known to be unbilled, `execution_unknown`
    when it may have been), recorded on the `model_calls` row, and *returned*.
    So a caller always holds a `ModelCall`, and a caller that goes straight to
    `response_text or ""` hands the empty string to its own parser and records
    a provider outage as the model failing to answer in the required shape.

    §24.2 forbids exactly that confusion — "treat material model changes as
    environment regime changes so provider drift is not mistaken for Cell
    evolution" — and an outage is the loudest provider change there is. The
    gateway already classified it correctly; this function is how a caller
    reads that classification instead of overwriting it with a story about
    the Cell.

    The text is `providers.redact`ed before it is persisted (`_handle_failure`),
    so a caller may copy it into its own record without re-running Charter
    C14's redaction — and should, rather than inventing a description of a
    failure it did not observe.
    """
    if call.status is ModelCallStatus.SUCCEEDED:
        return None
    return (
        f"model call {call.status.value} at provider {call.provider}: "
        f"{call.error_text or '(no error text recorded)'}"
    )


def _handle_success(
    conn: sqlite3.Connection,
    *,
    model_call_id: str,
    cell_id: str,
    provider_name: str,
    request: ModelRequest,
    response: providers.ModelResponse,
    real_reservation_id: str,
    resource_reservation_id: str,
    mirror_multiplier: float,
) -> None:
    """Record everything one billed call implies — in a single transaction.

    Settling the USD_REAL reservation, posting any overrun, metering both
    token types, settling the RESOURCE reservation, mirroring into USD_SIM
    and marking the `model_calls` row are six separate money-or-record
    movements describing *one* external charge. Charter C7 guarantees each is
    individually crash-atomic, but that is not the guarantee this path needs:
    a crash between them would leave the call recorded as `reserved` with its
    real money already spent, its resource budget unsettled, and no operator
    verb able to tell which of the six had happened. So they share one
    BEGIN IMMEDIATE and the guarantee extends to the composition.

    The consequence is deliberate: a crash anywhere in here rolls all of it
    back to the state the process was in when the provider was called — both
    reservations `reserved`, the `model_calls` row `reserved`, no money
    moved. That state is honest rather than complete: the provider may well
    have billed us, and the sweeper resolves it to `execution_unknown`
    (never to `released`) exactly as Charter C7 requires. What is lost is the
    response itself, which cannot be reconstructed and is the reconciliation
    flow's problem, not the ledger's.
    """
    # A provider may serve a different model than was requested (§24.2 treats
    # that as a regime change). Price against what it actually served when we
    # have a price for it, falling back to the requested model otherwise.
    # Resolved once and reused for metering below: pricing the USD_REAL charge
    # off one model and the RESOURCE shadow price off another would make the
    # two books disagree about the same call.
    billed_model = (
        response.resolved_model
        if _is_priced(provider_name, response.resolved_model)
        else request.model
    )
    actual_micro = pricing.cost_micro_usd(
        provider_name,
        billed_model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
    actual_minor = pricing.micro_usd_to_minor_units(actual_micro)
    # Priced before the write lock is taken: pure lookup, and an unknown model
    # should fail before anything is settled rather than halfway through.
    price = pricing.get_price(provider_name, billed_model)

    conn.execute("BEGIN IMMEDIATE")
    try:
        reservation = reservations.get_reservation(conn, real_reservation_id)
        assert reservation is not None
        settle_minor = min(actual_minor, reservation.maximum_amount)
        underestimated = actual_minor > reservation.maximum_amount

        _settle_and_release_remainder_locked(
            conn,
            real_reservation_id,
            settled_amount=settle_minor,
            destination_account_id=_EXTERNAL_EXPENSE,
        )
        if underestimated:
            _post_cost_overrun_locked(
                conn,
                model_call_id=model_call_id,
                cell_id=cell_id,
                shortfall=actual_minor - settle_minor,
                reserved=reservation.maximum_amount,
                actual=actual_minor,
            )

        # RESOURCE metering (Amendment A6): input and output tokens are
        # recorded separately, each shadow-priced from the same pricing table
        # that produced the real charge — this is the shadow-pricing
        # resource_metering.py's docstring deferred to its caller.
        # `model_calls` is not recorded as a usage row: the model_calls table
        # already counts calls, and giving it a share of the same cost would
        # double-count it.
        for resource_type, tokens, per_mtok in (
            (ResourceType.INPUT_TOKENS, response.input_tokens, price.input_usd_per_mtok),
            (ResourceType.OUTPUT_TOKENS, response.output_tokens, price.output_usd_per_mtok),
        ):
            if tokens <= 0:
                continue
            # Floored at 1: a metered operation that consumed real tokens must
            # leave a usage row even when its shadow price rounds to nothing,
            # or A6's completeness invariant would have a hole exactly where
            # the cheapest models are.
            minor = max(int(tokens * per_mtok), 1)
            # Read back from the DB each iteration — `reservation_remaining`
            # already accounts for every row written so far, so tracking a
            # running total alongside it would subtract each row twice and
            # exhaust the budget after the first usage type.
            remaining = reservation_remaining(conn, resource_reservation_id)
            if remaining <= 0:
                break
            resource_metering._record_usage_locked(
                conn,
                cell_id=cell_id,
                reservation_id=resource_reservation_id,
                resource_type=resource_type,
                quantity=tokens,
                minor_units=min(minor, remaining),
                idempotency_key=f"model_call:{model_call_id}:{resource_type.value}",
                metadata={"model_call_id": model_call_id, "model": request.model},
            )

        _settle_and_release_remainder_locked(
            conn,
            resource_reservation_id,
            settled_amount=resource_metering.total_minor_units(
                conn, resource_reservation_id
            ),
            destination_account_id=_INFRASTRUCTURE_RESERVE,
        )

        # Mirrors the *true* real cost, not the clamped settlement — the
        # synthetic signal a Cell trains against should reflect what the call
        # actually cost.
        mirror_minor, mirror_skipped = _mirror_to_sim_locked(
            conn,
            model_call_id=model_call_id,
            cell_id=cell_id,
            real_minor_units=actual_minor,
            multiplier=mirror_multiplier,
        )

        conn.execute(
            """
            UPDATE model_calls SET
                status = ?, resolved_model = ?, api_version = ?,
                input_tokens = ?, output_tokens = ?, latency_ms = ?,
                response_hash = ?, stop_reason = ?, response_text = ?,
                cost_actual_micro_usd = ?, settled_minor_units = ?,
                mirror_minor_units = ?, mirror_skipped_reason = ?
            WHERE model_call_id = ?
            """,
            (
                ModelCallStatus.SUCCEEDED.value,
                response.resolved_model,
                response.api_version,
                response.input_tokens,
                response.output_tokens,
                response.latency_ms,
                _sha256(response.text),
                response.stop_reason,
                response.text,
                actual_micro,
                # The total real spend recorded on the ledger for this call:
                # the settlement plus any overrun posted alongside it, which
                # together always equal the true cost.
                actual_minor,
                mirror_minor,
                mirror_skipped,
                model_call_id,
            ),
        )
        audit.record(
            conn,
            event_type="model_call_settled",
            cell_id=cell_id,
            description=(
                f"{provider_name}/{response.resolved_model}: "
                f"{response.input_tokens} in / {response.output_tokens} out, "
                f"{actual_micro} micro-USD"
            ),
            metadata={
                "model_call_id": model_call_id,
                "provider": provider_name,
                "cost_actual_micro_usd": actual_micro,
                "settled_minor_units": settle_minor,
                "pricing_table_version": pricing.PRICING_TABLE_VERSION,
                # Loud, because it means the ledger under-recorded a real
                # charge: the token estimate was too low and the settlement
                # was clamped to the reservation cap to preserve Charter C4.
                "cost_underestimated": underestimated,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _settle_and_release_remainder_locked(
    conn: sqlite3.Connection,
    reservation_id: str,
    *,
    settled_amount: int,
    destination_account_id: str,
) -> None:
    """Settle a reservation and hand back whatever was over-reserved. Caller
    holds the write transaction.

    The gateway always reserves the worst case (a conservative input-token
    estimate plus the full `max_tokens` of output), so a settled call almost
    always costs less than it reserved. Without this release the difference
    stays in `cell:{id}:committed` forever: conservation still holds and the
    hash chain stays green, but the Cell's spendable cash silently bleeds
    away one call at a time and `_concurrent_reserved` never comes back down,
    so the Charter C5 concurrent-reserved cap tightens on every call until
    the colony can no longer make one.

    `settle` moves the reservation to `settled` on a full settlement and
    `partially_settled` otherwise; only the latter has a remainder to
    release, and `partially_settled -> released` is the transition the FSM
    provides for exactly this (reservations._ALLOWED_TRANSITIONS).
    """
    reservation = reservations.get_reservation(conn, reservation_id)
    assert reservation is not None
    reservations._settle_locked(
        conn,
        reservation_id,
        settled_amount=settled_amount,
        destination_account_id=destination_account_id,
    )
    if settled_amount < reservation.maximum_amount:
        reservations._release_locked(conn, reservation_id)


def _handle_failure(
    conn: sqlite3.Connection,
    *,
    model_call_id: str,
    cell_id: str,
    real_reservation_id: str,
    resource_reservation_id: str,
    exc: providers.ProviderError,
) -> None:
    """A failed call still costs a reservation decision. See the module
    docstring: `execution_unknown` keeps the money committed because the
    provider may have billed us.

    Atomic for the same reason `_handle_success` is: resolving the real
    reservation, releasing the resource reservation and marking the
    `model_calls` row are three statements about one outcome, and a crash
    between them would leave the row claiming a call is still in flight
    while its reservations say otherwise.
    """
    unknown = isinstance(exc, providers.ProviderCallError) and exc.execution_unknown
    status = (
        ModelCallStatus.EXECUTION_UNKNOWN if unknown else ModelCallStatus.FAILED
    )
    error_text = providers.redact(str(exc))

    conn.execute("BEGIN IMMEDIATE")
    try:
        if unknown:
            reservations._bare_status_transition_locked(
                conn, real_reservation_id, ReservationStatus.EXECUTION_UNKNOWN
            )
        else:
            reservations._release_locked(conn, real_reservation_id)

        # The RESOURCE side is always released: no tokens were metered, and
        # RESOURCE is not an external charge that could have happened anyway.
        reservations._release_locked(conn, resource_reservation_id)

        conn.execute(
            "UPDATE model_calls SET status = ?, error_text = ? WHERE model_call_id = ?",
            (status.value, error_text, model_call_id),
        )
        audit.record(
            conn,
            event_type=(
                "model_call_execution_unknown" if unknown else "model_call_failed"
            ),
            cell_id=cell_id,
            description=error_text,
            metadata={"model_call_id": model_call_id},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _post_cost_overrun_locked(
    conn: sqlite3.Connection,
    *,
    model_call_id: str,
    cell_id: str,
    shortfall: int,
    reserved: int,
    actual: int,
) -> None:
    """Record real money that was spent above what the reservation authorised.
    Caller holds the write transaction.

    This is the one place the kernel posts USD_REAL spend outside a
    reservation, and it needs justifying. A settlement cannot exceed its
    reservation (`reservations.settle` rejects it, which is Charter C4 doing
    its job), so when the provider's reported usage prices out above the
    worst-case estimate, `settle` is clamped to the cap. Stopping there would
    leave the ledger recording *less* real spend than the provider actually
    billed — the colony would believe it had money it does not have, and
    Charter C5's caps would be computed off an understated figure. That is
    strictly worse than the alternative.

    So the shortfall is posted directly. The charge is already incurred; the
    ledger's job at that point is to be true, not to be flattering. Charter
    C4 governs *authorisation* — whether a Cell may commit to a spend — and
    the reservation already enforced it at the only moment enforcement can
    change an outcome. Recording an external charge that has already
    happened is accounting, not authorisation.

    This can drive the Cell's cash negative, deliberately: an overdrawn Cell
    fails every subsequent `reservations.request` balance check, so it stops
    spending immediately and visibly rather than quietly continuing.
    """
    ledger._post_transaction_locked(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type="model_call_cost_overrun",
        idempotency_key=f"model_call_cost_overrun:{model_call_id}",
        description=(
            f"model call {model_call_id} cost {actual} but reserved {reserved}"
        ),
        entries=[
            EntrySpec(
                account_id=cell_cash(cell_id),
                amount_minor_units=-shortfall,
                cell_id=cell_id,
            ),
            EntrySpec(
                account_id=_EXTERNAL_EXPENSE,
                amount_minor_units=shortfall,
                cell_id=cell_id,
            ),
        ],
    )
    audit.record(
        conn,
        event_type="model_call_cost_overrun",
        cell_id=cell_id,
        description=(
            f"real charge {actual} exceeded reservation {reserved}; "
            f"posted {shortfall} outside the reservation"
        ),
        metadata={
            "model_call_id": model_call_id,
            "shortfall_minor_units": shortfall,
            "reserved_minor_units": reserved,
            "actual_minor_units": actual,
        },
    )


def _mirror_to_sim_locked(
    conn: sqlite3.Connection,
    *,
    model_call_id: str,
    cell_id: str,
    real_minor_units: int,
    multiplier: float,
) -> tuple[int, str | None]:
    """§2.4's synthetic mirror: an *independent* USD_SIM expense of the same
    shape as the real charge, funded from the Cell's own synthetic cash. It is
    explicitly not a cross-book transfer — no USD_REAL value moves, and the
    two books' conservation equations stay separate.

    A Cell that cannot fund the mirror does not fail the call: the real
    accounting is already settled and correct, and refusing to record it
    because a *synthetic* posting is unfunded would be backwards. The skip is
    recorded on the row and in the audit trail rather than passing silently.

    Caller holds the write transaction.
    """
    if multiplier == 0:
        return 0, None
    if real_minor_units == 0:
        # Nothing real was charged (a zero-priced model), so there is nothing
        # to mirror. Not a skip — an empty mirror of an empty charge.
        return 0, None
    amount = int(real_minor_units * multiplier)
    if amount <= 0:
        return 0, "mirror of a sub-unit real charge rounds to zero"

    available = ledger.get_balance(conn, cell_cash(cell_id), Book.USD_SIM)
    if amount > available:
        audit.record(
            conn,
            event_type="model_call_mirror_skipped",
            cell_id=cell_id,
            description=(
                f"USD_SIM mirror of {amount} skipped: cell holds {available}"
            ),
            metadata={"model_call_id": model_call_id, "amount": amount},
        )
        return 0, f"insufficient USD_SIM cash ({available} < {amount})"

    ledger._post_transaction_locked(
        conn,
        book=Book.USD_SIM,
        currency="USD_SIM",
        transaction_type="model_call_sim_mirror",
        idempotency_key=f"model_call_sim_mirror:{model_call_id}",
        description=f"synthetic mirror of model call {model_call_id}",
        entries=[
            EntrySpec(
                account_id=cell_cash(cell_id),
                amount_minor_units=-amount,
                cell_id=cell_id,
            ),
            EntrySpec(
                account_id=_EXTERNAL_EXPENSE,
                amount_minor_units=amount,
                cell_id=cell_id,
            ),
        ],
    )
    return amount, None


# --- Crash recovery (Charter C7; SPEC.md §4.4) ------------------------------
#
# `_handle_success` and `_handle_failure` are each one transaction, so the
# only state a crash can leave behind is the one the process was in when it
# called the provider: both reservations `reserved`, the `model_calls` row
# `reserved`, no money moved. Resolving that is a two-part job — the
# reservations are the sweeper's, and the `model_calls` row is this module's,
# because sweeper.py has no business knowing what a model call is.

_MODEL_CALL_OPERATION = "model_call"


class GatewayOperationChecker:
    """`sweeper.ExternalOperationChecker` for model-call reservations.

    `sweeper.UnknownOperationChecker` is the Phase 1 default and answers
    UNKNOWN for every reservation carrying an `external_operation_id`,
    because when it was written no external system existed to ask about. One
    exists now, and for a model call the honest answer differs by book:

    - **USD_REAL: still UNKNOWN.** An expired `reserved` USD_REAL reservation
      attached to a `model_calls` row that never left `reserved` means the
      process died somewhere between "about to call the provider" and
      "recorded what the provider said". The request may have gone out and
      been billed, and nothing in the local database can tell the two apart.
      Charter C7 is explicit that unknown external operations are reconciled,
      never auto-released, so the funds stay committed and an operator (or
      §24.1 invoice reconciliation) settles it.
    - **RESOURCE: NOT_HAPPENED**, so the funds go back. RESOURCE is an
      internal shadow price — no provider can bill it, so releasing it masks
      no double-spend. Whatever *was* metered against it is reported as
      HAPPENED instead of being discarded; the gateway's single-transaction
      success path makes that unreachable, but direct callers of
      `resource_metering.record_usage` can produce it and throwing away a
      recorded consumption would breach Amendment A6.

    Anything that is not a model call is delegated back to the Phase 1
    default rather than guessed at.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._fallback = sweeper.UnknownOperationChecker()

    def check(self, reservation: Reservation) -> sweeper.CheckResult:
        if reservation.external_operation_type != _MODEL_CALL_OPERATION:
            return self._fallback.check(reservation)
        if reservation.book != Book.RESOURCE:
            return sweeper.CheckResult(sweeper.ExternalOutcome.UNKNOWN)
        metered = resource_metering.total_minor_units(
            self._conn, reservation.reservation_id
        )
        if metered > 0:
            return sweeper.CheckResult(
                sweeper.ExternalOutcome.HAPPENED,
                actual_amount=metered,
                destination_account_id=_INFRASTRUCTURE_RESERVE,
            )
        return sweeper.CheckResult(sweeper.ExternalOutcome.NOT_HAPPENED)


def resolve_stranded_calls(conn: sqlite3.Connection) -> list[ModelCall]:
    """Bring `model_calls` rows back into agreement with their reservations.

    A row is *stranded* when it still says `reserved` but its USD_REAL
    reservation has already been resolved — which only happens if the process
    died between reserving and recording the outcome, and something (the
    sweeper, or an operator) has since resolved the reservation. Until this
    runs, `mitosis status` reports a call as in flight that provably is not.

    The row's new status is read off the reservation, since that is the only
    surviving evidence:

    - reservation `released` -> `failed`. Releasing is only ever chosen when
      the external operation definitely did not happen, so no charge exists.
    - anything else non-`reserved` -> `execution_unknown`. That covers the
      expected `execution_unknown`/`disputed` case and also `settled`/
      `partially_settled`, where money demonstrably moved but the response
      that would justify a `succeeded` row is gone. Claiming success from a
      settlement alone would invent usage figures the kernel never saw.

    Returns the rows it changed. Idempotent: a second run finds nothing.
    """
    rows = conn.execute(
        """
        SELECT m.model_call_id AS model_call_id, r.status AS reservation_status
        FROM model_calls m
        JOIN reservations r ON r.reservation_id = m.real_reservation_id
        WHERE m.status = ? AND r.status != ?
        ORDER BY m.created_at_utc
        """,
        (ModelCallStatus.RESERVED.value, ReservationStatus.RESERVED.value),
    ).fetchall()

    resolved: list[ModelCall] = []
    for row in rows:
        reservation_status = ReservationStatus(row["reservation_status"])
        status = (
            ModelCallStatus.FAILED
            if reservation_status is ReservationStatus.RELEASED
            else ModelCallStatus.EXECUTION_UNKNOWN
        )
        call = get_model_call(conn, row["model_call_id"])
        assert call is not None

        conn.execute("BEGIN IMMEDIATE")
        try:
            # `AND status = 'reserved'` re-checks inside the write lock what
            # the SELECT above saw outside it. A second sweeper running
            # concurrently would otherwise re-resolve the same row and file a
            # duplicate audit event for one crash.
            changed = conn.execute(
                "UPDATE model_calls SET status = ?, error_text = ? "
                "WHERE model_call_id = ? AND status = ?",
                (
                    status.value,
                    "resolved after crash: reservation was "
                    f"{reservation_status.value!r} while the call was still "
                    "'reserved'",
                    call.model_call_id,
                    ModelCallStatus.RESERVED.value,
                ),
            ).rowcount
            if changed == 0:
                conn.execute("COMMIT")
                continue
            audit.record(
                conn,
                event_type="model_call_stranded_resolved",
                cell_id=call.cell_id,
                description=(
                    f"model call {call.model_call_id} was 'reserved' with its "
                    f"real reservation {reservation_status.value!r}; "
                    f"resolved to {status.value!r}"
                ),
                metadata={
                    "model_call_id": call.model_call_id,
                    "reservation_status": reservation_status.value,
                    "resolved_status": status.value,
                },
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        updated = get_model_call(conn, call.model_call_id)
        assert updated is not None
        resolved.append(updated)
    return resolved


def reservation_remaining(conn: sqlite3.Connection, reservation_id: str) -> int:
    reservation = reservations.get_reservation(conn, reservation_id)
    assert reservation is not None
    return reservation.maximum_amount - resource_metering.total_minor_units(
        conn, reservation_id
    )


def _worst_case_micro_usd(provider_name: str, request: ModelRequest) -> int:
    """Upper bound on what this call can cost: a conservative over-estimate of
    the input tokens (see providers._estimate_tokens) plus the full
    `max_tokens` of output, which is the most the provider can generate."""
    input_estimate = providers._estimate_tokens(providers._request_text(request))
    return pricing.cost_micro_usd(
        provider_name,
        request.model,
        input_tokens=input_estimate,
        output_tokens=request.max_tokens,
    )


def _is_priced(provider_name: str, model: str) -> bool:
    try:
        pricing.get_price(provider_name, model)
    except pricing.UnknownModelError:
        return False
    return True


def _insert_model_call(
    conn: sqlite3.Connection,
    *,
    model_call_id: str,
    cell_id: str,
    experiment_id: str | None,
    provider: str,
    request: ModelRequest,
    cost_estimate_micro_usd: int,
    real_reservation_id: str,
    resource_reservation_id: str,
    created_at_utc: datetime,
    idempotency_key: str,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO model_calls (
                model_call_id, cell_id, experiment_id, status, provider,
                requested_model, pricing_table_version, system_prompt_hash,
                user_prompt_hash, tool_schema_hashes_json, parameters_json,
                cost_estimate_micro_usd, real_reservation_id,
                resource_reservation_id, created_at_utc, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_call_id,
                cell_id,
                experiment_id,
                ModelCallStatus.RESERVED.value,
                provider,
                request.model,
                pricing.PRICING_TABLE_VERSION,
                _sha256(request.system) if request.system is not None else None,
                _sha256(
                    json.dumps(
                        [dict(m) for m in request.messages],
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
                "[]",
                json.dumps(_request_parameters(request), sort_keys=True),
                cost_estimate_micro_usd,
                real_reservation_id,
                resource_reservation_id,
                created_at_utc.isoformat(),
                idempotency_key,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_parameters(request: ModelRequest) -> dict[str, Any]:
    """§24.1's `parameters` — request-level settings, not response data.

    `temperature` is included only when the request actually carries one:
    most genomes declare no `model_policy` yet (ADR-067), and a stored `null`
    on every historical row would read as "the provider was asked for
    temperature 0" rather than "nobody asked". Absence stays absence.
    """
    parameters: dict[str, Any] = {"max_tokens": request.max_tokens}
    if request.temperature is not None:
        parameters["temperature"] = request.temperature
    return parameters


def _row_to_model_call(row: sqlite3.Row) -> ModelCall:
    return ModelCall(
        model_call_id=row["model_call_id"],
        cell_id=row["cell_id"],
        experiment_id=row["experiment_id"],
        status=ModelCallStatus(row["status"]),
        provider=row["provider"],
        requested_model=row["requested_model"],
        resolved_model=row["resolved_model"],
        api_version=row["api_version"],
        pricing_table_version=row["pricing_table_version"],
        system_prompt_hash=row["system_prompt_hash"],
        user_prompt_hash=row["user_prompt_hash"],
        tool_schema_hashes=tuple(json.loads(row["tool_schema_hashes_json"])),
        parameters=json.loads(row["parameters_json"]),
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        latency_ms=row["latency_ms"],
        response_hash=row["response_hash"],
        stop_reason=row["stop_reason"],
        response_text=row["response_text"],
        cost_estimate_micro_usd=row["cost_estimate_micro_usd"],
        cost_actual_micro_usd=row["cost_actual_micro_usd"],
        reconciled_micro_usd=row["reconciled_micro_usd"],
        reconciled_at_utc=(
            datetime.fromisoformat(row["reconciled_at_utc"])
            if row["reconciled_at_utc"]
            else None
        ),
        reconciliation_source=row["reconciliation_source"],
        settled_minor_units=row["settled_minor_units"],
        real_reservation_id=row["real_reservation_id"],
        resource_reservation_id=row["resource_reservation_id"],
        mirror_minor_units=row["mirror_minor_units"],
        mirror_skipped_reason=row["mirror_skipped_reason"],
        error_text=row["error_text"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        idempotency_key=row["idempotency_key"],
    )


def get_model_call(conn: sqlite3.Connection, model_call_id: str) -> ModelCall | None:
    row = conn.execute(
        "SELECT * FROM model_calls WHERE model_call_id = ?", (model_call_id,)
    ).fetchone()
    return _row_to_model_call(row) if row else None


def get_model_call_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> ModelCall | None:
    row = conn.execute(
        "SELECT * FROM model_calls WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return _row_to_model_call(row) if row else None


def spend_by_provider(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Per-provider call count, token totals, and settled real spend — the
    §2.6 / §24 reporting breakdown, used by `mitosis status`."""
    rows = conn.execute(
        """
        SELECT provider,
               COUNT(*) AS calls,
               COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               COALESCE(SUM(cost_actual_micro_usd), 0) AS micro_usd,
               COALESCE(SUM(settled_minor_units), 0) AS settled_minor_units
        FROM model_calls
        GROUP BY provider
        ORDER BY provider
        """
    ).fetchall()
    return {
        r["provider"]: {
            "calls": r["calls"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "micro_usd": r["micro_usd"],
            "settled_minor_units": r["settled_minor_units"],
        }
        for r in rows
    }


def count_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM model_calls GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}
