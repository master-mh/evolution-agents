"""Rights a person establishes (SPEC.md §20.1, §20.2, §20.3, §0.3, §3.6;
Charter C13; ADR-041).

ADR-035 built §20.2's inheritance in one direction: rights tighten, never
loosen, so an artifact built on a fetched page was `commercial_use: unknown`
forever and `real_commerce` could be opened and still sell nothing. These
defend the other direction and the four things it must not become — a laundering
path a Cell can reach (§0.3), a rewrite of what an artifact was born with (§3.6),
a way past Charter C13, and a position looser than the one a person actually
stated.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import (
    approval,
    artifacts,
    db,
    deliberation,
    lifecycle,
    providers,
    rights,
    tool_registry,
    tools,
)
from mitosis import ledger
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec

GENOME = {"market": "independent bookshops", "workflow": "read, then write"}
URL = "https://example.com/pricing"
OTHER_URL = "https://other.test/rates"

SRC = pathlib.Path(artifacts.__file__).parent

#: The only two modules that may write an attestation: the operator's CLI, and
#: the golden run, which drives an operator's actions in a replay.
ATTESTATION_WRITERS = {"cli.py", "golden.py", "rights.py"}


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


class FakeFetcher:
    def __init__(self, *, commercial_use="unknown", licence="unknown", personal=False):
        self.commercial_use, self.licence, self.personal = commercial_use, licence, personal

    def fetch(self, url, *, max_bytes):
        return tool_registry.FetchResult(
            text="Widgets cost £4.",
            http_status=200,
            source=url,
            licence=self.licence,
            permitted_uses="review only",
            commercial_use=self.commercial_use,
            contains_personal_data=self.personal,
        )


def _fund(conn, cell, amount: int = 50_000) -> None:
    for book, currency in (
        (Book.USD_REAL, "USD"),
        (Book.RESOURCE, "RESOURCE"),
        (Book.USD_SIM, "USD"),
    ):
        ledger.post_transaction(
            conn,
            book=book,
            currency=currency,
            transaction_type="cell_birth_funding",
            idempotency_key=f"fund:{cell.cell_id}:{book.value}",
            description="fund",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id),
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )


def _make_cell(conn, *, key="a"):
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key=key,
        genome_content=GENOME,
    )
    conn.commit()
    _fund(conn, cell)
    return lifecycle.get_cell(conn, cell.cell_id)


def _fetched(conn, cell, *, url=URL, key="t", **fetcher_kwargs) -> str:
    """Drive a real tool call and return its id, so the provenance is genuine
    rather than a fixture asserting against itself."""
    tools.set_autonomy(conn, flag="public_web_read", enabled=True)
    domain = rights.host_of(url)
    tools.allow_domain(conn, domain=domain, added_by="op", reason="fixture")
    reply = json.dumps(
        {
            "kind": "tool_request",
            "summary": "read the price page",
            "rationale": "need a price",
            "risk_tier": "LOW",
            "estimated_cost_minor_units": 0,
            "predictions": [],
            "tool_request": {"tool": "http_get", "arguments": {"url": url}},
        }
    )
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=reply),
        wake_key=f"tw:{cell.cell_id}:{key}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(r for r in approval.queue(conn) if r.proposal_id == result.proposal_id)
    grant = approval.approve(
        conn, request_id=request.request_id, decided_by="op", reason="fixture"
    )
    call = tools.execute_grant(
        conn,
        grant_id=grant.grant_id,
        executed_by="op",
        reason="fixture",
        fetcher=FakeFetcher(**fetcher_kwargs),
    )
    return call.tool_call_id


def _attest(conn, *, domain=None, colony=False, commercial_use="permitted",
            licence="CC-BY-4.0", by="operator", basis="the publisher's licensing page"):
    return rights.attest(
        conn,
        subject_kind=rights.SUBJECT_COLONY if colony else rights.SUBJECT_DOMAIN,
        subject=rights.SUBJECT_COLONY if colony else domain,
        licence=licence,
        permitted_uses="redistribution and resale with attribution",
        commercial_use=commercial_use,
        basis=basis,
        attested_by=by,
    )


def _refused(conn, artifact_id, *, commercial=True) -> bool:
    try:
        artifacts.check_exportable(conn, artifact_id, commercial=commercial)
        return False
    except artifacts.ExportRefused:
        return True


# --- the gap this closes ------------------------------------------------------


def test_an_attested_source_makes_an_existing_artifact_commercially_exportable(conn):
    """§20.2 gates commercial export on `permitted`; ADR-041 is the only way to
    reach it for anything derived from a fetch.

    The headline property, and the one four slices flagged as missing: an
    artifact that *already exists* becomes sellable when a person establishes
    its source's licence. If this fails, `real_commerce` can be opened and every
    listing is still refused at the export gate.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert _refused(conn, artifact.artifact_id), "unattested source should refuse"

    _attest(conn, domain="example.com")

    assert not _refused(conn, artifact.artifact_id)


