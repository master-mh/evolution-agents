"""Model gateway (SPEC.md §24, §5, §2.4; Amendment A6; Charter C4/C5/C7/C14).

The gateway is the first code path in the kernel whose success costs real
money, so these tests lean hard on the money-correctness edges: what the
ledger records when the estimate was wrong, what happens to committed funds
when the provider fails, and whether a failure can leave money stranded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    audit,
    db,
    gateway,
    ledger,
    lifecycle,
    pricing,
    providers,
    real_spend_breaker,
    reservations,
    resource_metering,
    sweeper,
)
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import (
    Book,
    CellType,
    EntrySpec,
    ModelCallStatus,
    RealSpendLimits,
    ReservationStatus,
    ResourceType,
)

PRICED_MODEL = "claude-opus-5"


class StubProvider:
    """Priced exactly like the real Anthropic provider, but makes no network
    call — the paid provider itself is covered in test_providers.py."""

    name = "anthropic"

    def __init__(self, *, input_tokens=2000, output_tokens=1000, fail=None, unknown=False):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.fail = fail
        self.unknown = unknown
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.fail is not None:
            raise providers.ProviderCallError(self.fail, execution_unknown=self.unknown)
        return providers.ModelResponse(
            text="stub reply",
            resolved_model=request.model,
            api_version="2023-06-01",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            stop_reason="end_turn",
            latency_ms=7,
        )


def _fund(conn, cell_id, book, amount):
    ledger.post_transaction(
        conn,
        book=book,
        currency=book.value,
        transaction_type="test_funding",
        idempotency_key=f"fund:{cell_id}:{book.value}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
            EntrySpec(account_id=cell_cash(cell_id), amount_minor_units=amount),
        ],
    )


@pytest.fixture()
def cell(conn):
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=500,
            per_hour_minor_units=5_000,
            per_day_minor_units=50_000,
            per_month_minor_units=500_000,
            max_concurrent_reserved_minor_units=5_000,
            provider_limits={},
        ),
    )
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=1_000,
        book=Book.USD_REAL,
        idempotency_key="gateway-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    _fund(conn, created.cell_id, Book.USD_SIM, 1_000)
    return created


def _request(prompt="hello there", max_tokens=1000, model=PRICED_MODEL):
    return providers.ModelRequest(
        model=model,
        messages=({"role": "user", "content": prompt},),
        max_tokens=max_tokens,
    )


def _call(conn, cell, provider, *, key="k", **kwargs):
    return gateway.call_model(
        conn,
        cell_id=cell.cell_id,
        provider=provider,
        request=kwargs.pop("request", _request()),
        idempotency_key=key,
        **kwargs,
    )


def _invariants_hold(conn):
    return (
        all(ledger.verify_conservation(conn, book) for book in Book)
        and ledger.verify_chain(conn)
        and resource_metering.verify_linkage(conn)
    )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_successful_call_settles_the_true_provider_cost(conn, cell):
    call = _call(conn, cell, StubProvider())
    assert call.status is ModelCallStatus.SUCCEEDED
    assert call.cost_actual_micro_usd == 2000 * 5 + 1000 * 25
    assert call.settled_minor_units == pricing.micro_usd_to_minor_units(35_000)
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 4
    assert _invariants_hold(conn)


def test_over_reservation_is_released_not_stranded_in_committed(conn, cell):
    """The gateway reserves the worst case; without an explicit release of the
    remainder the difference would sit in committed forever, quietly draining
    the Cell's spendable cash and ratcheting the C5 concurrent-reserved cap
    down on every call."""
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    call = _call(conn, cell, StubProvider())
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0
    assert (
        ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
        == before - call.settled_minor_units
    )
    assert real_spend_breaker.snapshot(conn).concurrent_reserved_minor_units == 0


def test_repeated_calls_do_not_ratchet_the_concurrent_reserved_cap(conn, cell):
    for i in range(5):
        _call(conn, cell, StubProvider(), key=f"k{i}")
    assert real_spend_breaker.snapshot(conn).concurrent_reserved_minor_units == 0
    assert _invariants_hold(conn)


def test_records_the_required_call_metadata(conn, cell):
    """SPEC.md §24.1's field list."""
    call = _call(conn, cell, StubProvider())
    assert call.provider == "anthropic"
    assert call.requested_model == PRICED_MODEL
    assert call.resolved_model == PRICED_MODEL
    assert call.api_version == "2023-06-01"
    assert call.pricing_table_version == pricing.PRICING_TABLE_VERSION
    assert call.user_prompt_hash and len(call.user_prompt_hash) == 64
    assert call.response_hash and len(call.response_hash) == 64
    assert call.parameters == {"max_tokens": 1000}
    assert call.input_tokens == 2000 and call.output_tokens == 1000
    assert call.latency_ms == 7
    assert call.stop_reason == "end_turn"
    assert call.cost_estimate_micro_usd > 0
    # §24.1's `reconciled cost` — no provider invoice exists to reconcile
    # against in this kernel, so it stays None by design.
    assert call.reconciled_micro_usd is None


