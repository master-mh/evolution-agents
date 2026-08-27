"""Auditor Cells and §23.2's independent summary (SPEC.md §23.2, §10.4, §0.3, §29.10).

The theme: §10.4 says Auditor reward is *precision-weighted* and §29's
acceptance criterion 10 is "Wrongful Auditor flags are penalised". Prose cannot
be penalised, so most of what these tests defend is the machinery that makes a
flag cost something — and the independence that makes it worth anything.
"""

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    auditor,
    cli,
    db,
    deliberation,
    ledger,
    lifecycle,
    population,
    prediction,
    providers,
)
from mitosis.models import Book, CellStatus, CellType, EntrySpec, PopulationLimits

LIMITS = PopulationLimits(
    max_living_cells=100,
    max_active_cells=100,
    max_parallel_experiments=20,
    max_births_per_epoch=50,
    max_lineage_population_fraction=1.0,
)

CONCERN = json.dumps(
    {
        "verdict": "concern",
        "summary": "claimed LOW, kernel assessed higher, and its record is unresolved",
        "probability": 0.2,
    },
    sort_keys=True,
)
NO_CONCERN = json.dumps(
    {"verdict": "no_concern", "summary": "proportionate and reversible", "probability": 0.8},
    sort_keys=True,
)


# --- fixtures ----------------------------------------------------------------


def _seed(conn):
    population.set_limits_if_absent(conn, LIMITS)
    for book, currency, amount in (
        (Book.USD_SIM, "USD", 500_000),
        (Book.USD_REAL, "USD", 50_000),
        (Book.RESOURCE, "RESOURCE", 500_000),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="external_capital_in",
            idempotency_key=f"seed:{book.value}",
            description="test seed",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id="seed_bank", amount_minor_units=amount),
            ],
        )


def _cell(conn, tag, cell_type=CellType.AUDITOR, *, fund=True):
    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=500,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
    )
    if fund:
        for book, currency, amount in (
            (Book.USD_REAL, "USD", 50),
            (Book.RESOURCE, "RESOURCE", 5_000),
        ):
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


def _queue_request(conn, subject, tag="s"):
    deliberation.deliberate(
        conn,
        cell_id=subject.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": "buy a sample dataset",
                    "rationale": "we think it converts",
                    "risk_tier": "LOW",
                    "estimated_cost_minor_units": 90,
                    "predictions": [],
                },
                sort_keys=True,
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    return next(r for r in approval.queue(conn) if r.cell_id == subject.cell_id)


def _audit(conn, request, auditor_cell, reply=CONCERN, **kwargs):
    return auditor.audit_request(
        conn,
        request_id=request.request_id,
        auditor_cell_id=auditor_cell.cell_id,
        provider=providers.MockProvider(reply=reply),
        model="mock-1",
        **kwargs,
    )


def _setup(conn):
    _seed(conn)
    subject = _cell(conn, "subject", CellType.COMMERCIAL)
    reviewer = _cell(conn, "auditor", CellType.AUDITOR)
    return subject, reviewer, _queue_request(conn, subject)


# --- §23.2: the field fills, and reads as absent when it should --------------


def test_an_unaudited_request_reports_no_summary_rather_than_a_clean_one(conn):
    """§23.2's summary must distinguish "nobody looked" from "looked and found
    nothing".

    A default of "no concerns" would be the most dangerous possible value: an
    operator glancing at the payload would read an absent Auditor as a passing
    one, which is the failure this field exists to prevent.
    """
    _, _, request = _setup(conn)

    detail = approval.payload(conn, request.request_id)
    assert detail.auditor_summary is None
    assert detail.audits == ()


def test_an_audit_fills_the_summary_with_attribution(conn):
    """§23.2 wants an *independent* summary, so whose it is matters.

    An unattributed summary reads as the kernel's own view, and the entire
    point of the clause is that it is somebody else's judgement.
    """
    _, reviewer, request = _setup(conn)
    result = _audit(conn, request, reviewer)

    detail = approval.payload(conn, request.request_id)
    assert detail.auditor_summary is not None
    assert reviewer.cell_id in detail.auditor_summary
    assert "concern" in detail.auditor_summary
    assert len(detail.audits) == 1
    assert result.subject_cell_id == request.cell_id


# --- independence (§23.2, §0.3) ---------------------------------------------


def test_a_cell_cannot_audit_its_own_request(conn):
    """§0.3: "a Cell may explain a result; it may never define the canonical
    result", and §23.2's word is *independent*.

    The proposing Cell already fills `cell_explanation`. If it could fill the
    Auditor summary too, the payload would show an operator the same Cell's
    view twice under two headings.
    """
    subject, _, request = _setup(conn)

    with pytest.raises(auditor.AuditError, match="cannot audit its own request"):
        _audit(conn, request, subject)


