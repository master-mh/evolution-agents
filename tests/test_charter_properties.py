"""Charter property tests (docs/DECISIONS.md ADR-013; SPEC.md §0.1).

Maps to named Charter test IDs (function/TestCase names below are chosen so
each ID is a literal substring of its node id, i.e. `pytest -k <id>` finds
it — see SPEC.md §0.1: "every clause maps to one or more named property-test
IDs that run in CI"):
  charter_ledger_balanced            -> C1
  charter_conservation_per_book      -> C2
  charter_balance_matches_ledger     -> C3
  charter_no_overspend                -> C4 (RESOURCE-book usage never exceeds its reservation
                                              cap; a reservation can never exceed a Cell's cash)
  charter_realspend_cap              -> C5 (concurrent-reserved cap vs configured limit)
  charter_idempotent_handlers        -> C6 (event redelivery applies handler side effects once)
  charter_crash_recovery             -> C7 (reservation FSM stateful machine)
  charter_dead_cell_inert            -> C8 (dead Cells reject every further transition)
  charter_carrying_capacity          -> C9 (birth licence vs configured limits; and via
                                              `_lineage_share`, §9.2's max population share
                                              descended from one ancestor, on the reproduce path)
  charter_audit_complete             -> C10 (every lifecycle transition emits an audit event)
  charter_canonical_forms            -> C11 (money/genome/timestamps: canonical by construction)
  charter_kernel_immutable           -> C15 (P1 slice: genome content is inert data, never code —
                                              full sandbox isolation is Phase 5, see C12)
"""

from __future__ import annotations

import importlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, precondition, rule

import mitosis
from mitosis import db, events, genome, ledger, lifecycle, lineage, money, population, real_spend_breaker, reservations, resource_metering
from mitosis.accounts import cell_cash, cell_committed
from mitosis.models import (
    Book,
    CellStatus,
    CellType,
    EntrySpec,
    ResourceType,
    PopulationLimits,
    RealSpendLimits,
    ReservationStatus,
)

FUTURE = datetime.now(timezone.utc) + timedelta(days=365)


# --- charter_ledger_balanced (C1) -------------------------------------------


@given(a=st.integers(min_value=-10_000, max_value=10_000).filter(lambda x: x != 0))
def test_charter_ledger_balanced(a):
    conn = db.connect_and_migrate()
    txn = ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="t",
        idempotency_key=f"k:{a}",
        entries=[
            EntrySpec(account_id="x", amount_minor_units=-a),
            EntrySpec(account_id="y", amount_minor_units=a),
        ],
    )
    assert sum(e.amount_minor_units for e in txn.entries) == 0


@given(
    a=st.integers(min_value=1, max_value=10_000),
    b=st.integers(min_value=1, max_value=10_000),
)
def test_charter_ledger_rejects_unbalanced(a, b):
    if a == b:
        return
    conn = db.connect_and_migrate()
    try:
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="t",
            idempotency_key=f"k:{a}:{b}",
            entries=[
                EntrySpec(account_id="x", amount_minor_units=-a),
                EntrySpec(account_id="y", amount_minor_units=b),
            ],
        )
        raise AssertionError("unbalanced transaction should have been rejected")
    except ledger.UnbalancedTransactionError:
        pass


# --- charter_conservation_per_book (C2) & charter_balance_matches_ledger (C3) --


@given(amounts=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20))
@settings(max_examples=50)
def test_charter_conservation_per_book_and_charter_balance_matches_ledger(amounts):
    conn = db.connect_and_migrate()
    for i, amount in enumerate(amounts):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="t",
            idempotency_key=f"k:{i}",
            entries=[
                EntrySpec(account_id="source", amount_minor_units=-amount),
                EntrySpec(account_id="dest", amount_minor_units=amount),
            ],
        )
    assert ledger.verify_conservation(conn, Book.USD_SIM) is True
    assert ledger.get_balance(conn, "source", Book.USD_SIM) == -sum(amounts)
    assert ledger.get_balance(conn, "dest", Book.USD_SIM) == sum(amounts)


