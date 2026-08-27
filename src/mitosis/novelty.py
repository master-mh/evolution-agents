"""§12's MAP-Elites archive, derived and stored nowhere (SPEC.md §12, §13.2,
§13.4, §16.1, §16.3, §9.4, §10.2, §10.3, §23.5, §31; ADR-043, ADR-058, ADR-059).

    §12.2 Raw descriptors. Store full raw behavioural descriptors **separately**;
    the archive is a **derived view**, allowing later rebuilding with different
    dimensions and bins.

**So §31's `novelty_archive` gets no table, and neither does
`behavioural_descriptors`.** That reads backwards until the clause is taken
literally: what §12.2 forbids is the archive *being* the record, so that a
rebinning cannot lose the underlying measurements. In this kernel the raw
measurements already live separately — in `cell_genomes`, which is
content-addressed and append-only, and in the hash-chained ledger and register.
Copying them into a descriptors table would create the second version §2.5
refuses ("balances are derived"), and §31 offers "suggested entities" rather
than a build order: the same reading refused `experiment_results` (ADR-043) and
`resource_usage.experiment_id` (ADR-044). **This slice ships no migration.**

The one thing that would justify a table is a descriptor nobody can recompute —
an Auditor's or a human's *judgment*, which is not derivable by definition.
ADR-059 identified exactly that gap and left it unbuilt; when it is built, it
brings its own storage and this module reads it.

## §12.1's three dimensions, and what this colony can measure

    buyer type:          human consumer / small business / enterprise / machine
    revenue recurrence:  one-off / repeat / subscription
    novelty distance:    adjacent / moderate / radical

**One of the three is live.** `novelty_distance` is structural: it compares a
genome's §16.2 content against every genome created before it. The other two
need a customer, and this colony has had one payment recorded by free-text
`source` — see `_buyer_type` and `_revenue_recurrence` for what specifically is
missing rather than a shrug.

## Why the bins are §13.4's language and not a threshold someone picked

    §13.4 Flag ideas where **only the industry label changed**, ordinary
    freelancing is described exotically, the same mechanism is renamed, or no
    new capability/transaction structure exists.

- **adjacent** — the nearest earlier genome differs in exactly **one** field.
  That is §13.4's first flag stated as a distance.
- **moderate** — differs in more than one field, but some earlier genome shares
  its `market`. Same customer, different approach.
- **radical** — no earlier genome shares its `market`. §16.3 makes the market
  hypothesis the inheritable thing that keeps a lineage *that* lineage, so a
  market nobody has tried is the one structural claim to novelty this kernel can
  make without reading meaning.

No numeric threshold is chosen anywhere except "exactly one", which §13.4 names.

**This is a distance, not a merit, and it reads in one direction.** A small
distance is evidence of §13.4's first flag. A large one proves nothing — a
genome that changed every field to nonsense scores `radical`, and detecting
*that* is §13.4's fourth flag, which ADR-058 built outside the kernel because it
needs a model call and §23.5 forbids one here.

## §23.5, and why this is safe today and will not always be

A Cell that could choose its own niche would choose the emptiest one and be the
elite of it by default — the same argument that leaves `ExperimentSpec` with no
rung field. Today the descriptor is derived from genome *content*, and genome
content is written by an operator passing `--mutation`; no Cell writes its own.
**§14's automated mutation is what changes that**, and the tell will be lineages
that drift across many fields at once for no economic reason. Recorded in
FUTURE_BUILD_HOOKS rather than pre-solved.

## What this deliberately does not do

**No elite per niche.** MAP-Elites keeps one, and picking one needs either a
scalar (§10.2 forbids it) or a Pareto comparison between Cells — which §10.3
restricts to near-duplicates, a *finer* grouping than a niche, because comparing
an Explorer with a Commercial on net contribution kills exactly the Cells whose
value is exploratory. §12.3's Thompson-sampling posteriors are the spec's own
answer for ranking inside a niche, and a beta-binomial over four Cells is noise.
`death.py` already answers domination where §10.3 permits the question.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from . import genome

#: §12.1's dimensions, transcribed with their bins. The archive is rebuildable
#: with different ones (§12.2) — this dict is the current choice, not a law.
DESCRIPTOR_SENSE: dict[str, tuple[str, ...]] = {
    "buyer_type": ("human_consumer", "small_business", "enterprise", "machine"),
    "revenue_recurrence": ("one_off", "repeat", "subscription"),
    "novelty_distance": ("adjacent", "moderate", "radical"),
}

#: The genome fields a novelty distance is measured over: §16.2's *business
#: hypothesis*, which is what §14.1's economic mutation operators act on
#: (customer, problem, channel, pricing, revenue-model, cross-domain transplant).
NOVELTY_FIELDS: frozenset[str] = frozenset(
    {"market", "problem", "product", "revenue_model", "acquisition_channel", "workflow"}
)

#: Why each remaining genome field is excluded. Reasons rather than a silent
#: complement, so a new §16.2 field cannot join a distance by default —
#: `unclassified_genome_fields()` fails until someone decides.
NON_NOVELTY_SENSE: dict[str, str] = {
    "cell_type": (
        "structural identity, not a business hypothesis. An Explorer and a "
        "Commercial pursuing the same market are not two ideas"
    ),
    "model_policy": (
        "§14.1's *prompt*-mutation half — which model drafts the work, not what "
        "the work is. A cheaper model is not a new idea"
    ),
    "mutation_rate": "how readily the lineage varies; a property of the search, not of the idea",
    "risk_class": (
        "permission-shaped (§16.2, ADR-033). A genome claiming a different risk "
        "class has not proposed anything different"
    ),
    "allowed_tools": "permission-shaped, as above: a request, never a capability",
}


def unclassified_descriptors() -> set[str]:
    """§12.1's dimensions that `DESCRIPTOR_SENSE` has not transcribed."""
    return {"buyer_type", "revenue_recurrence", "novelty_distance"} - set(DESCRIPTOR_SENSE)