def test_only_oversight_cells_audit(conn):
    """§10.4 pairs Auditor and Immune as the oversight roles.

    A Commercial Cell auditing a competitor's request for capital is not an
    independent evaluator; it is an interested party with an incentive to see
    the request refused.
    """
    _, _, request = _setup(conn)
    rival = _cell(conn, "rival", CellType.COMMERCIAL)

    with pytest.raises(auditor.AuditError, match="only auditor/immune"):
        _audit(conn, request, rival)

    immune = _cell(conn, "immune", CellType.IMMUNE)
    assert _audit(conn, request, immune).verdict is auditor.Verdict.CONCERN


def test_a_relative_is_not_an_independent_auditor(conn):
    """A parent auditing its own child is not independent.

    Lineage is already §23.4's aggregation key (ADR-027) for the same reason:
    it is the cheapest thing a Cell can split itself across, so it is also the
    cheapest way to manufacture a friendly reviewer — reproduce, and audit
    yourself through your child.
    """
    _seed(conn)
    parent = _cell(conn, "parent", CellType.AUDITOR)
    child = lifecycle.reproduce_stub if False else None  # noqa: F841  (see below)

    # The subject and the auditor share a founder: the subject reproduces and
    # its own descendant tries to vouch for it.
    from mitosis import lineage

    subject = _cell(conn, "subject2", CellType.COMMERCIAL)
    relative = lineage.reproduce(
        conn,
        parent_cell_id=subject.cell_id,
        budget_minor_units=50,
        idempotency_key="relative",
    )
    for book, currency, amount in ((Book.USD_REAL, "USD", 50), (Book.RESOURCE, "RESOURCE", 5_000)):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_funding",
            idempotency_key=f"fund:relative:{book.value}",
            description="thinking budget",
            entries=[
                EntrySpec(
                    account_id="seed_bank", amount_minor_units=-amount, cell_id=relative.cell_id
                ),
                EntrySpec(
                    account_id=f"cell:{relative.cell_id}:cash",
                    amount_minor_units=amount,
                    cell_id=relative.cell_id,
                ),
            ],
        )
    conn.execute(
        "UPDATE cells SET cell_type = ? WHERE cell_id = ?",
        (CellType.AUDITOR.value, relative.cell_id),
    )
    conn.commit()

    request = _queue_request(conn, subject, tag="s2")
    assert relative.founder_cell_id == subject.founder_cell_id

    with pytest.raises(auditor.AuditError, match="shares lineage"):
        _audit(conn, request, lifecycle.get_cell(conn, relative.cell_id))

    # An unrelated Auditor of the same type is fine, which is what makes the
    # refusal above about lineage rather than about types.
    assert _audit(conn, request, parent).verdict is auditor.Verdict.CONCERN


def test_a_quarantined_auditor_cannot_audit(conn):
    """§18.2, and Charter C8 for dead.

    A Cell under restriction whose word still moves capital through the
    approval payload is restricted in name only — and quarantine is exactly the
    state a Cell is in when the colony has stopped trusting its output.
    """
    _, reviewer, request = _setup(conn)
    lifecycle.quarantine(conn, reviewer.cell_id, reason="under review")

    with pytest.raises(auditor.AuditError, match="quarantined"):
        _audit(conn, request, reviewer)


def test_an_auditor_must_pay_for_its_own_thinking(conn):
    """§15.4. An audit is a model call, and the Auditor buys it.

    Refused before the gateway rather than inside it, so the failure is a clean
    message instead of an exception with a reservation half-made.
    """
    _seed(conn)
    subject = _cell(conn, "subject", CellType.COMMERCIAL)
    broke = _cell(conn, "broke", CellType.AUDITOR, fund=False)
    request = _queue_request(conn, subject)

    with pytest.raises(auditor.AuditError, match="pay for its own thinking"):
        _audit(conn, request, broke)


# --- §10.4: the flag has to cost something ----------------------------------


def test_every_audit_registers_a_prediction(conn):
    """§10.4's precision-weighting and §29.10 both require a flag to be
    penalisable, and prose is not.

    This is the mechanism that makes "wrongful flags are penalised" true at
    all: the Auditor's probability enters the same hash-chained register every
    other Cell is scored in, before the outcome is known.
    """
    _, reviewer, request = _setup(conn)
    result = _audit(conn, request, reviewer)

    registered = prediction.get(conn, result.prediction_id)
    assert registered is not None
    assert registered.cell_id == reviewer.cell_id
    assert registered.probability == 0.2
    assert registered.outcome is None, "registered before the outcome is known (§8.5)"