# --- charter_crash_recovery (C7) --------------------------------------------
# A reservation stuck in execution_unknown after a simulated crash must never
# be silently released, and conservation must hold under any interleaving of
# request / settle / release / crash / reconcile.


@settings(max_examples=30, stateful_step_count=25)
class ReservationKernelMachine(RuleBasedStateMachine):
    reservation_ids = Bundle("reservation_ids")

    def __init__(self):
        super().__init__()
        self.conn = db.connect_and_migrate()
        self.status: dict[str, ReservationStatus] = {}
        self._next_id = 0
        ledger.post_transaction(
            self.conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="seed",
            idempotency_key="seed",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-1_000_000),
                EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=1_000_000),
            ],
        )

    def _fresh_key(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}:{self._next_id}"

    @rule(target=reservation_ids, amount=st.integers(min_value=1, max_value=1000))
    def request(self, amount):
        r = reservations.request(
            self.conn,
            cell_id="cell-1",
            book=Book.USD_SIM,
            currency="USD",
            maximum_amount=amount,
            expires_at=FUTURE,
            idempotency_key=self._fresh_key("req"),
        )
        self.status[r.reservation_id] = r.status
        return r.reservation_id

    @precondition(lambda self: ReservationStatus.RESERVED in self.status.values())
    @rule(reservation_id=reservation_ids, fraction=st.integers(min_value=0, max_value=100))
    def settle_or_release(self, reservation_id, fraction):
        if self.status.get(reservation_id) != ReservationStatus.RESERVED:
            return
        r = reservations.get_reservation(self.conn, reservation_id)
        settle_amount = (r.maximum_amount * fraction) // 100
        if settle_amount == 0:
            result = reservations.release(self.conn, reservation_id)
        else:
            result = reservations.settle(
                self.conn,
                reservation_id,
                settled_amount=settle_amount,
                destination_account_id="external_expense",
            )
            if result.status == ReservationStatus.PARTIALLY_SETTLED:
                result = reservations.release(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @precondition(lambda self: ReservationStatus.RESERVED in self.status.values())
    @rule(reservation_id=reservation_ids)
    def crash_before_resolution(self, reservation_id):
        """Simulates a crash/timeout: the reservation can neither be
        confirmed executed nor confirmed unexecuted at this point."""
        if self.status.get(reservation_id) != ReservationStatus.RESERVED:
            return
        result = reservations.mark_execution_unknown(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @precondition(lambda self: ReservationStatus.EXECUTION_UNKNOWN in self.status.values())
    @rule(reservation_id=reservation_ids)
    def reconcile_unknown(self, reservation_id):
        if self.status.get(reservation_id) != ReservationStatus.EXECUTION_UNKNOWN:
            return
        result = reservations.release(self.conn, reservation_id)
        self.status[reservation_id] = result.status

    @invariant()
    def conservation_and_chain_hold(self):
        assert ledger.verify_conservation(self.conn, Book.USD_SIM) is True
        assert ledger.verify_chain(self.conn) is True

    @invariant()
    def committed_balance_matches_open_reservations(self):
        open_committed = 0
        for reservation_id, status in self.status.items():
            if status in (ReservationStatus.RELEASED, ReservationStatus.SETTLED):
                continue
            r = reservations.get_reservation(self.conn, reservation_id)
            open_committed += r.maximum_amount - r.settled_amount
        actual = ledger.get_balance(self.conn, cell_committed("cell-1"), Book.USD_SIM)
        assert actual == open_committed

    @invariant()
    def cell_cash_never_negative(self):
        """Charter C4: request() never lets committed reservations exceed
        what was ever in the cell's cash account."""
        assert ledger.get_balance(self.conn, cell_cash("cell-1"), Book.USD_SIM) >= 0

    def teardown(self):
        self.conn.close()


Test_charter_crash_recovery = ReservationKernelMachine.TestCase


# --- charter_carrying_capacity (C9) -----------------------------------------
# For any configured limit and any number of attempted births, the living
# and active Cell counts must never exceed their configured caps — every
# birth beyond capacity must be denied, never silently admitted.


@given(
    max_living=st.integers(min_value=1, max_value=10),
    attempts=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=50)
def test_charter_carrying_capacity(max_living, attempts):
    conn = db.connect_and_migrate()
    limits = PopulationLimits(
        max_living_cells=max_living,
        max_active_cells=max_living,  # active cap not the binding constraint here
        max_parallel_experiments=1,
        max_births_per_epoch=1,
        max_lineage_population_fraction=1.0,
    )
    population.set_limits_if_absent(conn, limits)

    granted = 0
    for i in range(attempts):
        try:
            lifecycle.create_cell(
                conn,
                cell_type=CellType.EXPLORER,
                budget_minor_units=10,
                book=Book.USD_SIM,
                idempotency_key=f"attempt:{i}",
            )
            granted += 1
        except population.CarryingCapacityError:
            pass
        # the invariant must hold after every single attempt, not just at the end
        assert population.living_count(conn) <= max_living

    assert granted == min(attempts, max_living)
    assert population.living_count(conn) == granted


# C9 again, via the *other* birth path: §9.2 counts "maximum population share
# descended from one ancestor" among the colony's carrying-capacity limits, so
# reproduction is subject to a birth licence exactly as seeded birth is. For
# any cap and any number of attempted reproductions, no lineage may end up
# holding more than its configured share of the living population.


@given(
    cap=st.sampled_from([0.2, 0.34, 0.5, 0.75, 1.0]),
    attempts=st.integers(min_value=0, max_value=12),
    founders=st.integers(min_value=1, max_value=6),
)
@settings(max_examples=50, deadline=None)
def test_charter_carrying_capacity_lineage_share(cap, attempts, founders):
    # The cap governs *descent*, so it can only bind once the seeded founders
    # alone are within it: a single founder is trivially 100% of a one-Cell
    # colony, and no birth licence can undo that (a founder has no ancestor).
    # test_seeded_founders_are_not_subject_to_the_lineage_cap pins that case.
    assume(1 / founders <= cap)

    conn = db.connect_and_migrate()
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=100,
            max_active_cells=100,
            max_parallel_experiments=1,
            max_births_per_epoch=1,
            max_lineage_population_fraction=cap,
        ),
    )
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="seed",
        idempotency_key="seed",
        description="seed",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-1_000_000),
            EntrySpec(account_id="seed_bank", amount_minor_units=1_000_000),
        ],
    )
    seeded = [
        lifecycle.create_cell(
            conn,
            cell_type=CellType.EXPLORER,
            budget_minor_units=100_000,
            book=Book.USD_SIM,
            idempotency_key=f"founder:{i}",
        )
        for i in range(founders)
    ]
    parent = seeded[0]

    for i in range(attempts):
        try:
            lineage.reproduce(
                conn,
                parent_cell_id=parent.cell_id,
                budget_minor_units=10,
                idempotency_key=f"child:{i}",
            )
        except lineage.LineageCapExceededError:
            pass

        # Must hold after every attempt, granted or denied — and for every
        # lineage in the colony, not just the one being grown.
        for entry in lineage.lineage_summary(conn):
            assert entry["fraction"] <= cap
        assert lineage.verify_lineage_integrity(conn) is True