def test_system_prompt_hash_recorded_only_when_a_system_prompt_is_sent(conn, cell):
    without = _call(conn, cell, StubProvider(), key="a")
    assert without.system_prompt_hash is None
    with_system = _call(
        conn,
        cell,
        StubProvider(),
        key="b",
        request=providers.ModelRequest(
            model=PRICED_MODEL,
            messages=({"role": "user", "content": "hi"},),
            max_tokens=100,
            system="be terse",
        ),
    )
    assert with_system.system_prompt_hash is not None


def test_is_idempotent_and_does_not_pay_twice(conn, cell):
    provider = StubProvider()
    first = _call(conn, cell, provider, key="same")
    second = _call(conn, cell, provider, key="same")
    assert first.model_call_id == second.model_call_id
    assert provider.calls == 1, "a replayed idempotency key must not re-bill"
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 4


# --------------------------------------------------------------------------
# Amendment A6 — resource metering
# --------------------------------------------------------------------------


def test_meters_input_and_output_tokens_against_one_reservation(conn, cell):
    call = _call(conn, cell, StubProvider())
    usage = resource_metering.usage_by_type(conn, call.resource_reservation_id)
    assert usage == {"input_tokens": 2000, "output_tokens": 1000}
    assert resource_metering.verify_linkage(conn)


def test_metering_survives_a_zero_priced_model(conn, cell):
    """A free model still consumes tokens, and A6's completeness invariant has
    no exemption for cheap calls — this used to silently drop the output-token
    row because the shadow price rounded to zero."""
    call = gateway.call_model(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(),
        request=_request(model="mock-1"),
        idempotency_key="free",
    )
    usage = resource_metering.usage_by_type(conn, call.resource_reservation_id)
    assert set(usage) == {"input_tokens", "output_tokens"}
    assert resource_metering.verify_linkage(conn)


def test_resource_reservation_failure_returns_the_real_money(conn, cell):
    """The RESOURCE leg is reserved second; if it fails there will be no call,
    so the USD_REAL leg must not stay committed."""
    lifecycle.create_cell  # noqa: B018 - readability anchor
    broke = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=500,
        book=Book.USD_REAL,
        idempotency_key="no-resource-budget",
    )
    with pytest.raises(reservations.InsufficientBalanceError):
        gateway.call_model(
            conn,
            cell_id=broke.cell_id,
            provider=StubProvider(),
            request=_request(),
            idempotency_key="k",
        )
    assert ledger.get_balance(conn, cell_committed(broke.cell_id), Book.USD_REAL) == 0
    assert ledger.get_balance(conn, cell_cash(broke.cell_id), Book.USD_REAL) == 500
    assert _invariants_hold(conn)


# --------------------------------------------------------------------------
# Failure paths — where the money is
# --------------------------------------------------------------------------


def test_definitely_unbilled_failure_releases_the_reservation(conn, cell):
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    call = _call(conn, cell, StubProvider(fail="BadRequestError: bad", unknown=False))
    assert call.status is ModelCallStatus.FAILED
    assert (
        reservations.get_reservation(conn, call.real_reservation_id).status
        is ReservationStatus.RELEASED
    )
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == before
    assert _invariants_hold(conn)


