"""The salted counterparty key, and what a person may declare under it
(SPEC.md §16.3, §21.2, §12.1, §0.3, §3.6, §2.5; ADR-036, ADR-041, ADR-061, ADR-062).

    §16.3 **Non-inheritable:** raw credentials, approvals, **customer identity**,
    private customer data, real platform account access, unresolved external
    communications, legal identity.

**A counterparty never exists in this colony as itself.** What is stored is an
HMAC of the normalised string under a per-colony salt, which supports exactly
one question — *is this the same party as that one?* — and no others. You cannot
read a customer list out of this colony, and neither can a Cell.

## Why this is its own module

It began inside `channel_registry` because §21.2's outbound registry was the
only thing that needed it. It has two consumers now: the outbound action
registry, and **inbound revenue** (§12.1's `buyer_type` and `revenue_recurrence`
both turn on whether one buyer paid twice). `revenue` sits at the ledger end of
the layering and `channel_registry` sits up where `context` can import it, so
leaving the primitive there would have made recording an inbound payment import
a module about outbound sending — a back-edge for a function that depends on
nothing but the salt row.

**Both directions share one salt, and that is a feature, not an accident.** A
counterparty who was contacted through §21.2 and later pays produces the *same*
digest, so the contact history and the money join up without either side ever
holding the identity. Two salts would have made that join impossible while
looking identical in every test that used only one direction.

## The key answers one question; a person answers the other

The digest supports *is this the same party as that one?* and nothing else —
which is exactly §12.1's `revenue_recurrence`, and exactly not its `buyer_type`.
A buyer *type* is a claim about who the buyer is, and §16.3 has already decided
this colony may not know that. So it arrives the only honest way left: **a person
who can see the buyer says so, and the record keeps who said it**
(`attest_buyer_type`).

That is ADR-041's mechanism rather than a new one — subject, claim, basis, who,
when; append-only; latest wins; withdrawal is a row and not a flag. The operator
names the party and the kernel hashes it, so the colony learns that some buyer is
an enterprise while remaining unable to say who any buyer is.

## The shape is enforced by the schema, not only here

`ledger_transactions.counterparty_hash` carries a CHECK constraint matching
`is_hash` — 64 lowercase hex characters. That is deliberate: the column
*cannot physically hold* an email address, so §16.3's guarantee does not depend
on every future caller remembering to hash first. A seam can be bypassed by a
caller that never heard of it; a CHECK constraint binds the operation.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ids

#: A digest as stored. Mirrored by the CHECK constraint in migration 0028 and
#: pinned to it by `test_counterparty.py` — two spellings of one rule that must
#: not drift apart.
HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


#: §12.1's four bins. Migration 0029's CHECK states the same list, and
#: `test_the_buyer_type_bins_are_one_rule` pins the two together.
BUYER_TYPES: tuple[str, ...] = ("human_consumer", "small_business", "enterprise", "machine")


class CounterpartyError(Exception):
    pass


@dataclass(frozen=True)
class BuyerAttestation:
    """One statement a person made about one buyer.

    `buyer_type` is `None` for a **withdrawal** — an attestation asserting no
    position, carrying its own basis (ADR-041's rule: a retraction leaves *why*
    in the record, where a flag would leave an absence).
    """

    attestation_id: str
    counterparty_hash: str
    buyer_type: str | None
    basis: str
    attested_by: str
    attested_at_utc: str


def is_hash(value: str | None) -> bool:
    """Whether `value` is in the only form this colony stores a party in."""
    return value is not None and HASH_PATTERN.fullmatch(value) is not None


def _salt(conn: sqlite3.Connection) -> bytes:
    """The colony's counterparty salt, created once on first use.

    Never rotated. Rotating it would silently empty the do-not-contact list, the
    contact history and every recurrence judgement — every hash would stop
    matching — which turns the one guarantee people actually rely on into a
    no-op with no error anywhere.

    Created lazily, which means an otherwise read-only caller can write this one
    row the first time it is asked anything. That is colony state rather than
    action state — the same row every later call reads — and the alternative,
    refusing to answer until someone runs a setup verb, would make the "ask
    before you send" path the awkward one.
    """
    row = conn.execute("SELECT salt_hex FROM counterparty_salt WHERE id = 1").fetchone()
    if row is not None:
        return bytes.fromhex(row["salt_hex"])
    salt_hex = secrets.token_hex(32)
    conn.execute(
        "INSERT OR IGNORE INTO counterparty_salt (id, salt_hex, created_at_utc) "
        "VALUES (1, ?, ?)",
        (salt_hex, datetime.now(timezone.utc).isoformat()),
    )
    row = conn.execute("SELECT salt_hex FROM counterparty_salt WHERE id = 1").fetchone()
    return bytes.fromhex(row["salt_hex"])


def normalise(value: str | None) -> str | None:
    """Trim and case-fold, because `Alice@Ex.com` and `alice@ex.com` are one
    person and a dedupe that misses that is a dedupe that does not work.

    Shared with §21.2's domain and platform-account keys so that the outbound
    and inbound sides agree on what "the same party" means.
    """
    if value is None:
        return None
    return value.strip().casefold() or None


def hash_of(conn: sqlite3.Connection, counterparty: str) -> str:
    """The only representation of a counterparty this colony ever stores.

    HMAC rather than a bare salted digest, so the salt is used as a key rather
    than as a prefix.
    """
    normalised = normalise(counterparty)
    if not normalised:
        raise CounterpartyError("a counterparty must not be blank")
    return hmac.new(_salt(conn), normalised.encode("utf-8"), hashlib.sha256).hexdigest()


# --- §12.1's buyer type: declared, never derived (§0.3, ADR-041's shape) -------


def attest_buyer_type(
    conn: sqlite3.Connection,
    *,
    counterparty: str,
    buyer_type: str | None,
    basis: str,
    attested_by: str,
    now: datetime | None = None,
) -> BuyerAttestation:
    """Record that a person classified a buyer. **Operator-only.**

    `counterparty` is the party as the operator knows them; only the digest is
    stored. `buyer_type` of `None` withdraws an earlier position.

    Refuses more than the schema does, and each refusal is a clause:

    * **A basis is required.** ADR-041's rule, and it applies here for a reason
      that clause does not have: a buyer type decides which §12.1 niche a genome
      occupies, so it is a *selection input*, and an unexplained selection input
      is how a fitness signal gets fabricated (`revenue.record_revenue` refuses
      an unattributed payment for the same reason).
    * **A declarer is required** (§0.3: a person, not a Cell).
    * **The party must already have paid.** There is no row to point a foreign
      key at — a counterparty is a value on payments, not an entity — so this is
      that check. Without it a mistyped party produces a *silent no-op*: a
      perfectly valid attestation that matches no payment and moves no
      descriptor, which is the failure mode hardest to notice. §12.1's dimension
      is about who **paid**, so a party who has not is out of scope by
      definition, not merely unverifiable.

    Nothing here is ever updated or deleted (§3.6). Attesting the same party
    again supersedes by insertion order, exactly as `rights.attest` does, and
    for the same replay reason: `rowid` is total and wall clock is not.
    """
    digest = hash_of(conn, counterparty)
    basis = (basis or "").strip()
    attested_by = (attested_by or "").strip()

    if buyer_type is not None and buyer_type not in BUYER_TYPES:
        raise CounterpartyError(
            f"buyer_type must be one of {', '.join(BUYER_TYPES)} or None to "
            f"withdraw, got {buyer_type!r} (§12.1)"
        )
    if not basis:
        raise CounterpartyError(
            "an attestation must state its basis — a buyer type is a selection "
            "input, and an unexplained one is a fabricated fitness signal"
        )
    if not attested_by:
        raise CounterpartyError(
            "an attestation must name who made it (§0.3: a person, not a Cell)"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Inside the write lock, like every other existence check in the kernel:
        # a payment could be recorded between a read and this write, and the
        # refusal must be decided against the state this row is written into.
        paid = conn.execute(
            "SELECT 1 FROM ledger_transactions WHERE counterparty_hash = ? LIMIT 1",
            (digest,),
        ).fetchone()
        if paid is None:
            raise CounterpartyError(
                f"no payment has been recorded from {counterparty!r} — §12.1's "
                "buyer type describes who paid, and attesting a party who has "
                "not would be a valid record that silently matches nothing"
            )

        attestation = BuyerAttestation(
            attestation_id=ids.new_id(),
            counterparty_hash=digest,
            buyer_type=buyer_type,
            basis=basis,
            attested_by=attested_by,
            attested_at_utc=(now or datetime.now(timezone.utc)).isoformat(),
        )
        conn.execute(
            "INSERT INTO buyer_attestations (attestation_id, counterparty_hash, "
            "buyer_type, basis, attested_by, attested_at_utc) VALUES (?, ?, ?, ?, ?, ?)",
            (
                attestation.attestation_id,
                attestation.counterparty_hash,
                attestation.buyer_type,
                attestation.basis,
                attestation.attested_by,
                attestation.attested_at_utc,
            ),
        )
        audit.record(
            conn,
            event_type="buyer_type_attested",
            metadata={
                # Whether and what, never who — the digest is a linkable key and
                # audit events are read by paths a Cell can reach (ADR-061).
                "buyer_type": buyer_type,
                "withdrawal": buyer_type is None,
                "attested_by": attested_by,
            },
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return attestation


def current_buyer_types(conn: sqlite3.Connection) -> dict[str, str | None]:
    """Every party's position in force, digest -> bin (`None` where withdrawn).

    One query rather than one per party, because the archive asks about every
    genome at once. **Ordered by `rowid`, not by `attested_at_utc`** — ADR-041's
    reason: insertion order is total and replay-stable, and two attestations
    inside one second would otherwise have no defined winner.

    A withdrawn party is present with `None` rather than absent, because
    "somebody looked and declined to say" and "nobody has looked" are different
    facts and `novelty._buyer_type` abstains with a different reason for each.
    """
    rows = conn.execute(
        """
        SELECT counterparty_hash, buyer_type FROM buyer_attestations
        WHERE rowid IN (
            SELECT max(rowid) FROM buyer_attestations GROUP BY counterparty_hash
        )
        """
    ).fetchall()
    return {row["counterparty_hash"]: row["buyer_type"] for row in rows}


def buyer_history(conn: sqlite3.Connection) -> list[BuyerAttestation]:
    """Every attestation ever made, newest first, including superseded ones."""
    return [
        BuyerAttestation(
            attestation_id=row["attestation_id"],
            counterparty_hash=row["counterparty_hash"],
            buyer_type=row["buyer_type"],
            basis=row["basis"],
            attested_by=row["attested_by"],
            attested_at_utc=row["attested_at_utc"],
        )
        for row in conn.execute(
            "SELECT * FROM buyer_attestations ORDER BY rowid DESC"
        ).fetchall()
    ]
