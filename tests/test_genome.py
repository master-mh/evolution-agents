"""Genome content, inheritance, and the two permission-shaped fields
(SPEC.md §16.2/§16.3/§16.4, §0.4, §23.5; ADR-018, ADR-027)."""

import json

import pytest

from mitosis import db, genome, ledger, lifecycle, lineage, population
from mitosis.genome import (
    GENOME_FIELDS,
    MODEL_POLICY_FIELDS,
    NON_INHERITABLE_SENSE,
    RISK_CLASSES,
    canonical_genome_json,
    compute_genome_hash,
    inherit,
    requested_tools,
    risk_class_of,
    temperature_of,
    unclassified_fields,
)
from mitosis.models import Book, CellType, EntrySpec, PopulationLimits
from mitosis.proposal import RiskTier

SEED = 1_000_000

SEEDED = {
    "market": "small accounting firms",
    "problem": "month-end close is manual",
    "revenue_model": "per-close fixed fee",
    "workflow": "probe cheaply, measure, iterate",
}


@pytest.fixture
def conn():
    connection = db.connect_and_migrate()
    yield connection
    connection.close()


def _colony(conn, *, genome_content=None, budget=100_000):
    population.set_limits_if_absent(
        conn,
        PopulationLimits(
            max_living_cells=100,
            max_active_cells=100,
            max_parallel_experiments=10,
            max_births_per_epoch=10,
            max_lineage_population_fraction=1.0,
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
            EntrySpec(account_id="external_capital", amount_minor_units=-SEED),
            EntrySpec(account_id="seed_bank", amount_minor_units=SEED),
        ],
    )
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.COMMERCIAL,
        budget_minor_units=budget,
        book=Book.USD_SIM,
        idempotency_key="founder",
        genome_content=genome_content,
    )


def _content_of(conn, genome_hash):
    row = conn.execute(
        "SELECT canonical_genome_json FROM cell_genomes WHERE genome_hash = ?",
        (genome_hash,),
    ).fetchone()
    return json.loads(row["canonical_genome_json"])


# --- content addressing (unchanged behaviour, still load-bearing) -------------


def test_same_cell_type_yields_same_hash():
    a = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    b = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    assert a == b


def test_different_cell_types_yield_different_hashes():
    a = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    b = compute_genome_hash(canonical_genome_json(CellType.BUILDER))
    assert a != b


def test_hash_is_sha256_hex():
    h = compute_genome_hash(canonical_genome_json(CellType.AUDITOR))
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


# --- §16.3 inheritance --------------------------------------------------------


def test_an_unmutated_child_inherits_its_parents_content(conn):
    """§16.3: a child inherits its parent's market/product/revenue hypotheses.

    The headline guard of this slice. Before genomes carried content, a child's
    canonical JSON was rebuilt from cell_type alone and the parent's content was
    never read — invisible while every genome was `{"cell_type": ...}`, and a
    silent disinheritance the moment content became real. If this fails, every
    child is born a blank slate and the lineage learns nothing.
    """
    parent = _colony(conn, genome_content=SEEDED)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    assert _content_of(conn, child.genome_hash) == _content_of(conn, parent.genome_hash)
    assert _content_of(conn, child.genome_hash)["market"] == "small accounting firms"


def test_a_mutation_overlays_rather_than_replaces(conn):
    """§16.3: mutating one field must not discard the rest of the genome.

    Replacement instead of overlay would make every mutation a near-total
    amnesia event, and §14's economic mutation operators (change the channel,
    change the pricing) would each destroy the strategy they were varying.
    """
    parent = _colony(conn, genome_content=SEEDED)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c1",
        mutation={"acquisition_channel": "directory listing"},
    )
    content = _content_of(conn, child.genome_hash)
    assert content["acquisition_channel"] == "directory listing"
    assert content["market"] == SEEDED["market"]
    assert content["revenue_model"] == SEEDED["revenue_model"]


def test_a_seeded_lineage_does_not_collapse_onto_the_bare_genome(conn):
    """ADR-018 content addressing plus lost inheritance = shared identity.

    A child rebuilt from cell_type alone hashes to the *same* genome as every
    other unseeded Cell of that type, so unrelated lineages would share one
    `cell_genomes` row — and with it MAP-Elites descriptors, mutation distance,
    and every counterfactual comparison §16.1 lists.
    """
    parent = _colony(conn, genome_content=SEEDED)
    child = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    bare = compute_genome_hash(canonical_genome_json(CellType.COMMERCIAL))
    assert child.genome_hash != bare


