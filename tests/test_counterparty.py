"""The inbound counterparty key: equality without identity
(SPEC.md §12.1, §12.2, §16.3, §21.2, §3.4, §3.6, §2.5; ADR-060, ADR-061).

Every test is named for the property it defends. Three themes:

- **The identity never enters the colony.** Not in the ledger, not in an audit
  event, not anywhere a scan of the whole database can find it — and the column
  itself cannot physically hold one.
- **The chain still verifies.** Extending a hash preimage is the one change that
  can make every existing colony report itself as tampered with, so the
  no-counterparty preimage is pinned against the formula that predates it.
- **The measurement abstains in the right direction.** `repeat` survives a
  partial record because more data can only add repeats; `one_off` does not,
  because a missing key could be the second payment.
"""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

from mitosis import (
    channel_registry,
    counterparty,
    db,
    ledger,
    lifecycle,
    models,
    novelty,
    population,
    revenue,
)
from mitosis.models import Book, CellType, EntrySpec

BASE = {
    "market": "independent bookshops",
    "problem": "stock decisions are guesswork",
    "product": "a weekly stock digest",
    "revenue_model": "monthly subscription per shop",
    "acquisition_channel": "trade newsletters",
    "workflow": "ingest sales, rank slow movers, publish",
}

PARTY = "Alice@Example.com"


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(connection, models.DEFAULT_POPULATION_LIMITS)
    ledger.post_transaction(
        connection,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="external_capital_in",
        idempotency_key="seed",
        description="test seed",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-100_000),
            EntrySpec(account_id="seed_bank", amount_minor_units=100_000),
        ],
    )
    yield connection
    connection.close()


def _cell(conn, tag, **overrides):
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        genome_content={**BASE, **overrides},
    )


def _genome_of(conn, cell):
    return conn.execute(
        "SELECT genome_hash FROM cells WHERE cell_id = ?", (cell.cell_id,)
    ).fetchone()["genome_hash"]


def _earn(conn, cell, source, party=None, amount=10):
    return revenue.record_revenue(
        conn,
        cell_id=cell.cell_id,
        amount_minor_units=amount,
        source=source,
        book=Book.USD_SIM,
        counterparty=party,
    )


def _recurrence(conn, cell):
    return next(
        d for d in novelty.descriptors(conn, _genome_of(conn, cell))
        if d.dimension == "revenue_recurrence"
    )


# --- §16.3: the party never exists here as itself -----------------------------


def test_the_same_party_spelled_differently_is_one_key(conn):
    """§16.3's key is only useful if it survives how a person types a name.

    `Alice@Ex.com` and `alice@ex.com` are one buyer. A key that misses that
    reports a repeat customer as two strangers, which is the exact failure
    `revenue_recurrence` exists to avoid — and it fails *silently*, because both
    spellings produce a perfectly valid digest.
    """
    a = counterparty.hash_of(conn, PARTY)
    b = counterparty.hash_of(conn, "  alice@example.com  ")
    c = counterparty.hash_of(conn, "bob@example.com")
    assert a == b
    assert a != c


def test_the_counterparty_is_never_stored_as_itself(conn):
    """§16.3 puts customer identity outside the colony; a scan proves it.

    Behavioural rather than structural on purpose: it is not enough that
    `record_revenue` hashes its argument, because the same string is one
    interpolation away from the description, the audit metadata or a note. This
    reads every value in every table and asserts the identity is in none of them.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", PARTY)

    needles = {PARTY, PARTY.casefold(), "Example.com", "example.com"}
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    ]
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():  # noqa: S608
            for value in tuple(row):
                if isinstance(value, str):
                    for needle in needles:
                        assert needle not in value, f"{needle!r} leaked into {table}"


def test_a_counterparty_never_reaches_the_audit_event(conn):
    """The audit event records *whether*, never *who* (§16.3, §21.2).

    A digest is not an identity but it is a linkable key, and audit events are
    read by paths a Cell can reach. §21.2's registry has followed this rule since
    ADR-036; the inbound side has to follow the same one or the guarantee is only
    as strong as its weaker half.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", PARTY)
    digest = counterparty.hash_of(conn, PARTY)

    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'cell_revenue_recorded'"
    ).fetchone()
    metadata = json.loads(row["metadata_json"])
    assert metadata["counterparty_recorded"] is True
    assert digest not in row["metadata_json"]
    assert not any(digest == value for value in metadata.values())


