"""Channels, the counterparty hash, and the §21.2 collision checks
(SPEC.md §21, §16.3, §23.4, §27.1, §28 Phase 8).

Split out of `external_actions.py` for the same layering reason
`tool_registry` was split out of `tools`, and the cut falls in the same place:
everything here **reads or refuses**, and the module that *claims* a grant sits
above `approval` where `context` cannot reach it. `context.py` has to render
what a Cell may request and what its past actions came to; `external_actions`
imports `approval`, which imports `deliberation`, which imports `context`. A
direct import would close that loop.

**The counterparty never exists in this colony as itself.** `counterparty_hash`
is the only form stored, and §16.3 is the reason: "customer identity" and
"private customer data" are non-inheritable, and §20.1 tracks personal data
because holding it is a liability rather than an asset. Every question §21.2
actually asks — have we contacted this person, did a sibling get there first,
did they ask us to stop — is a question about *equality*, which survives
hashing. "Who have we contacted" does not survive it, which is the point.

**What that buys, stated exactly.** The salt sits in the same database as the
hashes, so this is not protection against someone holding the file who already
has a particular person in mind. It is protection against the colony
enumerating the people it has dealt with — by a Cell, an Auditor, an inherited
genome, a coroner report, or an operator idly reading a table. §16.3's concern
is inheritance and drift, and that is the concern this closes.

**Refusals here refuse; they do not annotate.** ADR-027 took the opposite line
one layer up — a §23.4 signal escalates a tier and never auto-rejects, because
risk is a judgement and an automatic rejector is the next thing to optimise
against. A collision is not a judgement. "This counterparty was contacted four
hours ago by another lineage" is a fact, the operator's judgement was spent at
approval time on a world where it had not happened yet, and §21.2's own verb is
*prevent*. Refusing a claim also costs nothing irreversible: nothing has been
sent, and the operator can abandon, wait, or pick someone else.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import audit
from .tool_registry import autonomy_enabled

#: §25.1's ladder, and the number is deliberately **not** the flattering one.
#: Rung 8 is "Expanded pilot" and rung 7, "tiny capped live experiment", is
#: where `promotion.py` already put the colony. Reaching a real counterparty
#: looks like a climb past both, and it is not one: the ladder measures what the
#: colony does *unattended*, and unattended this path does nothing at all. A
#: human approves the §23 request, a human performs the action, and the kernel
#: writes down what happened and refuses what would collide.
#:
#: So this is rung 6, "human-reviewed prototype" — §28's Phase 8 by name, whose
#: acceptance is "all external action remains manual". Recording it as 8 would
#: be claiming a promotion the code did not earn.
LADDER_RUNG_HUMAN_REVIEWED_PROTOTYPE = 6

#: The rolling window §21.2's cumulative-exposure keys are counted over, in wall
#: seconds. Deliberately the same 24 hours as `approval.EXPOSURE_WINDOW_SECONDS`:
#: the two windows watch the same splitting behaviour on two different keys, and
#: a shorter one here would let a patient splitter space contacts out past the
#: edge of whichever window is narrower.
CONTACT_WINDOW_SECONDS = 86_400

#: What one human minute costs against a Cell's RESOURCE budget. Twice a whole
#: tool call (`tool_registry.RESOURCE_COST_PER_CALL` is 5) because §1's
#: autonomy-adjusted profit exists "to expose hidden human labour and subsidy" —
#: a Cell that can only work by consuming a person's attention should run out of
#: budget faster than one that reads a web page.
HUMAN_MINUTE_RESOURCE_COST = 10

#: Sanity bound on the *reported* figure. Not an economic limit — it exists so
#: that a mistyped 9999 cannot enter the record as fact. Anything genuinely
#: longer than a working day on one action is two actions.
MAX_HUMAN_MINUTES_PER_ACTION = 480

#: How long a claim's RESOURCE reservation stands before the sweeper may treat
#: it as stranded. Far longer than a tool call's 15 minutes because the work in
#: between is a person's, not a socket's, and a reservation reaped out from
#: under an operator who stepped away is worse than one held too long.
RESERVATION_TTL = timedelta(hours=8)

#: Where the metered human minutes settle. `infrastructure_reserve` already
#: means "metered consumption the Cell paid the colony for", and the *kind* of
#: consumption is carried by `resource_usage.resource_type` — which is exactly
#: the dimension `total_quantity_by_type` groups by, and therefore where Phase
#: 8's "human minutes/artifact" is computed from. A separate ledger account
#: would be a second copy of a distinction the RESOURCE book already draws, and
#: two copies of one fact eventually disagree.
INFRASTRUCTURE_RESERVE = "infrastructure_reserve"

#: §21.2's "reputation impact", as raw observed events. There is deliberately no
#: score: a reputation number nothing can validate is theatre, and §21.1's real
#: question is binary — did this cost the colony an asset money cannot repair.
OUTCOMES: frozenset[str] = frozenset(
    {
        "delivered",
        "no_response",
        "positive_reply",
        "negative_reply",
        "bounced",
        "complaint",
        "blocked",
    }
)

#: The two outcomes that are damage to §21.1's shared assets rather than an
#: ordinary disappointing result. Both freeze the channel and both put the
#: counterparty on the permanent do-not-contact list. `negative_reply` is
#: pointedly not here — being told no is a normal commercial outcome, and
#: treating it as reputational damage would make the colony unable to learn from
#: rejection.
DAMAGE_OUTCOMES: frozenset[str] = frozenset({"complaint", "blocked"})


class ChannelError(Exception):
    pass


class ExternalActionRefused(ChannelError):
    """§21.2: this action would collide with something the colony already did."""


class CounterpartyBlocked(ExternalActionRefused):
    """They asked to be left alone. Permanent, and the kernel has no unblock."""


class DuplicateContact(ExternalActionRefused):
    """§21.2's first named failure: the same person, the same channel, again."""


