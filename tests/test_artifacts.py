"""The artifact store (SPEC.md §20, §18.1, §11, §15.2, §19.3; A3; C13; ADR-035).

These defend the link between what a Cell made and what the colony earned, and
the two things that link must never do: launder a rights position it never had
(§20.2), or let the same work count twice under a new name (§11.3).
"""

from __future__ import annotations

import json

import pytest

from mitosis import (
    approval,
    artifacts,
    context,
    db,
    deliberation,
    ledger,
    lifecycle,
    providers,
    revenue,
    tool_registry,
    tools,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellType, EntrySpec

GENOME = {"market": "independent bookshops", "workflow": "read, then write"}
URL = "https://example.com/pricing"


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


class FakeFetcher:
    def __init__(self, *, commercial_use="unknown", personal=False):
        self.commercial_use, self.personal = commercial_use, personal

    def fetch(self, url, *, max_bytes):
        return tool_registry.FetchResult(
            text="Widgets cost £4.",
            http_status=200,
            source=url,
            licence="unknown",
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


def _fetched(conn, cell, **fetcher_kwargs) -> str:
    """Drive a real tool call and return its id, so provenance is genuine."""
    tools.set_autonomy(conn, flag="public_web_read", enabled=True)
    tools.allow_domain(conn, domain="example.com", added_by="op", reason="fixture")
    reply = json.dumps(
        {
            "kind": "tool_request",
            "summary": "read the price page",
            "rationale": "need a price",
            "risk_tier": "LOW",
            "estimated_cost_minor_units": 0,
            "predictions": [],
            "tool_request": {"tool": "http_get", "arguments": {"url": URL}},
        }
    )
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=reply),
        wake_key=f"tw:{cell.cell_id}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(
        r for r in approval.queue(conn) if r.proposal_id == result.proposal_id
    )
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


# --- §11.3: identity is content, so duplication is unrepresentable ------------


def test_identical_content_is_one_artifact(conn):
    """§11.3: "duplicated artifacts with new names" is a named gaming vector.

    Content addressing makes it unrepresentable rather than detectable — the
    same move §16.1 makes for genomes. If this fails, a Cell can inflate any
    downstream count by resubmitting its own work.
    """
    cell = _make_cell(conn)
    first = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices", content="Widgets £4."
    )
    second = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices", content="Widgets £4."
    )
    assert first.artifact_id == second.artifact_id
    assert conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"] == 1


def test_a_renamed_artifact_is_a_different_artifact(conn):
    """The title is part of the content address, so renaming is a real edit.

    The other half of §11.3: renaming must not be a way to *hide* that two
    things are the same, and must not be free either. A different title is
    different content and gets its own identity honestly.
    """
    cell = _make_cell(conn)
    a = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices", content="Widgets £4."
    )
    b = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Prices v2", content="Widgets £4."
    )
    assert a.artifact_id != b.artifact_id


def test_the_first_producer_keeps_authorship(conn):
    """A later independent rediscovery must not rewrite who got there first —
    the posture `lifecycle._get_or_create_genome` already takes (ADR-018)."""
    first = _make_cell(conn, key="a")
    second = _make_cell(conn, key="b")
    a = artifacts.create(
        conn, cell_id=first.cell_id, kind="report", title="P", content="same"
    )
    b = artifacts.create(
        conn, cell_id=second.cell_id, kind="report", title="P", content="same"
    )
    assert b.artifact_id == a.artifact_id
    assert b.created_by_cell_id == first.cell_id


# --- §20.2: rights propagate, they never reset --------------------------------


def test_rights_do_not_reset_through_a_derived_artifact(conn):
    """§20.2's laundering path, closed.

    A fetched page is `commercial_use: unknown` by construction. If an artifact
    derived from it came out `permitted`, "summarise it" would be a one-step
    launder from someone else's content into apparently-clean colony IP.
    """
    cell = _make_cell(conn)
    tool_call_id = _fetched(conn, cell)
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="What the wholesaler charges",
        content="They charge £4.",
        source_tool_call_ids=(tool_call_id,),
    )
    assert artifact.commercial_use == "unknown"
    assert artifacts.TAINT_UNTRUSTED_EXTERNAL in artifact.taint_labels


