"""The external-action registry (SPEC.md §21, §23.4, §16.3, §19.3, §28; ADR-036).

These defend the boundary between a colony that produces and a colony that
sells. §21.2's two verbs are *track* and *prevent*, and the tests are grouped by
which one they defend — plus a third group for the thing the design is most
easily "improved" into losing: the fact that no table here holds a person.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    artifacts,
    channel_registry,
    context,
    db,
    deliberation,
    external_actions,
    ledger,
    lifecycle,
    proposal as proposal_module,
    providers,
    reservations,
    resource_metering,
    tools,
)
from mitosis.accounts import cell_cash
from mitosis.models import Book, CellStatus, CellType, EntrySpec, ResourceType

GENOME = {"market": "independent bookshops", "workflow": "draft, then ask"}
COUNTERPARTY = "Alice@Example.com"


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


# --- fixtures -----------------------------------------------------------------


def _reply(**overrides) -> str:
    payload = {
        "kind": "external_action",
        "summary": "introduce the pricing draft to one bookshop",
        "rationale": "the hypothesis needs a real reaction, not another simulation",
        "risk_tier": "MEDIUM",
        "estimated_cost_minor_units": 0,
        "predictions": [],
        "external_action": {
            "channel": "email",
            "intent": "introduce the pricing draft",
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


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
                EntrySpec(
                    account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id
                ),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id),
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )


def _make_cell(conn, *, key: str = "a"):
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


def _open_the_gates(conn) -> None:
    tools.set_autonomy(conn, flag="external_message", enabled=True)
    tools.set_autonomy(conn, flag="external_publish", enabled=True)


def _approved_grant(conn, cell, *, wake_key: str = "w1", **overrides):
    """Drive the real path: deliberate, queue, approve."""
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply(**overrides)),
        wake_key=wake_key,
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    return approval.approve(
        conn, request_id=row["request_id"], decided_by="operator", reason="worth doing"
    )


# --- §16.3: the colony never holds a counterparty ------------------------------


def test_no_table_in_the_colony_holds_the_counterparty(conn):
    """§16.3 + §20.1: identity is a liability, and equality is all §21.2 needs.

    The test that guards the whole design, and it is deliberately blunt: after a
    real claim, the plaintext must not appear in *any* text column of *any*
    table. A label column "just for the operator", a counterparty echoed into an
    audit description, an intent that quotes the address — each is a plausible
    convenience and each reintroduces the customer list §16.3 forbids.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )

    needles = {COUNTERPARTY, COUNTERPARTY.casefold(), COUNTERPARTY.strip()}
    tables = [
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    ]
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}"):
            for value in tuple(row):
                if not isinstance(value, str):
                    continue
                for needle in needles:
                    assert needle not in value, (
                        f"table {table!r} holds the counterparty in plaintext: {value!r}. "
                        "§16.3 makes customer identity non-inheritable, and dedupe "
                        "needs equality, not identity."
                    )


def test_the_hash_is_stable_and_normalised(conn):
    """Dedupe that misses `Alice@Ex.com` vs `alice@ex.com` is dedupe that does
    not work — they are one person, and §21.2 is about that person."""
    a = channel_registry.counterparty_hash(conn, "Alice@Example.com")
    b = channel_registry.counterparty_hash(conn, "  alice@example.com  ")
    c = channel_registry.counterparty_hash(conn, "bob@example.com")
    assert a == b
    assert a != c


def test_a_cell_cannot_name_a_counterparty():
    """The schema tripwire (`proposal.FORBIDDEN_COUNTERPARTY_FIELDS`).

    `extra="forbid"` already rejects these, so this fails only if one becomes a
    real field — which is how widening the schema toward a Cell-supplied
    identity has to be an argued change to §16.3 rather than a helpful commit.
    """
    fields = set(proposal_module.ExternalActionSpec.model_fields)
    forbidden = fields & set(proposal_module.FORBIDDEN_COUNTERPARTY_FIELDS)
    assert not forbidden, (
        f"ExternalActionSpec carries {sorted(forbidden)} — a Cell naming a person "
        "puts a personal identifier into every context assembled from its history"
    )
    for name in proposal_module.FORBIDDEN_COUNTERPARTY_FIELDS:
        with pytest.raises(ValueError):
            proposal_module.ExternalActionSpec(
                channel="email", intent="hello", **{name: "alice@example.com"}
            )