class SiblingCollision(ExternalActionRefused):
    """§21.3: two lineages reaching one counterparty look like one business
    contradicting itself. Bidding wars and conflicting offers are this shape."""


class ChannelRateLimit(ExternalActionRefused):
    """§21.2's "account-rate-limit collisions", enforced before the platform
    enforces it for us — a platform's own rate limit is applied by suspending
    the account, which is §21.1 damage rather than a refusal."""


class ChannelQuotaExceeded(ExternalActionRefused):
    """Too many actions claimed and not yet finished on one channel."""


class ChannelFrozen(ExternalActionRefused):
    """§21.1 damage was recorded on this channel and no human has cleared it."""


class ChannelAutonomyRefused(ExternalActionRefused):
    """§27.1: the autonomy flag gating this channel is off."""


# --- the registry -------------------------------------------------------------


@dataclass(frozen=True)
class ChannelSpec:
    """One way of reaching the world, and the caps that bound it.

    **The caps are colony-wide, not per Cell**, and that is the whole of §21.1
    in one design choice: the sending reputation, the merchant identity and the
    platform quota are shared, so a per-Cell cap is escaped by reproducing.
    §9's reproduction is the cheapest way this colony can split anything, which
    ADR-027 established when it keyed the approval window on the lineage rather
    than the Cell.

    **The caps are rate and quota, never spend.** Money is already bounded five
    ways (Charter C4, C5, the real-spend breaker, the promotion pool, the
    metabolic alarm) and none of them bound the thing at risk here.
    """

    channel_id: str
    description: str
    #: The one-line form a §15 context renders. Separate from `description`
    #: because the operator-facing text can afford to explain itself and a
    #: Cell's context cannot — §15.1's budget is spent on this section every
    #: wake, whether or not the channel is even switched on.
    short_description: str
    #: A §27.1 `autonomy:` key. §0.4 grants autonomy "tool by tool"; a channel
    #: with no flag would be a capability nobody ever decided to allow.
    autonomy_flag: str
    #: Whether the action addresses a particular person. False for a listing or
    #: a page, which reach everyone and nobody.
    requires_counterparty: bool
    #: Actions on this channel per `CONTACT_WINDOW_SECONDS`, colony-wide.
    max_actions_per_window: int
    #: Claimed-but-unfinished actions on this channel, colony-wide.
    max_open_claims: int
    #: How many of a person's minutes the *Cell* pays for, and therefore what is
    #: reserved at claim time. Sized against a Cell's actual RESOURCE budget
    #: rather than against a theoretical worst case: reserving the worst case
    #: made a single email cost more than a Cell has, which is a cap that reads
    #: as prudent and is really just an off switch.
    #:
    #: Minutes beyond it are still *recorded* — see `external_actions.complete`.
    #: They become subsidy rather than an error, which is the distinction §1
    #: asks the colony to expose rather than to prevent.
    max_billable_human_minutes: int