def test_the_inbound_and_outbound_keys_are_the_same_digest(conn):
    """One salt, both directions (§21.2 + §12.1).

    A party the colony contacted and who then pays must produce the same key, or
    the contact history and the money can never be joined — and two separate
    salts would look identical to every test that exercised only one direction.
    """
    cell = _cell(conn, "a")
    transaction = _earn(conn, cell, "invoice-1", PARTY)
    assert transaction.counterparty_hash == channel_registry.counterparty_hash(conn, PARTY)


def test_a_blank_counterparty_is_refused(conn):
    """Supplied-but-empty is a caller error, not a synonym for `None`.

    Letting it through would put a digest of the empty string in the ledger,
    where it would compare equal to every other blank and manufacture a repeat
    customer out of two operators pressing return.
    """
    cell = _cell(conn, "a")
    with pytest.raises(revenue.RevenueError, match="blank"):
        _earn(conn, cell, "invoice-1", "   ")


# --- the schema is the guarantee, not the seam --------------------------------


def _check_expression() -> str:
    """The CHECK clause as migration 0028 actually declares it."""
    text = (
        Path(novelty.__file__).parent / "migrations" / "0028_revenue_counterparty.sql"
    ).read_text()
    match = re.search(r"ADD COLUMN counterparty_hash TEXT\s*(CHECK \(.*?\n    \));", text, re.S)
    assert match, "migration 0028 no longer declares a CHECK on counterparty_hash"
    return match.group(1)


def test_the_schema_check_and_is_hash_are_one_rule(conn):
    """Two spellings of the same constraint must not drift apart (ADR-047).

    `counterparty.is_hash` is the Python statement of what the column will hold;
    the CHECK in migration 0028 is the one that actually binds. This builds a
    probe table from the migration's own text so a change to either side that is
    not made to the other fails here.
    """
    probe = db.connect()
    probe.execute(f"CREATE TABLE probe (counterparty_hash TEXT {_check_expression()})")
    candidates = [
        None,
        "",
        "a" * 64,
        "0" * 64,
        hashlib.sha256(b"x").hexdigest(),
        hashlib.sha256(b"x").hexdigest().upper(),
        "a" * 63,
        "a" * 65,
        "alice@example.com",
        "g" * 64,
        " " + "a" * 63,
    ]
    for candidate in candidates:
        try:
            probe.execute("INSERT INTO probe VALUES (?)", (candidate,))
            accepted = True
        except sqlite3.IntegrityError:
            accepted = False
        # NULL is accepted by the column and is not a hash; every other value
        # must be judged identically by both rules.
        expected = True if candidate is None else counterparty.is_hash(candidate)
        assert accepted is expected, f"{candidate!r}: schema {accepted}, is_hash {expected}"
    probe.close()


def test_the_column_cannot_hold_a_customer_identity(conn):
    """§16.3 enforced by the schema, so no future caller can forget (ADR-047).

    A seam can be bypassed by a caller that never heard of it. This asserts the
    ledger itself refuses an unhashed party, which is what makes the guarantee
    hold for code that does not exist yet.
    """
    with pytest.raises(sqlite3.IntegrityError):
        ledger.post_transaction(
            conn,
            book=Book.USD_SIM,
            currency="USD",
            transaction_type="external_capital_in",
            idempotency_key="raw-identity",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-1),
                EntrySpec(account_id="seed_bank", amount_minor_units=1),
            ],
            counterparty_hash="alice@example.com",
        )


# --- §3.4: extending the preimage without breaking every colony ---------------


