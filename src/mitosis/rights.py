"""Rights a person establishes, as opposed to rights a fetch reports
(SPEC.md §20.1, §20.2, §20.3, §0.3, §3.6; ADR-041).

ADR-035 built §20.2's inheritance in one direction. An artifact takes the most
restrictive position among its sources; `fetchers.py` cannot read a licence, so
every fetched page is `commercial_use: unknown`; and the export gate refuses
commercial export of anything not `permitted`. The direction was right and the
consequence was that **rights could only ever tighten** — an artifact built on a
fetched page was `unknown` forever, and `real_commerce` could be opened and
still sell nothing. This is the other direction.

**What is attested is a source, not an artifact.** `check_exportable` had already
written the instruction it could not carry out — "Establish the rights position
on its sources first." Stamping a position onto one artifact is §20.2's
laundering path with an operator holding the pen: it does not compose, it does
not reach the next artifact built on the same page, and it asks a person to rule
on a derived work when what a person can actually read is a licence.

**A Cell has no path here, and that is structural rather than promised.** §0.3
lets a Cell explain a result and never define one; a rights position is the
canonical fact standing between the colony and selling something, so it is
exactly the fact §0.3 is about. Nothing in `tool_registry.REGISTRY` writes an
attestation, no proposal field names one, and `attest` is reachable only from
the CLI. `test_no_cell_reachable_module_writes_an_attestation` walks the import
graph and says so. The `own_provenance` clamp in `artifacts.inherit_provenance`
is the same boundary at the other end: a producer may declare its own content
`unknown` or `prohibited`, never `permitted`.

**Making this a §23 approval request was the alternative, and it inverts §0.3.**
The queue is where a Cell asks to act, so filing rights through it needs a Cell
to nominate its own rights position for a human to countersign — and §23.5 warns
the queue "is itself part of the environment and will be optimised against". A
Cell that can file "please mark my sources commercially permitted" holds a lever
on the one gate between it and revenue. An attestation is not a request from
inside the colony at all; it is an operator recording an external fact, and
nothing in the colony can raise it.

**Append-only, latest wins, and withdrawal is an adjustment (§3.6).** Nothing
here is ever updated or deleted. Attesting the same subject again supersedes;
withdrawing is an attestation of `unknown` carrying its own basis. That leaves
*why* a position was withdrawn in the record, where a `revoked` flag would leave
an absence, and it is the habit §3.6 already requires of the ledger. Ordering is
by insertion (`rowid`), not by wall clock, so a replay is deterministic and two
attestations in the same second still have one answer.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import audit, ids

#: An external source, keyed on its normalised host.
SUBJECT_DOMAIN = "domain"

#: The colony's own output — every artifact that read nothing. `inherit_
#: provenance` starts these at `unknown` and says why: whether the colony may
#: sell what it wrote is "a question for a person, not a default". This is the
#: subject that lets the person answer. It is not a domain and cannot be
#: expressed as one.
SUBJECT_COLONY = "colony"

SUBJECT_KINDS: frozenset[str] = frozenset({SUBJECT_DOMAIN, SUBJECT_COLONY})

#: §20.1's commercial-use status. Same three values as `artifacts.
#: COMMERCIAL_USE_PRECEDENCE`, which owns the ordering; this is membership only.
COMMERCIAL_USE_VALUES: frozenset[str] = frozenset({"permitted", "prohibited", "unknown"})

#: A licence string that names nothing. `permitted` may not be attested against
#: one — see `attest`.
UNNAMED_LICENCES: frozenset[str] = frozenset({"", "unknown", "none", "n/a", "?"})


class RightsError(Exception):
    pass


@dataclass(frozen=True)
class Attestation:
    """One operator statement about one subject, at one time."""

    attestation_id: str
    subject_kind: str
    subject: str
    licence: str
    permitted_uses: str
    commercial_use: str
    basis: str
    attested_by: str
    attested_at_utc: datetime

    @property
    def is_withdrawal(self) -> bool:
        """A `unknown` attestation makes no claim — §3.6's adjustment rather
        than a deletion. Named so callers do not have to recognise the shape."""
        return self.commercial_use == "unknown"


# --- writing ------------------------------------------------------------------


def attest(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject: str,
    licence: str,
    permitted_uses: str,
    commercial_use: str,
    basis: str,
    attested_by: str,
    now: datetime | None = None,
) -> Attestation:
    """Record that a person established a rights position. Operator-only.

    Refuses more than the schema does, and each refusal is a clause:

    * **A basis is required** (§20.3). The same rule `export` applies to its
      reason. An invalid data-use position is a liability rather than an
      oversight, so the record must say where the belief came from — and a page
      can assert its own licence in its own body, which is why "the publisher's
      licensing page" and "the page said so" must be distinguishable afterwards.
    * **`permitted` requires a named licence.** "You may sell this, and I cannot
      say under what" is incoherent, and it is the shape a hurried wave-through
      takes. It is also the only part of the operator's judgement the kernel is
      in a position to check.
    * **A domain must be a bare, normalised host.** Not a URL: a rights position
      that silently depended on a query string would be unmatchable later.
    """
    subject_kind, subject = _normalise_subject(subject_kind, subject)

    licence = (licence or "").strip()
    permitted_uses = (permitted_uses or "").strip()
    basis = (basis or "").strip()
    attested_by = (attested_by or "").strip()

    if commercial_use not in COMMERCIAL_USE_VALUES:
        raise RightsError(
            f"commercial_use must be one of {', '.join(sorted(COMMERCIAL_USE_VALUES))}, "
            f"got {commercial_use!r}"
        )
    if not basis:
        raise RightsError(
            "an attestation must state its basis — §20.3 makes an invalid data-use "
            "position a liability, and the record has to say where the belief came from"
        )
    if not attested_by:
        raise RightsError("an attestation must name who made it (§0.3: a person, not a Cell)")
    if not permitted_uses:
        raise RightsError("an attestation must state permitted uses (§20.1)")
    if commercial_use == "permitted" and licence.lower() in UNNAMED_LICENCES:
        raise RightsError(
            f"commercial_use='permitted' needs a named licence, got {licence!r}. "
            "§20.2 — 'you may sell this and I cannot say under what' is not a rights "
            "position. Withdraw instead by attesting 'unknown'."
        )
    if not licence:
        raise RightsError("an attestation must state a licence, or 'unknown' (§20.1)")

    now = now or datetime.now(timezone.utc)

    conn.execute("BEGIN IMMEDIATE")
    try:
        attestation = _attest_locked(
            conn,
            subject_kind=subject_kind,
            subject=subject,
            licence=licence,
            permitted_uses=permitted_uses,
            commercial_use=commercial_use,
            basis=basis,
            attested_by=attested_by,
            now=now,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return attestation


def _attest_locked(
    conn: sqlite3.Connection,
    *,
    subject_kind: str,
    subject: str,
    licence: str,
    permitted_uses: str,
    commercial_use: str,
    basis: str,
    attested_by: str,
    now: datetime,
) -> Attestation:
    """Caller holds the write lock. Validation belongs to `attest`, which is the
    only caller that has not already validated."""
    attestation_id = ids.new_id()
    previous = current(conn, subject_kind=subject_kind, subject=subject)

    conn.execute(
        """
        INSERT INTO rights_attestations (
            attestation_id, subject_kind, subject, licence, permitted_uses,
            commercial_use, basis, attested_by, attested_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attestation_id,
            subject_kind,
            subject,
            licence,
            permitted_uses,
            commercial_use,
            basis,
            attested_by,
            now.isoformat(),
        ),
    )

    audit.record(
        conn,
        event_type="rights_attested",
        cell_id=None,
        description=f"{subject_kind} {subject}: commercial_use={commercial_use} — {basis}",
        metadata={
            "attestation_id": attestation_id,
            "subject_kind": subject_kind,
            "subject": subject,
            "licence": licence,
            "commercial_use": commercial_use,
            "attested_by": attested_by,
            # What it displaced. An attestation that loosens a position is the
            # one a review would want to find, and a bare "now permitted" does
            # not say whether anything was overturned.
            "supersedes": previous.attestation_id if previous else None,
            "previous_commercial_use": previous.commercial_use if previous else None,
        },
    )
    return _row_to_attestation(
        conn.execute(
            "SELECT * FROM rights_attestations WHERE attestation_id = ?", (attestation_id,)
        ).fetchone()
    )


