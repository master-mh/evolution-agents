"""The artifact store: what a Cell makes (SPEC.md §20, §18.1, §11, §15.2, §19.3,
§31; Amendment A3; Charter C13; ADR-035).

A Cell could decide, and since ADR-034 it could read. The thing it *produces*
had nowhere to live. `revenue.record_revenue` attributed money to a free-text
`source`, and `ledger_entries.artifact_id` — an **Amendment A3 required field,
present since migration 0001** — was never populated by anything. This is the
object that closes that gap: the link between "a Cell decided" and "money moved
because of what it made".

**Identity is the content hash (§11.3).** The clause lists "duplicated artifacts
with new names" among the things Auditors inspect for. The obvious store — a
uuid and a title — makes that trivial to do and turns detection into a permanent
chore. Content addressing makes it *unrepresentable*: two identical artifacts are
one row, and a Cell that resubmits its own work gets its own artifact back. Same
move §16.1 makes for genomes (ADR-018), and the same shape as ADR-033's closed
genome schema — prefer making the bad state impossible over detecting it.

**§1 forbids the fitness dimension the obvious store would create.** The colony
"is *not* successful because it ... produces many artifacts". So nothing here
counts artifacts toward anything, and there is deliberately no `artifact_count`
on any fitness surface. §10.3 says an Explorer's value comes from *useful*
artifacts, and §11.2 makes usefulness strictly downstream — another Cell adopts
it, verification passes, the adopter progresses, it is not reciprocal farming,
the causal contribution is recorded. None of those five are things the producer
controls, which is the point.

**Rights propagate; they never reset (§20.2).** An artifact derived from a
fetched page inherits that page's rights position on a **most-restrictive-wins**
basis, and taint labels union. Without this, "summarise it into an artifact" is
a one-step launder: a page the colony may not redistribute becomes apparently
clean colony IP, and since every tool result records `commercial_use: unknown`,
anything built from one is `unknown` too. `test_rights_do_not_reset_through_a_
derived_artifact` is the guard.

**Production is free; export is gated.** §28's Phase 8 says Cells "may produce
product prototypes, landing-page drafts, pricing recommendations" and that
"humans review all **external use**" — and §19.3 names an "artifact-export
gateway". Writing to the colony's own store is not an external action, so
nothing here gates creation. What is gated is `export`, the recorded act of a
human taking an artifact outside. Gating production instead was the obvious
alternative and is worse twice over: it puts a human in the loop for a Cell
drafting into its own store, and it spends the §23 queue — a finite resource
§23.5 warns will be optimised against — on the cheapest thing a Cell does.

Nothing bounds production except the economics that already exist: identical
content collapses to one row, and varied content costs metered model calls.

**Charter C13's subject is artifacts, and this is its mechanism.** "Adversarial
taint artifacts cannot migrate to real-facing execution" is the only Charter
clause with no test, deferred to Phase 6. The export gateway is exactly the
router that clause describes, so it is built here and refuses on
`SIM_ADVERSARIAL`. **That makes C13's mechanism testable without making C13
satisfied**: §18.2 is about lineages evolved under adversarial synthetic
incentives, and nothing in the kernel can yet *produce* that label. The router
works; the thing it guards against does not exist. Said plainly rather than
counted as a win.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from . import audit, ids, lifecycle, rights

#: §18.1's provenance labels, verbatim.
TAINT_PUBLIC_SAFE = "PUBLIC_SAFE"
TAINT_SIM_STANDARD = "SIM_STANDARD"
TAINT_SIM_ADVERSARIAL = "SIM_ADVERSARIAL"
TAINT_UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"
TAINT_HUMAN_AUTHORED = "HUMAN_AUTHORED"
TAINT_AUDITED = "AUDITED"
TAINT_CLEAN_ROOM_REIMPLEMENTED = "CLEAN_ROOM_REIMPLEMENTED"

TAINT_LABELS: frozenset[str] = frozenset(
    {
        TAINT_PUBLIC_SAFE,
        TAINT_SIM_STANDARD,
        TAINT_SIM_ADVERSARIAL,
        TAINT_UNTRUSTED_EXTERNAL,
        TAINT_HUMAN_AUTHORED,
        TAINT_AUDITED,
        TAINT_CLEAN_ROOM_REIMPLEMENTED,
    }
)

#: Charter C13 / §18.2. A label here may never leave the colony. Only
#: SIM_ADVERSARIAL: the clause is about artifacts "evolved under adversarial
#: synthetic incentives", not about everything the colony did not write itself.
#: **UNTRUSTED_EXTERNAL is deliberately absent** — blocking it would forbid
#: exporting anything informed by research, which is every real deliverable.
#: What that label does instead is force individual review and, through
#: `commercial_use`, block *commercial* export specifically.
EXPORT_BLOCKING_TAINTS: frozenset[str] = frozenset({TAINT_SIM_ADVERSARIAL})

#: §20.1 `commercial-use status`, most restrictive first. Order *is* the policy:
#: `_most_restrictive` takes the earliest, so an unknown source can never be
#: averaged away by a permitted one.
COMMERCIAL_USE_PRECEDENCE: tuple[str, ...] = ("prohibited", "unknown", "permitted")

#: What a Cell may produce. Free text would make the artifact index unreadable
#: and §12's behavioural descriptors ungroupable; §28's Phase 8 names these.
ARTIFACT_KINDS: frozenset[str] = frozenset(
    {
        "prototype",
        "landing_page_draft",
        "pricing_recommendation",
        "fulfilment_artifact",
        "outreach_draft",
        "report",
        "negative_finding",
    }
)

#: Upper bound on content. Generous relative to a proposal (§15's caps exist so
#: that today's proposal is not tomorrow's context) because an artifact's
#: content **never enters context** — §15.2 asks for an artifact *index*, and
#: that is what `context.py` renders. The store holds the thing; the Cell sees
#: that it exists.
MAX_CONTENT_CHARS = 20_000


class ArtifactError(Exception):
    pass


class ExportRefused(ArtifactError):
    """§19.3's gateway refused. Charter C13, or §20.2 rights."""


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    artifact_hash: str
    kind: str
    title: str
    content: str
    content_bytes: int
    created_by_cell_id: str
    created_at_utc: datetime
    taint_labels: tuple[str, ...]
    licence: str
    permitted_uses: str
    commercial_use: str
    contains_personal_data: bool
    retention_rule: str
    source_summary: str
    exported_at_utc: datetime | None
    exported_by: str | None
    export_is_commercial: bool | None

    @property
    def is_exported(self) -> bool:
        return self.exported_at_utc is not None