def test_a_wrongful_flag_is_penalised(conn):
    """§29's acceptance criterion 10, in one test.

    The Auditor raised a concern at p=0.2 and the request achieved its claim.
    That is a false positive, and §10.4 says penalise it. The penalty is the
    Auditor's own calibration: Brier (0.2 - 1)^2 = 0.64, far worse than the
    0.25 an Auditor scores by knowing nothing.
    """
    _, reviewer, request = _setup(conn)
    result = _audit(conn, request, reviewer)
    prediction.resolve(conn, result.prediction_id, occurred=True, source="it worked")

    record = auditor.precision(conn, reviewer.cell_id)
    assert record.flags_raised == 1
    assert record.wrongful_flags == 1
    assert record.flags_vindicated == 0
    assert record.flag_precision == 0.0
    assert record.mean_brier == pytest.approx(0.64)


def test_a_vindicated_flag_scores_well(conn):
    """The mirror: §10.4's "reward valid detected errors"."""
    _, reviewer, request = _setup(conn)
    result = _audit(conn, request, reviewer)
    prediction.resolve(conn, result.prediction_id, occurred=False, source="it failed")

    record = auditor.precision(conn, reviewer.cell_id)
    assert record.flags_vindicated == 1
    assert record.wrongful_flags == 0
    assert record.flag_precision == 1.0
    assert record.mean_brier == pytest.approx(0.04)


def test_precision_is_unmeasured_rather_than_perfect_before_resolution(conn):
    """An Auditor with no resolved flags has *no* record, not a spotless one.

    Reporting 1.0 would rank a brand-new Auditor above one with a real history
    — the same error `promotion.transfer_degradation` avoids by reporting NULL
    rather than 0.
    """
    _, reviewer, request = _setup(conn)
    _audit(conn, request, reviewer)

    record = auditor.precision(conn, reviewer.cell_id)
    assert record.flags_raised == 1
    assert record.flags_resolved == 0
    assert record.flag_precision is None
    assert record.mean_brier is None


def test_precision_is_reported_beside_the_counts_not_alone(conn):
    """§10.2 forbids collapsing dimensions, and here the reason is concrete.

    Flag precision on its own is trivially maximised by never flagging
    anything: a silent Auditor has no wrongful flags and would rank top. The
    counts are what expose that strategy, so they travel with the ratio.
    """
    _, reviewer, request = _setup(conn)
    _audit(conn, request, reviewer, reply=NO_CONCERN)

    record = auditor.precision(conn, reviewer.cell_id)
    assert record.audits == 1
    assert record.flags_raised == 0
    assert record.flag_precision is None, "never flagging is unmeasured, not perfect"


def test_a_costless_hedged_flag_is_refused(conn):
    """The gap between what the operator reads and what the Auditor is scored on.

    An Auditor that says `concern` while predicting a 90% chance of success
    gets the operator's attention for free: the alarm is prose, and the number
    it will actually be judged by says the opposite. Refusing the incoherent
    pair is what keeps the verdict and the stake the same claim.

    Refused means *rejected and recorded*, not raised — the call is already
    paid for by then.
    """
    _, reviewer, request = _setup(conn)
    hedged = json.dumps(
        {"verdict": "concern", "summary": "worried, sort of", "probability": 0.9},
        sort_keys=True,
    )

    result = _audit(conn, request, reviewer, reply=hedged)
    assert not result.is_recorded
    assert "incoherent" in result.failure_reason
    assert result.prediction_id is None, "nothing was staked, so nothing is registered"
    assert approval.payload(conn, request.request_id).auditor_summary is None

    inverted = json.dumps(
        {"verdict": "no_concern", "summary": "fine, probably not", "probability": 0.1},
        sort_keys=True,
    )
    second = _audit(conn, request, reviewer, reply=inverted, idempotency_key="second")
    assert not second.is_recorded
    assert "incoherent" in second.failure_reason


def test_the_auditor_does_not_write_the_claim_it_is_scored_on(conn):
    """§0.3 binds the independent evaluator too.

    An Auditor allowed to phrase its own claim would phrase an unfalsifiable
    one — "this request carries some risk" is never wrong — and its calibration
    record would become decorative. The claim is composed by the kernel from
    the request, and the Auditor supplies only a number and prose.
    """
    _, reviewer, request = _setup(conn)
    result = _audit(conn, request, reviewer)

    registered = prediction.get(conn, result.prediction_id)
    assert request.request_id in registered.claim
    assert "achieves what its proposal claims" in registered.claim
    # Nothing the Auditor wrote reaches the claim.
    assert "claimed LOW" not in registered.claim