def test_possibly_billed_failure_holds_the_funds_as_execution_unknown(conn, cell):
    """Charter C7 / §4.4: a timeout may have been billed, so releasing would
    silently lose real money. The funds stay committed until reconciliation."""
    call = _call(conn, cell, StubProvider(fail="APITimeoutError: slow", unknown=True))
    assert call.status is ModelCallStatus.EXECUTION_UNKNOWN
    assert (
        reservations.get_reservation(conn, call.real_reservation_id).status
        is ReservationStatus.EXECUTION_UNKNOWN
    )
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) > 0
    assert _invariants_hold(conn)


def test_failure_always_releases_the_resource_reservation(conn, cell):
    """No tokens were metered and RESOURCE is not an external charge that
    could have happened anyway — it is released on both failure kinds."""
    for key, unknown in (("clean", False), ("unknown", True)):
        call = _call(
            conn, cell, StubProvider(fail="boom", unknown=unknown), key=key
        )
        assert (
            reservations.get_reservation(conn, call.resource_reservation_id).status
            is ReservationStatus.RELEASED
        )


def test_provider_error_text_is_redacted_before_it_is_stored(conn, cell):
    """Charter C14: an SDK exception message is the realistic leak path."""
    call = _call(
        conn,
        cell,
        StubProvider(fail="AuthenticationError: sk-ant-api03-SECRETSECRETSECRET"),
    )
    assert "sk-ant-api03-SECRETSECRETSECRET" not in (call.error_text or "")
    assert "[redacted]" in call.error_text
    stored = conn.execute("SELECT error_text FROM model_calls").fetchone()["error_text"]
    assert "SECRETSECRETSECRET" not in stored


# --------------------------------------------------------------------------
# Cost overrun — the ledger must be true, not flattering
# --------------------------------------------------------------------------


def test_cost_above_the_reservation_is_still_recorded_in_full(conn, cell):
    """`settle` clamps at the reservation cap (Charter C4 doing its job), but
    the charge was really incurred. Stopping at the clamp would have the
    ledger understate real spend, which is strictly worse — C5's caps would
    then be computed off a number that is too small."""
    provider = StubProvider(input_tokens=200_000, output_tokens=1_000)
    call = _call(conn, cell, provider)
    true_cost = pricing.micro_usd_to_minor_units(200_000 * 5 + 1_000 * 25)
    reservation = reservations.get_reservation(conn, call.real_reservation_id)
    assert true_cost > reservation.maximum_amount, "test must actually overrun"
    assert call.settled_minor_units == true_cost
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == true_cost
    assert _invariants_hold(conn)


def test_cost_overrun_is_audited_loudly(conn, cell):
    _call(conn, cell, StubProvider(input_tokens=200_000, output_tokens=1_000))
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM audit_events WHERE event_type = 'model_call_cost_overrun'"
    ).fetchone()
    assert rows["n"] == 1


def test_an_overdrawn_cell_stops_spending(conn, cell):
    """An overrun can drive cash negative. That is deliberate: the next
    reservation's balance check then fails closed."""
    # Sized to overdraw the Cell's 1,000 minor units without also tripping the
    # colony-wide hour cap, so this test isolates the per-Cell guard.
    _call(conn, cell, StubProvider(input_tokens=2_000_000, output_tokens=1_000))
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) < 0
    with pytest.raises(reservations.InsufficientBalanceError):
        _call(conn, cell, StubProvider(), key="after")


def test_overrun_spend_counts_against_the_global_caps(conn, cell):
    """Charter C5. An overrun is real money leaving the colony but is not a
    reservation settlement, so a breaker that only sums settlements cannot see
    it — and would go blind exactly when a provider is billing above estimate.
    """
    before = real_spend_breaker.snapshot(conn).spend_last_hour_minor_units
    call = _call(conn, cell, StubProvider(input_tokens=200_000, output_tokens=1_000))
    after = real_spend_breaker.snapshot(conn).spend_last_hour_minor_units
    assert after - before == call.settled_minor_units