@dataclass(frozen=True)
class Provenance:
    """§20.1's metadata for one artifact, after inheritance."""

    licence: str
    permitted_uses: str
    commercial_use: str
    contains_personal_data: bool
    retention_rule: str
    source_summary: str
    taint_labels: tuple[str, ...]


def compute_artifact_hash(*, kind: str, title: str, content: str) -> str:
    """The content address.

    Covers what the artifact *is* — kind, title, body — and deliberately not who
    made it or when. §16.1 wants a hash usable for deduplication and
    counterfactual comparison, which requires two structurally identical work
    products to hash identically regardless of which Cell produced them. That is
    also what makes §11.3's rename attack impossible rather than merely visible:
    a title change is a content change, so it is a *different* artifact, and
    submitting the same title with the same body returns the same row.
    """
    canonical = json.dumps(
        {"kind": kind, "title": title, "content": content},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- §20.2 rights inheritance -------------------------------------------------


#: Where an artifact that read nothing starts. Split out of
#: `inherit_provenance` so ADR-041's colony attestation has something to
#: overlay. **Only the three rights fields are an operator's to establish** —
#: the rest describe an artifact with no sources and are facts rather than
#: positions, so an attestation does not reach them.
COLONY_AUTHORED = Provenance(
    licence="colony-authored",
    permitted_uses="internal use; external use requires export approval",
    # Not `permitted`, and deliberately: whether the colony may sell what it
    # wrote is a question for a person. Until ADR-041 nothing could ask one, so
    # this default was also the permanent answer.
    commercial_use="unknown",
    contains_personal_data=False,
    retention_rule="retain until superseded",
    source_summary="no external sources",
    taint_labels=(),
)


def _attested(conn: sqlite3.Connection, recorded: Provenance, *, url: str) -> Provenance:
    """Overlay the operator's rights position for `url`'s host, if there is one.

    **The attestation replaces the recorded position; it is not folded with
    it.** Folding most-restrictive-wins would make `permitted` unreachable,
    since what it would fold against is `fetchers.py` reporting `unknown` — and
    that `unknown` is the absence of a statement, not a statement. A person who
    has read the licence supersedes a fetcher that could not. The same
    replacement carries the tightening direction: an attestation of `prohibited`
    overrides an optimistic recorded position just as readily.

    Most-restrictive-wins still governs *between* sources, so one attested
    source cannot wash out an unattested one in the same artifact.
    """
    attestation = rights.current_for_url(conn, url)
    if attestation is None:
        return recorded
    return replace(
        recorded,
        licence=attestation.licence,
        permitted_uses=attestation.permitted_uses,
        commercial_use=attestation.commercial_use,
    )


def _most_restrictive(values: list[str]) -> str:
    for candidate in COMMERCIAL_USE_PRECEDENCE:
        if candidate in values:
            return candidate
    return "unknown"


def inherit_provenance(
    sources: list[Provenance],
    *,
    own: Provenance | None = None,
    colony: Provenance | None = None,
) -> Provenance:
    """Combine source provenance into the derived artifact's own (§20.1, §18.1).

    **Most-restrictive-wins on rights, union on taint.** The alternative — take
    the producing Cell's declared rights, or the first source's — is the
    laundering path §20.2 exists to close: a page the colony may not
    redistribute becomes clean colony IP by being summarised once.

    `own` is what the producer declares about content it wrote itself. It is
    combined *with* the sources rather than overriding them, because a Cell
    cannot grant itself rights over material it merely read — **and it may never
    carry `permitted`**, which is §0.3 at this boundary. With no sources, `own`
    alone would decide, so a Cell able to declare itself commercially permitted
    would be defining the one canonical fact standing between the colony and
    selling something. It may say `unknown` or `prohibited`: the same asymmetry
    §23.5 forces on `claimed_tier`, where a Cell may raise its own risk and
    never lower it. Loosening is an operator's (ADR-041).

    `colony` is what an operator has established about the colony's own output,
    and applies only when nothing was read and nothing declared. An artifact
    built on a fetched page is not the colony's own work, so its rights come
    from the page and this never reaches it.
    """
    if own is not None and own.commercial_use == "permitted":
        raise ArtifactError(
            "a producer may not declare its own content commercially permitted "
            "(§0.3 — a Cell may explain a result, never define the canonical one). "
            "Commercial rights are established by an operator attestation: "
            "rights.attest / `mitosis set-rights`."
        )

    contributions = list(sources) + ([own] if own is not None else [])
    if not contributions:
        # Nothing was read and nothing declared: the Cell wrote it, so the
        # colony holds it — and whether the colony may *sell* its own output is
        # a question for a person, answered by a `colony` attestation if one has
        # been made and left `unknown` if not.
        return colony or COLONY_AUTHORED

    licences = sorted({c.licence for c in contributions})
    taints: set[str] = set()
    for contribution in contributions:
        taints.update(contribution.taint_labels)

    return Provenance(
        licence=licences[0] if len(licences) == 1 else "mixed: " + ", ".join(licences),
        permitted_uses=" | ".join(sorted({c.permitted_uses for c in contributions})),
        commercial_use=_most_restrictive([c.commercial_use for c in contributions]),
        contains_personal_data=any(c.contains_personal_data for c in contributions),
        retention_rule=" | ".join(sorted({c.retention_rule for c in contributions})),
        source_summary="; ".join(
            sorted({c.source_summary for c in contributions if c.source_summary})
        )
        or "no external sources",
        taint_labels=tuple(sorted(taints)),
    )


def provenance_of_tool_call(conn: sqlite3.Connection, tool_call_id: str) -> Provenance:
    """A tool result's §20.1 position, read as a source.

    Most fields come from what the fetcher reported. **The three rights fields
    do not, once an operator has attested the source** — `_attested` overlays
    their position for the host, so this returns what the colony currently
    believes about the page rather than only what the fetch could tell.
    A fetched page is `unknown` on licence and commercial use by construction
    (see `fetchers.py`), which is what made anything derived from one `unknown`
    too — and unsellable "until a person says otherwise". This is where a person
    says otherwise:
    `_attested` overlays an operator's position for the source's host, so this
    returns what the colony *currently believes* about the page rather than only
    what the fetch reported.

    Reading current attestations rather than a stored snapshot is what makes the
    position retroactive without editing anything. The `artifacts` row keeps
    what was known when the artifact was made (§3.6); this is what is known now.
    """
    row = conn.execute(
        "SELECT source, licence, permitted_uses, commercial_use, "
        "       contains_personal_data, taint_label "
        "FROM tool_calls WHERE tool_call_id = ? AND status = 'succeeded'",
        (tool_call_id,),
    ).fetchone()
    if row is None:
        raise ArtifactError(
            f"no succeeded tool call {tool_call_id!r} — an artifact cannot cite a "
            "source that did not return anything"
        )
    recorded = Provenance(
        licence=row["licence"] or "unknown",
        permitted_uses=row["permitted_uses"] or "unknown",
        commercial_use=row["commercial_use"] or "unknown",
        contains_personal_data=bool(row["contains_personal_data"]),
        retention_rule="follows source",
        source_summary=row["source"] or "unknown",
        taint_labels=(row["taint_label"],) if row["taint_label"] else (),
    )
    return _attested(conn, recorded, url=row["source"] or "")


def provenance_of_artifact(conn: sqlite3.Connection, artifact_id: str) -> Provenance:
    """The position stored on the row: **what was known when it was made.**

    A historical record, and left one deliberately. `effective_provenance` is
    what the colony believes now, and the two diverge for any artifact older
    than an attestation about one of its sources. Keeping both is §3.6's habit
    — post an adjustment, never edit history — applied to rights rather than to
    money. See `effective_provenance` for why the cascading alternative is
    worse.
    """
    artifact = get(conn, artifact_id)
    if artifact is None:
        raise ArtifactError(f"no such artifact: {artifact_id}")
    return Provenance(
        licence=artifact.licence,
        permitted_uses=artifact.permitted_uses,
        commercial_use=artifact.commercial_use,
        contains_personal_data=artifact.contains_personal_data,
        retention_rule=artifact.retention_rule,
        source_summary=artifact.source_summary,
        taint_labels=artifact.taint_labels,
    )


def effective_provenance(
    conn: sqlite3.Connection, artifact_id: str, *, _seen: frozenset[str] = frozenset()
) -> Provenance:
    """The artifact's §20.1 position as the colony understands it **now**
    (ADR-041).

    Re-derived from the same inputs `_create_locked` used — the lineage's
    sources and the producer's own declaration — except that each source is read
    against current attestations. So an operator who establishes that a page is
    CC-BY reaches every artifact already built on it, without a single row being
    rewritten.

    **The alternative was to cascade the new position into the stored columns,
    and §3.6 rules it out rather than taste.** An artifact exported
    non-commercially under `unknown` would afterwards read as having been
    `permitted` at the time, which is not what happened. "Never edit history to
    correct something — post a new, signed adjustment" is the ledger's rule and
    it is the right one here: the attestation *is* the adjustment, and the
    stored column stays the honest record of what was known.

    The cost is two notions of one artifact's rights, which is exactly the drift
    this repo keeps finding in its own comments. It is contained by making the
    division of labour explicit: **`check_exportable` is the only place the
    answer is load-bearing, and it reads this one.** The stored columns are for
    display and for the record.
    """
    if artifact_id in _seen:
        raise ArtifactError(
            f"artifact lineage cycles through {artifact_id} — an artifact cannot "
            "descend from itself"
        )
    row = conn.execute(
        "SELECT own_provenance_json FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        raise ArtifactError(f"no such artifact: {artifact_id}")

    seen = _seen | {artifact_id}
    sources: list[Provenance] = []
    for edge in lineage_of(conn, artifact_id):
        if edge["source_tool_call_id"]:
            sources.append(provenance_of_tool_call(conn, edge["source_tool_call_id"]))
        else:
            sources.append(
                effective_provenance(conn, edge["source_artifact_id"], _seen=seen)
            )

    return inherit_provenance(
        sources,
        own=_provenance_from_json(row["own_provenance_json"]),
        colony=colony_provenance(conn),
    )


def colony_provenance(conn: sqlite3.Connection) -> Provenance | None:
    """What an operator has established about the colony's own output, or None.

    Only the three rights fields move: an attestation is a position on a
    licence, not a claim about whether the work contains personal data.
    """
    attestation = rights.colony_attestation(conn)
    if attestation is None:
        return None
    return replace(
        COLONY_AUTHORED,
        licence=attestation.licence,
        permitted_uses=attestation.permitted_uses,
        commercial_use=attestation.commercial_use,
    )


def _provenance_to_json(provenance: Provenance | None) -> str | None:
    if provenance is None:
        return None
    return json.dumps(
        {
            "licence": provenance.licence,
            "permitted_uses": provenance.permitted_uses,
            "commercial_use": provenance.commercial_use,
            "contains_personal_data": provenance.contains_personal_data,
            "retention_rule": provenance.retention_rule,
            "source_summary": provenance.source_summary,
            "taint_labels": list(provenance.taint_labels),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _provenance_from_json(raw: str | None) -> Provenance | None:
    """NULL means the producer declared nothing, which is every row written
    before ADR-041 and every row written by a caller that passes no
    `own_provenance` — currently all of them."""
    if not raw:
        return None
    data = json.loads(raw)
    return Provenance(
        licence=data["licence"],
        permitted_uses=data["permitted_uses"],
        commercial_use=data["commercial_use"],
        contains_personal_data=bool(data["contains_personal_data"]),
        retention_rule=data["retention_rule"],
        source_summary=data["source_summary"],
        taint_labels=tuple(data["taint_labels"]),
    )


# --- creation -----------------------------------------------------------------


def create(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    kind: str,
    title: str,
    content: str,
    source_tool_call_ids: tuple[str, ...] = (),
    source_artifact_ids: tuple[str, ...] = (),
    deliberation_id: str | None = None,
    own_provenance: Provenance | None = None,
    now: datetime | None = None,
) -> Artifact:
    """Record what a Cell made. Not gated — see the module docstring.

    Idempotent by content: identical kind/title/content returns the existing
    artifact rather than a second one (§11.3). The *first* producer keeps
    authorship, exactly as `lifecycle._get_or_create_genome` keeps the first
    genome's provenance — a later independent rediscovery of the same content
    must not rewrite who got there first.
    """
    now = now or datetime.now(timezone.utc)
    _validate(kind=kind, title=title, content=content)

    conn.execute("BEGIN IMMEDIATE")
    try:
        artifact = _create_locked(
            conn,
            cell_id=cell_id,
            kind=kind,
            title=title,
            content=content,
            source_tool_call_ids=source_tool_call_ids,
            source_artifact_ids=source_artifact_ids,
            deliberation_id=deliberation_id,
            own_provenance=own_provenance,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return artifact


def _create_locked(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    kind: str,
    title: str,
    content: str,
    source_tool_call_ids: tuple[str, ...] = (),
    source_artifact_ids: tuple[str, ...] = (),
    deliberation_id: str | None = None,
    own_provenance: Provenance | None = None,
    now: datetime,
) -> Artifact:
    """Caller holds the write lock, so a deliberation can fold artifact
    creation into the same transaction that records its proposal."""
    artifact_hash = compute_artifact_hash(kind=kind, title=title, content=content)

    existing = conn.execute(
        "SELECT * FROM artifacts WHERE artifact_hash = ?", (artifact_hash,)
    ).fetchone()
    if existing is not None:
        return _row_to_artifact(existing)

    cell = lifecycle.get_cell(conn, cell_id)
    if cell is None:
        raise ArtifactError(f"unknown cell: {cell_id!r}")

    # `effective_provenance` rather than `provenance_of_artifact` for the source
    # artifacts: a new artifact should inherit what the colony believes about its
    # sources *now*, not the snapshot an older sibling happened to be born with.
    # Without this an attestation would reach existing artifacts (which read
    # through the effective path) but not new ones derived from them.
    sources = [
        provenance_of_tool_call(conn, tool_call_id) for tool_call_id in source_tool_call_ids
    ] + [effective_provenance(conn, source_id) for source_id in source_artifact_ids]
    provenance = inherit_provenance(
        sources, own=own_provenance, colony=colony_provenance(conn)
    )

    artifact_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO artifacts (
            artifact_id, artifact_hash, kind, title, content, content_bytes,
            created_by_cell_id, created_by_deliberation_id, created_at_utc,
            taint_labels_json, licence, permitted_uses, commercial_use,
            contains_personal_data, retention_rule, source_summary,
            own_provenance_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            artifact_hash,
            kind,
            title,
            content,
            len(content.encode("utf-8")),
            cell_id,
            deliberation_id,
            now.isoformat(),
            json.dumps(list(provenance.taint_labels), separators=(",", ":")),
            provenance.licence,
            provenance.permitted_uses,
            provenance.commercial_use,
            1 if provenance.contains_personal_data else 0,
            provenance.retention_rule,
            provenance.source_summary,
            # Stored apart from the fold so `effective_provenance` can rebuild
            # this artifact's position exactly. Folding it in and forgetting it
            # was harmless only while nothing passed one.
            _provenance_to_json(own_provenance),
        ),
    )

    # §11.4's contribution graph, first edges.
    for tool_call_id in source_tool_call_ids:
        conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(artifact_id, source_artifact_id, source_tool_call_id) VALUES (?, NULL, ?)",
            (artifact_id, tool_call_id),
        )
    for source_id in source_artifact_ids:
        conn.execute(
            "INSERT OR IGNORE INTO artifact_lineage "
            "(artifact_id, source_artifact_id, source_tool_call_id) VALUES (?, ?, NULL)",
            (artifact_id, source_id),
        )

    audit.record(
        conn,
        event_type="artifact_created",
        cell_id=cell_id,
        description=f"{kind}: {title}",
        metadata={
            "artifact_id": artifact_id,
            "artifact_hash": artifact_hash,
            "commercial_use": provenance.commercial_use,
            "taint_labels": list(provenance.taint_labels),
            "source_count": len(sources),
        },
    )

    row = conn.execute(
        "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    return _row_to_artifact(row)


def _validate(*, kind: str, title: str, content: str) -> None:
    if kind not in ARTIFACT_KINDS:
        raise ArtifactError(
            f"unknown artifact kind {kind!r}. Known: {', '.join(sorted(ARTIFACT_KINDS))}"
        )
    if not title.strip():
        raise ArtifactError("an artifact must have a title")
    if not content.strip():
        raise ArtifactError("an artifact must have content — an empty deliverable is not one")
    if len(content) > MAX_CONTENT_CHARS:
        raise ArtifactError(
            f"content is {len(content)} chars, over the {MAX_CONTENT_CHARS} cap"
        )


# --- §19.3's export gateway (Charter C13, §20.2) ------------------------------


def check_exportable(
    conn: sqlite3.Connection, artifact_id: str, *, commercial: bool
) -> None:
    """Would this artifact be allowed out? Raises `ExportRefused` if not.

    Two refusals, from two different clauses, and keeping them distinct matters
    because they mean different things to whoever is refused:

    1. **Charter C13 / §18.2** — an adversarial-taint artifact may never reach a
       real-facing environment, commercial or not. Absolute.
    2. **§20.2** — commercial export requires `commercial_use == permitted`.
       Public visibility is not a licence to resell, and a fetched page is
       `unknown` by construction, so anything derived from one cannot be sold
       until a person establishes the rights.

    **The two refusals read from two different places, and that is the point.**
    Charter C13 reads the taint labels *stored on the row*: taint is a fact
    about where content came from, it only ever unions, and no attestation
    touches it — so the historical record is the strongest available answer.
    §20.2 reads `effective_provenance`, because a rights position is a belief a
    person can update, and the whole purpose of ADR-041 is that updating it
    reaches artifacts that already exist. An implementation that read the stored
    `commercial_use` here would leave every pre-attestation artifact permanently
    unsellable, which is the gap this was built to close.

    Read-only, so an operator can ask before committing to anything.
    """
    artifact = get(conn, artifact_id)
    if artifact is None:
        raise ArtifactError(f"no such artifact: {artifact_id}")

    blocked = set(artifact.taint_labels) & EXPORT_BLOCKING_TAINTS
    if blocked:
        raise ExportRefused(
            f"artifact {artifact_id} carries {', '.join(sorted(blocked))} and may never "
            "leave the colony (Charter C13, §18.2). §18.3's clean-room path is the only "
            "route, and it is not built."
        )

    if commercial:
        effective = effective_provenance(conn, artifact_id)
        if effective.commercial_use != "permitted":
            # Name the remedy that exists for *this* artifact. One that read
            # nothing has no source to attest, and "establish the rights on its
            # sources" is advice its operator cannot act on.
            remedy = (
                "`mitosis set-rights --domain <host>` on its sources"
                if lineage_of(conn, artifact_id)
                else "`mitosis set-rights --colony` — it read nothing, so the "
                     "question is whether the colony may sell its own output"
            )
            raise ExportRefused(
                f"artifact {artifact_id} has commercial_use="
                f"{effective.commercial_use!r}; §20.2 — public visibility is not "
                f"permission to resell. Establish the rights position first: {remedy}."
            )


def export(
    conn: sqlite3.Connection,
    *,
    artifact_id: str,
    exported_by: str,
    reason: str,
    commercial: bool = False,
    now: datetime | None = None,
) -> Artifact:
    """Record that a human took this artifact outside the colony (§19.3).

    Export does not *deliver* anything — there is no channel, and §28's Phase 8
    requires that "all external action remains manual". What it does is put the
    two gates in front of a human's decision and record that the decision was
    made, so §11.4's contribution graph has a real edge between an artifact and
    whatever money follows it.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ArtifactError("an export must state a reason — §28's Phase 8 measures human review")

    now = now or datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-checked inside the lock, not before it: taint and rights are both
        # mutable by a concurrent write, and this is the boundary of the colony.
        check_exportable(conn, artifact_id, commercial=commercial)
        artifact = get(conn, artifact_id)
        # What actually authorised this, which after ADR-041 need not be what the
        # row says. An export recorded only against the stored `unknown` would be
        # unexplainable later: it would look like the gate had failed open.
        effective = effective_provenance(conn, artifact_id)
        if artifact.is_exported:
            raise ArtifactError(
                f"artifact {artifact_id} was already exported at "
                f"{artifact.exported_at_utc.isoformat()}"
            )
        conn.execute(
            "UPDATE artifacts SET exported_at_utc = ?, exported_by = ?, "
            "export_reason = ?, export_is_commercial = ? WHERE artifact_id = ?",
            (now.isoformat(), exported_by, reason, 1 if commercial else 0, artifact_id),
        )
        audit.record(
            conn,
            event_type="artifact_exported",
            cell_id=artifact.created_by_cell_id,
            description=f"{artifact.kind}: {artifact.title} — {reason}",
            metadata={
                "artifact_id": artifact_id,
                "exported_by": exported_by,
                "commercial": commercial,
                # Both, named apart. The first is what the artifact was born
                # with; the second is the position the gate actually applied.
                "commercial_use_at_creation": artifact.commercial_use,
                "commercial_use_effective": effective.commercial_use,
                "licence_effective": effective.licence,
                "taint_labels": list(artifact.taint_labels),
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get(conn, artifact_id)


# --- reads --------------------------------------------------------------------


def get(conn: sqlite3.Connection, artifact_id: str) -> Artifact | None:
    row = conn.execute(
        "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    return _row_to_artifact(row) if row is not None else None


def index_for(
    conn: sqlite3.Connection, cell_id: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    """§15.2's "artifact index" — one of its five memory tiers.

    An *index*, emphatically: title, kind, hash prefix, rights and export state.
    **The content is not included and must not be.** §15.1's budget is why an
    artifact may be 20k characters while a proposal may be 2k — the store holds
    the thing and the Cell sees only that it exists. An index that inlined
    content would make one long deliverable crowd out the Cell's own record.

    **`commercial_use_effective` is what the Cell is shown, not the stored
    column** (ADR-041). The row records what the artifact was born with, which
    for anything built on a fetched page is `unknown`; if that is what reached
    the prompt, an operator could establish a source's rights and the Cell whose
    work became sellable would still believe it was not — and would not propose
    selling it. The gap this slice closed at the export gate would simply have
    moved one step upstream.

    Reading it is not §0.3-sensitive: a Cell may not *define* a rights position
    and this does not let it. It lets it know one.
    """
    rows = conn.execute(
        """
        SELECT artifact_id, artifact_hash, kind, title, content_bytes,
               commercial_use, taint_labels_json, exported_at_utc
        FROM artifacts WHERE created_by_cell_id = ?
        ORDER BY created_at_utc DESC LIMIT ?
        """,
        (cell_id, limit),
    ).fetchall()
    index = []
    for row in rows:
        item = dict(row)
        item["commercial_use_effective"] = effective_provenance(
            conn, row["artifact_id"]
        ).commercial_use
        index.append(item)
    return index


def lineage_of(conn: sqlite3.Connection, artifact_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT source_artifact_id, source_tool_call_id FROM artifact_lineage "
            "WHERE artifact_id = ? ORDER BY rowid",
            (artifact_id,),
        )
    ]


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        artifact_id=row["artifact_id"],
        artifact_hash=row["artifact_hash"],
        kind=row["kind"],
        title=row["title"],
        content=row["content"],
        content_bytes=row["content_bytes"],
        created_by_cell_id=row["created_by_cell_id"],
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        taint_labels=tuple(json.loads(row["taint_labels_json"])),
        licence=row["licence"],
        permitted_uses=row["permitted_uses"],
        commercial_use=row["commercial_use"],
        contains_personal_data=bool(row["contains_personal_data"]),
        retention_rule=row["retention_rule"],
        source_summary=row["source_summary"],
        exported_at_utc=(
            datetime.fromisoformat(row["exported_at_utc"]) if row["exported_at_utc"] else None
        ),
        exported_by=row["exported_by"],
        export_is_commercial=(
            bool(row["export_is_commercial"])
            if row["export_is_commercial"] is not None
            else None
        ),
    )
