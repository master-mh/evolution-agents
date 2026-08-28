"""A dangling experiment_id is unrepresentable (SPEC.md §2.5, §2.6, §3.6;
Charter C3; ADR-043, ADR-044, ADR-047).

§2.6's experiment report is *derived* — six dimensions, every one a join on
`experiment_id`. That makes a dangling id the quietest way this kernel can be
wrong: it never fails a read, it only subtracts the work it names from every
dimension that would have counted it, and the report still prints a confident
number. ADR-044 validated the two operator-facing CLI paths and deferred the
rest; migration 0027 finished it with a foreign key rather than the injected
seam PRIORITIES and FUTURE_BUILD_HOOKS had scheduled.

These defend the constraint, the two things it must not break (NULL, and a
colony that already has dangling rows), and the message that explains it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    db,
    experiments,
    gateway,
    ledger,
    lifecycle,
    population,
    prediction,
    providers,
    real_spend_breaker,
    reservations,
    revenue,
)
from mitosis.accounts import cell_cash
from mitosis.models import (
    Book,
    CellType,
    EntrySpec,
    PopulationLimits,
    RealSpendLimits,
)

GHOST = "exp-that-never-existed"
FK_MIGRATION = "0027_experiment_id_foreign_keys.sql"

ATTRIBUTED_TABLES = (
    "ledger_entries",
    "reservations",
    "model_calls",
    "prediction_register",
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def conn():
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(
        connection,
        PopulationLimits(
            max_living_cells=1000,
            max_active_cells=100,
            max_parallel_experiments=2,
            max_births_per_epoch=25,
            max_lineage_population_fraction=0.20,
        ),
    )
    connection.commit()
    yield connection
    connection.close()


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
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_SIM,
        idempotency_key="attribution-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    conn.commit()
    return created


def _expires():
    return datetime.now(timezone.utc) + timedelta(hours=1)


# --------------------------------------------------------------------------
# The constraint itself
# --------------------------------------------------------------------------


def test_every_experiment_id_column_declares_the_foreign_key(conn):
    """Structural, and deliberately not a list of four tables.

    The four known columns were each bare TEXT because each predated the
    `experiments` table. Nothing stops the next migration reintroducing exactly
    that, and the failure is invisible — a column that holds an id naming
    nothing looks identical to one that holds a real id. This walks the live
    schema instead, so a fifth attributed table is covered on the day it lands.
    """
    tables = [
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    ]
    unconstrained = []
    for table in tables:
        # `experiments` *is* the referent — its own experiment_id is the
        # primary key everything else points at.
        if table == "experiments":
            continue
        columns = {c["name"] for c in conn.execute(f"PRAGMA table_info('{table}')")}
        if "experiment_id" not in columns:
            continue
        targets = {
            fk["table"]
            for fk in conn.execute(f"PRAGMA foreign_key_list('{table}')")
            if fk["from"] == "experiment_id"
        }
        if "experiments" not in targets:
            unconstrained.append(table)
    assert unconstrained == [], (
        f"{unconstrained} hold an experiment_id that names nothing in particular; "
        "§2.6's report joins on it and a dangling id silently subtracts"
    )


def test_the_four_tables_named_by_adr_044_are_covered(conn):
    """The specific four FUTURE_BUILD_HOOKS named, pinned by name.

    The structural test above passes vacuously if a table is renamed or dropped;
    this one names the tables ADR-044 listed as unvalidated so that losing one
    is a failure rather than a smaller sweep.
    """
    for table in ATTRIBUTED_TABLES:
        targets = {
            fk["table"]
            for fk in conn.execute(f"PRAGMA foreign_key_list('{table}')")
            if fk["from"] == "experiment_id"
        }
        assert "experiments" in targets, f"{table}.experiment_id is unconstrained"


def test_foreign_keys_are_actually_enforced_on_every_connection(conn):
    """The declaration is inert without the PRAGMA, and the PRAGMA is per
    connection, not per database. `db.connect` sets it; this asserts the
    guarantee survives `connect_and_migrate`, whose last act is a migration
    that turns foreign keys *off* to rebuild four tables."""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --------------------------------------------------------------------------
# Each write path refuses
# --------------------------------------------------------------------------


def test_ledger_refuses_an_entry_naming_no_experiment(conn, cell):
    """§2.6's money dimensions read `ledger_entries.experiment_id`. An entry
    naming nothing is real-cash spend attributed to no experiment while looking
    attributed."""
    with pytest.raises(db.UnknownExperimentError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test_funding",
            idempotency_key="ghost-entry",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-10,
                          experiment_id=GHOST),
                EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=10,
                          cell_id=cell.cell_id, experiment_id=GHOST),
            ],
        )


def test_reservations_refuse_a_dangling_experiment(conn, cell):
    """Also pins the coupling `ledger.py`'s comment relies on:
    `_request_locked` stamps its experiment_id onto the reserve entries before
    inserting the reservation row, so the ledger refuses first and the
    reservation inherits the named error. If that order is ever reversed this
    still fails the row — via the reservations foreign key — but with SQLite's
    bare message, and this test says which one arrived."""
    with pytest.raises(db.UnknownExperimentError):
        reservations.request(
            conn,
            cell_id=cell.cell_id,
            book=Book.USD_SIM,
            currency="USD",
            maximum_amount=10,
            expires_at=_expires(),
            idempotency_key="ghost-reservation",
            experiment_id=GHOST,
        )


def test_prediction_register_refuses_a_dangling_experiment(conn, cell):
    """§8.5's register is the reality-gap dimension of §2.6's report. This path
    touches no ledger entry, so it is the one that needed its own translation
    rather than inheriting the ledger's."""
    with pytest.raises(db.UnknownExperimentError):
        prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim="revenue >= 50 minor units",
            probability=0.6,
            resolves_by=datetime.now(timezone.utc) + timedelta(days=1),
            idempotency_key="ghost-prediction",
            experiment_id=GHOST,
        )


