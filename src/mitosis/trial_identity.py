"""The one legal identity a live trial trades under (SPEC.md §0.3, §3.6, §16.3,
§21, §28 Phase 9; ADR-100).

§28 Phase 9 requires "one legal business identity, one narrow product class, one
merchant channel". Since ADR-097 the colony can record revenue, refunds,
chargebacks and fees — all of which attribute to a legal person who was nowhere
in the database. This module is that record, and nothing more: it is an operator
stating a fact about the outside world, in the shape ADR-041's rights
attestations and ADR-062's buyer attestations already use.

**§16.3 and `genome.py` already settled whose it is.** Legal identity is
non-inheritable, and the genome refuses a `legal_identity` gene with the reason
"Phase 9 has exactly one, and it is the colony's". That tripwire was written
before anything could declare one; this is its other half. There is no per-Cell
identity, no proposal field for one, and no path here from a Cell — a structural
test walks every module and says so.

**The payment account is a label, and the schema enforces that.** A card number,
IBAN or account number must never enter this database: migration 0040's CHECKs
refuse eight consecutive digits and the obvious secret prefixes, and `attest`
refuses more with a message naming what to write instead. "Stripe account:
personal" is the intended value. Nothing here authenticates, and nothing here is
a credential — the account a person actually uses stays with that person.

**Append-only, latest wins, withdrawal is a new row** (§3.6): `attest(...,
withdraw=True)` records that no identity is in force and keeps *why* in the
record, where a delete would leave an absence. Ordering is by `rowid`, not wall
clock, for `rights.current`'s reason — replay stability.

**Nothing is gated on it yet, deliberately.** §27.1's `real_commerce` flag is
off, no channel can sell, and wiring "refuse a marketplace listing unless an
identity is in force" is a change to the §21 gate that belongs with the channel
work, not here (logged). What exists today is the record a trial needs before it
can honestly attribute a sale to anyone.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ids

#: Refused in the label, on top of the schema's own CHECKs. Each is a way an
#: account number or a credential reaches a database that has no business
#: holding one.
_SECRET_MARKERS = (
    "sk_live",
    "sk-",
    "pk_live",
    "whsec",
    "-----begin",
    "password",
    "passwd",
    "secret",
    "iban",
    "sort code",
    "routing",
    "cvv",
)

#: Any run of digits this long, or this many digits in total, is an account
#: rather than a name for one. A card is 16, an IBAN ~18, a UK account 8 with a
#: 6-digit sort code; "Stripe 2026" is 4.
_DIGIT_RUN = re.compile(r"\d{8,}")
_MAX_TOTAL_DIGITS = 11
_MAX_LABEL_LENGTH = 200


class TrialIdentityError(Exception):
    pass


@dataclass(frozen=True)
class TrialIdentity:
    """One operator statement about who the colony trades as, at one time."""

    attestation_id: str
    legal_entity: str | None
    jurisdiction: str | None
    payment_account_label: str | None
    basis: str
    attested_by: str
    attested_at_utc: datetime

    @property
    def is_withdrawal(self) -> bool:
        """No identity in force — §3.6's adjustment rather than a deletion."""
        return self.legal_entity is None