# --- charter_realspend_cap (C5) ---------------------------------------------
# For any configured max_concurrent_reserved cap and any sequence of USD_REAL
# reservation requests, concurrently reserved spend must never exceed the
# cap after any single request — granted or denied.


@given(
    cap=st.integers(min_value=10, max_value=200),
    amounts=st.lists(st.integers(min_value=1, max_value=100), min_size=0, max_size=15),
)
@settings(max_examples=50)
def test_charter_realspend_cap(cap, amounts):
    conn = db.connect_and_migrate()
    ledger.post_transaction(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type="seed_fund",
        idempotency_key="seed",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-1_000_000),
            EntrySpec(account_id=cell_cash("cell-1"), amount_minor_units=1_000_000),
        ],
    )
    limits = RealSpendLimits(
        per_request_minor_units=1_000_000,  # not the constraint under test
        per_hour_minor_units=1_000_000,
        per_day_minor_units=1_000_000,
        per_month_minor_units=1_000_000,
        max_concurrent_reserved_minor_units=cap,
        provider_limits={},
    )
    real_spend_breaker.set_limits(conn, limits)

    for i, amount in enumerate(amounts):
        try:
            reservations.request(
                conn,
                cell_id="cell-1",
                book=Book.USD_REAL,
                currency="USD",
                maximum_amount=amount,
                expires_at=FUTURE,
                idempotency_key=f"r:{i}",
            )
        except real_spend_breaker.RealSpendCapExceededError:
            pass
        # the invariant must hold after every single attempt, not just at the end
        snap = real_spend_breaker.snapshot(conn)
        assert snap.concurrent_reserved_minor_units <= cap