def test_a_transaction_without_a_counterparty_hashes_as_it_always_did(conn):
    """The pre-0028 formula, recomputed by hand and compared (§3.4).

    Adding `"counterparty_hash": None` to every preimage would change the hash of
    every transaction ever written, so `verify_chain` would report the whole
    ledger of every existing colony as tampered with — the exact alarm the chain
    exists to raise, for the exact wrong reason. This pins the old formula: it
    fails the moment the key stops being omitted when absent.
    """
    row = conn.execute(
        "SELECT * FROM ledger_transactions WHERE idempotency_key = 'seed'"
    ).fetchone()
    entries = conn.execute(
        "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY rowid",
        (row["transaction_id"],),
    ).fetchall()
    canonical = {
        "transaction_id": row["transaction_id"],
        "book": row["book"],
        "currency": row["currency"],
        "created_at_utc": row["created_at_utc"],
        "effective_at_utc": row["effective_at_utc"],
        "idempotency_key": row["idempotency_key"],
        "event_id": row["event_id"],
        "transaction_type": row["transaction_type"],
        "description": row["description"],
        "previous_transaction_hash": row["previous_transaction_hash"],
        "entries": [
            {
                "entry_id": e["entry_id"],
                "account_id": e["account_id"],
                "amount_minor_units": e["amount_minor_units"],
                "cell_id": e["cell_id"],
                "team_id": e["team_id"],
                "experiment_id": e["experiment_id"],
                "artifact_id": e["artifact_id"],
            }
            for e in entries
        ],
    }
    pre_0028 = hashlib.sha256(
        ledger._canonical_json(canonical).encode("utf-8")
    ).hexdigest()
    assert row["counterparty_hash"] is None
    assert pre_0028 == row["transaction_hash"]


def test_editing_who_paid_breaks_the_chain(conn):
    """§3.6: who paid is ledger history, and history is not edited.

    This is the whole argument for putting the key on the transaction rather than
    in `metadata_json` or a side table: the field decides whether a Cell occupies
    §12.1's `repeat` niche, which is a fitness-bearing claim, and it must not be
    quietly changeable after the fact.
    """
    cell = _cell(conn, "a")
    transaction = _earn(conn, cell, "invoice-1", PARTY)
    assert ledger.verify_chain(conn)

    conn.execute(
        "UPDATE ledger_transactions SET counterparty_hash = ? WHERE transaction_id = ?",
        (counterparty.hash_of(conn, "someone-else@example.com"), transaction.transaction_id),
    )
    assert not ledger.verify_chain(conn)


def test_clearing_who_paid_breaks_the_chain(conn):
    """The other direction: erasing a counterparty is a tamper too.

    Omitting the key from the preimage when it is absent is what keeps old rows
    verifying — the risk it creates is that *deleting* a counterparty could
    reproduce the old hash and slip through. It does not: the stored hash was
    computed with the key present.
    """
    cell = _cell(conn, "a")
    transaction = _earn(conn, cell, "invoice-1", PARTY)
    conn.execute(
        "UPDATE ledger_transactions SET counterparty_hash = NULL WHERE transaction_id = ?",
        (transaction.transaction_id,),
    )
    assert not ledger.verify_chain(conn)


# --- §12.1: the cadence, and which way it abstains ----------------------------


def test_a_genome_with_no_revenue_is_unevaluable(conn):
    """No payment is not the same fact as one payment (§12.1, ADR-059's split).

    `UNEVALUABLE` says this subject has no record yet; `UNMEASURABLE` says
    nothing here could produce one. Only one of the two is something a build can
    fix, which is why they are not one enum member.
    """
    cell = _cell(conn, "a")
    found = _recurrence(conn, cell)
    assert found.bin is None
    assert found.measurement is novelty.Measurement.UNEVALUABLE


def test_one_buyer_paying_twice_is_repeat(conn):
    """The conclusion that depends on two digests being equal (§12.1).

    If the salt were per-call, the normalisation dropped, or the counterparty
    silently not written, this would read `one_off` — which is why the golden run
    is pinned on `repeat` rather than on a single payment.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", PARTY)
    _earn(conn, cell, "invoice-2", "  alice@EXAMPLE.com ")
    found = _recurrence(conn, cell)
    assert found.bin == "repeat"
    assert found.measurement is novelty.Measurement.MEASURED


def test_two_buyers_paying_once_each_is_one_off(conn):
    """The trap ADR-060 named, closed: this is two customers, not a repeat.

    Counting payments per *Cell* would report this as `repeat`. Keying on the
    buyer is the whole difference.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", "alice@example.com")
    _earn(conn, cell, "invoice-2", "bob@example.com")
    found = _recurrence(conn, cell)
    assert found.bin == "one_off"