def test_a_child_of_a_different_type_still_inherits_the_content(conn):
    """The genome must describe the Cell that actually exists (§16.2).

    `reproduce(cell_type=...)` may change a child's type; its content should
    follow the parent while `cell_type` follows the child.
    """
    parent = _colony(conn, genome_content=SEEDED)
    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c1",
        cell_type=CellType.EXPLORER,
    )
    content = _content_of(conn, child.genome_hash)
    assert content["cell_type"] == "explorer"
    assert content["market"] == SEEDED["market"]


def test_inherited_content_is_validated_not_only_the_mutation():
    """Validation runs on the merged result, not the overlay.

    Checking only the mutation would let anything already sitting in a parent's
    genome propagate unchecked forever — which is precisely the §16.4 carry-away
    this schema exists to prevent.
    """
    with pytest.raises(genome.GenomeError, match="unknown genome field"):
        inherit({"smuggled": "value"}, None, cell_type=CellType.EXPLORER)


# --- §16.4: the closed schema -------------------------------------------------


def test_unknown_genome_fields_are_refused():
    """§16.4: an unclassified overlay field is the liability-escape hatch.

    A Cell that can attach arbitrary keys to its genome can carry a profitable
    asset into a child while leaving its obligations with the parent, which
    §16.4 names as the failure exact inheritance semantics exist to prevent.
    """
    with pytest.raises(genome.GenomeError, match="closed"):
        canonical_genome_json(CellType.EXPLORER, {"strategy": "sneaky"})


def test_no_non_inheritable_field_exists():
    """§16.3's non-inheritable categories must have no genome field at all.

    A tripwire on the schema itself (same shape as
    `proposal.FORBIDDEN_FIELD_SENSE`): if one of these ever becomes a real
    field, widening the genome toward credentials, customer identity, or legal
    identity has to be an argued change rather than a plausible commit.
    """
    assert set(NON_INHERITABLE_SENSE) & set(GENOME_FIELDS) == set()


def test_non_inheritable_names_are_refused_by_name():
    """The refusal should say *why*, not just "unknown field"."""
    for name in NON_INHERITABLE_SENSE:
        with pytest.raises(genome.GenomeError, match="non-inheritable"):
            canonical_genome_json(CellType.EXPLORER, {name: "x"})


def test_every_genome_field_is_classified():
    """Mirrors `accounts.unclassified_accounts()` (§16.3).

    Adding a field must force the decision "ordinary content, or
    permission-shaped claim?". Defaulting to ordinary content is how a
    permission-shaped field quietly becomes self-granting.
    """
    assert unclassified_fields() == frozenset()
    assert genome.unknown_classified_fields() == set()


# --- §0.4 / §23.5: claims and requests, never grants ---------------------------


def test_risk_classes_match_the_approval_tiers():
    """Structural: `genome.RISK_CLASSES` mirrors `proposal.RiskTier`.

    genome sits far below proposal in the dependency order, so the coupling is
    pinned by this test rather than by a back-edge import. Drift would make a
    genome's risk claim silently unparseable, and `_genome_risk_claim` returns
    None on unparseable input — so the failure mode is a claim that stops
    escalating, in the direction that favours the Cell.
    """
    assert RISK_CLASSES == tuple(t.value for t in RiskTier)


def test_a_genome_cannot_lower_its_cells_review_tier():
    """§23.5 + ADR-027: a claim may raise the tier and never lower it.

    A genome is Cell-mutable content, so a lineage able to write
    `risk_class: LOW` into its children would buy them cheap approvals for as
    long as the lineage survived — a more durable version of the per-proposal
    gaming ADR-027 already refused.
    """
    from mitosis.approval import _assessed_tier

    assert (
        _assessed_tier(
            claimed=RiskTier.HIGH,
            kernel_tier=RiskTier.HIGH,
            signals=(),
            genome_claim=RiskTier.LOW,
        )
        is RiskTier.HIGH
    )


def test_a_genome_can_raise_its_cells_review_tier():
    """The other half of `max`: a Cell that says it is dangerous is believed."""
    from mitosis.approval import _assessed_tier

    assert (
        _assessed_tier(
            claimed=RiskTier.LOW,
            kernel_tier=RiskTier.LOW,
            signals=(),
            genome_claim=RiskTier.CRITICAL,
        )
        is RiskTier.CRITICAL
    )


def test_allowed_tools_is_a_request_and_grants_nothing():
    """§0.4: autonomy is granted tool by tool, never by self-declaration.

    Structural as well as behavioural — the module deliberately offers no
    `has_tool`/`grants`/`is_allowed` helper, because the moment one exists a
    caller will treat the genome's list as an entitlement.
    """
    content = canonical_genome_json(
        CellType.EXPLORER, {"allowed_tools": ["http_get", "send_email"]}
    )
    assert requested_tools(content) == ("http_get", "send_email")
    assert not [
        name
        for name in dir(genome)
        if name.startswith(("has_", "grant", "is_allowed", "may_"))
    ]