REGISTRY: dict[str, ChannelSpec] = {
    "email": ChannelSpec(
        channel_id="email",
        description=(
            "One email to one recipient, sent by hand. The colony's sending "
            "reputation is shared by every Cell that ever uses it."
        ),
        short_description="one email to one recipient, sent by hand",
        autonomy_flag="external_message",
        requires_counterparty=True,
        max_actions_per_window=5,
        max_open_claims=2,
        max_billable_human_minutes=30,
    ),
    "marketplace_listing": ChannelSpec(
        channel_id="marketplace_listing",
        description=(
            "One listing on one marketplace account, posted by hand. Two "
            "lineages listing against each other is §21.2's bidding war."
        ),
        short_description="one marketplace listing, posted by hand",
        autonomy_flag="external_publish",
        requires_counterparty=False,
        max_actions_per_window=3,
        max_open_claims=2,
        max_billable_human_minutes=45,
    ),
    "web_publish": ChannelSpec(
        channel_id="web_publish",
        description=(
            "One page published on a colony domain, by hand. Addresses nobody "
            "in particular and is therefore the cheapest way to damage a brand."
        ),
        short_description="one page published on a colony domain, by hand",
        autonomy_flag="external_publish",
        requires_counterparty=False,
        max_actions_per_window=3,
        max_open_claims=2,
        max_billable_human_minutes=45,
    ),
}


def get_spec(channel: str) -> ChannelSpec:
    spec = REGISTRY.get(channel)
    if spec is None:
        raise ChannelError(
            f"unknown channel {channel!r}. Registered: "
            f"{', '.join(sorted(REGISTRY)) or '(none)'}"
        )
    return spec


def validate_request(channel: str, *, intent: str) -> ChannelSpec:
    """Check a proposed external action without claiming anything.

    Called at proposal-record time so a Cell naming a channel that does not
    exist is told immediately, and again inside the claim's write lock — the
    second check is not redundant, because the registry can change between a
    proposal and its approval.
    """
    spec = get_spec(channel)
    if not (intent or "").strip():
        raise ChannelError("an external action must state what it is for")
    return spec


# --- the counterparty hash (§16.3) --------------------------------------------


