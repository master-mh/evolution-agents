"""§12's archive, derived (SPEC.md §12, §13.4, §16.1, §16.2, §16.3, §2.5, §23.5).

Every test is named for the property it defends. The recurring theme is that a
descriptor is a statement about what came *before* — so the founder abstains, a
permission field is not an idea, and a dimension nobody can measure stays out of
the coordinate rather than becoming a bin called "unknown".
"""

import ast
import sqlite3
from pathlib import Path

import pytest

from mitosis import db, ledger, lifecycle, models, novelty, population
from mitosis.models import Book, CellType, EntrySpec

BASE = {
    "market": "independent bookshops",
    "problem": "stock decisions are guesswork",
    "product": "a weekly stock digest",
    "revenue_model": "monthly subscription per shop",
    "acquisition_channel": "trade newsletters",
    "workflow": "ingest sales, rank slow movers, publish",
}


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


def _founder(conn, tag, **overrides):
    content = {**BASE, **overrides}
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        genome_content=content,
    )
    return cell


def _distance(conn, cell):
    row = conn.execute("SELECT genome_hash FROM cells WHERE cell_id = ?",
                       (cell.cell_id,)).fetchone()
    found = next(d for d in novelty.descriptors(conn, row["genome_hash"])
                 if d.dimension == "novelty_distance")
    return found


def _hash_of(conn, cell):
    return conn.execute("SELECT genome_hash FROM cells WHERE cell_id = ?",
                        (cell.cell_id,)).fetchone()["genome_hash"]


# --- the clause's own lists ---------------------------------------------------


def test_every_dimension_and_genome_field_is_classified():
    """§12.1 names three dimensions and §16.2 names eleven fields; none may drift in.

    A genome field that is silently outside the novelty distance is one nobody
    decided was outside it — and the decision matters, because including
    `risk_class` would make a permission claim look like a new idea. Same
    forcing shape as `genome.unclassified_fields()` one layer down.
    """
    assert novelty.unclassified_descriptors() == set()
    assert novelty.unclassified_genome_fields() == set()
    assert not novelty.NOVELTY_FIELDS & set(novelty.NON_NOVELTY_SENSE)


def test_a_bin_outside_the_clause_is_refused():
    """§12.1's bins are the clause's, not a caller's.

    Without this a typo would create a niche of one, silently, and the archive
    would report an occupancy that no dimension defines.
    """
    with pytest.raises(ValueError):
        novelty.Descriptor("novelty_distance", "extremely_radical",
                           novelty.Measurement.MEASURED, "typo")


# --- the distance -------------------------------------------------------------


def test_the_first_genome_has_nothing_to_be_novel_against(conn):
    """The founder abstains; it is not radical.

    Calling the first genome radical would be a claim about an archive with no
    other members — and it would make every colony's founder occupy the niche
    reserved for a market nobody has tried. ADR-058's rule again: an
    unmeasurable thing abstains rather than taking a default.
    """
    found = _distance(conn, _founder(conn, "first"))
    assert found.measurement is novelty.Measurement.UNEVALUABLE
    assert found.bin is None


def test_a_market_nobody_has_tried_is_radical(conn):
    """§16.3 makes the market hypothesis what keeps a lineage that lineage.

    So a market no earlier genome shares is the one claim to structural novelty
    this kernel can make without reading meaning.
    """
    _founder(conn, "first")
    found = _distance(conn, _founder(conn, "second", market="hospital procurement teams"))
    assert found.bin == "radical"


def test_one_changed_field_is_adjacent(conn):
    """§13.4's first flag, stated as a distance.

    "Only the industry label changed" is one field. Anything that made this
    `moderate` would put a relabel in the same niche as a genuinely different
    approach to the same customer.
    """
    _founder(conn, "first")
    found = _distance(conn, _founder(conn, "second", product="a daily stock digest"))
    assert found.bin == "adjacent"