def test_the_cell_never_sees_the_counterparty_hash(conn):
    """A stable per-person token in a prompt is a re-identifiable handle: a Cell
    could correlate it across wakes and reconstruct by inference the identity
    the colony declined to store."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="no_response",
        human_minutes=6,
    )

    digest = channel_registry.counterparty_hash(conn, COUNTERPARTY)
    for item in channel_registry.history_for(conn, cell.cell_id):
        assert "counterparty_hash" not in item
        assert digest not in json.dumps(item)

    assembled = context.assemble(
        conn, cell=cell, canonical_genome=GENOME, wake_reason="check"
    )
    rendered = "\n".join(s.body for s in assembled.sections)
    assert digest not in rendered
    assert COUNTERPARTY.casefold() not in rendered.casefold()


# --- §21.2 "prevent" ----------------------------------------------------------


def test_the_same_counterparty_is_not_contacted_twice_on_one_channel(conn):
    """§21.2's first named failure: "prevent duplicate contact"."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    first = _approved_grant(conn, cell, wake_key="w1")
    external_actions.claim(
        conn, grant_id=first.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    second = _approved_grant(conn, cell, wake_key="w2")

    with pytest.raises(channel_registry.DuplicateContact):
        external_actions.claim(
            conn,
            grant_id=second.grant_id,
            claimed_by="operator",
            counterparty=COUNTERPARTY,
        )


def test_two_lineages_cannot_reach_one_counterparty(conn):
    """§21.3: "Cells are internally separate but externally may appear to be one
    business." The sibling bidding war §21.2 names, and the failure a
    lineage-keyed approval window structurally cannot see — every splitter *it*
    catches shares a founder, and this one by definition does not.
    """
    _open_the_gates(conn)
    one = _make_cell(conn, key="a")
    two = _make_cell(conn, key="b")
    assert one.founder_cell_id != two.founder_cell_id

    grant_one = _approved_grant(conn, one, wake_key="w1")
    external_actions.claim(
        conn, grant_id=grant_one.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )

    grant_two = _approved_grant(conn, two, wake_key="w2")
    with pytest.raises(channel_registry.SiblingCollision):
        external_actions.claim(
            conn,
            grant_id=grant_two.grant_id,
            claimed_by="operator",
            counterparty=COUNTERPARTY,
        )


def test_a_sibling_collision_is_found_across_channels(conn):
    """One counterparty, two channels, two lineages is still one business
    contradicting itself — the same-channel duplicate check alone would miss it."""
    _open_the_gates(conn)
    one = _make_cell(conn, key="a")
    two = _make_cell(conn, key="b")
    grant_one = _approved_grant(conn, one, wake_key="w1")
    external_actions.claim(
        conn, grant_id=grant_one.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )

    # A different channel that still addresses a person would collide; email is
    # the only such channel today, so assert the query itself is not
    # channel-scoped rather than inventing a second one.
    with pytest.raises(channel_registry.SiblingCollision):
        channel_registry.check_action(
            conn,
            channel="email",
            counterparty=COUNTERPARTY,
            founder_cell_id=two.founder_cell_id,
        )


def test_the_channel_cap_is_the_colony_s_and_not_the_cell_s(conn):
    """§21.1: the sending reputation is shared, so a per-Cell cap is escaped by
    reproducing — which §9 makes the cheapest thing this colony can do."""
    _open_the_gates(conn)
    spec = channel_registry.REGISTRY["email"]
    cells = [_make_cell(conn, key=f"c{i}") for i in range(spec.max_actions_per_window + 1)]

    for index, cell in enumerate(cells[: spec.max_actions_per_window]):
        grant = _approved_grant(conn, cell, wake_key=f"w{index}")
        external_actions.claim(
            conn,
            grant_id=grant.grant_id,
            claimed_by="operator",
            counterparty=f"person{index}@example.com",
        )
        action = conn.execute(
            "SELECT action_id FROM external_action_registry ORDER BY rowid DESC LIMIT 1"
        ).fetchone()["action_id"]
        external_actions.complete(
            conn,
            action_id=action,
            completed_by="operator",
            outcome="no_response",
            human_minutes=1,
        )

    last = _approved_grant(conn, cells[-1], wake_key="wlast")
    with pytest.raises(channel_registry.ChannelRateLimit):
        external_actions.claim(
            conn,
            grant_id=last.grant_id,
            claimed_by="operator",
            counterparty="someone-new@example.com",
        )


def test_a_complaint_freezes_the_channel_until_a_person_clears_it(conn):
    """§21.1: a refund does not undo a spam complaint.

    Every other guard in this kernel bounds money — Charter C4, C5, the
    real-spend breaker, the promotion pool. This is the first that bounds an
    asset money cannot repair, and it halts rather than annotating for the same
    reason §23.3's metabolic alarm does.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="complaint",
        human_minutes=3,
    )

    frozen, reason = channel_registry.channel_frozen(conn, "email")
    assert frozen and "complaint" in reason

    other = _make_cell(conn, key="b")
    next_grant = _approved_grant(conn, other, wake_key="w2")
    with pytest.raises(channel_registry.ChannelFrozen):
        external_actions.claim(
            conn,
            grant_id=next_grant.grant_id,
            claimed_by="operator",
            counterparty="different@example.com",
        )

    channel_registry.acknowledge_channel(
        conn, channel="email", acknowledged_by="operator", note="the template was wrong; fixed"
    )
    assert channel_registry.channel_frozen(conn, "email") == (False, None)


def test_a_complaint_blocks_that_counterparty_permanently(conn):
    """The strongest thing hashing buys, and the reason it beats a `customers`
    table with an opt-out flag: "never contact this person again" is honoured
    forever without the colony ever holding a list of the people who asked."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="blocked",
        human_minutes=2,
    )
    channel_registry.acknowledge_channel(
        conn, channel="email", acknowledged_by="operator", note="reviewed"
    )

    # Far past the rolling contact window: a block is not a cooling-off period.
    with pytest.raises(channel_registry.CounterpartyBlocked):
        channel_registry.check_action(
            conn,
            channel="email",
            counterparty=COUNTERPARTY,
            now=datetime.now(timezone.utc) + timedelta(days=3650),
        )
    assert not hasattr(channel_registry, "unblock_counterparty")


