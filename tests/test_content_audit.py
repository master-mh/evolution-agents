"""The Auditor path for §13.3/§13.4's content judgments (SPEC.md §13.3,
§13.4, §10.4, §0.3, §29.10).

The theme is the same one `test_auditor.py` defends, generalised from a
request to a genome: a flag must cost something (a registered, scored
probability), the Auditor never phrases the claim it is judged against, and
independence is checked against the *content* under review — which, unlike a
request, may belong to several Cells, one, or none.
"""

import ast
import json
from pathlib import Path

import pytest

from mitosis import (
    content_audit,
    db,
    lifecycle,
    ledger,
    population,
    prediction,
    providers,
)
from mitosis.models import Book, CellType, EntrySpec, PopulationLimits

LIMITS = PopulationLimits(
    max_living_cells=100,
    max_active_cells=100,
    max_parallel_experiments=20,
    max_births_per_epoch=50,
    max_lineage_population_fraction=1.0,
)

BASE = {
    "market": "independent bookshops",
    "problem": "stock decisions are guesswork",
    "product": "a weekly stock digest",
    "revenue_model": "monthly subscription per shop",
    "acquisition_channel": "trade newsletters",
    "workflow": "ingest sales, rank slow movers, publish",
}

CONCERN = json.dumps(
    {"verdict": "concern", "summary": "reads as ordinary freelancing", "probability": 0.2},
    sort_keys=True,
)
NO_CONCERN = json.dumps(
    {"verdict": "no_concern", "summary": "genuinely combinatorial", "probability": 0.8},
    sort_keys=True,
)


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(connection, LIMITS)
    ledger.post_transaction(
        connection,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="external_capital_in",
        idempotency_key="seed",
        description="test seed",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-500_000),
            EntrySpec(account_id="seed_bank", amount_minor_units=500_000),
        ],
    )
    yield connection
    connection.close()


def _cell(conn, tag, cell_type=CellType.AUDITOR, *, fund=True, **genome_overrides):
    content = {**BASE, **genome_overrides} if genome_overrides else None
    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=500,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        genome_content=content,
    )
    if fund:
        for book, currency, amount in ((Book.USD_REAL, "USD", 50), (Book.RESOURCE, "RESOURCE", 5_000)):
            ledger.post_transaction(
                conn,
                book=book,
                currency=currency,
                transaction_type="cell_funding",
                idempotency_key=f"fund:{tag}:{book.value}",
                description="§15.4: a Cell pays for its own thinking",
                entries=[
                    EntrySpec(
                        account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id
                    ),
                    EntrySpec(
                        account_id=f"cell:{cell.cell_id}:cash",
                        amount_minor_units=amount,
                        cell_id=cell.cell_id,
                    ),
                ],
            )
    return cell


def _audit_genome(conn, genome_hash, reviewer, reply=CONCERN, **kwargs):
    return content_audit.audit_genome(
        conn,
        genome_hash=genome_hash,
        auditor_cell_id=reviewer.cell_id,
        provider=providers.MockProvider(reply=reply),
        model="mock-1",
        **kwargs,
    )


def _audit_pair(conn, genome_hash, compared, reviewer, reply=CONCERN, **kwargs):
    return content_audit.audit_genome_pair(
        conn,
        genome_hash=genome_hash,
        compared_genome_hash=compared,
        auditor_cell_id=reviewer.cell_id,
        provider=providers.MockProvider(reply=reply),
        model="mock-1",
        **kwargs,
    )


# --- happy paths ---------------------------------------------------------------