# --- an audit advises, it never blocks (§10.4) -------------------------------


def test_an_audit_does_not_block_approval(conn):
    """§10.4 penalises "unnecessary blocking", and §23.2 asks only that the
    summary be *shown*.

    An Auditor with a veto is a second approver, which is a governance change
    nobody argued for — and it would make flagging strictly better than not,
    inverting the incentive the rest of this module builds.
    """
    _, reviewer, request = _setup(conn)
    _audit(conn, request, reviewer)

    grant = approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="noted, proceeding"
    )
    assert grant is not None


def test_no_approval_path_consults_an_audit():
    """Structural, because the runtime consequence is a silent veto.

    `approval.py` reads the `audits` table to *render* §23.2's field — that is
    the clause being satisfied. What it must never do is let an audit change a
    decision: no branch on a verdict, and no import of the module that owns
    auditing (which would also close a dependency cycle).
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    approval_source = (source_dir / "approval.py").read_text()

    imported = set()
    for node in ast.walk(ast.parse(approval_source)):
        if isinstance(node, ast.ImportFrom) and node.level:
            imported.update(alias.name for alias in node.names)
    assert "auditor" not in imported, (
        "approval.py must not import auditor — an audit that could reach a "
        "decision is a veto, and §10.4 penalises unnecessary blocking"
    )

    for forbidden in ("Verdict.CONCERN", "'concern'", '"concern"'):
        assert forbidden not in approval_source, (
            f"approval.py branches on {forbidden}: a decision path that reads a "
            "verdict is a veto by another name"
        )


# --- idempotency and one-audit-per-auditor ----------------------------------


def test_a_repeated_audit_returns_the_first_and_buys_no_second_call(conn):
    """Charter C6, and the money is the point.

    A redelivered audit that bought a second model call would spend real money
    on redelivery — and would let an Auditor quietly replace an opinion that
    aged badly.
    """
    _, reviewer, request = _setup(conn)
    first = _audit(conn, request, reviewer)
    second = _audit(conn, request, reviewer, reply=NO_CONCERN)

    assert second.audit_id == first.audit_id
    assert second.verdict is auditor.Verdict.CONCERN, "the first opinion stands"
    calls = conn.execute(
        "SELECT COUNT(*) AS n FROM model_calls WHERE cell_id = ?", (reviewer.cell_id,)
    ).fetchone()["n"]
    assert calls == 1


def test_a_second_auditor_may_audit_the_same_request(conn):
    """Two independent opinions are evidence; the same opinion twice is not.

    So the constraint is one audit per *Auditor* per request, not one audit per
    request — and both appear in the payload separately, because an operator
    reading "two Auditors agree" needs to know they were two.
    """
    _, first_reviewer, request = _setup(conn)
    second_reviewer = _cell(conn, "auditor2", CellType.AUDITOR)

    _audit(conn, request, first_reviewer, reply=CONCERN)
    _audit(conn, request, second_reviewer, reply=NO_CONCERN)

    detail = approval.payload(conn, request.request_id)
    assert len(detail.audits) == 2
    assert first_reviewer.cell_id in detail.auditor_summary
    assert second_reviewer.cell_id in detail.auditor_summary


def test_a_decided_request_cannot_be_audited(conn):
    """Evidence produced after a decision is not evidence for it.

    Allowing it would let an audit be filed against a request that already
    succeeded or failed, which is the same defect re-resolving a prediction
    would be — a record improved once the answer is visible.
    """
    _, reviewer, request = _setup(conn)
    approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="fine"
    )

    with pytest.raises(auditor.AuditError, match="auditing a decided request"):
        _audit(conn, request, reviewer)


# --- the reply parser --------------------------------------------------------


def test_an_unusable_reply_is_recorded_rather_than_raised(conn):
    """The money is why. The gateway commits before the reply is parsed
    (ADR-022), so by the time a reply turns out to be garbage the Auditor has
    already paid for it.

    Raising would leave real spend with nothing explaining what it bought, and
    would hide an Auditor that reliably produces nothing — which §10.4 needs to
    see. The reply is still never salvaged: no verdict is invented, no
    probability is guessed, and §23.2's field stays empty.
    """
    _, reviewer, request = _setup(conn)

    result = _audit(conn, request, reviewer, reply="I have concerns about this one.")
    assert not result.is_recorded
    assert "not JSON" in result.failure_reason
    assert result.verdict is None and result.probability is None
    assert result.model_call_id is not None, "the call happened and is linked"

    # §23.2's field must not show a rejected audit as an opinion.
    assert approval.payload(conn, request.request_id).auditor_summary is None

    schema_violation = _audit(
        conn,
        request,
        reviewer,
        reply=json.dumps({"verdict": "concern", "summary": "x"}),
        idempotency_key="missing-probability",
    )
    assert not schema_violation.is_recorded

    record = auditor.precision(conn, reviewer.cell_id)
    assert record.rejected == 2
    assert record.flags_raised == 0, "a rejected reply is neither a flag nor a clearance"


def test_certainty_is_refused(conn):
    """`prediction.py`'s rule, inherited: the log score of a
    confident-and-wrong claim is infinite, and one such flag would pin an
    Auditor's mean at -inf permanently, leaving the population unorderable."""
    _, reviewer, request = _setup(conn)
    certain = json.dumps(
        {"verdict": "concern", "summary": "certain this fails", "probability": 0.0},
        sort_keys=True,
    )

    result = _audit(conn, request, reviewer, reply=certain)
    assert not result.is_recorded
    assert result.prediction_id is None