# --- charter_idempotent_handlers (C6) ---------------------------------------
# For any number of redelivery attempts against the same event_id, a
# handler's ledger-affecting side effect must be applied exactly once, and
# the event must end up 'processed' regardless of how many times it's
# redelivered before or after that point.


@given(
    redelivery_count=st.integers(min_value=1, max_value=15),
    amount=st.integers(min_value=1, max_value=1000),
)
@settings(max_examples=50)
def test_charter_idempotent_handlers(redelivery_count, amount):
    conn = db.connect_and_migrate()
    call_count = 0

    def handler(conn, event):
        nonlocal call_count
        call_count += 1
        ledger._write_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="event_side_effect",
            idempotency_key=f"event_side_effect:{event.event_id}",
            entries=[
                EntrySpec(account_id="source", amount_minor_units=-amount),
                EntrySpec(account_id="dest", amount_minor_units=amount),
            ],
        )
        return []

    event = events.enqueue(conn, event_type="t", source="test", priority=0, dedupe_key="dk-1")
    for _ in range(redelivery_count):
        result = events.process_event(conn, event.event_id, handler)

    assert call_count == 1
    assert result.status.value == "processed"
    assert ledger.get_balance(conn, "dest", Book.USD_SIM) == amount


# --- charter_dead_cell_inert (C8) & charter_audit_complete (C10) ------------
# For any interleaving of birth/sleep/wake/quarantine/clear_quarantine/kill:
# a dead Cell must reject every further transition attempt (C8), and every
# transition that *does* succeed — birth included — emits exactly one more
# cell_lifecycle_transition audit event for that Cell (C10).


@settings(max_examples=30, stateful_step_count=25)
class CellLifecycleMachine(RuleBasedStateMachine):
    cell_ids = Bundle("cell_ids")

    def __init__(self):
        super().__init__()
        self.conn = db.connect_and_migrate()
        self.status: dict[str, CellStatus] = {}
        self.transition_count: dict[str, int] = {}
        self._next_id = 0

    def _fresh_key(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}:{self._next_id}"

    def _note(self, cell_id, status):
        self.status[cell_id] = status
        self.transition_count[cell_id] = self.transition_count.get(cell_id, 0) + 1

    def _attempt(self, cell_id, fn, **kwargs):
        """Call a bare transition regardless of the modeled current status.
        A transition that raises is always safe to ignore (nothing changed,
        C8's terminal-dead guarantee holds); a transition that succeeds must
        never have started from a modeled-dead Cell."""
        was_dead = self.status[cell_id] == CellStatus.DEAD
        try:
            result = fn(self.conn, cell_id, **kwargs)
        except (lifecycle.InvalidTransitionError, lifecycle.LifecycleError):
            return
        assert not was_dead, "a transition succeeded against a dead Cell (C8)"
        self._note(cell_id, result.status)

    @rule(target=cell_ids)
    def birth(self):
        cell = lifecycle.create_cell(
            self.conn, cell_type=CellType.EXPLORER, budget_minor_units=10,
            book=Book.USD_SIM, idempotency_key=self._fresh_key("birth"),
        )
        self._note(cell.cell_id, cell.status)
        return cell.cell_id

    @rule(cell_id=cell_ids)
    def sleep(self, cell_id):
        self._attempt(cell_id, lifecycle.sleep)

    @rule(cell_id=cell_ids)
    def wake(self, cell_id):
        self._attempt(cell_id, lifecycle.wake)

    @rule(cell_id=cell_ids)
    def quarantine(self, cell_id):
        self._attempt(cell_id, lifecycle.quarantine, reason="test")

    @rule(cell_id=cell_ids, target_alive=st.booleans())
    def clear_quarantine(self, cell_id, target_alive):
        to_status = CellStatus.ALIVE if target_alive else CellStatus.DORMANT
        self._attempt(cell_id, lifecycle.clear_quarantine, to_status=to_status)

    @rule(cell_id=cell_ids)
    def kill(self, cell_id):
        self._attempt(cell_id, lifecycle.kill, cause_of_death="test")

    @invariant()
    def dead_cells_are_terminal(self):
        for cell_id, status in self.status.items():
            if status == CellStatus.DEAD:
                assert lifecycle.get_cell(self.conn, cell_id).status == CellStatus.DEAD

    @invariant()
    def audit_trail_matches_transition_count(self):
        for cell_id, expected in self.transition_count.items():
            actual = self.conn.execute(
                "SELECT COUNT(*) AS n FROM audit_events "
                "WHERE cell_id = ? AND event_type = 'cell_lifecycle_transition'",
                (cell_id,),
            ).fetchone()["n"]
            assert actual == expected

    def teardown(self):
        self.conn.close()