def unclassified_genome_fields() -> set[str]:
    """§16.2 fields that are neither part of a novelty distance nor excused.

    Forces the decision the way `genome.unclassified_fields()` does one layer
    down: a field that is silently outside the distance is one nobody decided
    was outside it.
    """
    known = set(genome.INHERITABLE_FIELDS) | set(genome.CLAIMED_FIELDS)
    return known - NOVELTY_FIELDS - set(NON_NOVELTY_SENSE)


class Measurement(StrEnum):
    """Why a descriptor has no bin, when it has none.

    `UNMEASURABLE` means nothing in this kernel could produce it; `UNEVALUABLE`
    means this subject has no record yet — the founder genome with nothing
    earlier to be novel against. The split is ADR-059's and exists for the same
    reason: only one of the two is something a build can fix.
    """

    MEASURED = "measured"
    UNEVALUABLE = "unevaluable"
    UNMEASURABLE = "unmeasurable"


@dataclass(frozen=True)
class Descriptor:
    """One §12.1 dimension for one genome.

    `bin` is `None` unless `measurement is MEASURED`, and never a default bin —
    a genome binned `one_off` because nothing is known would be a claim about a
    revenue model nobody has observed.
    """

    dimension: str
    bin: str | None
    measurement: Measurement
    reason: str

    def __post_init__(self) -> None:
        if self.bin is not None and self.bin not in DESCRIPTOR_SENSE[self.dimension]:
            raise ValueError(f"{self.bin!r} is not a bin of {self.dimension}")


@dataclass(frozen=True)
class Niche:
    """One cell of the archive: a coordinate, and the genomes that landed in it.

    `coordinate` names only the dimensions that were measured, so a colony that
    can measure one dimension has a one-dimensional archive and says so, rather
    than filling the other two with a bin meaning "unknown" and pretending to
    three (§12.4: high-dimensional archives stay nearly empty anyway).
    """

    coordinate: tuple[tuple[str, str], ...]
    genome_hashes: tuple[str, ...]
    living_cells: int

    @property
    def label(self) -> str:
        return "/".join(f"{k}={v}" for k, v in self.coordinate) or "(unbinned)"


@dataclass(frozen=True)
class Archive:
    """§12's archive, derived on every read (§12.2) and stored nowhere (§2.5)."""

    niches: tuple[Niche, ...]
    unbinned_genome_hashes: tuple[str, ...]
    measured_dimensions: tuple[str, ...]
    unmeasured_dimensions: tuple[str, ...]

    @property
    def occupied(self) -> int:
        return len(self.niches)