def test_revenue_refuses_a_dangling_experiment(conn, cell):
    """`mitosis record-revenue --experiment` was validated at the CLI by
    ADR-044. This asserts the kernel refuses it too, so the guarantee does not
    depend on which caller reached `revenue`."""
    with pytest.raises(db.UnknownExperimentError):
        revenue.record_revenue(
            conn,
            cell_id=cell.cell_id,
            book=Book.USD_SIM,
            amount_minor_units=50,
            source="test",
            idempotency_key="ghost-revenue",
            experiment_id=GHOST,
        )


def test_gateway_refuses_a_dangling_experiment_before_spending(conn):
    """The gateway is the one path where being late costs money.

    It reserves before it calls (ADR-022), and the reservation carries the
    attribution — so the refusal lands before anything leaves the machine, and
    `model_calls` never gets a row. That ordering is why `gateway.py` needs no
    translation of its own; this test is what keeps it true.
    """
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
        idempotency_key="gateway-ghost-cell",
    )
    _fund(conn, created.cell_id, Book.RESOURCE, 10_000_000)
    conn.commit()

    class Unreachable:
        name = "mock"

        def complete(self, request):  # pragma: no cover - must never run
            raise AssertionError("the provider was called with a dangling experiment")

    with pytest.raises(db.UnknownExperimentError):
        gateway.call_model(
            conn,
            cell_id=created.cell_id,
            provider=Unreachable(),
            request=providers.ModelRequest(
                model="mock-1",
                messages=({"role": "user", "content": "hi"},),
                max_tokens=100,
            ),
            idempotency_key="ghost-call",
            experiment_id=GHOST,
        )

    assert conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
    assert ledger.get_balance(conn, cell_cash(created.cell_id), Book.USD_REAL) == 1_000


# --------------------------------------------------------------------------
# What the constraint must NOT break
# --------------------------------------------------------------------------


def test_null_experiment_id_is_still_accepted(conn, cell):
    """ADR-044: "`None` is a result, not a gap." Most consumption in a colony
    has no experiment behind it, and a foreign key exempts NULL — so the
    constraint refuses exactly the case that was never a legitimate result, an
    id naming nothing, and nothing else."""
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=10,
        expires_at=_expires(),
        idempotency_key="unattributed",
        experiment_id=None,
    )
    assert reservation.experiment_id is None


def test_a_real_experiment_id_is_accepted(conn, cell):
    """The constraint has teeth only if it still lets the true case through."""
    experiment = experiments.start(
        conn, cell_id=cell.cell_id, hypothesis="widgets sell at 4"
    )
    conn.commit()
    reservation = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=10,
        expires_at=_expires(),
        idempotency_key="attributed",
        experiment_id=experiment.experiment_id,
    )
    assert reservation.experiment_id == experiment.experiment_id