Test_charter_dead_cell_inert_charter_audit_complete = CellLifecycleMachine.TestCase


# --- charter_no_overspend (C4) -----------------------------------------------
# For any reservation cap and any sequence of attempted resource-usage
# recordings against it, cumulative recorded minor_units must never exceed
# the cap after any single attempt — granted or denied.


@given(
    cap=st.integers(min_value=10, max_value=500),
    amounts=st.lists(st.integers(min_value=1, max_value=200), min_size=0, max_size=15),
)
@settings(max_examples=50)
def test_charter_no_overspend(cap, amounts):
    conn = db.connect_and_migrate()
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=1_000_000,
        book=Book.RESOURCE, idempotency_key="cell",
    )
    r = reservations.request(
        conn, cell_id=cell.cell_id, book=Book.RESOURCE, currency="RESOURCE",
        maximum_amount=cap, expires_at=FUTURE, idempotency_key="r",
    )

    for i, amount in enumerate(amounts):
        try:
            resource_metering.record_usage(
                conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
                resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=amount,
                idempotency_key=f"u:{i}",
            )
        except resource_metering.ResourceOverspendError:
            pass
        # the invariant must hold after every single attempt, not just at the end
        assert resource_metering.total_minor_units(conn, r.reservation_id) <= cap


# --- charter_no_overspend (C4), reservation vs. cell cash --------------------
# The RESOURCE-metering test above covers usage vs. a reservation's own cap;
# this covers the earlier gate — a reservation itself can never exceed what
# the Cell holds in cash, across all books.


@given(
    budget=st.integers(min_value=1, max_value=100_000),
    requested=st.integers(min_value=1, max_value=200_000),
)
@settings(max_examples=75)
def test_charter_no_overspend_reservation_cannot_exceed_cell_cash(budget, requested):
    conn = db.connect_and_migrate()
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="seed_fund",
        idempotency_key="seed",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-budget),
            EntrySpec(account_id=cell_cash("cell-x"), amount_minor_units=budget),
        ],
    )
    if requested > budget:
        with pytest.raises(reservations.InsufficientBalanceError):
            reservations.request(
                conn, cell_id="cell-x", book=Book.USD_SIM, currency="USD",
                maximum_amount=requested, expires_at=FUTURE, idempotency_key="req",
            )
        assert ledger.get_balance(conn, cell_cash("cell-x"), Book.USD_SIM) == budget
    else:
        r = reservations.request(
            conn, cell_id="cell-x", book=Book.USD_SIM, currency="USD",
            maximum_amount=requested, expires_at=FUTURE, idempotency_key="req",
        )
        assert r.status == ReservationStatus.RESERVED
        assert ledger.get_balance(conn, cell_cash("cell-x"), Book.USD_SIM) == budget - requested