# --- reading ------------------------------------------------------------------


def current(
    conn: sqlite3.Connection, *, subject_kind: str, subject: str
) -> Attestation | None:
    """The attestation in force for a subject, or None.

    **Ordered by `rowid`, not by `attested_at_utc`.** Insertion order is total
    and replay-stable; wall clock is neither — §6.3 keeps the simulated and wall
    clocks unmixed, and two attestations inside one second would otherwise have
    no defined winner.
    """
    subject_kind, subject = _normalise_subject(subject_kind, subject)
    row = conn.execute(
        "SELECT * FROM rights_attestations WHERE subject_kind = ? AND subject = ? "
        "ORDER BY rowid DESC LIMIT 1",
        (subject_kind, subject),
    ).fetchone()
    return _row_to_attestation(row) if row is not None else None


def current_for_url(conn: sqlite3.Connection, url: str) -> Attestation | None:
    """The attestation covering the host of `url`, or None.

    **Exact host, never a dotted suffix** — deliberately unlike the Charter C12
    egress allowlist this sits beside. Over-matching there means fetching a page
    the operator did not picture; over-matching here means *selling* material
    under a licence that never covered it, which §20.3 files under legal
    liability. `docs.example.com` is a different subject from `example.com` and
    has to be attested on its own.
    """
    host = host_of(url)
    if not host:
        return None
    return current(conn, subject_kind=SUBJECT_DOMAIN, subject=host)