def test_the_most_restrictive_source_wins(conn):
    """One prohibited source is enough. Averaging rights would let a Cell dilute
    a restriction by citing enough permissive material alongside it."""
    merged = artifacts.inherit_provenance(
        [
            artifacts.Provenance("CC0", "any", "permitted", False, "keep", "a", ()),
            artifacts.Provenance("All rights", "none", "prohibited", False, "keep", "b", ()),
        ]
    )
    assert merged.commercial_use == "prohibited"


def test_personal_data_and_taint_are_unions(conn):
    """§18.1/§20.1: one source carrying personal data taints the derivative."""
    merged = artifacts.inherit_provenance(
        [
            artifacts.Provenance("a", "x", "permitted", False, "k", "a", ("PUBLIC_SAFE",)),
            artifacts.Provenance(
                "b", "y", "permitted", True, "k", "b", ("UNTRUSTED_EXTERNAL",)
            ),
        ]
    )
    assert merged.contains_personal_data is True
    assert set(merged.taint_labels) == {"PUBLIC_SAFE", "UNTRUSTED_EXTERNAL"}


def test_an_artifact_citing_nothing_is_not_automatically_sellable(conn):
    """Colony-authored still starts `unknown`, not `permitted`.

    Whether the colony may *sell* its own output is a question for a person.
    Defaulting to permitted would make every unsourced draft look sellable.
    """
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="Own work", content="mine"
    )
    assert artifact.commercial_use == "unknown"


def test_an_artifact_cannot_cite_a_source_that_returned_nothing(conn):
    """Provenance that points at a failed call is not provenance."""
    cell = _make_cell(conn)
    with pytest.raises(artifacts.ArtifactError, match="did not return"):
        artifacts.create(
            conn,
            cell_id=cell.cell_id,
            kind="report",
            title="t",
            content="c",
            source_tool_call_ids=("no-such-call",),
        )


# --- §11.4: the contribution graph --------------------------------------------


def test_lineage_records_what_an_artifact_was_built_from(conn):
    """§11.4's graph: discovery -> hypothesis -> prototype -> ... Without the
    edges, credit cannot be assigned to the work that actually caused it."""
    cell = _make_cell(conn)
    tool_call_id = _fetched(conn, cell)
    first = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="Raw findings",
        content="£4",
        source_tool_call_ids=(tool_call_id,),
    )
    second = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="pricing_recommendation",
        title="Suggested retail",
        content="Sell at £7",
        source_artifact_ids=(first.artifact_id,),
    )
    assert artifacts.lineage_of(conn, first.artifact_id) == [
        {"source_artifact_id": None, "source_tool_call_id": tool_call_id}
    ]
    assert artifacts.lineage_of(conn, second.artifact_id) == [
        {"source_artifact_id": first.artifact_id, "source_tool_call_id": None}
    ]


# --- §19.3's export gateway (Charter C13, §20.2) ------------------------------


def test_an_adversarial_artifact_can_never_be_exported(conn):
    """Charter C13 / §18.2: adversarial-taint artifacts cannot reach real-facing
    environments, commercial or not.

    The label is set directly here because **nothing in the kernel can produce
    it yet** — §18.2 is about lineages evolved under adversarial synthetic
    incentives and the shadow economy is Phase 6. This tests the *router*, which
    is the part that must already work when such a lineage first exists.
    """
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="prototype", title="t", content="c"
    )
    conn.execute(
        "UPDATE artifacts SET taint_labels_json = ? WHERE artifact_id = ?",
        (json.dumps([artifacts.TAINT_SIM_ADVERSARIAL]), artifact.artifact_id),
    )
    conn.commit()

    for commercial in (False, True):
        with pytest.raises(artifacts.ExportRefused, match="C13"):
            artifacts.export(
                conn,
                artifact_id=artifact.artifact_id,
                exported_by="op",
                reason="try it",
                commercial=commercial,
            )