# --- charter_canonical_forms (C11) -------------------------------------------
# Money is integer minor units (never binary float), genomes have a
# canonical deterministic hash, and every kernel timestamp is rejected
# unless timezone-aware UTC. Each half is already enforced structurally at
# write time (money.py's Decimal parsing, genome.py's canonical JSON,
# ledger/reservations/events' explicit tzinfo checks) — this pins all three
# under the one Charter ID rather than leaving C11 untested.


@given(
    dollars=st.integers(min_value=-1_000_000, max_value=1_000_000),
    cents=st.integers(min_value=0, max_value=99),
)
@settings(max_examples=50)
def test_charter_canonical_forms_money_round_trips_through_integer_minor_units(dollars, cents):
    sign = "-" if dollars < 0 else ""
    amount_str = f"{sign}{abs(dollars)}.{cents:02d}"
    minor_units = money.parse_minor_units(amount_str, "USD_SIM")
    assert isinstance(minor_units, int)
    assert money.format_minor_units(minor_units, "USD_SIM") == amount_str
    # round-tripping the formatted string must reproduce the same integer exactly
    assert money.parse_minor_units(money.format_minor_units(minor_units, "USD_SIM"), "USD_SIM") == minor_units


def test_charter_canonical_forms_genome_hash_is_deterministic_and_content_addressed():
    a = genome.canonical_genome_json(CellType.EXPLORER)
    b = genome.canonical_genome_json(CellType.EXPLORER)
    c = genome.canonical_genome_json(CellType.BUILDER)
    assert genome.compute_genome_hash(a) == genome.compute_genome_hash(b)
    assert genome.compute_genome_hash(a) != genome.compute_genome_hash(c)
    assert len(genome.compute_genome_hash(a)) == 64  # sha256 hex digest


def test_charter_canonical_forms_naive_timestamps_are_rejected_everywhere():
    conn = db.connect_and_migrate()
    naive = datetime(2026, 1, 1)  # no tzinfo — Charter C11 violation by construction
    with pytest.raises(ledger.LedgerError):
        ledger._write_transaction(
            conn, book=Book.USD_SIM, currency="USD", transaction_type="t",
            idempotency_key="naive-txn", entries=[
                EntrySpec(account_id="source", amount_minor_units=-1),
                EntrySpec(account_id="dest", amount_minor_units=1),
            ],
            effective_at_utc=naive,
        )
    with pytest.raises(reservations.ReservationError):
        reservations.request(
            conn, cell_id="cell-1", book=Book.USD_SIM, currency="USD",
            maximum_amount=1, expires_at=naive, idempotency_key="naive-res",
        )
    with pytest.raises(events.EventError):
        events.enqueue(
            conn, event_type="t", source="test", priority=0,
            dedupe_key="naive-event", available_at=naive,
        )


# --- charter_kernel_immutable (C15), Phase-1 slice ---------------------------
# Full sandbox isolation (Cell-authored code cannot reach host files/secrets/
# the kernel — Charter C12) is Phase 5 scope: no Cell in this kernel executes
# any code at all. What's checkable now is the Phase-1-relevant half of C15:
# a Cell's genome is inert JSON data, never evaluated or executed by the
# kernel, and no kernel module writes into its own source tree at runtime.


def test_charter_kernel_immutable_genome_is_inert_data_not_code():
    genome_src = inspect.getsource(genome)
    assert "eval(" not in genome_src
    assert "exec(" not in genome_src
    assert "importlib" not in genome_src
    assert "__import__" not in genome_src


def test_charter_kernel_immutable_no_module_writes_its_own_source_tree():
    kernel_dir = str(Path(mitosis.__file__).parent)
    for name in (
        "ledger", "lifecycle", "reservations", "events", "cli",
        "genome", "resource_metering", "population", "real_spend_breaker",
    ):
        mod_src = inspect.getsource(importlib.import_module(f"mitosis.{name}"))
        assert kernel_dir not in mod_src
        assert "open(" not in mod_src  # the kernel only ever writes via sqlite3, not raw file I/O