def test_attesting_does_not_rewrite_what_an_artifact_was_born_with(conn):
    """§3.6 — "never edit history to correct something; post a new, signed
    adjustment".

    The stored row is the position at creation. If an attestation cascaded into
    it, an artifact exported non-commercially under `unknown` would afterwards
    read as having been `permitted` at the time, which is not what happened.
    The attestation is the adjustment; the row is the memory.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    _attest(conn, domain="example.com")

    stored = artifacts.get(conn, artifact.artifact_id)
    assert stored.commercial_use == "unknown"
    assert stored.licence == artifact.licence
    assert artifacts.effective_provenance(conn, artifact.artifact_id).commercial_use == "permitted"


def test_an_artifact_made_after_the_attestation_is_born_permitted(conn):
    """The forward direction. An attestation is about a *source*, so it reaches
    every artifact built on it — including ones that do not exist yet.

    This is what makes the subject a source rather than an artifact: per-artifact
    stamping would leave the next artifact from the same page `unknown` again,
    reopening the gap on every new deliverable.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    _attest(conn, domain="example.com")

    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert artifact.commercial_use == "permitted"
    assert artifact.licence == "CC-BY-4.0"


def test_a_derived_artifact_inherits_the_attested_position(conn):
    """§20.2's inheritance runs through artifacts as well as tool calls, so the
    effective position has to recurse. If it stopped at the first hop, an
    artifact built on an artifact built on an attested page would be `unknown`
    — and "summarise it once more" would become a way to *lose* rights.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    first = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    second = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices, restated",
        content="Widgets cost four pounds.", source_artifact_ids=(first.artifact_id,),
    )
    assert _refused(conn, second.artifact_id)

    _attest(conn, domain="example.com")

    assert not _refused(conn, second.artifact_id)
    assert artifacts.effective_provenance(conn, second.artifact_id).commercial_use == "permitted"


# --- what it must not become --------------------------------------------------


def test_one_attested_source_cannot_wash_out_an_unattested_one(conn):
    """§20.2's most-restrictive-wins still governs *between* sources.

    An attestation replaces what one source reported; it does not decide the
    artifact. If this fails, citing one CC-BY page alongside a licence-unknown
    one launders the second — exactly the path ADR-035 closed, reopened from
    the operator's side.
    """
    cell = _make_cell(conn)
    attested_call = _fetched(conn, cell, url=URL, key="a")
    other_call = _fetched(conn, cell, url=OTHER_URL, key="b")
    _attest(conn, domain="example.com")

    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Both",
        content="Two sources.", source_tool_call_ids=(attested_call, other_call),
    )
    assert artifact.commercial_use == "unknown"
    assert _refused(conn, artifact.artifact_id)


def test_charter_c13_refuses_regardless_of_any_attestation(conn):
    """Charter C13 / §18.2 is absolute and is not a rights question.

    An adversarial-taint artifact may never leave the colony, commercial or
    not. No operator statement about a licence can reach that gate — if it
    could, ADR-041 would have opened a route around the one Charter clause the
    export gateway exists to enforce.
    """
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Tainted", content="x",
        own_provenance=artifacts.Provenance(
            licence="colony-authored", permitted_uses="none", commercial_use="unknown",
            contains_personal_data=False, retention_rule="n/a", source_summary="sim",
            taint_labels=(artifacts.TAINT_SIM_ADVERSARIAL,),
        ),
    )
    _attest(conn, colony=True)

    assert _refused(conn, artifact.artifact_id, commercial=True)
    assert _refused(conn, artifact.artifact_id, commercial=False)


def test_the_effective_taint_matches_the_stored_taint(conn):
    """`check_exportable` reads taint from the stored row and rights from the
    effective fold, and that split is only safe while taint cannot drift.

    Taint unions from sources and no attestation touches it, so the two must
    agree for every artifact. This test is what defends that reasoning: if a
    future change ever lets taint be re-derived differently, C13's gate would be
    reading the weaker of two answers and nothing else would say so.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    made = [
        artifacts.create(
            conn, cell_id=cell.cell_id, kind="report", title="Prices",
            content="Widgets £4.", source_tool_call_ids=(call,),
        ),
        artifacts.create(
            conn, cell_id=cell.cell_id, kind="report", title="Alone", content="No sources."
        ),
    ]
    made.append(
        artifacts.create(
            conn, cell_id=cell.cell_id, kind="report", title="Derived",
            content="From the first.", source_artifact_ids=(made[0].artifact_id,),
        )
    )
    _attest(conn, domain="example.com")

    for artifact in made:
        effective = artifacts.effective_provenance(conn, artifact.artifact_id)
        assert set(effective.taint_labels) == set(artifact.taint_labels), artifact.title