def _salt(conn: sqlite3.Connection) -> bytes:
    """The colony's counterparty salt, created once on first use.

    Never rotated. Rotating it would silently empty the do-not-contact list and
    the contact history — every hash would stop matching — which turns the one
    guarantee people actually rely on into a no-op with no error anywhere.

    Created lazily, which means the otherwise read-only `check_action` can write
    this one row the first time it is asked anything. That is colony state
    rather than action state — the same row every later call reads — and the
    alternative, refusing to answer until someone runs a setup verb, would make
    the "ask before you send" path the awkward one.
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


def counterparty_hash(conn: sqlite3.Connection, counterparty: str) -> str:
    """The only representation of a counterparty this colony ever stores.

    Normalised before hashing — trimmed and case-folded — because `Alice@Ex.com`
    and `alice@ex.com` are one person, and a dedupe that misses that is a dedupe
    that does not work. HMAC rather than a bare salted digest so the salt is
    used as a key rather than as a prefix.
    """
    normalised = (counterparty or "").strip().casefold()
    if not normalised:
        raise ChannelError("a counterparty must not be blank")
    return hmac.new(_salt(conn), normalised.encode("utf-8"), hashlib.sha256).hexdigest()


# --- §21.1 channel freeze -----------------------------------------------------


def channel_frozen(conn: sqlite3.Connection, channel: str) -> tuple[bool, str | None]:
    row = conn.execute(
        "SELECT frozen_at_utc, frozen_reason FROM channel_state WHERE channel = ?",
        (channel,),
    ).fetchone()
    if row is None or row["frozen_at_utc"] is None:
        return False, None
    return True, row["frozen_reason"]


def _freeze_channel_locked(
    conn: sqlite3.Connection,
    *,
    channel: str,
    reason: str,
    action_id: str | None,
    now: datetime,
) -> None:
    """Caller holds the write lock. Halts a channel until a person clears it."""
    conn.execute(
        """
        INSERT INTO channel_state (
            channel, frozen_at_utc, frozen_reason, frozen_by_action_id,
            acknowledged_at_utc, acknowledged_by, acknowledgement_note
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL)
        ON CONFLICT (channel) DO UPDATE SET
            frozen_at_utc = excluded.frozen_at_utc,
            frozen_reason = excluded.frozen_reason,
            frozen_by_action_id = excluded.frozen_by_action_id,
            acknowledged_at_utc = NULL,
            acknowledged_by = NULL,
            acknowledgement_note = NULL
        """,
        (channel, now.isoformat(), reason, action_id),
    )


def acknowledge_channel(
    conn: sqlite3.Connection, *, channel: str, acknowledged_by: str, note: str
) -> None:
    """Clear a frozen channel. Mirrors `scheduler.acknowledge_metabolic_alarm`.

    The note is required for the same reason that one is: the record of *why
    someone thought it was safe to continue* is the only thing that makes a
    repeated freeze legible later.
    """
    get_spec(channel)
    note = (note or "").strip()
    if not note:
        raise ChannelError(
            "clearing a frozen channel must state why it is safe to continue — "
            "§21.1's shared assets are what was damaged"
        )
    frozen, _ = channel_frozen(conn, channel)
    if not frozen:
        raise ChannelError(f"channel {channel!r} is not frozen")

    now = datetime.now(timezone.utc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE channel_state SET frozen_at_utc = NULL, acknowledged_at_utc = ?, "
            "acknowledged_by = ?, acknowledgement_note = ? WHERE channel = ?",
            (now.isoformat(), acknowledged_by, note, channel),
        )
        audit.record(
            conn,
            event_type="channel_unfrozen",
            cell_id=None,
            description=f"{channel} unfrozen: {note}",
            metadata={"channel": channel, "acknowledged_by": acknowledged_by},
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --- §21.2 collision checks ---------------------------------------------------


def _window_start(now: datetime) -> datetime:
    return now - timedelta(seconds=CONTACT_WINDOW_SECONDS)


def check_action(
    conn: sqlite3.Connection,
    *,
    channel: str,
    counterparty: str | None = None,
    founder_cell_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Would this action be allowed? Raises `ExternalActionRefused` if not.

    Read-only, so an operator can ask *before* doing anything — which is what
    §21.2's "prevent" requires. `external_actions.claim` runs the identical
    check inside its write lock, because check-then-lock is the bug class this
    kernel fixed across the board once already and here it would mean two
    lineages contacting one person on the strength of two checks that each saw
    an empty table.

    An unknown `founder_cell_id` is treated as *not* being any existing
    lineage, so the sibling check is at its strictest — an operator asking "may
    I contact this person" gets the most conservative answer available rather
    than a laxer one than the claim will apply.
    """
    now = now or datetime.now(timezone.utc)
    spec = get_spec(channel)

    if not autonomy_enabled(conn, spec.autonomy_flag):
        raise ChannelAutonomyRefused(
            f"autonomy.{spec.autonomy_flag} is disabled (§27.1 ships it false), "
            f"so nothing may go out on {channel}"
        )

    frozen, reason = channel_frozen(conn, channel)
    if frozen:
        raise ChannelFrozen(
            f"channel {channel!r} is frozen: {reason}. §21.1 — a person must "
            "acknowledge it before anything else goes out."
        )

    if spec.requires_counterparty and not (counterparty or "").strip():
        raise ChannelError(f"channel {channel!r} addresses one counterparty; name it")
    if counterparty is not None and not spec.requires_counterparty:
        raise ChannelError(
            f"channel {channel!r} addresses nobody in particular; it takes no counterparty"
        )

    if counterparty is not None:
        digest = counterparty_hash(conn, counterparty)
        _check_counterparty_locked(
            conn,
            digest=digest,
            channel=channel,
            founder_cell_id=founder_cell_id,
            now=now,
        )

    _check_channel_caps_locked(conn, spec=spec, now=now)