def test_overrun_spend_counts_against_the_per_provider_cap(conn, cell):
    limits = real_spend_breaker.get_limits(conn)
    real_spend_breaker.set_limits(
        conn, limits.model_copy(update={"provider_limits": {"anthropic": 10_000}})
    )
    call = _call(conn, cell, StubProvider(input_tokens=200_000, output_tokens=1_000))
    assert real_spend_breaker.provider_exposure(conn, "anthropic") == call.settled_minor_units


# --------------------------------------------------------------------------
# §2.4 — the USD_SIM mirror
# --------------------------------------------------------------------------


def test_mirror_is_an_independent_sim_expense_not_a_cross_book_transfer(conn, cell):
    real_before = ledger.get_balance(conn, "external_expense", Book.USD_REAL)
    call = _call(conn, cell, StubProvider())
    assert call.mirror_minor_units == call.settled_minor_units
    assert ledger.get_balance(conn, "external_expense", Book.USD_SIM) == call.mirror_minor_units
    # The real book saw only the real charge — no synthetic value crossed in.
    assert (
        ledger.get_balance(conn, "external_expense", Book.USD_REAL) - real_before
        == call.settled_minor_units
    )
    assert all(ledger.verify_conservation(conn, book) for book in Book)


def test_mirror_multiplier_scales_the_synthetic_charge(conn, cell):
    call = _call(conn, cell, StubProvider(), mirror_multiplier=3.0)
    assert call.mirror_minor_units == call.settled_minor_units * 3


def test_mirror_can_be_disabled(conn, cell):
    call = _call(conn, cell, StubProvider(), mirror_multiplier=0.0)
    assert call.mirror_minor_units == 0
    assert call.mirror_skipped_reason is None
    assert ledger.get_balance(conn, "external_expense", Book.USD_SIM) == 0


def test_unfunded_mirror_is_skipped_without_failing_the_real_accounting(conn, cell):
    """The real charge is already settled and correct; refusing to record it
    because a *synthetic* posting is unfunded would be backwards."""
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD_SIM",
        transaction_type="drain",
        idempotency_key="drain-sim",
        entries=[
            EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=-1_000),
            EntrySpec(account_id="colony_treasury", amount_minor_units=1_000),
        ],
    )
    call = _call(conn, cell, StubProvider())
    assert call.status is ModelCallStatus.SUCCEEDED
    assert call.mirror_minor_units == 0
    assert "insufficient USD_SIM" in call.mirror_skipped_reason
    assert call.settled_minor_units == 4
    assert _invariants_hold(conn)


# --------------------------------------------------------------------------
# Caps and validation
# --------------------------------------------------------------------------


def test_per_provider_cap_is_enforced(conn, cell):
    """§5.1's "max real spend per provider", stored-but-unenforced until now."""
    limits = real_spend_breaker.get_limits(conn)
    real_spend_breaker.set_limits(
        conn, limits.model_copy(update={"provider_limits": {"anthropic": 1}})
    )
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="provider cap"):
        _call(conn, cell, StubProvider())
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == 0


def test_per_provider_cap_counts_settled_spend_too(conn, cell):
    """§5.3's settled+reserved basis, per provider: many small calls must not
    collectively exceed a cap that each individually respects."""
    limits = real_spend_breaker.get_limits(conn)
    real_spend_breaker.set_limits(
        conn, limits.model_copy(update={"provider_limits": {"anthropic": 9}})
    )
    for i in range(2):
        _call(conn, cell, StubProvider(), key=f"c{i}")
    assert real_spend_breaker.provider_exposure(conn, "anthropic") == 8
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="provider cap"):
        _call(conn, cell, StubProvider(), key="third")


def test_an_uncapped_provider_still_faces_the_global_caps(conn, cell):
    limits = real_spend_breaker.get_limits(conn)
    real_spend_breaker.set_limits(
        conn, limits.model_copy(update={"per_request_minor_units": 1})
    )
    with pytest.raises(real_spend_breaker.RealSpendCapExceededError, match="per-request"):
        _call(conn, cell, StubProvider())