def test_a_producer_may_not_declare_its_own_content_commercially_permitted(conn):
    """§0.3 — "a Cell may explain a result; it may never define the canonical
    result", applied to rights.

    With no sources, `own_provenance` alone decides the artifact's position, so
    a producer able to declare `permitted` would be defining the single fact
    standing between the colony and selling something. The same asymmetry §23.5
    forces on `claimed_tier`: a Cell may make its own position worse, never
    better.
    """
    cell = _make_cell(conn)
    with pytest.raises(artifacts.ArtifactError, match="§0.3"):
        artifacts.create(
            conn, cell_id=cell.cell_id, kind="report", title="Self-granted", content="mine",
            own_provenance=artifacts.Provenance(
                licence="colony-authored", permitted_uses="anything",
                commercial_use="permitted", contains_personal_data=False,
                retention_rule="n/a", source_summary="", taint_labels=(),
            ),
        )


def test_a_producer_may_still_declare_its_own_content_prohibited(conn):
    """The other half of the same asymmetry: tightening is always allowed.

    A clamp that refused every `own_provenance` would be a different rule, and
    a worse one — a producer that knows its content may not be sold should be
    able to say so.
    """
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Careful", content="mine",
        own_provenance=artifacts.Provenance(
            licence="colony-authored", permitted_uses="internal only",
            commercial_use="prohibited", contains_personal_data=False,
            retention_rule="n/a", source_summary="", taint_labels=(),
        ),
    )
    assert artifact.commercial_use == "prohibited"
    _attest(conn, colony=True)
    # The colony attestation applies only where nothing was declared.
    assert artifacts.effective_provenance(conn, artifact.artifact_id).commercial_use == "prohibited"


def test_the_refusal_names_a_remedy_the_operator_can_act_on(conn):
    """An artifact that read nothing has no source to attest, so telling its
    operator to "establish the rights position on its sources" is advice that
    cannot be followed.

    A small thing, and exactly the shape this repo keeps finding in its own
    prose: a message asserting a route that does not exist for the case in hand.
    The two artifacts need two different remedies and the refusal has to know
    which it is looking at.
    """
    cell = _make_cell(conn)
    sourceless = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Unaided", content="ours"
    )
    call = _fetched(conn, cell)
    derived = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )

    with pytest.raises(artifacts.ExportRefused, match="--colony"):
        artifacts.check_exportable(conn, sourceless.artifact_id, commercial=True)
    with pytest.raises(artifacts.ExportRefused, match="--domain"):
        artifacts.check_exportable(conn, derived.artifact_id, commercial=True)


# --- the matching rule --------------------------------------------------------