def test_untrusted_external_does_not_block_export(conn):
    """The control, and it matters as much as the block.

    Blocking UNTRUSTED_EXTERNAL would forbid exporting anything informed by
    research — every real deliverable. §18.2 names adversarial lineages, not
    everything the colony did not write itself.
    """
    cell = _make_cell(conn)
    tool_call_id = _fetched(conn, cell)
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="t",
        content="c",
        source_tool_call_ids=(tool_call_id,),
    )
    exported = artifacts.export(
        conn, artifact_id=artifact.artifact_id, exported_by="op", reason="share the draft"
    )
    assert exported.is_exported


def test_commercial_export_requires_established_rights(conn):
    """§20.2: public visibility is not permission to resell."""
    cell = _make_cell(conn)
    tool_call_id = _fetched(conn, cell)
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="t",
        content="c",
        source_tool_call_ids=(tool_call_id,),
    )
    with pytest.raises(artifacts.ExportRefused, match="20.2"):
        artifacts.export(
            conn,
            artifact_id=artifact.artifact_id,
            exported_by="op",
            reason="sell it",
            commercial=True,
        )


def test_commercial_export_is_allowed_once_rights_permit(conn):
    """The other side: with a permitted source, commercial export goes through.

    A gate that refused everything would pass the refusal tests and be useless.
    """
    cell = _make_cell(conn)
    tool_call_id = _fetched(conn, cell, commercial_use="permitted")
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="t",
        content="c",
        source_tool_call_ids=(tool_call_id,),
    )
    exported = artifacts.export(
        conn,
        artifact_id=artifact.artifact_id,
        exported_by="op",
        reason="sell it",
        commercial=True,
    )
    assert exported.export_is_commercial is True


def test_an_export_must_state_a_reason(conn):
    """§28 Phase 8 measures human review; an unexplained export measures nothing."""
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="t", content="c"
    )
    with pytest.raises(artifacts.ArtifactError, match="reason"):
        artifacts.export(
            conn, artifact_id=artifact.artifact_id, exported_by="op", reason="  "
        )


def test_an_artifact_is_exported_at_most_once(conn):
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="t", content="c"
    )
    artifacts.export(conn, artifact_id=artifact.artifact_id, exported_by="op", reason="once")
    with pytest.raises(artifacts.ArtifactError, match="already exported"):
        artifacts.export(
            conn, artifact_id=artifact.artifact_id, exported_by="op", reason="twice"
        )


# --- Amendment A3: the ledger link --------------------------------------------


def test_revenue_can_name_what_was_sold(conn):
    """A3's `ledger_entries.artifact_id` has existed since migration 0001 and
    nothing populated it. This is the edge §11.4's graph needs between a Cell's
    work and the money that followed."""
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn, cell_id=cell.cell_id, kind="report", title="t", content="c"
    )
    revenue.record_revenue(
        conn,
        cell_id=cell.cell_id,
        amount_minor_units=500,
        source="invoice 1",
        book=Book.USD_SIM,
        artifact_id=artifact.artifact_id,
    )
    row = conn.execute(
        "SELECT artifact_id FROM ledger_entries WHERE artifact_id IS NOT NULL"
    ).fetchone()
    assert row["artifact_id"] == artifact.artifact_id


def test_revenue_cannot_name_an_artifact_that_does_not_exist(conn):
    """An attribution pointing nowhere looks like provenance and is not."""
    cell = _make_cell(conn)
    with pytest.raises(revenue.RevenueError, match="no such artifact"):
        revenue.record_revenue(
            conn,
            cell_id=cell.cell_id,
            amount_minor_units=500,
            source="invoice 1",
            book=Book.USD_SIM,
            artifact_id="nope",
        )


def test_revenue_without_an_artifact_still_works(conn):
    """Optional on purpose — a retainer or a correction has no deliverable, and
    a required field satisfied with a placeholder is worse than an honest null."""
    cell = _make_cell(conn)
    revenue.record_revenue(
        conn,
        cell_id=cell.cell_id,
        amount_minor_units=500,
        source="retainer",
        book=Book.USD_SIM,
    )
    assert revenue.total_revenue(conn, cell.cell_id, Book.USD_SIM) == 500