def test_only_gateway_reservations_carry_a_provider_tag(conn, cell):
    call = _call(conn, cell, StubProvider())
    tagged = reservations.get_reservation(conn, call.real_reservation_id)
    assert tagged.provider == "anthropic"
    # The RESOURCE leg is not real spend, so it is not part of the §5.1 cap.
    assert reservations.get_reservation(conn, call.resource_reservation_id).provider is None


def test_unpriced_model_is_refused_before_any_reservation_or_call(conn, cell):
    provider = StubProvider()
    with pytest.raises(pricing.UnknownModelError):
        _call(conn, cell, provider, request=_request(model="gpt-4"))
    assert provider.calls == 0
    assert reservations.count_by_status(conn) == {}
    assert conn.execute("SELECT COUNT(*) AS n FROM model_calls").fetchone()["n"] == 0


def test_rejects_non_positive_max_tokens_and_negative_mirror(conn, cell):
    with pytest.raises(gateway.GatewayError):
        _call(conn, cell, StubProvider(), request=_request(max_tokens=0))
    with pytest.raises(gateway.GatewayError):
        _call(conn, cell, StubProvider(), mirror_multiplier=-1.0)


def test_reporting_breakdown(conn, cell):
    _call(conn, cell, StubProvider(), key="a")
    _call(conn, cell, StubProvider(fail="BadRequestError: x"), key="b")
    assert gateway.count_by_status(conn) == {"succeeded": 1, "failed": 1}
    stats = gateway.spend_by_provider(conn)["anthropic"]
    assert stats["calls"] == 2
    assert stats["input_tokens"] == 2000
    assert stats["settled_minor_units"] == 4


def test_a_substituted_model_prices_both_books_the_same_way(conn, cell):
    """§24.2: a provider may serve a different model than was requested. The
    USD_REAL charge and the RESOURCE shadow price must be derived from the
    same model, or the two books disagree about what one call cost."""

    class _Substituting(StubProvider):
        def complete(self, request):
            response = super().complete(request)
            return response.model_copy(update={"resolved_model": "claude-haiku-4-5"})

    call = _call(conn, cell, _Substituting())
    # Haiku rates ($1/$5 per MTok), not the requested Opus rates.
    assert call.resolved_model == "claude-haiku-4-5"
    assert call.cost_actual_micro_usd == 2000 * 1 + 1000 * 5
    usage = {
        row["resource_type"]: row["minor_units"]
        for row in conn.execute("SELECT * FROM resource_usage")
    }
    assert usage == {"input_tokens": 2000 * 1, "output_tokens": 1000 * 5}


# --------------------------------------------------------------------------
# Crash atomicity (Charter C7) — the success path is all-or-nothing
# --------------------------------------------------------------------------
#
# `_handle_success` resolves two reservations, meters two token types,
# mirrors into USD_SIM and marks the `model_calls` row. Charter C7 makes each
# of those individually crash-atomic; these tests cover their *composition*,
# which it does not.
#
# The injected failure derives from BaseException so the gateway's own
# `except Exception: ROLLBACK` never runs — otherwise this would test the
# cleanup handler rather than a crash. The connection is then closed with the
# transaction still open, and SQLite rolls it back on reopen exactly as it
# would after the process died.


class SimulatedCrash(BaseException):
    pass


def _crash_at(monkeypatch, target_module, attribute):
    def boom(*args, **kwargs):
        raise SimulatedCrash(f"crash at {attribute}")

    monkeypatch.setattr(target_module, attribute, boom)


@pytest.fixture()
def file_colony(tmp_path):
    """A file-backed colony, because a crash test has to survive closing and
    reopening the database — an in-memory one dies with the connection."""
    path = str(tmp_path / "crash.db")

    def open_conn():
        return db.connect_and_migrate(path)

    conn = open_conn()
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=500,
            per_hour_minor_units=5_000,
            per_day_minor_units=50_000,
            per_month_minor_units=500_000,
            max_concurrent_reserved_minor_units=5_000,
            provider_limits={},
        ),
    )
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=1_000,
        book=Book.USD_REAL,
        idempotency_key="crash-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    _fund(conn, created.cell_id, Book.USD_SIM, 1_000)
    conn.close()
    return open_conn, created