def test_a_negative_reply_is_not_reputation_damage(conn):
    """The control. A guard that froze on every disappointing outcome would pass
    every refusal test above and make the colony unable to learn from a no."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="negative_reply",
        human_minutes=4,
    )
    assert channel_registry.channel_frozen(conn, "email") == (False, None)
    assert conn.execute("SELECT COUNT(*) AS n FROM counterparty_blocks").fetchone()["n"] == 0


def test_an_abandoned_claim_frees_the_counterparty(conn):
    """A claim held before acting is a lock, and a lock with no release is a
    denial of service the colony inflicts on itself."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell, wake_key="w1")
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.abandon(
        conn, action_id=action.action_id, abandoned_by="operator", reason="wrong contact"
    )

    channel_registry.check_action(conn, channel="email", counterparty=COUNTERPARTY)

    reservation = reservations.get_reservation(conn, action.resource_reservation_id)
    assert reservation.status.value == "released"


def test_abandoning_does_not_give_the_grant_back(conn):
    """Claiming took a slot another lineage could have used. Restoring the grant
    would make a claim a free way to reconnoitre who has already been contacted."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.abandon(
        conn, action_id=action.action_id, abandoned_by="operator", reason="changed my mind"
    )
    with pytest.raises(external_actions.ExternalActionError, match="already consumed"):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty="b@example.com"
        )


# --- §0.4 and §27.1: the gates ------------------------------------------------


def test_a_closed_autonomy_flag_refuses_the_channel(conn):
    """§27.1 ships every flag false, and the state that matters is the state at
    the moment the claim is made — not at approval."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    tools.set_autonomy(conn, flag="external_message", enabled=False)

    with pytest.raises(channel_registry.ChannelAutonomyRefused):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
        )