def test_matching_is_exact_host_and_not_a_dotted_suffix(conn):
    """Deliberately unlike the Charter C12 egress allowlist beside it.

    `_check_egress_locked` matches `example.com` or anything under it, because
    over-matching there means *reading* a page the operator did not picture.
    Over-matching here means selling material under a licence that never
    covered it — §20.3's "legal liabilities if its data use is invalid". Same
    key shape, opposite consequence, so the looser rule is not inherited.
    """
    _attest(conn, domain="example.com")
    assert rights.current_for_url(conn, "https://example.com/a").commercial_use == "permitted"
    assert rights.current_for_url(conn, "https://docs.example.com/a") is None
    assert rights.current_for_url(conn, "https://notexample.com/a") is None


def test_a_subdomain_source_is_not_covered_by_the_parent_domain(conn):
    """The same rule where it actually bites: through the artifact.

    A test that only checked `current_for_url` would pass against a fold that
    resolved the host some other way.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell, url="https://docs.example.com/pricing")
    _attest(conn, domain="example.com")

    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert artifact.commercial_use == "unknown"
    assert _refused(conn, artifact.artifact_id)


def test_a_domain_attestation_refuses_a_url(conn):
    """A rights position that depended on a path or query string could not be
    matched to a later fetch of the same page — so the subject has to be the
    bare host, and saying so loudly beats normalising silently."""
    for bad in ("https://example.com/docs", "example.com/docs", "example.com:443"):
        with pytest.raises(rights.RightsError, match="bare domain"):
            _attest(conn, domain=bad)


# --- what the operator has to say ---------------------------------------------


def test_commercial_permitted_needs_a_named_licence(conn):
    """The one part of the operator's judgement the kernel can check.

    "You may sell this, and I cannot tell you under what" is not a rights
    position — it is the shape a hurried wave-through takes, and §20.3 makes it
    a liability rather than a mistake. Refusing it means the attestation that
    opens §20.2's gate always carries the thing a dispute would ask for.
    """
    for unnamed in ("unknown", "", "  ", "n/a"):
        with pytest.raises(rights.RightsError, match="named licence"):
            _attest(conn, domain="example.com", licence=unnamed)


def test_an_attestation_must_state_its_basis(conn):
    """§20.3. The same rule `export` applies to its reason.

    A fetched page can assert its own licence in its own body and a Cell chooses
    what to fetch, so an operator reading that claim back is being told what to
    attest by the material under attestation. A required basis is what keeps
    "the publisher's licensing page" distinguishable from "the page said so".
    """
    with pytest.raises(rights.RightsError, match="basis"):
        _attest(conn, domain="example.com", basis="   ")


def test_an_attestation_must_name_who_made_it(conn):
    """§0.3 — the record has to name a person, because the whole point is that
    this is not the colony's own claim about itself."""
    with pytest.raises(rights.RightsError, match="who made it"):
        _attest(conn, domain="example.com", by=" ")


# --- §3.6: append-only, latest wins, withdrawal is an adjustment ---------------


def test_the_latest_attestation_wins(conn):
    """Supersession, not mutation. Both rows survive."""
    first = _attest(conn, domain="example.com", licence="CC-BY-4.0")
    second = _attest(
        conn, domain="example.com", licence="CC-BY-SA-4.0", basis="publisher corrected it"
    )
    assert rights.current(
        conn, subject_kind="domain", subject="example.com"
    ).attestation_id == second.attestation_id
    assert {a.attestation_id for a in rights.history(conn)} == {
        first.attestation_id, second.attestation_id
    }


def test_withdrawing_closes_the_gate_and_leaves_the_reason_on_the_record(conn):
    """§3.6's adjustment rather than a delete.

    Withdrawing is an attestation of `unknown` carrying its own basis, so the
    record says *why* a position was withdrawn. A `revoked` flag would leave an
    absence, and deleting the row would leave nothing at all — while a commercial
    export made in between would become unexplainable.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    _attest(conn, domain="example.com")
    assert not _refused(conn, artifact.artifact_id)

    withdrawal = _attest(
        conn, domain="example.com", commercial_use="unknown", licence="unknown",
        basis="publisher changed terms on 2026-08-24",
    )
    assert withdrawal.is_withdrawal
    assert _refused(conn, artifact.artifact_id)
    assert len(rights.history(conn, subject_kind="domain", subject="example.com")) == 2
    assert "publisher changed terms" in rights.history(conn)[0].basis


def test_an_attestation_can_tighten_as_well_as_loosen(conn):
    """An attestation states a fact, and facts can be worse than the fetcher
    assumed. If only loosening were possible, an operator who discovered a
    source was expressly non-commercial could not record it.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell, commercial_use="permitted", licence="MIT")
    _attest(conn, domain="example.com", commercial_use="prohibited", licence="proprietary")

    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert artifact.commercial_use == "prohibited"
    assert _refused(conn, artifact.artifact_id)