def _crash_during_call(open_conn, cell, monkeypatch, module, attribute):
    """Run one call that dies partway through `_handle_success`, then reopen
    the database the way a restarted process would."""
    conn = open_conn()
    _crash_at(monkeypatch, module, attribute)
    with pytest.raises(SimulatedCrash):
        gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=StubProvider(),
            request=_request(),
            idempotency_key="crash-key",
        )
    conn.close()  # process death: no COMMIT, no ROLLBACK
    monkeypatch.undo()
    return open_conn()


@pytest.mark.parametrize(
    ("module", "attribute"),
    [
        # Each fires strictly inside `_handle_success`'s transaction, after
        # the USD_REAL settlement has already been written to it. `_sha256`
        # would look like a fourth option but runs before the call too, in
        # `_insert_model_call`, so a crash there proves nothing.
        (resource_metering, "_record_usage_locked"),
        (gateway, "_mirror_to_sim_locked"),
        (audit, "record"),
    ],
    ids=["during-metering", "during-mirror", "during-final-audit"],
)
def test_charter_crash_recovery_gateway_leaves_no_money_half_moved(
    file_colony, monkeypatch, module, attribute
):
    """Charter C7, extended from one reservation to the gateway's composition
    of several: a crash anywhere after the provider replies must roll back to
    the pre-call state, never to a state where some of the six steps landed.

    Conservation and the hash chain are deliberately *not* the assertion
    here. They stayed green through the pre-fix bug — a settled reservation
    with an unrecorded call balances perfectly — which is exactly why this
    needed its own test.
    """
    open_conn, cell = file_colony
    conn = _crash_during_call(open_conn, cell, monkeypatch, module, attribute)

    # Reserving before executing is the point, so the two reservations are
    # committed and their funds sit in `committed`. Nothing after that ran.
    assert reservations.count_by_status(conn) == {"reserved": 2}
    assert gateway.count_by_status(conn) == {"reserved": 1}
    assert ledger.get_balance(conn, "external_expense", Book.USD_REAL) == 0
    assert ledger.get_balance(conn, "external_expense", Book.USD_SIM) == 0
    assert ledger.get_balance(conn, "infrastructure_reserve", Book.RESOURCE) == 0
    assert resource_metering.count(conn) == 0
    assert _invariants_hold(conn)
    conn.close()


def test_charter_crash_recovery_gateway_sweeps_to_execution_unknown(
    file_colony, monkeypatch
):
    """The recovery half: a crashed call resolves to `execution_unknown` with
    its real money still committed (Charter C7 forbids auto-releasing an
    external operation whose outcome is unknown), while the RESOURCE leg —
    which no provider can bill — goes back to the Cell."""
    open_conn, cell = file_colony
    conn = _crash_during_call(
        open_conn, cell, monkeypatch, gateway, "_mirror_to_sim_locked"
    )

    real_cash_before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    committed_before = ledger.get_balance(
        conn, cell_committed(cell.cell_id), Book.USD_REAL
    )
    assert committed_before > 0

    swept = sweeper.sweep(
        conn,
        now=datetime.now(timezone.utc) + timedelta(hours=1),
        checker=gateway.GatewayOperationChecker(conn),
    )
    outcomes = {r.book: r.status for r in swept}
    assert outcomes[Book.USD_REAL] is ReservationStatus.EXECUTION_UNKNOWN
    assert outcomes[Book.RESOURCE] is ReservationStatus.RELEASED

    # Real money stays committed; the resource budget comes back.
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == real_cash_before
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.USD_REAL) == committed_before
    assert ledger.get_balance(conn, cell_committed(cell.cell_id), Book.RESOURCE) == 0

    resolved = gateway.resolve_stranded_calls(conn)
    assert [c.status for c in resolved] == [ModelCallStatus.EXECUTION_UNKNOWN]
    assert gateway.count_by_status(conn) == {"execution_unknown": 1}
    assert gateway.resolve_stranded_calls(conn) == []  # idempotent
    assert _invariants_hold(conn)
    conn.close()