def test_several_changed_fields_in_a_known_market_are_moderate(conn):
    """Same customer, different approach — the middle bin has to be reachable.

    Without this test `moderate` could be dead and the archive would still look
    healthy, which is the empty-bin version of a guard that never fires.
    """
    _founder(conn, "first")
    found = _distance(
        conn,
        _founder(conn, "second",
                 product="a daily stock digest",
                 revenue_model="per-report fee",
                 acquisition_channel="direct visits"),
    )
    assert found.bin == "moderate"


def test_a_market_only_change_is_radical_and_not_adjacent(conn):
    """Order of the two checks, and it is not cosmetic.

    A genome differing in exactly one field where that field *is* the market has
    a nearest neighbour one step away and pursues a customer nobody has tried.
    Checking the neighbour first would call it `adjacent` — a new market filed as
    a relabel, which inverts §13.4's flag rather than applying it. Note the flag
    still fires on the same genome (below): it *is* a relabel structurally, and
    the distance and the flag are allowed to disagree because they answer
    different questions.
    """
    _founder(conn, "first")
    second = _founder(conn, "second", market="hospital procurement teams")
    assert _distance(conn, second).bin == "radical"
    assert novelty.only_the_label_changed(conn, _hash_of(conn, second)) is not None


def test_a_permission_claim_is_not_a_new_idea(conn):
    """`risk_class` and `allowed_tools` are requests, never hypotheses (ADR-033).

    A genome identical except that it asks for more tools has proposed nothing
    new — it gets its own content hash (§16.1) and must not thereby get its own
    distance. If this fails, a Cell could reach a further niche by asking for
    permissions instead of by having an idea, which is §23.5's shape exactly.
    """
    first = _founder(conn, "first")
    second = _founder(conn, "second", risk_class="HIGH", allowed_tools=["http_fetch"])
    assert _hash_of(conn, first) != _hash_of(conn, second), "different content, different genome"

    assert novelty.field_differences({**BASE, "risk_class": "HIGH"}, BASE) == frozenset()
    found = _distance(conn, second)
    assert found.bin == "adjacent"
    assert "propose nothing" in found.reason, (
        "an identical hypothesis must not be reported as a one-field mutation"
    )


def test_a_model_policy_change_is_not_a_new_idea(conn):
    """The other half of `NON_NOVELTY_SENSE`: §14.1's *prompt*-mutation fields.

    A cheaper drafting model is a change to how the work is done, not to what
    the work is. `model_policy` and `mutation_rate` are excluded for that reason
    and this is what fails if either quietly joins the distance. `model_policy`
    is a structured `{"temperature": ...}` dict as of ADR-067 (§14.1's sampling
    socket) rather than free text — the shape changed, the exclusion did not.
    """
    _founder(conn, "first")
    second = _founder(conn, "second", model_policy={"temperature": 0.9},
                      mutation_rate=0.9)
    found = _distance(conn, second)
    assert found.bin == "adjacent"
    assert "propose nothing" in found.reason


# --- §13.4's first flag -------------------------------------------------------


def test_only_the_label_changed_names_what_it_relabels(conn):
    """§13.4's first flag, computable now that the archive is the prior.

    ADR-058 could score only §13.4's fourth clause because the other three need
    something to have changed *from*. This is the first flag in its exact
    structural form: same problem, product, revenue model, channel and workflow,
    new industry on the front.
    """
    first = _founder(conn, "first")
    second = _founder(conn, "second", market="hospital procurement teams")
    assert novelty.only_the_label_changed(conn, _hash_of(conn, second)) == _hash_of(conn, first)


def test_a_genome_that_changed_more_than_its_label_is_not_flagged(conn):
    """The other half: the flag must be able to *not* fire.

    A flag that fired on every mutation would look identical to one that worked,
    and §13.4 exists to separate ordinary ideas from relabelled ones.
    """
    _founder(conn, "first")
    second = _founder(conn, "second", market="hospital procurement teams",
                      product="a procurement price index")
    assert novelty.only_the_label_changed(conn, _hash_of(conn, second)) is None