def test_ordering_is_by_insertion_not_by_wall_clock(conn):
    """§6.3 keeps the simulated and wall clocks unmixed, so a timestamp is not a
    total order here — two attestations inside one second, or a corrected clock,
    would otherwise leave "which position is in force" undefined. Insertion
    order always answers.
    """
    past = datetime.now(timezone.utc) - timedelta(days=30)
    rights.attest(
        conn, subject_kind="domain", subject="example.com", licence="CC-BY-4.0",
        permitted_uses="resale", commercial_use="permitted", basis="first",
        attested_by="operator",
    )
    later_row_earlier_clock = rights.attest(
        conn, subject_kind="domain", subject="example.com", licence="unknown",
        permitted_uses="review only", commercial_use="unknown", basis="withdrawn",
        attested_by="operator", now=past,
    )
    in_force = rights.current(conn, subject_kind="domain", subject="example.com")
    assert in_force.attestation_id == later_row_earlier_clock.attestation_id
    assert in_force.commercial_use == "unknown"


# --- the colony as a subject --------------------------------------------------


def test_a_colony_attestation_makes_source_less_work_sellable(conn):
    """`inherit_provenance` starts an artifact that read nothing at `unknown`,
    saying outright that whether the colony may sell its own output "is a
    question for a person, not a default". Nothing could ask the person.

    A domain attestation cannot reach this case — there is no domain — which is
    why the subject kind is required rather than implied.
    """
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Our own", content="We wrote this."
    )
    assert _refused(conn, artifact.artifact_id)

    _attest(conn, colony=True, licence="colony-owned, all rights reserved")

    assert not _refused(conn, artifact.artifact_id)