def test_a_grant_for_another_kind_cannot_claim_a_channel(conn):
    """Approving an experiment is a human saying "go think about that". Reading
    it as permission to contact a customer would let a Cell obtain the colony's
    scarcest capability by proposing something else entirely."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(
        conn,
        cell,
        kind="experiment",
        external_action=None,
        summary="run a simulated pricing sweep",
    )
    with pytest.raises(external_actions.ExternalActionError, match="only an external_action"):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
        )


def test_a_dead_cell_takes_no_external_action(conn):
    """Charter C8. Spending the colony's shared reputation for a Cell that can
    no longer answer for it is the worst possible trade."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    lifecycle.kill(conn, cell.cell_id, cause_of_death="test")

    with pytest.raises(external_actions.ExternalActionError, match="cannot take an external"):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
        )


def test_an_expired_grant_cannot_be_claimed(conn):
    """§23.3: an expired approval is regenerated, never acted on late. An offer
    authorised against last week's market is a different offer."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    with pytest.raises(external_actions.ExternalActionError, match="expired"):
        external_actions.claim(
            conn,
            grant_id=grant.grant_id,
            claimed_by="operator",
            counterparty=COUNTERPARTY,
            now=grant.expires_at_utc + timedelta(seconds=1),
        )


# --- §19.3: delivery is not a second way out of the colony ---------------------


def _exported_artifact(conn, cell, *, commercial: bool = False):
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="outreach_draft",
        title="Pricing note",
        content="Our pricing, in one page.",
    )
    artifacts.export(
        conn,
        artifact_id=artifact.artifact_id,
        exported_by="operator",
        reason="reviewed",
        commercial=commercial,
    )
    return artifact


def test_an_unexported_artifact_cannot_be_delivered(conn):
    """§19.3's export gateway decides *whether* something may leave the colony;
    a channel decides only where it goes. Re-deriving that decision here would
    make delivery a second, laxer way out — and Charter C13's block sits on the
    export path, not on this one."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    artifact = artifacts.create(
        conn,
        cell_id=cell.cell_id,
        kind="outreach_draft",
        title="Pricing note",
        content="Our pricing, in one page.",
    )
    grant = _approved_grant(
        conn,
        cell,
        external_action={
            "channel": "email",
            "intent": "send the pricing note",
            "artifact_id": artifact.artifact_id,
        },
    )
    with pytest.raises(external_actions.ExternalActionError, match="has not been exported"):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
        )


def test_an_exported_artifact_can_be_delivered(conn):
    """The control for the test above: a gate that refused every artifact would
    pass the refusal test and deliver nothing, ever."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    artifact = _exported_artifact(conn, cell)
    grant = _approved_grant(
        conn,
        cell,
        external_action={
            "channel": "email",
            "intent": "send the pricing note",
            "artifact_id": artifact.artifact_id,
        },
    )
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    assert action.artifact_id == artifact.artifact_id


def test_a_cell_cannot_deliver_another_cell_s_work(conn):
    """§11.2 puts usefulness strictly downstream — an adopter earns credit
    through a recorded contribution, not by putting someone else's artifact on
    the colony's one channel."""
    _open_the_gates(conn)
    author = _make_cell(conn, key="a")
    other = _make_cell(conn, key="b")
    artifact = _exported_artifact(conn, author)
    grant = _approved_grant(
        conn,
        other,
        external_action={
            "channel": "email",
            "intent": "send someone else's note",
            "artifact_id": artifact.artifact_id,
        },
    )
    with pytest.raises(external_actions.ExternalActionError, match="was made by"):
        external_actions.claim(
            conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
        )