def test_resolve_stranded_calls_reads_the_status_off_the_reservation(conn, cell):
    """A released reservation means the operation definitely did not happen,
    so the call is `failed`; anything else non-`reserved` is
    `execution_unknown`, because a settlement without a recorded response
    cannot honestly be called a success."""
    call = _call(conn, cell, StubProvider())
    conn.execute(
        "UPDATE model_calls SET status = 'reserved' WHERE model_call_id = ?",
        (call.model_call_id,),
    )

    for reservation_status, expected in (
        (ReservationStatus.RELEASED, ModelCallStatus.FAILED),
        (ReservationStatus.EXECUTION_UNKNOWN, ModelCallStatus.EXECUTION_UNKNOWN),
        (ReservationStatus.SETTLED, ModelCallStatus.EXECUTION_UNKNOWN),
        (ReservationStatus.DISPUTED, ModelCallStatus.EXECUTION_UNKNOWN),
    ):
        conn.execute(
            "UPDATE model_calls SET status = 'reserved' WHERE model_call_id = ?",
            (call.model_call_id,),
        )
        conn.execute(
            "UPDATE reservations SET status = ? WHERE reservation_id = ?",
            (reservation_status.value, call.real_reservation_id),
        )
        assert [c.status for c in gateway.resolve_stranded_calls(conn)] == [expected]


def test_resolve_stranded_calls_leaves_a_genuinely_in_flight_call_alone(conn, cell):
    """A `reserved` call whose reservation is still `reserved` is in flight,
    not stranded — resolving it would kill a live call."""

    class _Slow(StubProvider):
        def complete(self, request):
            assert gateway.resolve_stranded_calls(self.conn) == []
            return super().complete(request)

    provider = _Slow()
    provider.conn = conn
    call = _call(conn, cell, provider)
    assert call.status is ModelCallStatus.SUCCEEDED


def test_gateway_checker_defers_to_the_phase_1_default_for_other_operations(conn, cell):
    """Nothing but a model call is guessed at: the gateway checker hands any
    other external operation back to `UnknownOperationChecker`."""
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_REAL,
        currency="USD",
        maximum_amount=10,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        idempotency_key="not-a-model-call",
        external_operation_type="sandbox_run",
        external_operation_id="op-1",
    )
    result = gateway.GatewayOperationChecker(conn).check(reservation)
    assert result.outcome is sweeper.ExternalOutcome.UNKNOWN


def test_gateway_checker_reports_metered_resource_usage_rather_than_discarding_it(
    conn, cell
):
    """Amendment A6: usage recorded against a RESOURCE reservation must reach
    a settlement. If a sweep finds one with rows already on it, those are
    settled, not released away."""
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.RESOURCE,
        currency="RESOURCE",
        maximum_amount=100,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        idempotency_key="resource-with-usage",
        external_operation_type="model_call",
        external_operation_id="mc-1",
    )
    resource_metering.record_usage(
        conn,
        cell_id=cell.cell_id,
        reservation_id=reservation.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS,
        quantity=40,
        minor_units=40,
        idempotency_key="usage-1",
    )
    result = gateway.GatewayOperationChecker(conn).check(reservation)
    assert result.outcome is sweeper.ExternalOutcome.HAPPENED
    assert result.actual_amount == 40
    assert result.destination_account_id == "infrastructure_reserve"


def test_failure_path_is_atomic_too(file_colony, monkeypatch):
    """`_handle_failure` resolves both reservations and marks the row; a crash
    between them would leave the call claiming to be in flight while its
    reservations say otherwise.

    Crashing on the *resource* release means the USD_REAL leg has already
    been moved to `execution_unknown` inside the transaction — so the
    rollback has something real to undo.
    """
    open_conn, cell = file_colony
    conn = open_conn()
    _crash_at(monkeypatch, reservations, "_release_locked")
    with pytest.raises(SimulatedCrash):
        gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=StubProvider(fail="TimeoutError: gone", unknown=True),
            request=_request(),
            idempotency_key="crash-fail",
        )
    conn.close()
    monkeypatch.undo()

    conn = open_conn()
    assert reservations.count_by_status(conn) == {"reserved": 2}
    assert gateway.count_by_status(conn) == {"reserved": 1}
    assert _invariants_hold(conn)
    conn.close()