# --- the raw record -----------------------------------------------------------


@dataclass(frozen=True)
class GenomeRecord:
    genome_hash: str
    created_at: str
    content: dict


def genome_records(conn: sqlite3.Connection) -> list[GenomeRecord]:
    """Every genome, oldest first — the archive's raw material.

    Ordered by creation because "novel" is a claim about what came *before*.
    `rowid` breaks ties so two genomes written in the same second still have a
    determinate order; without it a colony that seeded several at once would
    rebin itself between reads.
    """
    rows = conn.execute(
        "SELECT genome_hash, created_at, canonical_genome_json FROM cell_genomes "
        "ORDER BY created_at, rowid"
    ).fetchall()
    return [
        GenomeRecord(
            genome_hash=row["genome_hash"],
            created_at=row["created_at"],
            content=json.loads(row["canonical_genome_json"]),
        )
        for row in rows
    ]


def field_differences(left: dict, right: dict) -> frozenset[str]:
    """Which `NOVELTY_FIELDS` two genomes disagree on.

    A field absent from one and present in the other counts as a difference;
    absent from both does not. Compared on canonical content, so two genomes
    that differ only in key order are the same genome by §16.1 and never reach
    this function.
    """
    return frozenset(
        field for field in NOVELTY_FIELDS
        if left.get(field) != right.get(field)
    )


# --- §12.1's dimensions -------------------------------------------------------


def _novelty_distance(record: GenomeRecord, earlier: list[GenomeRecord]) -> Descriptor:
    """adjacent / moderate / radical, from structure alone.

    Order matters: `radical` is checked first, because "no earlier genome shares
    this market" is a statement about the whole archive, while `adjacent` is a
    statement about the nearest neighbour. Checking the nearest first would let
    a genome that differs from one predecessor in a single field be called
    adjacent while pursuing a market nobody has tried.
    """
    if not earlier:
        return Descriptor(
            "novelty_distance", None, Measurement.UNEVALUABLE,
            "the first genome in the archive: nothing earlier to be novel against",
        )
    market = record.content.get("market")
    if not any(prior.content.get("market") == market for prior in earlier):
        return Descriptor(
            "novelty_distance", "radical", Measurement.MEASURED,
            "no earlier genome shares this market hypothesis (§16.3)",
        )
    nearest = min(len(field_differences(record.content, prior.content)) for prior in earlier)
    if nearest == 0:
        # Not a hole: two genomes can differ *only* outside NOVELTY_FIELDS — a
        # different `risk_class` or `allowed_tools` gives a new content hash and
        # the same business hypothesis. That is nearer than adjacent, and it
        # shares adjacent's meaning ("next door to something tried"), so it bins
        # there rather than earning a fourth bin §12.1 does not have. The reason
        # keeps the two apart, because "changed nothing" and "changed one thing"
        # are different facts and only one of them is a mutation.
        return Descriptor(
            "novelty_distance", "adjacent", Measurement.MEASURED,
            "identical business hypothesis to an earlier genome; it differs only "
            "in permission-shaped or search-shaped fields, which propose nothing",
        )
    if nearest == 1:
        return Descriptor(
            "novelty_distance", "adjacent", Measurement.MEASURED,
            "differs from its nearest earlier genome in exactly one field "
            "— §13.4's \"only the industry label changed\", as a distance",
        )
    return Descriptor(
        "novelty_distance", "moderate", Measurement.MEASURED,
        f"differs from its nearest earlier genome in {nearest} fields, and an "
        "earlier genome shares its market",
    )


def _buyer_type() -> Descriptor:
    """Unmeasurable, and the missing piece is specific.

    §12.1's bins are about *who paid*. `revenue.record_revenue` takes a `source`
    — "an invoice id, a customer reference, 'manual'" — which is free text, so
    two payments from one buyer are indistinguishable from one payment each from
    two. The outbound direction already solved this: §21.2's
    `external_action_registry` stores a **salted hash** of a counterparty,
    equality without identity, exactly as §16.3 requires. Revenue has no such
    key, and inventing a buyer classification from free text would be a
    judgment, which §0.3 puts outside the kernel.
    """
    return Descriptor(
        "buyer_type", None, Measurement.UNMEASURABLE,
        "revenue records who paid as free text; there is no counterparty key "
        "inbound, though §21.2 has one outbound",
    )