def _check_counterparty_locked(
    conn: sqlite3.Connection,
    *,
    digest: str,
    channel: str,
    founder_cell_id: str | None,
    now: datetime,
) -> None:
    blocked = conn.execute(
        "SELECT reason, blocked_at_utc FROM counterparty_blocks WHERE counterparty_hash = ?",
        (digest,),
    ).fetchone()
    if blocked is not None:
        raise CounterpartyBlocked(
            f"this counterparty is on the do-not-contact list ({blocked['reason']}, "
            f"{blocked['blocked_at_utc']}). There is no unblock — §21.1's damage is "
            "not the colony's to undo."
        )

    since = _window_start(now).isoformat()

    # A *different lineage* first, even though a same-channel repeat by anyone
    # is also a duplicate. §21.3 is the more serious and the less obvious
    # finding — "externally the colony is one business" — and an operator told
    # only "already contacted" would read it as their own oversight rather than
    # as two lineages competing for one person.
    #
    # **Only when the caller said which lineage they are.** An operator asking
    # "may I contact this person" from `check_action` supplies no founder, and
    # the strictest reading is still applied — any prior contact refuses — but
    # it is reported as prior contact rather than as a cross-lineage conflict.
    # Naming §21.3 there was a live-run finding: the message accused a second
    # lineage of interfering when the only claim on record belonged to the
    # asker's own. A refusal that misidentifies what went wrong is worse than a
    # blunter one, because the operator acts on the diagnosis.
    if founder_cell_id is not None:
        sibling = conn.execute(
            """
            SELECT action_id, founder_cell_id, channel, claimed_at_utc
              FROM external_action_registry
             WHERE counterparty_hash = ? AND status != 'abandoned'
               AND claimed_at_utc >= ? AND founder_cell_id <> ?
             ORDER BY claimed_at_utc DESC LIMIT 1
            """,
            (digest, since, founder_cell_id),
        ).fetchone()
        if sibling is not None:
            raise SiblingCollision(
                f"§21.3: lineage {sibling['founder_cell_id']} reached this counterparty "
                f"on {sibling['channel']} at {sibling['claimed_at_utc']} (action "
                f"{sibling['action_id']}). Externally the colony is one business, and "
                "two lineages contacting one person is how it contradicts itself."
            )
    else:
        prior = conn.execute(
            """
            SELECT action_id, channel, claimed_at_utc
              FROM external_action_registry
             WHERE counterparty_hash = ? AND status != 'abandoned'
               AND claimed_at_utc >= ?
             ORDER BY claimed_at_utc DESC LIMIT 1
            """,
            (digest, since),
        ).fetchone()
        if prior is not None:
            raise DuplicateContact(
                f"§21.2: this counterparty was already contacted on {prior['channel']} "
                f"at {prior['claimed_at_utc']} (action {prior['action_id']}), within "
                f"the last {CONTACT_WINDOW_SECONDS}s"
            )

    same_channel = conn.execute(
        """
        SELECT action_id, founder_cell_id, claimed_at_utc
          FROM external_action_registry
         WHERE counterparty_hash = ? AND channel = ? AND status != 'abandoned'
           AND claimed_at_utc >= ?
         ORDER BY claimed_at_utc DESC LIMIT 1
        """,
        (digest, channel, since),
    ).fetchone()
    if same_channel is not None:
        raise DuplicateContact(
            f"§21.2: this counterparty was already contacted on {channel} at "
            f"{same_channel['claimed_at_utc']} (action {same_channel['action_id']}), "
            f"within the last {CONTACT_WINDOW_SECONDS}s"
        )