def colony_attestation(conn: sqlite3.Connection) -> Attestation | None:
    return current(conn, subject_kind=SUBJECT_COLONY, subject=SUBJECT_COLONY)


def history(
    conn: sqlite3.Connection, *, subject_kind: str | None = None, subject: str | None = None
) -> list[Attestation]:
    """Every attestation, newest first. Nothing is ever removed, so this is the
    whole record — including positions that were later withdrawn."""
    if (subject_kind is None) != (subject is None):
        raise RightsError(
            "history() filters on a subject_kind *and* a subject, or on neither — "
            "half a key silently returned the whole table"
        )
    if subject_kind is not None:
        subject_kind, subject = _normalise_subject(subject_kind, subject)
        rows = conn.execute(
            "SELECT * FROM rights_attestations WHERE subject_kind = ? AND subject = ? "
            "ORDER BY rowid DESC",
            (subject_kind, subject),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rights_attestations ORDER BY rowid DESC"
        ).fetchall()
    return [_row_to_attestation(row) for row in rows]


def in_force(conn: sqlite3.Connection) -> list[Attestation]:
    """One row per subject: what the colony currently believes."""
    rows = conn.execute(
        """
        SELECT * FROM rights_attestations
        WHERE rowid IN (
            SELECT MAX(rowid) FROM rights_attestations GROUP BY subject_kind, subject
        )
        ORDER BY subject_kind, subject
        """
    ).fetchall()
    return [_row_to_attestation(row) for row in rows]


# --- keys ---------------------------------------------------------------------


def host_of(url: str) -> str:
    """The normalised host of a URL, or "" if it has none.

    Kept here rather than borrowed from `tool_registry._normalise_domain`
    because the two answer different questions — that one refuses anything that
    is not already a bare domain, this one extracts one from a source string a
    fetcher recorded.
    """
    parsed = urlparse((url or "").strip())
    return (parsed.hostname or "").strip().lower().rstrip(".")


def _normalise_subject(subject_kind: str, subject: str) -> tuple[str, str]:
    if subject_kind not in SUBJECT_KINDS:
        raise RightsError(
            f"unknown subject kind {subject_kind!r}. Known: {', '.join(sorted(SUBJECT_KINDS))}"
        )
    if subject_kind == SUBJECT_COLONY:
        # One colony, one row-space. Accepts the literal or nothing at all so a
        # caller does not have to repeat the word.
        given = (subject or SUBJECT_COLONY).strip().lower()
        if given != SUBJECT_COLONY:
            raise RightsError(
                f"the colony is a single subject; {subject!r} is not a valid colony subject"
            )
        return SUBJECT_COLONY, SUBJECT_COLONY

    domain = (subject or "").strip().lower().rstrip(".")
    if not domain:
        raise RightsError("a domain attestation needs a domain")
    if "/" in domain or ":" in domain or " " in domain:
        raise RightsError(
            f"not a bare domain: {subject!r}. Attest the host — a rights position that "
            "depended on a path or query string could not be matched to a later fetch."
        )
    return SUBJECT_DOMAIN, domain


def _row_to_attestation(row: sqlite3.Row) -> Attestation:
    return Attestation(
        attestation_id=row["attestation_id"],
        subject_kind=row["subject_kind"],
        subject=row["subject"],
        licence=row["licence"],
        permitted_uses=row["permitted_uses"],
        commercial_use=row["commercial_use"],
        basis=row["basis"],
        attested_by=row["attested_by"],
        attested_at_utc=datetime.fromisoformat(row["attested_at_utc"]),
    )