# --- §28 Phase 8: human labour is measured -------------------------------------


def test_human_minutes_are_metered_against_the_cell(conn):
    """§2.2's `HUMAN_MINUTES`, declared since Phase 1 and consumed by nothing.

    §1's autonomy-adjusted profit exists "to expose hidden human labour and
    subsidy"; `outcome.py` counts intervention *events* and has never counted
    time. A Cell that can only act by consuming a person's attention now runs
    out of budget for doing so.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    # After the deliberation, which meters its own model call against the same
    # book — the delta being asserted is this action's, not the wake's.
    before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.RESOURCE)

    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="positive_reply",
        human_minutes=12,
    )

    by_type = resource_metering.total_quantity_by_type(conn)
    assert by_type[ResourceType.HUMAN_MINUTES.value] == 12
    after = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.RESOURCE)
    assert after == before - 12 * channel_registry.HUMAN_MINUTE_RESOURCE_COST
    assert channel_registry.human_minutes_total(conn) == 12


def test_an_action_cannot_claim_zero_human_minutes(conn):
    """§28 Phase 8's acceptance is that human labour *is measured*. A completion
    reporting zero minutes is either untrue or a report that something was
    automated — the one thing this phase says does not happen."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    with pytest.raises(external_actions.ExternalActionError, match="at least one human minute"):
        external_actions.complete(
            conn,
            action_id=action.action_id,
            completed_by="operator",
            outcome="delivered",
            human_minutes=0,
        )


def test_the_reservation_releases_what_the_person_did_not_use(conn):
    """Charter C4 binds against the claim-time ceiling; the remainder must come
    back, exactly as an over-reserved model call's does."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    reservation = reservations.get_reservation(conn, action.resource_reservation_id)
    assert reservation.maximum_amount == (
        channel_registry.REGISTRY["email"].max_billable_human_minutes
        * channel_registry.HUMAN_MINUTE_RESOURCE_COST
    )

    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="delivered",
        human_minutes=5,
    )
    settled = reservations.get_reservation(conn, action.resource_reservation_id)
    assert settled.settled_amount == 5 * channel_registry.HUMAN_MINUTE_RESOURCE_COST
    assert settled.status.value == "released"


# --- §23: how the queue sees an external action --------------------------------


def test_an_external_action_is_never_reversible(conn):
    """§23.1 tiers on reversibility, and until ADR-036 only USD_REAL was
    irreversible. §21.1's assets are worse: a refund does not undo a spam
    complaint. Reading one as reversible would let it be batch-approved
    alongside a USD_SIM experiment."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(reply=_reply()),
        wake_key="w1",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = approval.get_request(
        conn,
        conn.execute(
            "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
            (result.proposal_id,),
        ).fetchone()["request_id"],
    )
    assert request.reversible is False
    assert request.assessed_tier.value in ("HIGH", "CRITICAL")


def test_the_aggregation_key_is_the_channel_not_the_lineage(conn):
    """§23.4 asks for "counterparty/domain/channel"; ADR-027 keyed on the
    lineage as an explicit stand-in until they existed. The channel now does,
    and §21.2's worry — many lineages, one channel — is exactly what a
    lineage-keyed window cannot see."""
    _open_the_gates(conn)
    one = _make_cell(conn, key="a")
    two = _make_cell(conn, key="b")
    keys = set()
    for index, cell in enumerate((one, two)):
        result = deliberation.deliberate(
            conn,
            cell_id=cell.cell_id,
            provider=providers.MockProvider(reply=_reply()),
            wake_key=f"w{index}",
            model="mock-1",
            proposal_sink=approval.QueueSink(),
        )
        keys.add(
            conn.execute(
                "SELECT aggregation_key FROM approval_requests WHERE proposal_id = ?",
                (result.proposal_id,),
            ).fetchone()["aggregation_key"]
        )
    assert keys == {"channel:email"}