def test_the_prompt_renders_enum_choices_as_a_string_not_a_list():
    """The bug the first live model run found, in a second prompt.

    `deliberation`'s schema hint once rendered `"risk_tier": ["LOW", ...]`, and
    the model returned `["MEDIUM"]` — a correct choice in the wrong shape,
    because the prompt showed the field as a list. A mock provider cannot find
    this, since its reply is an input rather than a response to these words. So
    this module reuses `proposal._one_of` rather than re-deriving the
    rendering, and this test pins that it did.
    """
    schema = auditor._prompt_schema()
    assert isinstance(schema["verdict"], str)
    assert "exactly one of" in schema["verdict"]
    assert "concern | no_concern" in schema["verdict"]


def test_the_brief_shows_the_assessed_tier_not_only_the_claimed_one(conn):
    """§23.5: a Cell optimises against the review path it can see.

    An Auditor briefed only on the tier the subject claimed would be reviewing
    the subject's framing. The kernel's assessed tier is the one thing in the
    brief the subject provably cannot set.
    """
    subject, reviewer, request = _setup(conn)
    detail = approval.payload(conn, request.request_id)
    brief = auditor._brief(conn, detail, lifecycle.get_cell(conn, subject.cell_id))

    assert "assessed risk tier" in brief
    assert detail.request.assessed_tier.value in brief
    assert "overdue" in brief, "§23.2's evidence half must reach the Auditor"


# --- CLI ---------------------------------------------------------------------


def test_audit_cli_end_to_end(tmp_path, capsys):
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    connection = db.connect_and_migrate(db_path)
    _seed(connection)
    subject = _cell(connection, "subject", CellType.COMMERCIAL)
    reviewer = _cell(connection, "auditor", CellType.AUDITOR)
    request = _queue_request(connection, subject)
    connection.close()
    capsys.readouterr()

    exit_code = cli.main(
        [
            "--db",
            str(db_path),
            "audit",
            request.request_id,
            "--auditor",
            reviewer.cell_id,
            "--provider",
            "mock",
        ]
    )
    # `--provider mock` produces the mock's default reply, which is not
    # audit-shaped — so this exercises the *rejected* branch, and that is the
    # honest thing for it to exercise. `MockProvider`'s reply is a constructor
    # argument (§7.3 wants it configurable) and the CLI has no flag to set it,
    # so the recorded branch is covered by the module-level tests above, where
    # a reply can actually be injected.
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "REJECTED" in out
    assert "paid for this call and produced nothing usable" in out

    assert cli.main(["--db", str(db_path), "auditor-record", "--cell", reviewer.cell_id]) == 0
    record_out = capsys.readouterr().out
    assert "flag precision" in record_out
    assert "wrongful" in record_out
    assert "rejected replies:  1" in record_out, (
        "a paid call that produced nothing must show up in the Auditor's record"
    )


def test_audit_cli_refuses_a_dependent_auditor(tmp_path, capsys):
    db_path = tmp_path / "colony.db"
    cli.main(["--db", str(db_path), "init"])
    connection = db.connect_and_migrate(db_path)
    _seed(connection)
    subject = _cell(connection, "subject", CellType.COMMERCIAL)
    request = _queue_request(connection, subject)
    connection.close()
    capsys.readouterr()

    exit_code = cli.main(
        [
            "--db",
            str(db_path),
            "audit",
            request.request_id,
            "--auditor",
            subject.cell_id,
            "--provider",
            "mock",
        ]
    )
    assert exit_code == 1
    assert "cannot audit its own request" in capsys.readouterr().err