# --- §15.2's artifact index ---------------------------------------------------


def test_the_index_shows_that_an_artifact_exists_not_what_it_says(conn):
    """§15.2 names an artifact *index* among its five memory tiers.

    Inlining content would let one long draft crowd out the Cell's own ledger
    record — the exact failure §15.1 describes, and the reason an artifact may
    be 20k characters while a proposal may be 2k.
    """
    cell = _make_cell(conn)
    artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="report",
        title="Bookshop findings",
        content="SECRET-BODY-TEXT " * 200,
    )
    assembled = context.assemble(
        conn,
        cell=lifecycle.get_cell(conn, cell.cell_id),
        canonical_genome={"cell_type": "explorer", **GENOME},
        wake_reason="scheduled research cycle",
    )
    rendered = assembled.render()
    assert "Bookshop findings" in rendered
    assert "SECRET-BODY-TEXT" not in rendered
    assert "commercial use: unknown" in rendered


# --- production is free, export is gated --------------------------------------


def test_producing_an_artifact_needs_no_approval(conn):
    """§28 Phase 8 gates *external use*, not production. Gating creation would
    spend the §23 queue — a finite resource §23.5 warns is optimised against —
    on the cheapest thing a Cell does."""
    cell = _make_cell(conn)
    before = len(approval.queue(conn))
    artifacts.create(conn, cell_id=cell.cell_id, kind="report", title="t", content="c")
    assert len(approval.queue(conn)) == before


def test_a_wake_can_produce_an_artifact_alongside_its_proposal(conn):
    """One wake, one transaction. A crash that recorded the proposal but not the
    artifact would lose the half that has no other record."""
    cell = _make_cell(conn)
    reply = json.dumps(
        {
            "kind": "strategy",
            "summary": "wrote up what I found",
            "rationale": "the market hypothesis needed a price",
            "risk_tier": "LOW",
            "estimated_cost_minor_units": 0,
            "predictions": [],
            "artifact": {
                "kind": "report",
                "title": "Trade prices, first pass",
                "content": "Widgets land at £4.20.",
            },
        }
    )
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=reply),
        wake_key="w1",
        model="mock-1",
    )
    row = conn.execute(
        "SELECT title, created_by_deliberation_id FROM artifacts WHERE created_by_cell_id = ?",
        (cell.cell_id,),
    ).fetchone()
    assert row["title"] == "Trade prices, first pass"
    assert row["created_by_deliberation_id"] is not None


def test_an_abstaining_cell_produces_nothing(conn):
    """ABSTAIN exists so a Cell with nothing worth doing can say so. Attaching
    work to it would make abstention the cheapest way to produce without
    proposing anything reviewable."""
    from mitosis.proposal import ProposalError, parse

    with pytest.raises(ProposalError, match="abstain"):
        parse(
            json.dumps(
                {
                    "kind": "abstain",
                    "summary": "nothing worth doing",
                    "rationale": "thin record",
                    "risk_tier": "LOW",
                    "estimated_cost_minor_units": 0,
                    "artifact": {"kind": "report", "title": "t", "content": "c"},
                }
            )
        )


# --- §1: artifact count is not a success metric -------------------------------


def test_nothing_counts_artifacts_toward_fitness():
    """§1: the colony "is *not* successful because it ... produces many
    artifacts".

    Structural, because this is the failure mode a work-product store most
    invites. §10.3 makes an Explorer's value depend on *useful* artifacts and
    §11.2 makes usefulness strictly downstream — none of whose five conditions
    the producer controls. If a raw count ever reaches a fitness surface, the
    cheapest strategy in the colony becomes writing many short documents.
    """
    import inspect

    from mitosis import death, outcome

    for module in (death, outcome):
        source = inspect.getsource(module)
        assert "artifact" not in source.lower(), (
            f"{module.__name__} references artifacts — §1 forbids artifact "
            "production being a success signal"
        )