def test_the_label_flag_is_about_the_market_and_not_about_the_count(conn):
    """One field changed is not the flag; **that** field changed is.

    §13.4's clause is "only the *industry label* changed" — a genome that
    changes only its product has proposed a different thing to the same
    customers, which is an ordinary idea. A flag keyed on the number of changed
    fields would report it as fake novelty, and a test that only ever showed the
    flag a two-field change could not tell the two rules apart.
    """
    _founder(conn, "first")
    second = _founder(conn, "second", product="a daily stock digest")
    assert novelty.field_differences(
        {**BASE, "product": "a daily stock digest"}, BASE
    ) == frozenset({"product"}), "exactly one field, and it is not the market"
    assert novelty.only_the_label_changed(conn, _hash_of(conn, second)) is None


# --- the archive --------------------------------------------------------------


def test_the_archive_is_derived_and_stores_nothing(conn):
    """§12.2's "the archive is a derived view", and §2.5's balances rule.

    A `novelty_archive` table would be the second version §2.5 refuses, and
    §12.2's own reason for keeping raw descriptors separate is so a rebinning
    cannot lose them. Here the raw material is `cell_genomes`, which is
    content-addressed and append-only.
    """
    _founder(conn, "first")
    _founder(conn, "second", market="hospital procurement teams")
    before = _fingerprint(conn)
    novelty.archive(conn)
    assert _fingerprint(conn) == before

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {t for t in tables if "novelty" in t or "descriptor" in t}


def test_a_genome_with_no_measured_dimension_is_unbinned_not_pooled(conn):
    """No catch-all niche.

    The founder's every dimension abstains. Placing it in a niche meaning
    "unknown" would leave the archive reporting that cell as occupied long after
    the colony stopped measuring anything — and §12.4's whole worry is archives
    that look fuller than they are.
    """
    founder = _founder(conn, "first")
    result = novelty.archive(conn)
    assert result.unbinned_genome_hashes == (_hash_of(conn, founder),)
    assert result.niches == ()
    assert "novelty_distance" in result.unmeasured_dimensions


def test_the_archive_bins_by_measured_dimensions_only(conn):
    """A one-dimensional archive says it is one-dimensional.

    Two of §12.1's three dimensions have no data here, so a coordinate names one
    axis. Padding it with a placeholder bin would claim a three-dimensional
    archive that §12.4 warns is nearly empty at realistic population sizes.
    """
    _founder(conn, "first")
    _founder(conn, "second", market="hospital procurement teams")
    result = novelty.archive(conn)
    assert result.measured_dimensions == ("novelty_distance",)
    assert set(result.unmeasured_dimensions) == {"buyer_type", "revenue_recurrence"}
    assert [n.coordinate for n in result.niches] == [(("novelty_distance", "radical"),)]


def test_a_niche_counts_living_cells_and_not_the_genomes_they_share(conn):
    """§9.4's niche-specific carrying capacity needs this number to exist.

    A niche's occupancy is Cells, not genomes — two Cells sharing one strategy
    are two competitors for the same capacity, which is the measure §9.4 lists
    among its founder-effect controls. **The two counts must differ in the
    fixture**, or a niche that reported `len(genome_hashes)` would pass: the
    second and third Cells here share content, so §16.1 gives them one genome.
    """
    _founder(conn, "first")
    second = _founder(conn, "second", market="hospital procurement teams")
    third = _founder(conn, "third", market="hospital procurement teams")
    assert _hash_of(conn, second) == _hash_of(conn, third), "content addressing (§16.1)"

    niche = novelty.archive(conn).niches[0]
    assert len(niche.genome_hashes) == 1
    assert niche.living_cells == 2


# --- §23.5 --------------------------------------------------------------------


def test_the_archive_never_reaches_a_cell():
    """§23.5: a Cell that learns which niche it is in learns to change niche.

    Today the descriptor is derived from genome content an operator writes, so
    there is nothing for a Cell to move. §14's automated mutation is what changes
    that, and this boundary is what stops the Cell reading the map first.
    """
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    for module in ("context.py", "deliberation.py"):
        assert "novelty" not in _imported_modules(source_dir / module), (
            f"{module} can reach the archive; a Cell shown its niche learns to pick one"
        )


def _fingerprint(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


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