def _revenue_recurrence() -> Descriptor:
    """Unmeasurable for the same missing key, one step further along.

    one-off / repeat / subscription is a statement about *the same buyer paying
    again*, so it needs what `_buyer_type` needs before a cadence means anything.
    Counting payments per Cell instead would report a Cell with three one-off
    customers as `repeat`, which is the undercount-versus-abstain trap ADR-044
    named — a wrong number is worse than a stated absence, because only the
    absence is visible.
    """
    return Descriptor(
        "revenue_recurrence", None, Measurement.UNMEASURABLE,
        "needs the same inbound counterparty key: recurrence is one buyer "
        "paying twice, not one Cell being paid twice",
    )


def descriptors(conn: sqlite3.Connection, genome_hash: str) -> tuple[Descriptor, ...]:
    """§12.1's three dimensions for one genome, in the clause's own order."""
    records = genome_records(conn)
    index = next((i for i, r in enumerate(records) if r.genome_hash == genome_hash), None)
    if index is None:
        raise KeyError(genome_hash)
    return (
        _buyer_type(),
        _revenue_recurrence(),
        _novelty_distance(records[index], records[:index]),
    )


# --- §13.4's first flag, which the archive makes computable -------------------


def only_the_label_changed(conn: sqlite3.Connection, genome_hash: str) -> str | None:
    """§13.4's first flag: "only the industry label changed".

    Returns the earlier genome hash this one differs from **in `market` alone**,
    or `None`. ADR-058 could not score this flag because it needed a prior; the
    archive is that prior, and this is the exact structural form of the clause —
    same problem, same product, same revenue model, same channel, new industry
    named on the front.

    §13.4's third flag ("the same mechanism is renamed") stays unbuildable here.
    Detecting a rename means deciding two different strings describe one
    mechanism, which is semantics — a model call, and §23.5 keeps those out of
    the kernel.
    """
    records = genome_records(conn)
    index = next((i for i, r in enumerate(records) if r.genome_hash == genome_hash), None)
    if index is None:
        raise KeyError(genome_hash)
    record = records[index]
    for prior in records[:index]:
        if field_differences(record.content, prior.content) == frozenset({"market"}):
            return prior.genome_hash
    return None


# --- the archive --------------------------------------------------------------


def archive(conn: sqlite3.Connection) -> Archive:
    """Group every genome by its measured descriptors (§12.2's derived view).

    A genome whose every dimension abstains is *unbinned* rather than placed in
    a catch-all niche. A niche called "unknown" is one an archive would go on
    reporting as occupied long after the colony stopped measuring anything.
    """
    records = genome_records(conn)
    living = {
        row["genome_hash"]: int(row["n"])
        for row in conn.execute(
            "SELECT genome_hash, count(*) AS n FROM cells "
            "WHERE status IN ('created', 'alive', 'dormant', 'quarantined') "
            "GROUP BY genome_hash"
        )
    }

    grouped: dict[tuple[tuple[str, str], ...], list[str]] = {}
    unbinned: list[str] = []
    measured: set[str] = set()
    for index, record in enumerate(records):
        found = (
            _buyer_type(),
            _revenue_recurrence(),
            _novelty_distance(record, records[:index]),
        )
        coordinate = tuple(
            (d.dimension, d.bin) for d in found
            if d.measurement is Measurement.MEASURED and d.bin is not None
        )
        measured.update(dimension for dimension, _ in coordinate)
        if not coordinate:
            unbinned.append(record.genome_hash)
            continue
        grouped.setdefault(coordinate, []).append(record.genome_hash)

    niches = tuple(
        Niche(
            coordinate=coordinate,
            genome_hashes=tuple(hashes),
            living_cells=sum(living.get(h, 0) for h in hashes),
        )
        for coordinate, hashes in sorted(grouped.items())
    )
    return Archive(
        niches=niches,
        unbinned_genome_hashes=tuple(unbinned),
        measured_dimensions=tuple(sorted(measured)),
        unmeasured_dimensions=tuple(sorted(set(DESCRIPTOR_SENSE) - measured)),
    )