# --- field validation ---------------------------------------------------------


def test_risk_class_must_be_a_known_tier():
    with pytest.raises(genome.GenomeError, match="risk_class"):
        canonical_genome_json(CellType.EXPLORER, {"risk_class": "harmless"})


def test_allowed_tools_must_be_a_list_of_strings():
    with pytest.raises(genome.GenomeError, match="allowed_tools"):
        canonical_genome_json(CellType.EXPLORER, {"allowed_tools": "http_get"})


def test_mutation_rate_is_bounded():
    with pytest.raises(genome.GenomeError, match="between 0 and 1"):
        canonical_genome_json(CellType.EXPLORER, {"mutation_rate": 4})


def test_non_serializable_content_is_rejected():
    """Charter C11: the hash is computed over json.dumps output."""
    with pytest.raises(genome.GenomeError, match="JSON-serializable"):
        canonical_genome_json(CellType.EXPLORER, {"market": object()})


def test_risk_class_of_and_requested_tools_tolerate_an_empty_genome():
    assert risk_class_of(None) is None
    assert risk_class_of({}) is None
    assert requested_tools(None) == ()


# --- §14.1's model_policy socket (ADR-067) -------------------------------------


def test_model_policy_temperature_round_trips():
    content = canonical_genome_json(CellType.EXPLORER, {"model_policy": {"temperature": 0.4}})
    assert temperature_of(content) == 0.4


def test_model_policy_temperature_must_be_in_range():
    with pytest.raises(genome.GenomeError, match="between 0.0 and 1.0"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": {"temperature": 1.5}})
    with pytest.raises(genome.GenomeError, match="between 0.0 and 1.0"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": {"temperature": -0.1}})


def test_model_policy_temperature_must_be_a_number():
    with pytest.raises(genome.GenomeError, match="temperature must be a number"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": {"temperature": "hot"}})
    with pytest.raises(genome.GenomeError, match="temperature must be a number"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": {"temperature": True}})


def test_model_policy_must_be_a_dict():
    with pytest.raises(genome.GenomeError, match="model_policy must be a dict"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": 0.7})


def test_model_policy_rejects_an_unknown_key():
    """§14.1's other named operators (model-route, reasoning-budget mutation)
    are not yet built. A misspelled or half-built key must fail loudly rather
    than being silently ignored by whichever provider does not recognise it."""
    with pytest.raises(genome.GenomeError, match="unknown model_policy field"):
        canonical_genome_json(CellType.EXPLORER, {"model_policy": {"model_route": "opus"}})
    assert set(MODEL_POLICY_FIELDS) == {"temperature"}


def test_temperature_of_is_none_not_zero_for_a_silent_genome():
    """No declared policy is "no opinion", never greedy decoding. A provider
    reading `None` must fall back to its own default, not to temperature 0 —
    the exact `temperature: 0` kernel default ADR-050 refused."""
    assert temperature_of(None) is None
    assert temperature_of({}) is None
    assert temperature_of({"cell_type": "explorer"}) is None
    assert temperature_of({"model_policy": {}}) is None


def test_model_policy_is_inherited_and_mutable_like_every_other_field(conn):
    """§14.2's counterfactual-twin obligation needs both halves: a child must
    keep its parent's policy unless a mutation overlays it — the identical
    inherit/mutate mechanism every other genome field already uses, not a new
    one built for this field."""
    parent = _colony(conn, genome_content={**SEEDED, "model_policy": {"temperature": 0.6}})
    unmutated = lineage.reproduce(
        conn, parent_cell_id=parent.cell_id, budget_minor_units=100, idempotency_key="c1"
    )
    assert temperature_of(_content_of(conn, unmutated.genome_hash)) == 0.6

    mutated = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=100,
        idempotency_key="c2",
        mutation={"model_policy": {"temperature": 0.1}},
    )
    content = _content_of(conn, mutated.genome_hash)
    assert temperature_of(content) == 0.1
    assert content["market"] == SEEDED["market"], "the mutation overlays, it does not replace"


# --- founders -----------------------------------------------------------------


def test_a_founder_can_be_seeded_with_content(conn):
    """§14: the operator seeds diverse founders; mutation explores from there.

    A founder is the only entry point for genome content — every other genome
    descends from one — so a `create_cell` that could not carry content would
    make the whole field set unreachable.
    """
    cell = _colony(conn, genome_content=SEEDED)
    assert _content_of(conn, cell.genome_hash)["revenue_model"] == "per-close fixed fee"


def test_an_unseeded_founder_is_still_legal(conn):
    """Content is optional: a Cell with only its type is the pre-slice colony."""
    cell = _colony(conn)
    assert _content_of(conn, cell.genome_hash) == {"cell_type": "commercial"}