def test_a_non_experiment_integrity_error_is_re_raised_unchanged(conn, cell):
    """The translator must not swallow other constraints.

    Every table it guards declares constraints of its own — a UNIQUE
    idempotency_key, a NOT NULL, other foreign keys — and a helper that
    relabelled any of them as a missing experiment would send a caller looking
    in the wrong place. It re-raises anything that is not this foreign key.
    """
    with pytest.raises(sqlite3.IntegrityError) as caught:
        conn.execute("INSERT INTO experiments (experiment_id) VALUES (NULL)")
    assert not isinstance(caught.value, db.UnknownExperimentError)

    # And the helper itself, handed a violation that is not a foreign key,
    # returns rather than raising.
    db.raise_for_unknown_experiment(
        conn, sqlite3.IntegrityError("UNIQUE constraint failed"),
        experiment_ids=(GHOST,),
    )


def test_the_refusal_names_the_id_and_offers_the_alternative(conn, cell):
    """SQLite says "FOREIGN KEY constraint failed" and nothing else — no
    column, no value. `model_calls` declares four foreign keys, so on the table
    where a dangling experiment is most likely the bare message is least able
    to say which one broke."""
    with pytest.raises(db.UnknownExperimentError) as caught:
        prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim="revenue >= 50 minor units",
            probability=0.6,
            resolves_by=datetime.now(timezone.utc) + timedelta(days=1),
            idempotency_key="named-refusal",
            experiment_id=GHOST,
        )
    message = str(caught.value)
    assert GHOST in message
    assert "attribution_for" in message
    assert caught.value.__cause__ is not None


# --------------------------------------------------------------------------
# The rebuild itself
# --------------------------------------------------------------------------


def _migrate_all_except(conn, skipped_filename):
    """Apply every migration in order **except** one, so a database can be built
    in its pre-`skipped_filename` shape and then upgraded.

    Was `_migrate_through(conn, "0026_experiments.sql")` — stop at 0026 — which
    said "a colony at 0026" while meaning "a colony without the foreign keys".
    Those coincided until migration 0028 added a column the kernel writes
    unconditionally, and then the fixture started failing on a schema gap that
    has nothing to do with what these tests are about. Naming the *excluded*
    migration keeps the fixture true as later ones land.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ")"
    )
    applied = False
    for path in db._migration_files():
        if path.name == skipped_filename:
            applied = True
            continue
        conn.executescript(path.read_text())
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
    assert applied, f"{skipped_filename} is not a migration; the fixture is testing nothing"
    return conn


@pytest.fixture()
def pre_fk_conn():
    """Today's schema minus the experiment foreign keys."""
    connection = db.connect()
    _migrate_all_except(connection, FK_MIGRATION)
    population.set_limits_if_absent(
        connection,
        PopulationLimits(
            max_living_cells=1000,
            max_active_cells=100,
            max_parallel_experiments=2,
            max_births_per_epoch=25,
            max_lineage_population_fraction=0.20,
        ),
    )
    connection.commit()
    yield connection
    connection.close()