def test_a_genome_audit_registers_a_prediction_and_records_the_verdict(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a distinct market")

    result = _audit_genome(conn, subject.genome_hash, reviewer, reply=CONCERN)

    assert result.is_recorded
    assert result.kind is content_audit.Kind.SOFTWARE_NATIVE_ADVANTAGE
    assert result.compared_genome_hash is None
    assert result.raised_a_flag
    assert result.probability == 0.2
    registered = prediction.get(conn, result.prediction_id)
    assert subject.genome_hash in registered.claim
    assert registered.cell_id == reviewer.cell_id


def test_a_genome_pair_audit_registers_a_prediction_and_records_the_verdict(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    a = _cell(conn, "a", CellType.COMMERCIAL, market="market A")
    b = _cell(conn, "b", CellType.COMMERCIAL, market="market B")

    result = _audit_pair(conn, a.genome_hash, b.genome_hash, reviewer, reply=NO_CONCERN)

    assert result.is_recorded
    assert result.kind is content_audit.Kind.RENAMED_MECHANISM
    assert result.compared_genome_hash == b.genome_hash
    assert not result.raised_a_flag
    registered = prediction.get(conn, result.prediction_id)
    assert a.genome_hash in registered.claim
    assert b.genome_hash in registered.claim
    assert "distinct" in registered.claim


def test_a_genome_cannot_be_paired_against_itself(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="solo market")

    with pytest.raises(content_audit.ContentAuditError, match="cannot be compared against itself"):
        _audit_pair(conn, subject.genome_hash, subject.genome_hash, reviewer)


# --- §0.3: independence, generalised to a genome --------------------------------


def test_an_auditor_cannot_judge_its_own_genome(conn):
    """§0.3 generalised: an Auditor carrying the genome under review is not an
    independent evaluator of its own business hypothesis."""
    reviewer = _cell(conn, "auditor", CellType.AUDITOR, market="the auditor's own market")

    with pytest.raises(content_audit.ContentAuditError, match="own business hypothesis"):
        _audit_genome(conn, reviewer.genome_hash, reviewer)


def test_an_auditor_cannot_judge_a_pair_containing_its_own_genome(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR, market="the auditor's own market")
    other = _cell(conn, "other", CellType.COMMERCIAL, market="a different market")

    with pytest.raises(content_audit.ContentAuditError, match="own business hypothesis"):
        _audit_pair(conn, other.genome_hash, reviewer.genome_hash, reviewer)


def test_a_relative_is_not_an_independent_auditor_of_a_genome(conn):
    """A Cell sharing lineage with a genome's carrier is not independent, the
    same reasoning `auditor._validated_auditor` applies to one Cell, applied
    here to every Cell that has ever carried the genome under review."""
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a lineage market")
    relative = _cell(conn, "relative", CellType.AUDITOR, market="a different market entirely")
    conn.execute(
        "UPDATE cells SET founder_cell_id = ? WHERE cell_id = ?",
        (subject.founder_cell_id, relative.cell_id),
    )

    with pytest.raises(content_audit.ContentAuditError, match="shares lineage"):
        _audit_genome(conn, subject.genome_hash, relative)


def test_only_oversight_cells_audit_a_genome(conn):
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    not_an_auditor = _cell(conn, "explorer", CellType.EXPLORER, market="another market")

    with pytest.raises(content_audit.ContentAuditError, match="only .*Cells audit"):
        _audit_genome(conn, subject.genome_hash, not_an_auditor)


def test_a_quarantined_auditor_cannot_audit_a_genome(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    conn.execute(
        "UPDATE cells SET status = 'quarantined' WHERE cell_id = ?", (reviewer.cell_id,)
    )

    with pytest.raises(content_audit.ContentAuditError, match="quarantined"):
        _audit_genome(conn, subject.genome_hash, reviewer)


# --- §10.4: a costless flag is refused -------------------------------------------


def test_a_costless_hedged_flag_is_refused_for_a_genome_audit(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    hedged = json.dumps(
        {"verdict": "concern", "summary": "hedging", "probability": 0.9}, sort_keys=True
    )

    result = _audit_genome(conn, subject.genome_hash, reviewer, reply=hedged)

    assert result.status == content_audit.STATUS_REJECTED
    assert "incoherent" in (result.failure_reason or "")


def test_malformed_json_is_recorded_rejected_not_raised(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")

    result = _audit_genome(conn, subject.genome_hash, reviewer, reply="not json at all")

    assert result.status == content_audit.STATUS_REJECTED
    assert result.verdict is None
    assert result.prediction_id is None


# --- the kernel composes the claim ------------------------------------------------


def test_the_auditor_does_not_write_the_claim_it_is_scored_on(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")

    result = _audit_genome(conn, subject.genome_hash, reviewer, reply=CONCERN)

    registered = prediction.get(conn, result.prediction_id)
    assert subject.genome_hash in registered.claim
    assert "program-native" in registered.claim
    assert "reads as ordinary freelancing" not in registered.claim


# --- idempotency and one-opinion-per-auditor --------------------------------------


def test_a_repeated_audit_returns_the_first_and_buys_no_model_call(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")

    first = _audit_genome(conn, subject.genome_hash, reviewer, reply=CONCERN, idempotency_key="k1")
    second = _audit_genome(
        conn, subject.genome_hash, reviewer, reply=NO_CONCERN, idempotency_key="k1"
    )

    assert first.audit_id == second.audit_id
    assert second.probability == 0.2  # the first reply, not the second


def test_the_schema_refuses_a_second_opinion_from_the_same_auditor(conn):
    """`idx_genome_content_audits_one_opinion`: a *fresh* idempotency key from
    the same Auditor on the same subject must not buy a second, different
    opinion — the direct-insert version of the property, since the Python
    layer's idempotency-key check only catches a *repeated* key."""
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    _audit_genome(conn, subject.genome_hash, reviewer, reply=CONCERN, idempotency_key="first")

    with pytest.raises(Exception, match="UNIQUE constraint failed"):
        _audit_genome(conn, subject.genome_hash, reviewer, reply=NO_CONCERN, idempotency_key="second")


def test_the_schema_permits_a_second_opinion_from_a_different_auditor(conn):
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    first_reviewer = _cell(conn, "auditor1", CellType.AUDITOR)
    second_reviewer = _cell(conn, "auditor2", CellType.AUDITOR)
    _audit_genome(conn, subject.genome_hash, first_reviewer, reply=CONCERN)

    second = _audit_genome(conn, subject.genome_hash, second_reviewer, reply=NO_CONCERN)
    assert second.is_recorded


def test_the_schema_refuses_a_pairing_mismatch_by_direct_insert(conn):
    """Migration 0031's CHECK: `software_native_advantage` forbids a second
    genome, and `renamed_mechanism` requires one distinct from the first."""
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")

    with pytest.raises(Exception):
        conn.execute(
            """
            INSERT INTO genome_content_audits (
                audit_id, kind, genome_hash, compared_genome_hash, auditor_cell_id,
                status, verdict, summary, probability, prediction_id,
                wake_reason, created_at_utc, idempotency_key
            ) VALUES ('x', 'software_native_advantage', ?, ?, ?,
                      'recorded', 'no_concern', 'smuggled', 0.9, NULL,
                      'audit request', '2026-01-01T00:00:00+00:00', 'x-key')
            """,
            (subject.genome_hash, subject.genome_hash, reviewer.cell_id),
        )


# --- §10.4's precision record, kept separate from `auditor.Precision` -----------


def test_precision_reports_vindicated_and_wrongful_flags_separately(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    genuine = _cell(conn, "genuine", CellType.COMMERCIAL, market="market genuine")
    fake = _cell(conn, "fake", CellType.COMMERCIAL, market="market fake")

    right_flag = _audit_genome(
        conn, fake.genome_hash, reviewer, reply=CONCERN, idempotency_key="fake-audit"
    )
    wrong_flag = _audit_genome(
        conn, genuine.genome_hash, reviewer, reply=CONCERN, idempotency_key="genuine-audit"
    )
    # The claim is "genuinely program-native". A concern that was right
    # resolves the claim false; a wrongful one resolves it true.
    prediction.resolve(conn, right_flag.prediction_id, occurred=False, source="test")
    prediction.resolve(conn, wrong_flag.prediction_id, occurred=True, source="test")

    record = content_audit.precision(conn, reviewer.cell_id)
    assert record.flags_raised == 2
    assert record.flags_vindicated == 1
    assert record.wrongful_flags == 1
    assert record.flag_precision == pytest.approx(0.5)


def test_precision_is_unmeasured_before_any_resolution(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    _audit_genome(conn, subject.genome_hash, reviewer, reply=CONCERN)

    record = content_audit.precision(conn, reviewer.cell_id)
    assert record.flag_precision is None, "unmeasured, not perfect"


def test_a_rejected_audit_is_counted_but_not_as_a_flag(conn):
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    subject = _cell(conn, "subject", CellType.COMMERCIAL, market="a market")
    _audit_genome(conn, subject.genome_hash, reviewer, reply="garbage")

    record = content_audit.precision(conn, reviewer.cell_id)
    assert record.audits == 1
    assert record.rejected == 1
    assert record.flags_raised == 0


# --- structural guarantees ---------------------------------------------------------


def test_a_content_audit_never_reaches_a_cell():
    """§23.5: a Cell that could see it is scored on "genuine program-native
    advantage" or "not a renamed mechanism" learns to perform novelty rather
    than have it."""
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    for module in ("context.py", "deliberation.py"):
        assert "content_audit" not in _imported_modules(source_dir / module), (
            f"{module} can reach the content-audit module; a Cell that learns "
            "it is judged on §13.3/§13.4 learns to perform the judgment (§23.5)"
        )


def test_only_selection_consumes_a_content_audit():
    """`selection.py`'s `software_native_advantage` gate is the one deliberate
    consumer (see `test_selection.py`'s gate tests) — it reads only a
    *resolved* audit, never an unresolved one, which would be exactly the
    "estimated negative EV" shape §10.5 keeps out of an automatic decision.
    Nothing else may import this module until the same argument is made for
    it."""
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    allowed = {"content_audit.py", "selection.py", "cli.py", "golden.py"}
    consumers = sorted(
        path.name for path in source_dir.glob("*.py")
        if path.name not in allowed and "content_audit" in _imported_modules(path)
    )
    assert not consumers, (
        f"{consumers} imports content_audit before a deliberate wiring decision "
        "has been made about how a resolved judgment should be consumed"
    )


def test_the_reply_schema_has_no_field_naming_an_outcome():
    """Same shape as `auditor.AuditReply`, and the same reason: §0.3 binds the
    evaluator too. Structural, so a field cannot be added back quietly."""
    fields = content_audit.ContentAuditReply.model_fields
    assert set(fields) == {"verdict", "summary", "probability"}


def _imported_modules(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.update(node.module.split("."))
            if node.level:
                imported.update(alias.name for alias in node.names)
    return imported