def test_a_colony_attestation_does_not_reach_an_artifact_built_on_a_page(conn):
    """Scope. An artifact citing a fetched page is not the colony's own work,
    so its rights come from the page. If the colony position leaked into it,
    one statement about the colony's own output would launder every source it
    ever read.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    _attest(conn, colony=True, licence="colony-owned, all rights reserved")

    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert artifact.commercial_use == "unknown"
    assert _refused(conn, artifact.artifact_id)


def test_the_colony_is_a_single_subject(conn):
    """One colony, one row-space — not a namespace an operator can shard."""
    with pytest.raises(rights.RightsError, match="single subject"):
        rights.attest(
            conn, subject_kind=rights.SUBJECT_COLONY, subject="some-other-colony",
            licence="x", permitted_uses="y", commercial_use="unknown",
            basis="b", attested_by="operator",
        )


# --- the record ---------------------------------------------------------------


def test_an_export_records_the_position_that_authorised_it(conn):
    """After ADR-041 the row's `commercial_use` need not be what the gate
    applied, so an audit trail naming only the row would make a commercial
    export look like the gate had failed open."""
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    _attest(conn, domain="example.com")
    artifacts.export(
        conn, artifact_id=artifact.artifact_id, exported_by="operator",
        reason="sold to a customer", commercial=True,
    )
    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'artifact_exported'"
    ).fetchone()
    metadata = json.loads(row["metadata_json"])
    assert metadata["commercial_use_at_creation"] == "unknown"
    assert metadata["commercial_use_effective"] == "permitted"
    assert metadata["licence_effective"] == "CC-BY-4.0"


def test_attesting_records_what_it_displaced(conn):
    """A bare "now permitted" does not say whether anything was overturned, and
    an attestation that *loosens* a position is the one a review wants to find.
    """
    first = _attest(conn, domain="example.com", commercial_use="prohibited",
                    licence="proprietary")
    _attest(conn, domain="example.com", commercial_use="permitted", licence="CC-BY-4.0",
            basis="publisher relicensed")
    events = [
        json.loads(r["metadata_json"])
        for r in conn.execute(
            "SELECT metadata_json FROM audit_events WHERE event_type = 'rights_attested' "
            "ORDER BY rowid"
        )
    ]
    assert events[0]["supersedes"] is None
    assert events[1]["supersedes"] == first.attestation_id
    assert events[1]["previous_commercial_use"] == "prohibited"


def test_a_cell_sees_the_position_in_force_for_its_own_work(conn):
    """§15.2's artifact index feeds the prompt a Cell deliberates against.

    If it showed the stored column, an operator could establish a source's
    rights and the Cell whose work had just become sellable would still read
    `unknown` — and would not propose selling it. That moves this slice's gap
    one step upstream rather than closing it, and moves it somewhere quieter:
    the export gate would be open and nothing would ever reach it.

    Reading a position is not §0.3-sensitive. Defining one is, and this does
    not let a Cell do that.
    """
    cell = _make_cell(conn)
    call = _fetched(conn, cell)
    artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices",
        content="Widgets £4.", source_tool_call_ids=(call,),
    )
    assert artifacts.index_for(conn, cell.cell_id)[0]["commercial_use_effective"] == "unknown"

    _attest(conn, domain="example.com")

    entry = artifacts.index_for(conn, cell.cell_id)[0]
    assert entry["commercial_use_effective"] == "permitted"
    assert entry["commercial_use"] == "unknown", "the stored column is still the record"


def test_history_refuses_half_a_key(conn):
    """A filter given a `subject_kind` and no `subject` used to return the whole
    table — a silent wrong answer rather than an error, which is the worst shape
    for a query an operator runs to check what they attested.
    """
    _attest(conn, domain="example.com")
    with pytest.raises(rights.RightsError, match="half a key"):
        rights.history(conn, subject_kind="domain")
    with pytest.raises(rights.RightsError, match="half a key"):
        rights.history(conn, subject="example.com")
    assert len(rights.history(conn)) == 1


# --- structural: §0.3 and §3.6 as shapes, not promises ------------------------


def _module_sources():
    for path in sorted(SRC.glob("*.py")):
        if path.name in ATTESTATION_WRITERS:
            continue
        yield path, ast.parse(path.read_text())


def test_no_cell_reachable_module_writes_an_attestation():
    """§0.3, structurally. A rights position is the canonical fact standing
    between the colony and selling something, so it is exactly what a Cell may
    never define.

    An AST walk rather than a grep, and over *every* module except the operator
    surfaces — the claim is "only a person writes one", and enumerating a
    hand-picked subset of Cell-reachable modules would let the next module
    quietly fall outside it.
    """
    offenders = []
    for path, tree in _module_sources():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("attest", "_attest_locked")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "rights"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "rights_attestations" in node.value and "INSERT" in node.value.upper():
                    offenders.append(f"{path.name}:{node.lineno} (raw INSERT)")
    assert not offenders, (
        "only the operator may establish a rights position (§0.3); found: "
        + ", ".join(offenders)
    )


def test_no_module_updates_or_deletes_an_attestation():
    """§3.6 — the record is append-only, and withdrawal is a new row.

    Walks string constants in every module including `rights.py` itself: the
    guarantee is about the table, so the module that owns it is the one most
    worth checking.
    """
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            sql = " ".join(node.value.upper().split())
            if "RIGHTS_ATTESTATIONS" in sql and (
                "UPDATE RIGHTS_ATTESTATIONS" in sql or "DELETE FROM RIGHTS_ATTESTATIONS" in sql
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, "rights_attestations is append-only (§3.6); found: " + ", ".join(offenders)


def test_no_tool_can_establish_rights():
    """The other end of §0.3: not just "no module calls attest" but "no
    capability exists to be granted". A tool named here would be a Cell-facing
    route to the same table.
    """
    for spec in tool_registry.REGISTRY.values():
        assert "rights" not in spec.tool_id
        assert "attest" not in spec.description.lower()
