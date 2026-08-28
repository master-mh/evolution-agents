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

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from . import audit, counterparty
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
    """§21.3: two lineages reaching one *target* look like one business
    contradicting itself. Bidding wars and conflicting offers are this shape.

    The target is whichever §21.2 key the channel is keyed on — a counterparty,
    a domain, or a platform account. ADR-037 widened this from the counterparty
    alone, because for a channel that addresses nobody the counterparty check
    was skipped entirely and this refusal could never fire.
    """


class DuplicatePublication(ExternalActionRefused):
    """§21.2's "duplicate", for a channel with no person to key it on.

    The same content-addressed artifact going to the same target twice. ADR-035
    made an artifact's identity its content hash so that §11.3's "duplicated
    artifacts with new names" is unrepresentable; this is the first check that
    spends that identity. Unlike a sibling collision it applies to *any*
    lineage, including the one that published it the first time — a marketplace
    suspends an account for duplicate listings without asking who filed them.
    """


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


class TargetKind(str, Enum):
    """Which of §21.2's aggregation keys a channel's collisions are keyed on.

    §21.2 names "counterparty/domain/channel over a rolling window", and §21.1's
    shared assets add the platform account. Every channel collides on exactly
    one of them, and the channel dimension is already the cap.

    This replaced a `requires_counterparty: bool` (ADR-037). The boolean was not
    wrong so much as it only described the `email` case: everything it said
    "no" to fell out of §21.2's checks altogether, so `marketplace_listing` and
    `web_publish` had a registry entry, a rate cap, a freeze — and no duplicate,
    sibling or block check at all. Naming the key instead means a channel that
    addresses nobody still collides on *something*, and a new channel has to say
    what.
    """

    COUNTERPARTY = "counterparty"
    DOMAIN = "domain"
    PLATFORM_ACCOUNT = "platform_account"


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
    #: with no flag would be a capability nobody ever decided to allow — and no
    #: flag may serve two channels, which is ADR-037 and is enforced by a test.
    autonomy_flag: str
    #: Which §21.2 key this channel's collisions are keyed on. **Required at
    #: claim time**, so a channel fails closed rather than skipping its checks:
    #: an action whose target is unknown cannot be compared against anything,
    #: and "cannot be compared" must not read as "does not collide".
    target_kind: TargetKind
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
        target_kind=TargetKind.COUNTERPARTY,
        max_actions_per_window=5,
        max_open_claims=2,
        max_billable_human_minutes=30,
    ),
    # §0.4's "no real commerce", not its "no public publishing": a listing is an
    # **offer to sell**, which is §28 Phase 9's "one narrow product class, one
    # merchant channel" and not Phase 8's landing-page draft. ADR-037 moved it
    # off `external_publish` for that reason — the old flag granted a Phase 9
    # capability along with a Phase 8 one, so the defensible half could not be
    # turned on by itself.
    "marketplace_listing": ChannelSpec(
        channel_id="marketplace_listing",
        description=(
            "One listing on one marketplace account, posted by hand. Two "
            "lineages listing against each other is §21.2's bidding war, and "
            "the platform account is what they collide on."
        ),
        short_description="one marketplace listing, posted by hand",
        autonomy_flag="real_commerce",
        target_kind=TargetKind.PLATFORM_ACCOUNT,
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
        target_kind=TargetKind.DOMAIN,
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
#
# Moved to `counterparty.py` (ADR-061) once §12.1's inbound revenue key needed
# the same digest under the same salt. What is left here is §21.2's *target*
# normalisation, which is a channel concept: a domain and a platform account are
# addressed openly and are stored as typed-but-normalised, not hashed.


def normalise_target(value: str | None) -> str | None:
    """§21.2's domain and platform account, in the form the aggregation uses.

    Normalised by `counterparty.normalise`, the same function that normalises
    what gets hashed, and for the reason given there: `Alice@Ex.com` and
    `alice@ex.com` are one person, and a dedupe that misses that is a dedupe
    that does not work. `Colony.Test` and `colony.test` are one domain — DNS
    says so — and two operators typing a platform account differently would
    otherwise collide on nothing.

    **Applied on write as well as on read**, and to every channel rather than
    only the one keyed on the column. The sibling query for a domain deliberately
    looks across channels, so an `email` row holding `Golden.Test` while a
    `web_publish` claim asks about `golden.test` would be exactly the collision
    §21.3 exists to catch, missed on a capitalisation. Where two spellings really
    are distinct platform accounts this over-refuses, which is the safe
    direction: a refused claim costs a conversation, a missed collision costs
    §21.1's shared assets.
    """
    return counterparty.normalise(value)


def counterparty_hash(conn: sqlite3.Connection, party: str) -> str:
    """§21.2's spelling of `counterparty.hash_of`, raising this module's error.

    Kept as a name because §21.2's callers speak of a counterparty hash and
    catch `ChannelError`; the digest itself is not a channel concept and no
    longer lives here.
    """
    try:
        return counterparty.hash_of(conn, party)
    except counterparty.CounterpartyError as exc:
        raise ChannelError(str(exc)) from exc


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


def target_of(
    spec: ChannelSpec,
    *,
    counterparty: str | None,
    domain: str | None,
    platform_account: str | None,
) -> str:
    """The value this channel collides on, validated. Raises if it is missing.

    **Fails closed.** A channel whose target is unknown cannot be compared
    against anything on record, and the whole failure ADR-037 fixed was that
    "cannot be compared" read as "does not collide" — `marketplace_listing` and
    `web_publish` carried a registry entry, a rate cap and a freeze, and no
    duplicate or sibling check at all, because both were keyed on a
    counterparty they do not have.

    The other two fields stay recordable either way: §21.2 tracks "domain used"
    and "platform account" as facts, and an email genuinely has a sending
    domain even though it collides on the recipient. Only the counterparty is
    refused where it does not belong, because that one carries §16.3's hazard —
    a page addressed to nobody has no business holding a person's identifier.
    """
    supplied = {
        TargetKind.COUNTERPARTY: counterparty,
        TargetKind.DOMAIN: domain,
        TargetKind.PLATFORM_ACCOUNT: platform_account,
    }

    if spec.target_kind is not TargetKind.COUNTERPARTY and counterparty is not None:
        raise ChannelError(
            f"channel {spec.channel_id!r} addresses nobody in particular; it takes no "
            f"counterparty. It collides on its {spec.target_kind.value}."
        )

    # Normalised exactly as `counterparty_hash` normalises, and for the reason
    # it gives: `Alice@Ex.com` and `alice@ex.com` are one person, and a dedupe
    # that misses that is a dedupe that does not work. `Colony.Test` and
    # `colony.test` are one domain — DNS says so — and two operators typing a
    # platform account differently would otherwise collide on nothing. Where the
    # two spellings really are distinct accounts this over-refuses, which is the
    # safe direction: a refused claim costs a conversation and a missed
    # collision costs §21.1's shared assets.
    value = normalise_target(supplied[spec.target_kind]) or ""
    if not value:
        raise ChannelError(
            f"channel {spec.channel_id!r} collides on its {spec.target_kind.value}; "
            f"name it. §21.2 aggregates on counterparty/domain/channel, and an "
            "action with no target cannot be checked against anything."
        )
    return value


def check_action(
    conn: sqlite3.Connection,
    *,
    channel: str,
    counterparty: str | None = None,
    domain: str | None = None,
    platform_account: str | None = None,
    artifact_id: str | None = None,
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

    **That strictest-reading trick does not transfer to a target channel, and
    the difference is the whole of ADR-037's third consequence.** Contacting one
    person twice is §21.2's duplicate; publishing twice to your own domain is a
    business publishing twice. So "refuse on any prior action" — conservative
    for a counterparty — would refuse the *normal* case for a domain, and
    ADR-036 already established that a refusal misidentifying what went wrong is
    worse than a blunter one, because the operator acts on the diagnosis. A
    target-keyed channel therefore **refuses to answer** without a lineage
    rather than guessing which way to be wrong.
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

    target = target_of(
        spec,
        counterparty=counterparty,
        domain=domain,
        platform_account=platform_account,
    )

    if spec.target_kind is TargetKind.COUNTERPARTY:
        _check_counterparty_locked(
            conn,
            digest=counterparty_hash(conn, target),
            channel=channel,
            founder_cell_id=founder_cell_id,
            now=now,
        )
    else:
        _check_target_locked(
            conn,
            spec=spec,
            target=target,
            artifact_id=artifact_id,
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


def _check_target_locked(
    conn: sqlite3.Connection,
    *,
    spec: ChannelSpec,
    target: str,
    artifact_id: str | None,
    founder_cell_id: str | None,
    now: datetime,
) -> None:
    """§21.2 for a channel that addresses nobody (ADR-037).

    Two checks, and they are deliberately *not* the counterparty's two:

    1. **Sibling collision (§21.3)** — a different lineage acting on the same
       domain or platform account inside the window. This is where "bidding
       wars, conflicting offers, cannibalisation" actually live for a publish
       channel: two lineages listing against each other on one merchant account
       is one business contradicting itself, exactly as two lineages emailing
       one person is.
    2. **Duplicate publication** — the same artifact to the same target, by
       *anyone*. A person can be contacted once; a domain can be published to
       all day. What cannot happen twice is the same content, and ADR-035 made
       content the artifact's identity, so this is the one duplicate check a
       target channel can honestly make.

    **A same-lineage repeat is not a collision here**, which is the asymmetry
    with `_check_counterparty_locked`. Refusing it would refuse a business
    publishing twice to its own site — and a guard that fires on the normal case
    is the failure ADR-036 caught in `understated_risk`, arrived at from the
    other direction.
    """
    column = spec.target_kind.value  # a TargetKind member, never caller input
    since = _window_start(now).isoformat()

    if founder_cell_id is None:
        raise ChannelError(
            f"channel {spec.channel_id!r} collides on its {column}, where a repeat by "
            "the *same* lineage is not a collision at all — so this check needs to "
            "know which lineage is asking. Name a cell."
        )

    sibling = conn.execute(
        f"""
        SELECT action_id, founder_cell_id, channel, claimed_at_utc
          FROM external_action_registry
         WHERE {column} = ? AND status != 'abandoned'
           AND claimed_at_utc >= ? AND founder_cell_id <> ?
         ORDER BY claimed_at_utc DESC LIMIT 1
        """,
        (target, since, founder_cell_id),
    ).fetchone()
    if sibling is not None:
        raise SiblingCollision(
            f"§21.3: lineage {sibling['founder_cell_id']} acted on {column} "
            f"{target!r} via {sibling['channel']} at {sibling['claimed_at_utc']} "
            f"(action {sibling['action_id']}). Externally the colony is one "
            "business, and two lineages on one channel account is how it bids "
            "against itself."
        )

    if artifact_id is None:
        return

    # Windowed, on the same clock as everything else in this module. §21.2's own
    # words are "cumulative-exposure aggregation keys … over a rolling window",
    # and an unwindowed version would be a permanent lock with no release: an
    # artifact could never be republished after a listing expired, and the
    # kernel has no unpublish to pair with it. One window rather than two, for
    # the reason `CONTACT_WINDOW_SECONDS` already gives — a patient splitter
    # spaces its actions past whichever window is narrower.
    #
    # **Scoped to the channel, unlike the sibling check above.** Two lineages on
    # one domain contradict each other whichever channels they used, so that one
    # looks across all of them. But emailing a write-up from a domain and then
    # publishing it on that same domain is one business doing two normal things
    # — it is only a duplicate if the same content goes out the same way twice.
    duplicate = conn.execute(
        f"""
        SELECT action_id, founder_cell_id, claimed_at_utc
          FROM external_action_registry
         WHERE {column} = ? AND artifact_id = ? AND channel = ?
           AND status != 'abandoned' AND claimed_at_utc >= ?
         ORDER BY claimed_at_utc DESC LIMIT 1
        """,
        (target, artifact_id, spec.channel_id, since),
    ).fetchone()
    if duplicate is not None:
        raise DuplicatePublication(
            f"§21.2: artifact {artifact_id} already went to {column} {target!r} at "
            f"{duplicate['claimed_at_utc']} (action {duplicate['action_id']}). It is "
            "the same content — §11.3's 'duplicated artifacts with new names' cannot "
            "get around this, because an artifact is identified by its content."
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
