"""§1.1's two profit figures, derived from the books (SPEC.md §1.1, §2.2, §2.4,
§2.5, §2.6, §10.1, §27.2; §28 Phase 9; ADR-099).

`REAL_SETTLED_NET_PROFIT` and `AUTONOMY_ADJUSTED_PROFIT` are what §1.1 and §32
call the colony's measure of success, and §28 Phase 9's acceptance asks for both
by name. Every term §1.1 lists now has a path except the operating costs nothing
records, so this module sums them — **derived on every read and stored nowhere**
(§2.5, Charter C3), like §2.6's experiment report beside it.

```text
REAL_SETTLED_NET_PROFIT = settled revenue - refunds - chargebacks - payment fees
                          - real API/cloud spend - other external operating costs
```

**The second figure needs a rate, and §2.4 forbids the code choosing one.** Human
minutes and local compute are metered in the RESOURCE book, and §2.2 is exact
about what that book is: resources "may be shadow-priced for *reporting* but are
never posted as real cash". §2.6's sample report nonetheless prints an
"Autonomy-adjusted shadow cost ... USD_REAL-equivalent", so a rate must exist —
and a rate this module picked would be §2.4's forbidden bridge with a reporting
label on it. So the rate is **declared by a person** (`declare_shadow_rate`,
migration 0039), recorded with who declared it, and read here and nowhere else.
Until one is declared, the second figure is reported as unavailable with its
reason, never as 0 — a 0 reads as "nothing was subsidised", which is the claim
§1.1 exists to disprove.

**The autonomy adjustment is defined for real profit only.** Human minutes and
compute are colony-wide RESOURCE consumption; subtracting a USD-equivalent of
them from a *synthetic* profit would mix books in the direction §2.4 spends a
whole clause forbidding. A USD_SIM report therefore carries the first figure and
abstains on the second.

**What is missing is named, not zeroed.** Hosting, advertising, data/software and
fulfilment have no recording path (they are chosen spend and want a reservation,
not a posting — logged in FUTURE_BUILD_HOOKS), and nothing records donated
infrastructure at all. Both appear in `unmeasured` on every report, so a reader
can never mistake "not recorded" for "did not happen".
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ledger, payment_fees, pricing, providers, revenue
from .channel_registry import HUMAN_MINUTE_RESOURCE_COST
from .models import Book, ResourceType

_EXTERNAL_EXPENSE = "external_expense"

#: §1.1 names these costs and nothing in this kernel can record one. Stated on
#: every report rather than folded into a 0 (ADR-042's rule: a figure that should
#: abstain must abstain).
UNMEASURED_OPERATING_COSTS = (
    "other external operating costs (§1.1: hosting, advertising, data/software, "
    "fulfilment): chosen spend, which has no recording path yet"
)
UNMEASURED_DONATED_INFRASTRUCTURE = (
    "donated infrastructure (§1.1): nothing records a donation"
)
UNMEASURED_NO_SHADOW_RATE = (
    "autonomy-adjusted profit: no shadow rate declared (§2.4 forbids this module "
    "choosing one — `mitosis set-shadow-rate`)"
)
UNMEASURED_SIM_AUTONOMY = (
    "autonomy-adjusted profit is defined for real profit (§1.1); a synthetic book "
    "has no USD_REAL-equivalent to subtract"
)


class ProfitError(Exception):
    pass


@dataclass(frozen=True)
class ShadowRate:
    """What a person says one RESOURCE unit is worth, for reporting only."""

    micro_usd_per_resource_unit: int
    declared_by: str
    declared_at_utc: datetime
    note: str


@dataclass(frozen=True)
class ProfitReport:
    """§1.1's report for one money book. Every field is a sum over the ledger at
    read time; nothing here is stored."""

    book: str

    # --- REAL_SETTLED_NET_PROFIT's terms, in §1.1's own order ----------------
    gross_revenue_minor_units: int
    refunds_minor_units: int
    chargebacks_minor_units: int
    payment_fees_minor_units: int
    model_and_cloud_spend_minor_units: int
    real_settled_net_profit_minor_units: int

    # --- what the second figure subtracts ------------------------------------
    #: Minutes a person gave, and the part of them no Cell paid for (§1.1's
    #: "hidden human labour"). Reported whether or not a rate exists.
    human_minutes: int
    human_minutes_subsidised: int
    human_shadow_resource_units: int
    #: §1.1's "free tiers": calls to a locally-hosted model, priced at zero in
    #: USD_REAL and metered in RESOURCE. The colony's own machine is the subsidy.
    local_model_calls: int
    local_model_resource_units: int

    shadow_rate_micro_usd_per_resource_unit: int | None
    shadow_cost_minor_units: int | None
    autonomy_adjusted_profit_minor_units: int | None

    #: Every term §1.1 names that this kernel cannot measure, each with why.
    unmeasured: tuple[str, ...]


def declare_shadow_rate(
    conn: sqlite3.Connection,
    *,
    micro_usd_per_resource_unit: int,
    declared_by: str,
    note: str = "",
) -> ShadowRate:
    """Declare what one RESOURCE unit is worth in micro-USD, for §1.1's second
    figure. Operator-only by construction: nothing a Cell can reach calls this,
    and the value never reaches a ledger posting.

    Redeclaring replaces the rate and records the previous one in the audit
    trail, because a rate that changed silently would move every profit figure
    derived from it with no record of why.
    """
    if not isinstance(micro_usd_per_resource_unit, int) or isinstance(
        micro_usd_per_resource_unit, bool
    ):
        raise ProfitError("the shadow rate must be an integer number of micro-USD per unit")
    if micro_usd_per_resource_unit <= 0:
        raise ProfitError(
            f"the shadow rate must be positive, got {micro_usd_per_resource_unit} — a rate of "
            "0 reports subsidised work as free, which is what §1.1 exists to expose"
        )
    if not declared_by.strip():
        raise ProfitError(
            "declared_by is required — §2.4 allows a reporting rate a person chose, and the "
            "record of who chose it is what distinguishes one from a rate the code invented"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        previous = get_shadow_rate(conn)
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO shadow_price_config (
                id, resource_micro_usd_per_unit, declared_by, declared_at_utc, note
            ) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                resource_micro_usd_per_unit = excluded.resource_micro_usd_per_unit,
                declared_by = excluded.declared_by,
                declared_at_utc = excluded.declared_at_utc,
                note = excluded.note
            """,
            (micro_usd_per_resource_unit, declared_by.strip(), now.isoformat(), note),
        )
        audit.record(
            conn,
            event_type="shadow_price_declared",
            description=(
                f"shadow rate set to {micro_usd_per_resource_unit} micro-USD per RESOURCE unit "
                f"by {declared_by.strip()}"
            ),
            metadata={
                "before_micro_usd_per_unit": (
                    previous.micro_usd_per_resource_unit if previous else None
                ),
                "after_micro_usd_per_unit": micro_usd_per_resource_unit,
                "declared_by": declared_by.strip(),
                "note": note,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    rate = get_shadow_rate(conn)
    assert rate is not None
    return rate


def get_shadow_rate(conn: sqlite3.Connection) -> ShadowRate | None:
    """The declared rate, or `None` when nobody has declared one."""
    row = conn.execute("SELECT * FROM shadow_price_config WHERE id = 1").fetchone()
    if row is None:
        return None
    return ShadowRate(
        micro_usd_per_resource_unit=row["resource_micro_usd_per_unit"],
        declared_by=row["declared_by"],
        declared_at_utc=datetime.fromisoformat(row["declared_at_utc"]),
        note=row["note"],
    )


def report(conn: sqlite3.Connection, book: Book = Book.USD_REAL) -> ProfitReport:
    """§1.1's two figures for one money book, derived on read (§2.5)."""
    if book is Book.RESOURCE:
        raise ProfitError(
            "RESOURCE is a shadow-price book for metering, not money (§2.2) — it has no "
            "profit. Its consumption is subtracted from real profit as a shadow cost."
        )

    gross = revenue.colony_gross_revenue(conn, book)
    refunds = revenue.colony_reversed_revenue(conn, book, kind=revenue.ReversalKind.REFUND)
    chargebacks = revenue.colony_reversed_revenue(
        conn, book, kind=revenue.ReversalKind.CHARGEBACK
    )
    fees = payment_fees.colony_fees_total(conn, book)
    # Everything that left the colony under this book, less the fees counted on
    # their own line. §1.1 separates API, hosting, advertising, data and
    # fulfilment; this kernel can only record model-gateway spend, so the rest
    # of the line is 0 by absence — which `unmeasured` says out loud.
    external_expense = ledger.get_balance(conn, _EXTERNAL_EXPENSE, book)
    model_and_cloud = external_expense - fees
    net_profit = gross - refunds - chargebacks - fees - model_and_cloud

    minutes, subsidised = _human_labour(conn)
    human_units = minutes * HUMAN_MINUTE_RESOURCE_COST
    local_calls, local_units = _local_compute(conn)

    unmeasured = (UNMEASURED_OPERATING_COSTS, UNMEASURED_DONATED_INFRASTRUCTURE)
    rate = get_shadow_rate(conn)
    shadow_cost: int | None = None
    autonomy: int | None = None
    if book is not Book.USD_REAL:
        unmeasured += (UNMEASURED_SIM_AUTONOMY,)
    elif rate is None:
        unmeasured += (UNMEASURED_NO_SHADOW_RATE,)
    else:
        shadow_cost = pricing.micro_usd_to_minor_units(
            (human_units + local_units) * rate.micro_usd_per_resource_unit
        )
        autonomy = net_profit - shadow_cost

    return ProfitReport(
        book=book.value,
        gross_revenue_minor_units=gross,
        refunds_minor_units=refunds,
        chargebacks_minor_units=chargebacks,
        payment_fees_minor_units=fees,
        model_and_cloud_spend_minor_units=model_and_cloud,
        real_settled_net_profit_minor_units=net_profit,
        human_minutes=minutes,
        human_minutes_subsidised=subsidised,
        human_shadow_resource_units=human_units,
        local_model_calls=local_calls,
        local_model_resource_units=local_units,
        shadow_rate_micro_usd_per_resource_unit=(
            rate.micro_usd_per_resource_unit if rate is not None else None
        ),
        shadow_cost_minor_units=shadow_cost,
        autonomy_adjusted_profit_minor_units=autonomy,
        unmeasured=unmeasured,
    )


def _human_labour(conn: sqlite3.Connection) -> tuple[int, int]:
    """Colony-wide (minutes a person gave, of which subsidised).

    Billed **plus** subsidised, for the reason `experiments._human_labour` gives
    per experiment: summing what a Cell paid for would make the colony's human
    cost smaller the more of it a person absorbed unpaid — hidden by the figure
    §1.1 wrote to expose it.
    """
    rows = conn.execute(
        "SELECT quantity, metadata_json FROM resource_usage WHERE resource_type = ?",
        (ResourceType.HUMAN_MINUTES.value,),
    ).fetchall()
    billed = sum(int(row["quantity"]) for row in rows)
    subsidised = 0
    for row in rows:
        recorded = json.loads(row["metadata_json"] or "{}").get("subsidised_human_minutes", 0)
        if isinstance(recorded, int) and not isinstance(recorded, bool) and recorded > 0:
            subsidised += recorded
    return billed + subsidised, subsidised


def _local_compute(conn: sqlite3.Connection) -> tuple[int, int]:
    """Calls to a locally-hosted model, and the RESOURCE units they metered.

    §1.1's "free tiers and founder subsidies": a local model is priced at zero in
    USD_REAL (`pricing.PRICING_TABLE`) precisely because no one invoices for it,
    which makes the colony look cheaper than it is by exactly the compute someone
    is donating. The mock provider is excluded — a test double is not a subsidy.
    """
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT m.model_call_id) AS calls,
               COALESCE(SUM(u.minor_units), 0) AS units
        FROM model_calls m
        LEFT JOIN resource_usage u ON u.reservation_id = m.resource_reservation_id
        WHERE m.provider = ?
        """,
        (providers.OLLAMA_PROVIDER,),
    ).fetchone()
    return int(row["calls"]), int(row["units"])
