"""The salted counterparty key: equality without identity (SPEC.md §16.3, §21.2,
§12.1, §2.5; ADR-036, ADR-061).

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
from datetime import datetime, timezone

#: A digest as stored. Mirrored by the CHECK constraint in migration 0028 and
#: pinned to it by `test_counterparty.py` — two spellings of one rule that must
#: not drift apart.
HASH_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


class CounterpartyError(Exception):
    pass


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