def attest(
    conn: sqlite3.Connection,
    *,
    legal_entity: str | None = None,
    jurisdiction: str | None = None,
    payment_account_label: str | None = None,
    basis: str,
    attested_by: str,
    withdraw: bool = False,
    now: datetime | None = None,
) -> TrialIdentity:
    """Record who the colony trades as. Operator-only.

    `withdraw=True` records that no identity is in force, superseding whatever
    stood before it, and still requires a basis: a retraction leaves *why* in the
    record where a deletion leaves an absence.

    Refuses: a partial identity (all three fields or none), a missing basis or
    attester, and a payment account label that looks like an account rather than
    a name for one.
    """
    basis = (basis or "").strip()
    attested_by = (attested_by or "").strip()
    if not basis:
        raise TrialIdentityError(
            "an attestation must state its basis — who is trading and on whose account is "
            "the fact a dispute turns on, so the record has to say where it came from"
        )
    if not attested_by:
        raise TrialIdentityError(
            "an attestation must name who made it (§0.3: a person, not a Cell)"
        )

    if withdraw:
        if any(v is not None for v in (legal_entity, jurisdiction, payment_account_label)):
            raise TrialIdentityError(
                "a withdrawal asserts that no identity is in force, so it carries no entity, "
                "jurisdiction or account — attest the new identity instead"
            )
        entity = jurisdiction_value = label = None
    else:
        entity = (legal_entity or "").strip()
        jurisdiction_value = (jurisdiction or "").strip()
        label = (payment_account_label or "").strip()
        missing = [
            name
            for name, value in (
                ("legal_entity", entity),
                ("jurisdiction", jurisdiction_value),
                ("payment_account_label", label),
            )
            if not value
        ]
        if missing:
            raise TrialIdentityError(
                f"an identity needs all of legal_entity, jurisdiction and "
                f"payment_account_label; missing: {', '.join(missing)}. Half an identity in "
                "force is not a state — use withdraw=True to assert none."
            )
        _refuse_account_numbers(label)

    now = now or datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = current(conn)
        attestation_id = ids.new_id()
        conn.execute(
            """
            INSERT INTO trial_identity_attestations (
                attestation_id, legal_entity, jurisdiction, payment_account_label,
                basis, attested_by, attested_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attestation_id,
                entity,
                jurisdiction_value,
                label,
                basis,
                attested_by,
                now.isoformat(),
            ),
        )
        audit.record(
            conn,
            event_type="trial_identity_attested",
            cell_id=None,
            description=(
                f"trial identity withdrawn — {basis}"
                if entity is None
                else f"trial identity: {entity} ({jurisdiction_value}) — {basis}"
            ),
            metadata={
                "attestation_id": attestation_id,
                "legal_entity": entity,
                "jurisdiction": jurisdiction_value,
                # The label, never an account: the schema cannot hold one and
                # `_refuse_account_numbers` has already run.
                "payment_account_label": label,
                "attested_by": attested_by,
                "withdrawal": entity is None,
                # What it displaced. Changing who trades is the change a review
                # would most want to find.
                "supersedes": previous.attestation_id if previous else None,
                "previous_legal_entity": previous.legal_entity if previous else None,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    row = conn.execute(
        "SELECT * FROM trial_identity_attestations WHERE attestation_id = ?", (attestation_id,)
    ).fetchone()
    return _row_to_identity(row)


def _refuse_account_numbers(label: str) -> None:
    """The boundary this module exists to hold: a name for an account, never the
    account. Refused in Python with an explanation, and again by migration
    0040's CHECKs, which no caller can talk past."""
    if len(label) > _MAX_LABEL_LENGTH:
        raise TrialIdentityError(
            f"the payment account label is {len(label)} characters; it is a short name for an "
            f"account (\"Stripe account: personal\"), not a document"
        )
    lowered = label.lower()
    marker = next((m for m in _SECRET_MARKERS if m in lowered), None)
    if marker is not None:
        raise TrialIdentityError(
            f"the payment account label contains {marker!r}, which is how a credential or an "
            "account number reaches a database that must never hold one. Write a name for the "
            'account instead, e.g. "Stripe account: personal".'
        )
    digits = sum(character.isdigit() for character in label)
    if _DIGIT_RUN.search(label) or digits > _MAX_TOTAL_DIGITS:
        raise TrialIdentityError(
            "the payment account label looks like an account number. Nothing in this colony "
            "needs one — write a name for the account instead, e.g. "
            '"Stripe account: personal".'
        )


def current(conn: sqlite3.Connection) -> TrialIdentity | None:
    """The attestation in force, or None if nobody has made one.

    Ordered by `rowid` rather than `attested_at_utc`, for `rights.current`'s
    reason: insertion order is total and replay-stable, and two attestations
    inside one second would otherwise have no defined winner.
    """
    row = conn.execute(
        "SELECT * FROM trial_identity_attestations ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return _row_to_identity(row) if row is not None else None


def in_force(conn: sqlite3.Connection) -> TrialIdentity | None:
    """The identity the colony trades under, or None — where `current` returns a
    withdrawal, this returns None, because a withdrawal *is* no identity."""
    latest = current(conn)
    if latest is None or latest.is_withdrawal:
        return None
    return latest


def history(conn: sqlite3.Connection) -> list[TrialIdentity]:
    """Every attestation, newest first. Nothing is ever removed, so this is the
    whole record — including identities later withdrawn."""
    rows = conn.execute(
        "SELECT * FROM trial_identity_attestations ORDER BY rowid DESC"
    ).fetchall()
    return [_row_to_identity(row) for row in rows]


def _row_to_identity(row: sqlite3.Row) -> TrialIdentity:
    return TrialIdentity(
        attestation_id=row["attestation_id"],
        legal_entity=row["legal_entity"],
        jurisdiction=row["jurisdiction"],
        payment_account_label=row["payment_account_label"],
        basis=row["basis"],
        attested_by=row["attested_by"],
        attested_at_utc=datetime.fromisoformat(row["attested_at_utc"]),
    )
