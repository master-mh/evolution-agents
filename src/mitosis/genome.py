"""Genome content addressing and inheritance (SPEC.md §16, Charter C11).

A genome is *what business a Cell is in*: §16.2's v0.1 fields — market,
problem, product, revenue_model, acquisition_channel, workflow, model_policy,
mutation_rate — plus the two permission-shaped ones discussed below. Until this
slice the canonical content was a placeholder carrying `cell_type` and nothing
else, so a Cell's only real decisions were about its own books.

**Content addressing.** A genome is identified *by its content*: identical
canonical content always yields the same hash and therefore the same
`cell_genomes` row. That has a direct consequence for reproduction — a child
whose content is identical to its parent's is not a new genome, it *is* the
parent's genome, and recording a parent_genome_hashes edge for it would be a
self-loop (ADR-018, ADR-019). Parentage deliberately lives *outside* the
canonical content, because §16.1 wants the hash usable for deduplication and
counterfactual comparison, which require two structurally identical strategies
to hash identically regardless of who produced them.

**Inheritance was coincidental before this slice, and that was a latent bug.**
`lifecycle._get_or_create_genome` built a child's genome from its cell_type and
the caller's mutation; the parent's content was never read. While every genome
was `{"cell_type": ...}` this was invisible — parent and child collided into the
same row, so "an unmutated child reuses its parent's genome" looked true. With
real content it is false in two directions at once: an unmutated child would
have been born a *blank slate*, losing everything its parent knew, and that
blank content would have addressed to the same row as every other bare Cell of
its type, giving unrelated lineages one shared genome. `inherit()` is the fix,
and `test_an_unmutated_child_inherits_its_parents_content` is the guard.

**§16.4 is the clause that shapes the schema:**

    Without exact inheritance semantics, Cells could reproduce to *escape
    liabilities while keeping profitable assets*.

So the schema is **closed**. Only the fields below are accepted; anything else
is refused by name. A blocklist of credential-shaped keys was the obvious
alternative and is strictly worse — it fails open on every spelling nobody
thought of, and §16.3's non-inheritable list (raw credentials, approvals,
customer identity, private customer data, real platform account access,
unresolved external communications, legal identity) is exactly the content that
must never reach a content-addressed object whose hash is a public dedup key.
Closure makes those categories *unrepresentable* rather than merely rejected.
`NON_INHERITABLE_SENSE` records why each category has no field, and its test
fails if one ever acquires one — the same tripwire shape as
`proposal.FORBIDDEN_FIELD_SENSE`.

**Two of §16.2's own fields are permission-shaped, and a mutable genome must
not be allowed to self-grant.** §0.4 grants autonomy "tool by tool, phase by
phase"; §23.5 warns that the approval queue "will be optimised against". A Cell
that mutated `risk_class` downward into its children would have bought them
cheap approvals, and one that appended to `allowed_tools` would have granted
itself a capability. ADR-027 already drew this line for `claimed_tier` versus
`assessed_tier`, and this module reuses that decision rather than inventing a
parallel one: `risk_class` and `allowed_tools` are inherited, mutable, and
recorded — but they are **claims and requests, never grants**. `risk_class`
folds into `approval._assessed_tier` with the same `max` that governs
`claimed_tier`, so it can only ever raise the tier. `allowed_tools` names
capabilities the kernel does not yet have and grants none of them.

Deliberately out of scope: §16.3's **liability-linked** class, which forbids
revenue-producing assets transferring without their refund liabilities and
service obligations. Nothing provisions a liability reserve yet (`accounts` has
the account; no policy posts to it), so this slice cannot honestly enforce that
rule — and rather than fake the check, the v0.1 field set simply carries no
field denoting a transferable revenue-producing asset. See
`NON_INHERITABLE_SENSE["revenue_producing_asset"]`.

**`model_policy` was written at birth and read by nothing until ADR-067.**
ADR-050 measured that sampling temperature dominates parse rate more than
model choice does, and refused the obvious one-line fix — `temperature: 0` as
a provider constant — because §14.1 names "temperature/sampling mutation" as a
prompt-mutation operator: that puts sampling in the *mutable Cell* column, not
the kernel's. `model_policy` was already §16.2's reserved socket for exactly
this. ADR-067 gives it a first, single-key shape: `{"temperature": 0.0-1.0}`,
validated and read by `providers.py` the same way every other genome field is
inherited and mutated — `inherit()`'s overlay needs no new mechanism, because
answering "inherited, mutated, or both" was already the standing answer for
every field in `INHERITABLE_FIELDS`. `MODEL_POLICY_FIELDS` is closed the same
way the top-level schema is, because §14.1 lists model-route and
reasoning-budget mutation as future occupants of this same socket, and a
misspelled or half-built key should fail loudly rather than being silently
ignored by whichever provider does not recognise it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import CellType


class GenomeError(Exception):
    pass


#: §16.3 **Inheritable**: "workflow structure, prompts, market/pricing
#: hypotheses, tested code modules, model policies, validated economic
#: beliefs". These pass from parent to child untouched unless a mutation
#: overlays them, and they are the whole point of the genome — the content a
#: Cell reasons *from* when it decides what to propose.
INHERITABLE_FIELDS: dict[str, str] = {
    "cell_type": "structural identity; the child's own type when reproduction overrides it",
    "market": "who is being sold to — a §16.3 market hypothesis",
    "problem": "the need being addressed",
    "product": "what is delivered",
    "revenue_model": "how money is supposed to arrive — a §16.3 economic belief",
    "acquisition_channel": (
        "how customers are supposed to be reached. The *hypothesis* is "
        "inheritable; a real platform account is §16.3 non-inheritable and has "
        "no field here"
    ),
    "workflow": "§16.3 workflow structure",
    "model_policy": "§16.3 model policy — which models this strategy prefers",
    "mutation_rate": "how readily this lineage varies (§14)",
}

#: Permission-shaped fields. Inherited and mutable like everything else, but
#: **read as claims, never as grants** — see the module docstring. Kept
#: separate from INHERITABLE_FIELDS so that a future field cannot quietly join
#: the permission set without a decision: `unclassified_fields()` forces every
#: genome field into exactly one of these two dicts.
CLAIMED_FIELDS: dict[str, str] = {
    "risk_class": (
        "the Cell's *claim* about its own risk. Folded into "
        "approval._assessed_tier with `max` (ADR-027), so it may raise the "
        "review tier and can never lower it"
    ),
    "allowed_tools": (
        "capabilities this strategy *requests*. §0.4 grants autonomy tool by "
        "tool; naming a tool here grants nothing"
    ),
}

#: §16.2's v0.1 field list, transcribed verbatim and **declared independently
#: of the classification above**. Deriving this from the two dicts was the
#: first version and was wrong in a way that is easy to miss: it made
#: `unclassified_fields()` empty by construction, so the guard meant to force a
#: classification decision could never fire. `accounts.py` works precisely
#: because `FIXED_ACCOUNTS` is its own declaration and the spend/capital dicts
#: must cover it; this mirrors that, and `test_every_genome_field_is_classified`
#: now has something to fail against.
GENOME_FIELDS: frozenset[str] = frozenset(
    {
        "cell_type",
        "market",
        "problem",
        "product",
        "revenue_model",
        "acquisition_channel",
        "workflow",
        "model_policy",
        "mutation_rate",
        "allowed_tools",
        "risk_class",
    }
)

#: §16.3's non-inheritable categories, and why each has **no field** rather
#: than a field that is skipped on inheritance. This is not a blocklist the
#: validator consults — the closed schema already refuses every one of these,
#: so none could be accepted today. It is a **tripwire for the schema itself**:
#: `test_no_non_inheritable_field_exists` fails if any of these names ever
#: becomes a real field, so widening the genome toward liability-escape has to
#: be a deliberate, argued change to §16.3 rather than a plausible commit.
NON_INHERITABLE_SENSE: dict[str, str] = {
    "credentials": "§16.3 raw credentials; a content-addressed, inherited object is the worst place for a secret",
    "secrets": "as above; spelled only in the general, because Charter C14's canary scans kernel source for credential identifiers and it is right to",
    "approvals": "§16.3; an approval is §23's to grant, per request, and never inherited",
    "customer_identity": "§16.3 customer identity",
    "customer_data": "§16.3 private customer data; §20 governs it and it is not genome content",
    "platform_account": "§16.3 real platform account access — §21.1's shared reputation is not a heritable asset",
    "legal_identity": "§16.3 legal identity; Phase 9 has exactly one, and it is the colony's",
    "open_communications": "§16.3 unresolved external communications",
    "revenue_producing_asset": (
        "§16.3 liability-linked. Such an asset may not transfer without its "
        "refund liabilities and service obligations, and no liability reserve "
        "is provisioned yet — so the honest move is no field, not an "
        "unenforced one"
    ),
}

#: §14.1's mutation operators, given a concrete shape inside `model_policy`.
#: Closed the same way the top-level genome schema is closed: an unknown key
#: is refused by name, so a future occupant of this socket (§14.1 also names
#: model-route and reasoning-budget mutation) is a deliberate decision rather
#: than a field that quietly starts being ignored by whichever provider
#: doesn't recognise it.
MODEL_POLICY_FIELDS: dict[str, str] = {
    "temperature": (
        "§14.1 temperature/sampling mutation. Bounded to [0.0, 1.0] — the "
        "tighter of the two providers' accepted ranges, so a genome mutated "
        "once stays valid on every provider it might run against (§14.2's "
        "counterfactual-twin obligation)"
    ),
}

#: Valid `risk_class` values. Held as plain strings rather than importing
#: `proposal.RiskTier`, because `proposal` sits far above `genome` in the
#: dependency order and a back-edge here would invert the layering the kernel
#: keeps everywhere else. The coupling is real, so it is pinned by a
#: structural test (`test_risk_classes_match_the_approval_tiers`) instead of by
#: an import — the same trade the repo makes elsewhere.
RISK_CLASSES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def unclassified_fields() -> frozenset[str]:
    """Genome fields that are neither inheritable nor a claim.

    Non-empty means a field was added without deciding whether it is content a
    child may simply inherit or a permission-shaped claim that must never
    grant. Mirrors `accounts.unclassified_accounts()`: adding a field forces
    the classification instead of silently defaulting to "ordinary content",
    which for a permission-shaped field is how a Cell ends up granting itself
    something.
    """
    return GENOME_FIELDS - set(INHERITABLE_FIELDS) - set(CLAIMED_FIELDS)


def unknown_classified_fields() -> frozenset[str]:
    """Classified names that are not §16.2 fields — the other direction.

    Catches a classification that outlives the field it described, which would
    otherwise sit in the dicts looking like an enforced rule for a field the
    validator no longer accepts.
    """
    return (set(INHERITABLE_FIELDS) | set(CLAIMED_FIELDS)) - GENOME_FIELDS


def canonical_genome_json(
    cell_type: CellType, mutation: dict[str, Any] | None = None
) -> dict:
    """The canonical content for a founder's genome.

    A founder has no parent to inherit from, so its content is exactly what the
    operator seeds plus its type. `mutation` is the seed here; on reproduction
    the same overlay is applied to the *parent's* content by `inherit()`.
    """
    return inherit({}, mutation, cell_type=cell_type)


def inherit(
    parent_content: dict[str, Any] | None,
    mutation: dict[str, Any] | None,
    *,
    cell_type: CellType,
) -> dict:
    """Child content = the parent's, overlaid with `mutation`.

    `cell_type` is always the child's own, because `lineage.reproduce` may give
    a child a different type from its parent and the genome must describe the
    Cell that actually exists.

    Overlaying rather than replacing is the whole of §16.3's inheritable class:
    a mutation that changes the acquisition channel must not silently discard
    the market and revenue model the lineage was built on. That is also why an
    empty mutation is a no-op returning the parent's content unchanged — under
    content addressing that child *is* its parent's genome (ADR-018), which is
    now true by construction rather than by the accident of both being blank.
    """
    content: dict[str, Any] = dict(parent_content or {})
    if mutation:
        _validate_mutation(mutation)
        content.update(mutation)
    content["cell_type"] = cell_type.value
    _validate_content(content)
    return content


def compute_genome_hash(canonical_genome: dict) -> str:
    canonical = json.dumps(canonical_genome, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def risk_class_of(content: dict[str, Any] | None) -> str | None:
    """The Cell's claimed risk class, or None if its genome states none.

    Named `_of` rather than `get_` to keep it obvious at the call site that
    this is a *claim* being read, not a permission being checked.
    """
    if not content:
        return None
    value = content.get("risk_class")
    return value if isinstance(value, str) else None


def temperature_of(content: dict[str, Any] | None) -> float | None:
    """§14.1's sampling temperature, as declared in this genome's
    `model_policy` — or `None` if the genome declares no policy at all.

    `None` here means "no opinion", never "zero" — a genome that has not
    mutated `model_policy` is not thereby claiming greedy decoding, so a
    provider reads `None` as "use your own default" (`providers.py`), not as
    a temperature of 0.
    """
    if not content:
        return None
    policy = content.get("model_policy")
    if not isinstance(policy, dict):
        return None
    value = policy.get("temperature")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def requested_tools(content: dict[str, Any] | None) -> tuple[str, ...]:
    """Tools this genome *requests*. Grants nothing (§0.4).

    Exists so that the request is legible to an operator and to §23's review
    payload without any caller being tempted to treat the list as an
    entitlement — there is deliberately no `has_tool()` here to call.
    """
    if not content:
        return ()
    value = content.get("allowed_tools")
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


# --- validation --------------------------------------------------------------


def _validate_mutation(mutation: dict[str, Any]) -> None:
    if not isinstance(mutation, dict):
        raise GenomeError("mutation must be a dict")
    for key in mutation:
        if not isinstance(key, str):
            raise GenomeError(f"mutation keys must be strings, got {type(key).__name__}")


def _validate_content(content: dict[str, Any]) -> None:
    """Validate the *whole* canonical content, not just the mutation.

    Deliberately validates the merged result rather than the overlay alone:
    inherited content reaches a child without passing through a mutation, so
    checking only the mutation would let anything already in a parent's genome
    propagate unchecked forever.
    """
    for key in sorted(content):
        if key in NON_INHERITABLE_SENSE:
            raise GenomeError(
                f"{key!r} is §16.3 non-inheritable and has no genome field: "
                f"{NON_INHERITABLE_SENSE[key]}"
            )
        if key not in GENOME_FIELDS:
            raise GenomeError(
                f"unknown genome field {key!r}. The genome schema is closed "
                f"(§16.4): an unclassified field is exactly the overlay a Cell "
                f"could use to carry a profitable asset away from its "
                f"liabilities. Known fields: {', '.join(sorted(GENOME_FIELDS))}"
            )

    risk_class = content.get("risk_class")
    if risk_class is not None and risk_class not in RISK_CLASSES:
        raise GenomeError(
            f"risk_class must be one of {', '.join(RISK_CLASSES)}, got {risk_class!r}"
        )

    tools = content.get("allowed_tools")
    if tools is not None:
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise GenomeError("allowed_tools must be a list of strings")

    rate = content.get("mutation_rate")
    if rate is not None:
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise GenomeError("mutation_rate must be a number between 0 and 1")
        if not 0.0 <= float(rate) <= 1.0:
            raise GenomeError(f"mutation_rate must be between 0 and 1, got {rate}")

    policy = content.get("model_policy")
    if policy is not None:
        _validate_model_policy(policy)

    try:
        # The hash is computed over json.dumps output, so anything that can't
        # serialize deterministically can't be part of a genome (Charter C11).
        json.dumps(content, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise GenomeError(f"genome content must be JSON-serializable: {exc}") from exc


def _validate_model_policy(policy: Any) -> None:
    """§14.1's sampling policy, given a concrete, closed shape. See
    `MODEL_POLICY_FIELDS` and the module docstring for why this is closed the
    same way the top-level genome schema is."""
    if not isinstance(policy, dict):
        raise GenomeError("model_policy must be a dict")
    for key in policy:
        if key not in MODEL_POLICY_FIELDS:
            raise GenomeError(
                f"unknown model_policy field {key!r}. model_policy is closed "
                f"(§14.1): known fields: {', '.join(sorted(MODEL_POLICY_FIELDS))}"
            )

    temperature = policy.get("temperature")
    if temperature is not None:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise GenomeError("model_policy.temperature must be a number between 0.0 and 1.0")
        if not 0.0 <= float(temperature) <= 1.0:
            raise GenomeError(
                f"model_policy.temperature must be between 0.0 and 1.0, got {temperature}"
            )