def test_the_rebuild_preserves_both_hash_chains(pre_fk_conn):
    """The migration's single largest risk, and it is not the data.

    `ledger_transactions` and `prediction_register` are hash-chained, and both
    `verify_chain`s read their rows `ORDER BY rowid` — the ledger's folds every
    entry of a transaction into that transaction's hash, in rowid order. A
    table rebuild renumbers every rowid. Copy the rows back in a different
    relative order and every hash after the first divergence is wrong, which
    would read exactly like tamper-evidence firing (§3.4).
    """
    conn = pre_fk_conn
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_SIM,
        idempotency_key="chain-cell",
    )
    experiment = experiments.start(
        conn, cell_id=cell.cell_id, hypothesis="widgets sell at 4"
    )
    conn.commit()

    # Several transactions, each with multiple entries, some attributed and
    # some not — so intra-transaction entry order is actually load-bearing.
    for n in range(5):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test_funding",
            idempotency_key=f"chain-txn-{n}",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-10,
                          experiment_id=experiment.experiment_id if n % 2 else None),
                EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=10,
                          cell_id=cell.cell_id,
                          experiment_id=experiment.experiment_id if n % 2 else None),
            ],
        )
    for n in range(5):
        prediction.register(
            conn,
            cell_id=cell.cell_id,
            claim=f"revenue >= {n} minor units",
            probability=0.5 + n / 100,
            resolves_by=datetime.now(timezone.utc) + timedelta(days=1),
            idempotency_key=f"chain-pred-{n}",
            experiment_id=experiment.experiment_id if n % 2 else None,
        )
    conn.commit()

    assert ledger.verify_chain(conn)
    assert prediction.verify_chain(conn)
    before_entries = conn.execute(
        "SELECT entry_id FROM ledger_entries ORDER BY rowid"
    ).fetchall()
    before_predictions = conn.execute(
        "SELECT prediction_id FROM prediction_register ORDER BY rowid"
    ).fetchall()
    before_reservations = conn.execute(
        "SELECT reservation_id FROM reservations ORDER BY rowid"
    ).fetchall()

    assert FK_MIGRATION in db.migrate(conn)

    assert ledger.verify_chain(conn), "the rebuild reordered ledger entries"
    assert prediction.verify_chain(conn), "the rebuild reordered the register"
    assert conn.execute(
        "SELECT entry_id FROM ledger_entries ORDER BY rowid"
    ).fetchall() == before_entries
    assert conn.execute(
        "SELECT prediction_id FROM prediction_register ORDER BY rowid"
    ).fetchall() == before_predictions
    assert conn.execute(
        "SELECT reservation_id FROM reservations ORDER BY rowid"
    ).fetchall() == before_reservations


def test_an_open_dangling_reservation_is_repaired_rather_than_frozen(pre_fk_conn):
    """The case that would have stranded a live colony's money.

    `settle` and `release` write *new* ledger entries carrying the
    reservation's experiment_id, so an open reservation already holding a
    dangling id has no path out once the entry constraint exists — every exit
    writes an entry the foreign key refuses, and its committed funds stay
    committed forever. A PRAGMA-level probe misses this entirely: a bare UPDATE
    of a non-key column on a violating row is allowed, so the row looks healthy
    until the kernel actually tries to release it.

    The migration clears the false attribution to NULL — the true value, per
    ADR-044 — and records the id it cleared, so the repair is legible rather
    than silent.
    """
    conn = pre_fk_conn
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_SIM,
        idempotency_key="legacy-cell",
    )
    legacy = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=10,
        expires_at=_expires(),
        idempotency_key="legacy-dangling",
        experiment_id=GHOST,
    )
    conn.commit()

    assert FK_MIGRATION in db.migrate(conn)

    repaired = conn.execute(
        "SELECT experiment_id FROM reservations WHERE reservation_id = ?",
        (legacy.reservation_id,),
    ).fetchone()
    assert repaired["experiment_id"] is None

    # Cleared, not dropped: the id it used to hold is on the record.
    trail = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = ?",
        ("reservation_attribution_cleared",),
    ).fetchall()
    assert len(trail) == 1
    assert GHOST in trail[0]["metadata_json"]
    assert legacy.reservation_id in trail[0]["metadata_json"]

    # And the reservation can complete, which is the whole point.
    reservations.release(conn, legacy.reservation_id)
    assert ledger.verify_conservation(conn, Book.USD_SIM)
    assert ledger.verify_chain(conn)


def test_a_dangling_ledger_entry_keeps_its_evidence(pre_fk_conn):
    """§3.6: history is corrected by adjustment, never by editing it.

    A ledger entry is settled history — nothing will ever write another entry
    on its behalf — so a dangling id there strands nothing and is the *evidence*
    that a report had been undercounting. The migration copies it through
    untouched, and `PRAGMA foreign_key_check` makes it findable rather than
    silent. This is the line between the two halves: repair what is still live,
    preserve what is already history.
    """
    conn = pre_fk_conn
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_SIM,
        idempotency_key="legacy-entry-cell",
    )
    ledger.post_transaction(
        conn,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="test_funding",
        idempotency_key="legacy-entry",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-10,
                      experiment_id=GHOST),
            EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=10,
                      cell_id=cell.cell_id, experiment_id=GHOST),
        ],
    )
    conn.commit()
    assert ledger.verify_chain(conn)

    assert FK_MIGRATION in db.migrate(conn)

    surviving = conn.execute(
        "SELECT COUNT(*) FROM ledger_entries WHERE experiment_id = ?", (GHOST,)
    ).fetchone()[0]
    assert surviving == 2, "history was edited to satisfy the new constraint"
    assert ledger.verify_chain(conn), "editing an entry would break the chain"

    violations = conn.execute("PRAGMA foreign_key_check('ledger_entries')").fetchall()
    assert len(violations) == 2

    # No repair audit row: nothing live was touched.
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = ?",
        ("reservation_attribution_cleared",),
    ).fetchone()[0] == 0

    # And a new dangling write is still refused.
    with pytest.raises(db.UnknownExperimentError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="test_funding",
            idempotency_key="new-dangling-entry",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-10,
                          experiment_id=GHOST),
                EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=10,
                          cell_id=cell.cell_id, experiment_id=GHOST),
            ],
        )