def _check_channel_caps_locked(
    conn: sqlite3.Connection, *, spec: ChannelSpec, now: datetime
) -> None:
    recent = conn.execute(
        """
        SELECT COUNT(*) AS n FROM external_action_registry
         WHERE channel = ? AND status != 'abandoned' AND claimed_at_utc >= ?
        """,
        (spec.channel_id, _window_start(now).isoformat()),
    ).fetchone()["n"]
    if recent >= spec.max_actions_per_window:
        raise ChannelRateLimit(
            f"§21.2: {recent} actions already on {spec.channel_id} in the last "
            f"{CONTACT_WINDOW_SECONDS}s, at the colony-wide cap of "
            f"{spec.max_actions_per_window}. The cap is the colony's, not this "
            "Cell's — §21.1's assets are shared."
        )

    open_claims = conn.execute(
        "SELECT COUNT(*) AS n FROM external_action_registry "
        "WHERE channel = ? AND status = 'claimed'",
        (spec.channel_id,),
    ).fetchone()["n"]
    if open_claims >= spec.max_open_claims:
        raise ChannelQuotaExceeded(
            f"{open_claims} unfinished claims on {spec.channel_id} (cap "
            f"{spec.max_open_claims}). Complete or abandon one first."
        )


# --- reads --------------------------------------------------------------------


def history_for(
    conn: sqlite3.Connection, cell_id: str, *, limit: int = 5
) -> list[dict]:
    """One Cell's external actions, most recent first — a **read**.

    This is what `context.py` calls, and the reason `context` may import this
    module at all. There is deliberately no path from here into `claim`.

    **`counterparty_hash` is not selected.** A Cell has no use for it: it cannot
    contact anyone directly, it cannot compute the hash of a name it does not
    have, and putting a stable per-person token into a prompt is how a colony
    that carefully avoided storing identities reconstructs one anyway.
    """
    rows = conn.execute(
        """
        SELECT action_id, channel, intent, status, outcome, human_minutes,
               claimed_at_utc, completed_at_utc, artifact_id
          FROM external_action_registry
         WHERE cell_id = ?
         ORDER BY claimed_at_utc DESC LIMIT ?
        """,
        (cell_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def open_claims(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT action_id, cell_id, channel, intent, claimed_at_utc, claimed_by
          FROM external_action_registry WHERE status = 'claimed'
         ORDER BY claimed_at_utc
        """
    ).fetchall()
    return [dict(row) for row in rows]


def human_minutes_total(conn: sqlite3.Connection) -> int:
    """§28 Phase 8's "human labour is measured", colony-wide.

    Read from the registry rather than from `resource_usage` because the two
    answer different questions: this is the wall time a person spent, and the
    metering table is what that consumption cost the Cell's budget.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(human_minutes), 0) AS m FROM external_action_registry"
    ).fetchone()
    return int(row["m"])
