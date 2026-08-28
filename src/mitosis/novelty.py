"""§12's MAP-Elites archive, derived from records it does not own (SPEC.md §12,
§13.2, §13.4, §16.1, §16.3, §0.3, §9.4, §10.2, §10.3, §23.5, §31; ADR-043,
ADR-058, ADR-059, ADR-061, ADR-062).

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
`resource_usage.experiment_id` (ADR-044). **This module still owns no table.**

ADR-060 predicted the one exception: "a descriptor nobody can recompute — an
Auditor's or a human's *judgment*, which is not derivable by definition ... when
it is built, it brings its own storage and this module reads it." **That has now
happened** (ADR-062). `buyer_attestations` is a person's judgment about a buyer,
it is owned by `counterparty.py`, and this module only reads it — which is the
prediction working as stated rather than an exception to §12.2. The archive is
still derived on every read and still stores nothing.

## §12.1's three dimensions, and what this colony can measure

    buyer type:          human consumer / small business / enterprise / machine
    revenue recurrence:  one-off / repeat / subscription
    novelty distance:    adjacent / moderate / radical

**All three are live** (ADR-060, ADR-061, ADR-062), and they reach the archive
by three different routes, which is the interesting part:

- `novelty_distance` is **structural** — a genome's §16.2 content against every
  genome created before it. The kernel computes it.
- `revenue_recurrence` is **observed** — the salted counterparty key on a revenue
  transaction, equality without identity, the same digest §21.2 uses outbound.
  The kernel derives it from the ledger.
- `buyer_type` is **declared** — a person who can see the buyer says so, and the
  record keeps who said it. No query can produce it: a digest answers "same
  party?" and nothing else, while human consumer / small business / enterprise /
  machine is a claim about who the buyer *is*, which §16.3 puts permanently
  outside this colony. §0.3 names the route ("external evaluators"), ADR-041
  built the mechanism, and ADR-062 wired this dimension to it.

**A Cell writes none of the three**, and for `buyer_type` that is structural
rather than promised: nothing Cell-reachable can call `attest_buyer_type`, and an
AST walk over every module says so.

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

from . import counterparty, genome
from .revenue import REVENUE_TRANSACTION_TYPE

#: §12.1's dimensions, transcribed with their bins. The archive is rebuildable
#: with different ones (§12.2) — this dict is the current choice, not a law.
DESCRIPTOR_SENSE: dict[str, tuple[str, ...]] = {
    "buyer_type": ("human_consumer", "small_business", "enterprise", "machine"),
    "revenue_recurrence": ("one_off", "repeat", "subscription"),
    "novelty_distance": ("adjacent", "moderate", "radical"),
}

#: Bins §12.1 names that nothing in this kernel can produce, and why. Written
#: down rather than left as an empty branch, because a bin that never appears
#: looks identical to a bin that never happens — and only one of those is a
#: statement about the colony.
UNREACHABLE_BINS: dict[str, str] = {
    "subscription": (
        "a subscription is a *contract*, not a payment pattern: three payments "
        "under one agreement and three separate invoices from a loyal buyer are "
        "the same rows here. Telling them apart needs the service-obligation "
        "record §16.3 calls liability-linked, and this colony has none, so a "
        "subscription lands in `repeat` and is described honestly there"
    ),
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


def _buyer_type(
    payments: tuple[str | None, ...],
    attested: dict[str, str | None],
) -> Descriptor:
    """§12.1's segment, read off what a person declared about the buyers.

    **No query can produce this** (ADR-061). A salted digest gives equality,
    never identity, and human consumer / small business / enterprise / machine is
    a claim about who the buyer *is* — which §16.3 keeps outside this colony
    permanently. So it arrives declared, with its declarer recorded
    (`counterparty.attest_buyer_type`), which is §0.3's own answer: canonical
    metrics come from independent systems and external evaluators, and an
    operator reading an invoice is one.

    `attested` maps a counterparty digest to the position in force, with `None`
    where a position was **withdrawn** — a party somebody looked at and declined
    to classify, which is a different fact from one nobody has looked at, and
    they abstain with different reasons.

    **Mixed is checked before incomplete, and the order is load-bearing.** Two
    different types among the attested buyers is monotone: no further attestation
    can unmix them, so that abstention is *permanent* and says so. Every other
    abstention here is a gap somebody can close. Reporting both the same way
    would tell an operator to go and attest more buyers in the one case where it
    cannot help.

    §12.1 has no bin for a genome selling into two segments, and none is
    invented. A dominant-segment rule would need a threshold nobody has chosen —
    the same refusal `_novelty_distance` makes, where the only number is
    §13.4's own "exactly one".
    """
    if not payments:
        return Descriptor(
            "buyer_type", None, Measurement.UNEVALUABLE,
            "no revenue has been recorded for this genome; a buyer type "
            "describes who paid",
        )

    keyed = [digest for digest in payments if digest is not None]
    buyers = set(keyed)
    positions = {digest: attested.get(digest) for digest in buyers if digest in attested}
    named = {bin_ for bin_ in positions.values() if bin_ is not None}

    if len(named) > 1:
        return Descriptor(
            "buyer_type", None, Measurement.UNMEASURABLE,
            f"its buyers span {len(named)} segments ({', '.join(sorted(named))}); "
            "§12.1 has no bin for that and no further attestation can unmix them",
        )

    unkeyed = len(payments) - len(keyed)
    unattested = len(buyers - set(positions))
    withdrawn = sum(1 for bin_ in positions.values() if bin_ is None)
    if unkeyed or unattested or withdrawn:
        missing = []
        if unkeyed:
            missing.append(f"{unkeyed} of {len(payments)} payment(s) carry no counterparty key")
        if unattested:
            missing.append(f"{unattested} of {len(buyers)} buyer(s) have no attestation")
        if withdrawn:
            missing.append(f"{withdrawn} attestation(s) were withdrawn")
        return Descriptor(
            "buyer_type", None, Measurement.UNMEASURABLE,
            "; ".join(missing) + " — any of them could be a second segment, and "
            "§12.1's bin is a claim about every buyer, not the ones on record",
        )

    return Descriptor(
        "buyer_type", named.pop(), Measurement.MEASURED,
        f"all {len(buyers)} buyer(s) across {len(payments)} payment(s) were "
        "attested to one segment by a person (§0.3)",
    )


def _revenue_recurrence(payments: tuple[str | None, ...]) -> Descriptor:
    """§12.1's cadence, read off the counterparty keys on a genome's revenue.

    `payments` is one entry per revenue transaction credited to a Cell carrying
    this genome, holding that payment's counterparty digest or `None` where the
    payment was recorded without one.

    **The rule is deliberately monotone, and abstains asymmetrically.** More
    data can add a repeat and can never remove one, so:

    - a digest seen twice is `repeat` **even if other payments are unkeyed** —
      the conclusion cannot be overturned by the missing rows;
    - all payments keyed and all distinct is `one_off`;
    - all distinct *but some payments unkeyed* abstains, because the unkeyed
      ones could be the second payment that makes it `repeat`, and reporting
      `one_off` there is precisely ADR-044's undercount trap: a wrong number is
      worse than a stated absence, because only the absence is visible.

    **Aggregated across the genome's Cells, not per Cell.** One buyer paying two
    siblings is a buyer coming back to the same business idea, and the archive
    bins genomes. The trap ADR-060 named runs the other way — counting *payments*
    per Cell, which would call three one-off customers `repeat` — and keying on
    the buyer is what closes it.

    `subscription` is never returned; see `UNREACHABLE_BINS`.
    """
    if not payments:
        return Descriptor(
            "revenue_recurrence", None, Measurement.UNEVALUABLE,
            "no revenue has been recorded for this genome; a cadence needs a "
            "payment before it means anything",
        )
    keyed = [digest for digest in payments if digest is not None]
    distinct = set(keyed)
    if len(distinct) < len(keyed):
        return Descriptor(
            "revenue_recurrence", "repeat", Measurement.MEASURED,
            f"one counterparty paid more than once across {len(payments)} "
            "payment(s). A subscription would land here too: this colony has no "
            "service-obligation record to tell a contract from a loyal buyer",
        )
    unkeyed = len(payments) - len(keyed)
    if unkeyed:
        return Descriptor(
            "revenue_recurrence", None, Measurement.UNMEASURABLE,
            f"{unkeyed} of {len(payments)} payment(s) carry no counterparty key, "
            "and any one of them could be the second payment from a buyer "
            "already counted; `one_off` cannot be read from a partial record",
        )
    return Descriptor(
        "revenue_recurrence", "one_off", Measurement.MEASURED,
        f"{len(distinct)} counterparties across {len(payments)} payment(s), each "
        "paying exactly once, and every payment carries a key",
    )


def revenue_counterparties(conn: sqlite3.Connection) -> dict[str, tuple[str | None, ...]]:
    """Every genome's revenue payments, as counterparty digests (§12.1's raw material).

    One query for the whole colony rather than one per genome, because `archive`
    asks for every genome at once. The join runs through the *cash* leg: a
    revenue transaction has two entries and only the credit to the Cell carries
    a `cell_id`, so this yields exactly one row per payment.

    `None` means the payment was recorded without a counterparty — revenue that
    predates migration 0028, or an operator who did not have the buyer to hand.
    It is kept rather than dropped, because the *count* of unkeyed payments is
    what `_revenue_recurrence` needs in order to know it must abstain.
    """
    rows = conn.execute(
        """
        SELECT c.genome_hash AS genome_hash, t.counterparty_hash AS counterparty_hash
        FROM ledger_transactions t
        JOIN ledger_entries e ON e.transaction_id = t.transaction_id
        JOIN cells c ON c.cell_id = e.cell_id
        WHERE t.transaction_type = ?
        ORDER BY t.rowid
        """,
        (REVENUE_TRANSACTION_TYPE,),
    ).fetchall()
    payments: dict[str, list[str | None]] = {}
    for row in rows:
        payments.setdefault(row["genome_hash"], []).append(row["counterparty_hash"])
    return {genome_hash: tuple(v) for genome_hash, v in payments.items()}


def descriptors(conn: sqlite3.Connection, genome_hash: str) -> tuple[Descriptor, ...]:
    """§12.1's three dimensions for one genome, in the clause's own order."""
    records = genome_records(conn)
    index = next((i for i, r in enumerate(records) if r.genome_hash == genome_hash), None)
    if index is None:
        raise KeyError(genome_hash)
    payments = revenue_counterparties(conn).get(genome_hash, ())
    attested = counterparty.current_buyer_types(conn)
    return (
        _buyer_type(payments, attested),
        _revenue_recurrence(payments),
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

    payments = revenue_counterparties(conn)
    attested = counterparty.current_buyer_types(conn)

    grouped: dict[tuple[tuple[str, str], ...], list[str]] = {}
    unbinned: list[str] = []
    measured: set[str] = set()
    for index, record in enumerate(records):
        found = (
            _buyer_type(payments.get(record.genome_hash, ()), attested),
            _revenue_recurrence(payments.get(record.genome_hash, ())),
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