def test_a_settled_dangling_reservation_keeps_its_evidence(pre_fk_conn):
    """The other side of the repair's status filter.

    A settled reservation is finished: no path writes another ledger entry for
    it, so its dangling id strands nothing and clearing it would destroy
    evidence for no benefit. The repair is scoped to *open* reservations for
    exactly that reason, and without this the filter could be dropped and only
    a test about ledger entries would notice.
    """
    conn = pre_fk_conn
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_SIM,
        idempotency_key="settled-legacy-cell",
    )
    legacy = reservations.request(
        conn,
        cell_id=cell.cell_id,
        book=Book.USD_SIM,
        currency="USD",
        maximum_amount=10,
        expires_at=_expires(),
        idempotency_key="settled-dangling",
        experiment_id=GHOST,
    )
    reservations.settle(
        conn, legacy.reservation_id, settled_amount=10,
        destination_account_id="external_expense",
    )
    conn.commit()

    assert FK_MIGRATION in db.migrate(conn)

    kept = conn.execute(
        "SELECT experiment_id, status FROM reservations WHERE reservation_id = ?",
        (legacy.reservation_id,),
    ).fetchone()
    assert kept["status"] == "settled"
    assert kept["experiment_id"] == GHOST, "a finished reservation lost its evidence"
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type = ?",
        ("reservation_attribution_cleared",),
    ).fetchone()[0] == 0


def test_a_different_foreign_key_on_the_same_row_is_not_blamed_on_the_experiment(conn, cell):
    """SQLite's message cannot tell two foreign keys apart, so the translator
    must.

    `prediction_register` and `model_calls` each reference `cells` as well as
    `experiments`, and `model_calls` references `reservations` twice. All four
    fail with the identical eight words. A translator that assumed the
    experiment was at fault would send a caller hunting for a missing
    experiment when the real problem was a missing cell — turning a precise
    refusal back into a misleading one, which is the failure this whole slice
    exists to end.
    """
    experiment = experiments.start(
        conn, cell_id=cell.cell_id, hypothesis="widgets sell at 4"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError) as caught:
        conn.execute(
            """
            INSERT INTO prediction_register (
                prediction_id, cell_id, experiment_id, claim, probability,
                resolves_by_utc, created_at_utc, prediction_hash, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p1", "no-such-cell", experiment.experiment_id, "c", 0.5,
             "2030-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00", "h", "k"),
        )

    # The experiment named is real, so this is not the experiment's foreign key.
    db.raise_for_unknown_experiment(
        conn, caught.value, experiment_ids=(experiment.experiment_id,)
    )


def test_a_null_experiment_is_never_blamed_for_someone_elses_foreign_key(conn, cell):
    """The same trap reached with NULL.

    Most rows in a colony carry `experiment_id IS NULL` (ADR-044: unattributed
    is a result). If one of those rows breaks a *different* foreign key, the
    translator must not read NULL as "an experiment named nothing" and report
    a missing experiment that was never claimed in the first place.
    """
    with pytest.raises(sqlite3.IntegrityError) as caught:
        conn.execute(
            """
            INSERT INTO prediction_register (
                prediction_id, cell_id, experiment_id, claim, probability,
                resolves_by_utc, created_at_utc, prediction_hash, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p2", "no-such-cell", None, "c", 0.5,
             "2030-01-01T00:00:00+00:00", "2030-01-01T00:00:00+00:00", "h", "k2"),
        )

    db.raise_for_unknown_experiment(conn, caught.value, experiment_ids=(None,))