def test_an_unknown_channel_is_treated_as_critical(conn):
    """Failing closed on the unknown case, as the tool path does. A reviewer
    cannot judge an action on a channel that does not exist, and CRITICAL is
    what stops it being approved in a batch alongside things they did read."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=_reply(external_action={"channel": "carrier_pigeon", "intent": "hello"})
        ),
        wake_key="w1",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    row = conn.execute(
        "SELECT assessed_tier FROM approval_requests WHERE proposal_id = ?",
        (result.proposal_id,),
    ).fetchone()
    assert row["assessed_tier"] == "CRITICAL"


# --- §28 Phase 8: nothing here sends anything ----------------------------------


def test_nothing_in_the_registry_transmits(conn):
    """§28 Phase 8: "all external action remains manual", and §21.2's own verbs
    are *track* and *prevent*.

    Structural rather than behavioural, because the behavioural version of this
    test is "assert no email was sent", which passes trivially against code that
    would send one. Neither module may import anything that opens a socket.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    forbidden = {
        "urllib",
        "http",
        "socket",
        "smtplib",
        "requests",
        "httpx",
        "fetchers",
        "tools",
    }
    for module in ("external_actions.py", "channel_registry.py"):
        tree = ast.parse((source_dir / module).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0].lstrip("."))
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
        offending = imported & forbidden
        assert not offending, (
            f"{module} imports {sorted(offending)} — §28's Phase 8 requires that "
            "every external action be performed by a person, so nothing here may "
            "be able to perform one"
        )