def test_a_partial_record_abstains_rather_than_reading_one_off(conn):
    """ADR-044's undercount trap: a wrong bin is worse than a stated absence.

    One of these payments has no key. It could be Alice paying again, which would
    make this `repeat`. Reporting `one_off` would be a claim about a revenue model
    that the record does not support, and it would be invisible — only the
    abstention is visible.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", "alice@example.com")
    _earn(conn, cell, "invoice-2", None)
    found = _recurrence(conn, cell)
    assert found.bin is None
    assert found.measurement is novelty.Measurement.UNMEASURABLE
    assert "1 of 2" in found.reason


def test_a_repeat_survives_a_partial_record(conn):
    """The rule is monotone, and abstains in one direction only (§12.1).

    More data can add a repeat and can never remove one, so a repeat already
    visible in the keyed payments is not weakened by unkeyed ones. An
    implementation that abstained whenever *any* payment lacked a key would be
    safe and would also throw away a conclusion it had already earned.
    """
    cell = _cell(conn, "a")
    _earn(conn, cell, "invoice-1", "alice@example.com")
    _earn(conn, cell, "invoice-2", "alice@example.com")
    _earn(conn, cell, "invoice-3", None)
    assert _recurrence(conn, cell).bin == "repeat"


def test_one_buyer_paying_two_siblings_is_repeat(conn):
    """The archive bins genomes, so the cadence aggregates across their Cells.

    A buyer coming back to the same business idea is a repeat customer of that
    idea, whichever sibling took the second payment. Aggregating per Cell would
    split the evidence and read `one_off` twice.
    """
    first = _cell(conn, "a")
    second = _cell(conn, "b")
    assert _genome_of(conn, first) == _genome_of(conn, second)
    _earn(conn, first, "invoice-1", PARTY)
    _earn(conn, second, "invoice-2", PARTY)
    assert _recurrence(conn, first).bin == "repeat"


def test_a_subscription_is_never_reported(conn):
    """§12.1 names a bin this colony cannot produce, and says so (UNREACHABLE_BINS).

    Distinguishing a subscription from a loyal buyer needs the service-obligation
    record §16.3 calls liability-linked, and there is none. A bin that never
    appears looks identical to a bin that never happens, so the refusal is
    written down rather than left as an absent branch — and pinned here across
    every shape of payment record.
    """
    assert set(novelty.UNREACHABLE_BINS) <= set(
        novelty.DESCRIPTOR_SENSE["revenue_recurrence"]
    )
    shapes = [
        (), (None,), ("a" * 64,), ("a" * 64, "a" * 64), ("a" * 64, "b" * 64),
        ("a" * 64, None), ("a" * 64, "a" * 64, None), (None, None),
    ]
    for shape in shapes:
        assert novelty._revenue_recurrence(shape).bin != "subscription"


# --- what the key did not unblock ---------------------------------------------


def test_the_key_does_not_unblock_buyer_type(conn):
    """ADR-060 said this key blocked `buyer_type`. It did not (§16.3).

    A digest answers "is this the same party?" and nothing else. human consumer /
    small business / enterprise / machine is a claim about who the buyer *is*,
    and §16.3 keeps customer identity out of this colony permanently — so there
    is nothing here to classify from, with or without the key. It needs a
    declarer, not a better query, and this test fails if someone later derives
    one from the channel or the amount.
    """
    _cell(conn, "a")
    earner = _cell(conn, "b", market="village halls")
    _earn(conn, earner, "invoice-1", PARTY)
    _earn(conn, earner, "invoice-2", PARTY)
    found = novelty.archive(conn)
    assert "revenue_recurrence" in found.measured_dimensions
    assert found.unmeasured_dimensions == ("buyer_type",)


def test_the_archive_gains_a_dimension_when_a_buyer_is_keyed(conn):
    """§12.1 asks for two or three dimensions; ADR-060 could only ship one.

    The coordinate names only what was measured, so the archive going from
    one-dimensional to two-dimensional is the visible result of the key existing
    at all.
    """
    _cell(conn, "a")
    # Two genomes, because the founder has nothing earlier to be novel against
    # and a one-genome colony measures nothing at all.
    cell = _cell(conn, "b", market="village halls")
    assert novelty.archive(conn).measured_dimensions == ("novelty_distance",)
    _earn(conn, cell, "invoice-1", PARTY)
    assert novelty.archive(conn).measured_dimensions == (
        "novelty_distance",
        "revenue_recurrence",
    )