def test_the_deliberation_path_cannot_claim_a_channel():
    """The §19.4 shape applied to §21: a fetched page saying "email this
    address" must not be able to close the loop. `context` may read the registry
    (`channel_registry`); nothing in the deliberation path may reach the claim."""
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    for module in ("context.py", "deliberation.py", "scheduler.py"):
        tree = ast.parse((source_dir / module).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in (None, "mitosis"):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                imported += [a.name.split(".")[-1] for a in node.names]
        assert "external_actions" not in imported, (
            f"{module} imports the external-action executor — §28 Phase 8 requires "
            "a person take every external action"
        )


def test_every_channel_names_an_autonomy_flag():
    """§0.4: autonomy is granted capability by capability. A channel with no
    flag is a capability nobody ever decided to allow."""
    from mitosis.tool_registry import _AUTONOMY_COLUMNS

    for spec in channel_registry.REGISTRY.values():
        assert spec.autonomy_flag in _AUTONOMY_COLUMNS


def test_minutes_beyond_the_ceiling_are_recorded_as_subsidy_not_refused(conn):
    """§1: autonomy-adjusted profit exists "to expose hidden human labour and
    subsidy".

    Refusing an over-ceiling completion was the obvious alternative and it makes
    the colony's account of itself quieter than reality — the minutes were
    already spent, and refusing to write them down does not un-spend them. So
    the Cell pays what it authorised, the registry records the truth, and the
    gap is an audit event with the word `subsidised` in it.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    ceiling = channel_registry.REGISTRY["email"].max_billable_human_minutes
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    completed = external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="delivered",
        human_minutes=ceiling + 20,
    )

    assert completed.human_minutes == ceiling + 20
    assert channel_registry.human_minutes_total(conn) == ceiling + 20
    by_type = resource_metering.total_quantity_by_type(conn)
    assert by_type[ResourceType.HUMAN_MINUTES.value] == ceiling

    event = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'human_minutes_subsidised'"
    ).fetchone()
    assert event is not None
    assert json.loads(event["metadata_json"])["subsidised_human_minutes"] == 20


def test_a_normal_action_records_no_subsidy(conn):
    """The control. A path that logged a subsidy every time would satisfy the
    test above and make the figure meaningless."""
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    action = external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )
    external_actions.complete(
        conn,
        action_id=action.action_id,
        completed_by="operator",
        outcome="delivered",
        human_minutes=3,
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events "
            "WHERE event_type = 'human_minutes_subsidised'"
        ).fetchone()["n"]
        == 0
    )


def test_a_claim_costs_less_than_a_cell_s_whole_budget(conn):
    """The bug this ceiling replaced: reserving a theoretical worst case made
    one email cost more RESOURCE than a Cell has, which is not a prudent cap but
    an off switch nobody meant to install. Caught by the golden run, not by a
    unit test, because every unit fixture funds generously."""
    for spec in channel_registry.REGISTRY.values():
        reserved = spec.max_billable_human_minutes * channel_registry.HUMAN_MINUTE_RESOURCE_COST
        assert reserved <= 500, (
            f"{spec.channel_id} reserves {reserved} RESOURCE per action — a real Cell "
            "carries a couple of thousand, and a cap it can never afford to hit is an "
            "off switch"
        )


def test_the_cell_is_told_the_tier_so_the_signal_still_means_something(conn):
    """§23.4's `understated_risk` is only worth having while it distinguishes.

    The kernel assesses every external action HIGH. If a Cell were never told
    that, an honest MEDIUM claim would trip the signal on *every* external
    action ever proposed — a detection that fires unconditionally, which is the
    same defect as a test that passes for the wrong reason. So the context says
    the tier outright, and both halves are pinned here: an honest claim is
    clean, and an understated one is not.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    assembled = context.assemble(
        conn, cell=cell, canonical_genome=GENOME, wake_reason="check"
    )
    channels = next(s for s in assembled.sections if s.name == "Channels you may request")
    assert "HIGH" in channels.body

    def _signals_for(risk_tier: str, wake_key: str) -> list[str]:
        result = deliberation.deliberate(
            conn,
            cell_id=cell.cell_id,
            provider=providers.MockProvider(reply=_reply(risk_tier=risk_tier)),
            wake_key=wake_key,
            model="mock-1",
            proposal_sink=approval.QueueSink(),
        )
        row = conn.execute(
            "SELECT request_id FROM approval_requests WHERE proposal_id = ?",
            (result.proposal_id,),
        ).fetchone()
        return [
            r["signal"]
            for r in conn.execute(
                "SELECT signal FROM approval_signals WHERE request_id = ?",
                (row["request_id"],),
            )
        ]

    assert "understated_risk" not in _signals_for("HIGH", "w-honest")
    assert "understated_risk" in _signals_for("LOW", "w-understated")


def test_an_operator_check_names_prior_contact_rather_than_accusing_a_sibling(conn):
    """A live-run finding. `external-check` supplies no lineage, so the sibling
    query matched the asker's *own* claim and reported it as §21.3 interference.

    The strictness is right and unchanged — any prior contact still refuses —
    but the diagnosis has to be one the operator can act on. `check_action`
    without a founder now reports prior contact; only a caller that says which
    lineage it is can be told a *different* one got there first.
    """
    _open_the_gates(conn)
    cell = _make_cell(conn)
    grant = _approved_grant(conn, cell)
    external_actions.claim(
        conn, grant_id=grant.grant_id, claimed_by="operator", counterparty=COUNTERPARTY
    )

    with pytest.raises(channel_registry.DuplicateContact):
        channel_registry.check_action(conn, channel="email", counterparty=COUNTERPARTY)

    # Still strict: the refusal happens either way, only its name changes.
    other = _make_cell(conn, key="b")
    with pytest.raises(channel_registry.SiblingCollision):
        channel_registry.check_action(
            conn,
            channel="email",
            counterparty=COUNTERPARTY,
            founder_cell_id=other.founder_cell_id,
        )
