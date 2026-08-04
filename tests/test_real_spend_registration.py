"""Registration completeness for the real-spend circuit breaker (Charter C5).

`real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES` is the list that both the
hour/day/month caps and the per-provider cap read. A USD_REAL transaction type
that posts to `external_expense` but is missing from that tuple is real money
the breaker cannot see, and the caps then fail *open* — the one direction that
matters.

Registration has been a convention enforced by a reviewer noticing, and it was
missed twice in a single arc: `model_call_cost_overrun` shipped unregistered
(the gateway slice), and `model_call_reconciliation_adjustment` arrived as the
first type whose amount can be *negative*, which both queries mishandled. These
tests replace the reviewer.

Three angles, because no one of them is sufficient:

1. `..._every_transaction_type_is_classified` walks the kernel's AST and
   requires every `transaction_type=` it finds to be either registered or
   explicitly exempted with a stated reason. This is the angle that fires on a
   *new* type, whatever that type does.
2. `..._external_expense_sites_are_registered` requires any call site naming
   `external_expense` to use a registered type. This is the precise check and
   the one that would have caught the cost overrun — but it structurally cannot
   see `reservation_settle`, whose destination account comes from the
   reservation record at runtime rather than appearing in the source.
3. `..._registered_types_are_counted` proves each registered type is actually
   summed by *both* windows. Presence in the tuple is necessary but not
   sufficient for the per-provider query, which additionally depends on the
   `{transaction_type}:{model_call_id}` idempotency-key convention — an
   undocumented coupling that a newly-registered type could silently break.

Named to be collectible as `pytest -k charter_realspend_cap` alongside the
existing C5 property test, per SPEC.md §0.1.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import mitosis
from mitosis import ids, ledger, lifecycle, real_spend_breaker, reservations
from mitosis.models import Book, CellType, EntrySpec, RealSpendLimits

SRC = pathlib.Path(mitosis.__file__).parent

_EXTERNAL_EXPENSE = "external_expense"

# Every transaction type in the kernel that is *not* real spend, with the reason
# it cannot be. Each reason was verified against the call site's book and its
# entry accounts, not assumed from the name — `colony_seed_capital` in
# particular is USD_REAL-capable and touches an `external_capital` account,
# which is a different account from `external_expense` and flows the other way.
_EXEMPT_TRANSACTION_TYPES = {
    "colony_seed_capital": "external_capital -> seed_bank: capital entering the colony, not leaving",
    "cell_revenue": (
        "revenue -> cell cash: money entering the colony. USD_REAL-capable and it does "
        "raise a Cell's spending power via Charter C4's balance check, but it never "
        "touches external_expense, and Charter C5's caps bound gross spend rather than "
        "a net position — earning must not buy permission to spend past a cap"
    ),
    "cell_funding": "seed_bank -> cell cash: internal transfer",
    "cell_birth_funding": "funding account -> cell cash: internal transfer",
    "cell_reproduction_funding": "parent cash -> child cash: internal transfer (ADR-019)",
    "reservation_reserve": (
        "cell cash -> cell committed: internal, and the committed leg is counted "
        "separately by _concurrent_reserved rather than as settled spend"
    ),
    "reservation_release": "cell committed -> cell cash: returns money, never spends it",
    "model_call_sim_mirror": "Book.USD_SIM only (§2.4): a synthetic mirror is never real spend",
    "event_side_effect": "Book.USD_SIM only: golden-run scenario handler",
}

# Non-literal `transaction_type=` expressions that relay a type rather than
# introduce one. Anything not listed here fails the classification test, so a
# new dynamic form has to be looked at by a human instead of slipping past the
# AST walk unnoticed.
_KNOWN_NON_LITERAL_FORMS = {
    "transaction_type",  # ledger.py's own pass-through parameter
    'row["transaction_type"]',  # ledger.py reconstructing a Transaction from a row
}

_PROVIDER = "test-provider"
_AMOUNT = 300


@dataclasses.dataclass(frozen=True)
class _CallSite:
    module: str
    lineno: int
    transaction_type: str
    names_external_expense: bool
    # True only when `book=` is statically `Book.USD_SIM`. A dynamic `book=book`
    # is treated as possibly-real, because at runtime it can be.
    provably_sim_only: bool

    @property
    def is_real_spend_shaped(self) -> bool:
        return self.names_external_expense and not self.provably_sim_only


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so a call site that passes a
    constant (`RECONCILIATION_TRANSACTION_TYPE`, `_EXTERNAL_EXPENSE`) resolves
    the same way as one passing the string directly."""
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants[target.id] = node.value.value
    return constants


def _resolve_string(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _mentions(call: ast.Call, constants: dict[str, str], target: str) -> bool:
    """Whether `target` appears anywhere in this call's subtree, as a literal or
    via a module constant. Deliberately broad: a nested unrelated mention would
    force a type to be registered when it need not be, which is the harmless
    direction to be wrong in."""
    for node in ast.walk(call):
        if isinstance(node, ast.Constant) and node.value == target:
            return True
        if isinstance(node, ast.Name) and constants.get(node.id) == target:
            return True
    return False


def _static_book(call: ast.Call) -> str | None:
    """The `book=` argument when it is a plain `Book.MEMBER` attribute, else None
    for a dynamic one (`book=book`, `book=reservation.book`)."""
    for keyword in call.keywords:
        if keyword.arg != "book":
            continue
        node = keyword.value
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "Book"
        ):
            return f"Book.{node.attr}"
    return None


def _call_sites() -> tuple[list[_CallSite], list[tuple[str, int, str | None]]]:
    sites: list[_CallSite] = []
    unresolved: list[tuple[str, int, str | None]] = []
    for path in sorted(SRC.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "transaction_type":
                    continue
                value = _resolve_string(keyword.value, constants)
                if value is None:
                    unresolved.append(
                        (
                            path.name,
                            keyword.value.lineno,
                            ast.get_source_segment(source, keyword.value),
                        )
                    )
                    continue
                sites.append(
                    _CallSite(
                        module=path.name,
                        lineno=node.lineno,
                        transaction_type=value,
                        names_external_expense=_mentions(node, constants, _EXTERNAL_EXPENSE),
                        provably_sim_only=_static_book(node) == "Book.USD_SIM",
                    )
                )
    return sites, unresolved


def _registered() -> set[str]:
    return set(real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES)


# --- charter_realspend_cap (C5): static registration guards ------------------


def test_charter_realspend_cap_every_transaction_type_is_classified():
    sites, unresolved = _call_sites()

    # If the walk ever stops finding call sites it would pass vacuously forever.
    assert len(sites) >= 10, f"AST walk found only {len(sites)} call sites — the walk is broken"

    stray_forms = {form for _, _, form in unresolved} - _KNOWN_NON_LITERAL_FORMS
    assert not stray_forms, (
        f"transaction_type passed as an unrecognised expression: {sorted(stray_forms)}. "
        "The AST walk cannot classify it. Either make it a module-level constant or add "
        "it to _KNOWN_NON_LITERAL_FORMS after confirming it only relays an existing type."
    )

    unclassified = {s.transaction_type for s in sites} - _registered() - set(_EXEMPT_TRANSACTION_TYPES)
    assert not unclassified, (
        f"unclassified transaction type(s): {sorted(unclassified)}. If the type can post a "
        "USD_REAL entry to external_expense, add it to "
        "real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES — otherwise the hour/day/month and "
        "per-provider caps cannot see that spend and will fail open. If it cannot, add it to "
        "_EXEMPT_TRANSACTION_TYPES here with the book and accounts that make it exempt."
    )


def test_charter_realspend_cap_external_expense_sites_are_registered():
    sites, _ = _call_sites()

    spending = [s for s in sites if s.is_real_spend_shaped]
    assert spending, "no call site names external_expense — this check has gone vacuous"

    offenders = sorted(
        f"{s.module}:{s.lineno} posts {s.transaction_type!r}"
        for s in spending
        if s.transaction_type not in _registered()
    )
    assert not offenders, (
        "call site(s) posting to external_expense with an unregistered transaction type: "
        f"{offenders}. This is real money the circuit breaker cannot see."
    )


def test_sim_book_postings_to_external_expense_are_excluded_deliberately():
    """`external_expense` is an account name, not a book, and the USD_SIM mirror
    (§2.4) posts to it too. The breaker's queries filter `book = 'USD_REAL'`, so
    those postings are correctly invisible to it — but the exclusion is asserted
    here rather than left implicit, since it is the one way a genuinely
    unregistered real-spend type could hide from the check above."""
    excluded = {
        s.transaction_type
        for s in _call_sites()[0]
        if s.names_external_expense and s.provably_sim_only
    }
    assert excluded == {"model_call_sim_mirror"}, (
        f"the set of USD_SIM postings to external_expense changed: {sorted(excluded)}. "
        "Confirm each is genuinely synthetic before widening this — a real-spend type "
        "misfiled as USD_SIM would be skipped by the registration check."
    )


def test_registry_and_exemptions_are_disjoint_and_current():
    registered, exempt = _registered(), set(_EXEMPT_TRANSACTION_TYPES)
    discovered = {s.transaction_type for s in _call_sites()[0]}

    assert not (registered & exempt), (
        f"type(s) both registered and exempt: {sorted(registered & exempt)}"
    )
    assert not (exempt - discovered), (
        f"stale exemption(s) for type(s) no longer in the kernel: {sorted(exempt - discovered)}"
    )
    assert not (registered - discovered), (
        f"registered type(s) no call site posts — likely a typo: {sorted(registered - discovered)}"
    )
    assert all(_EXEMPT_TRANSACTION_TYPES.values()), "every exemption must state its reason"


# --- charter_realspend_cap (C5): the registry actually has teeth -------------


@pytest.fixture()
def spender(conn):
    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(
        conn,
        RealSpendLimits(
            per_request_minor_units=5_000,
            per_hour_minor_units=50_000,
            per_day_minor_units=500_000,
            per_month_minor_units=5_000_000,
            max_concurrent_reserved_minor_units=50_000,
            provider_limits={},
        ),
    )
    created = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=10_000,
        book=Book.USD_REAL,
        idempotency_key="registration-cell",
    )
    # `model_calls.resource_reservation_id` is NOT NULL, and Charter C4 means a
    # RESOURCE reservation needs RESOURCE cash to draw on.
    ledger.post_transaction(
        conn,
        book=Book.RESOURCE,
        currency="RESOURCE",
        transaction_type="test_funding",
        idempotency_key=f"fund-resource:{created.cell_id}",
        entries=[
            EntrySpec(account_id="seed_bank", amount_minor_units=-10_000),
            EntrySpec(
                account_id=f"cell:{created.cell_id}:cash",
                amount_minor_units=10_000,
                cell_id=created.cell_id,
            ),
        ],
    )
    return created


def _model_call_row(conn, cell_id: str) -> str:
    """A minimal `model_calls` row tagged with `_PROVIDER`, which the
    per-provider query joins through. Built directly rather than by driving the
    gateway: this test is about the breaker's SQL, and a real call would drag in
    pricing and a provider."""
    real = reservations.request(
        conn,
        cell_id=cell_id,
        book=Book.USD_REAL,
        currency="USD",
        maximum_amount=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=f"row-real:{cell_id}",
        provider=_PROVIDER,
    )
    resource = reservations.request(
        conn,
        cell_id=cell_id,
        book=Book.RESOURCE,
        currency="RESOURCE",
        maximum_amount=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key=f"row-resource:{cell_id}",
    )
    model_call_id = ids.new_id()
    conn.execute(
        """
        INSERT INTO model_calls (
            model_call_id, cell_id, status, provider, requested_model,
            pricing_table_version, user_prompt_hash, real_reservation_id,
            resource_reservation_id, created_at_utc, idempotency_key
        ) VALUES (?, ?, 'succeeded', ?, 'test-model', 'test', 'hash', ?, ?, ?, ?)
        """,
        (
            model_call_id,
            cell_id,
            _PROVIDER,
            real.reservation_id,
            resource.reservation_id,
            datetime.now(timezone.utc).isoformat(),
            f"call:{model_call_id}",
        ),
    )
    conn.commit()
    return model_call_id


def _post_spend(conn, cell_id: str, transaction_type: str) -> None:
    """Move `_AMOUNT` of USD_REAL to external_expense under `transaction_type`,
    attributed to `_PROVIDER` the way production does it for that type."""
    if transaction_type == "reservation_settle":
        reservation = reservations.request(
            conn,
            cell_id=cell_id,
            book=Book.USD_REAL,
            currency="USD",
            maximum_amount=_AMOUNT,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            idempotency_key=f"settle-me:{cell_id}",
            provider=_PROVIDER,
        )
        reservations.settle(
            conn,
            reservation.reservation_id,
            settled_amount=_AMOUNT,
            destination_account_id=_EXTERNAL_EXPENSE,
        )
        return

    # Every other registered type posts directly, and the per-provider query
    # finds it by joining model_calls on `{transaction_type}:{model_call_id}`.
    model_call_id = _model_call_row(conn, cell_id)
    ledger.post_transaction(
        conn,
        book=Book.USD_REAL,
        currency="USD",
        transaction_type=transaction_type,
        idempotency_key=f"{transaction_type}:{model_call_id}",
        entries=[
            EntrySpec(
                account_id=f"cell:{cell_id}:cash",
                amount_minor_units=-_AMOUNT,
                cell_id=cell_id,
            ),
            EntrySpec(account_id=_EXTERNAL_EXPENSE, amount_minor_units=_AMOUNT),
        ],
    )


@pytest.mark.parametrize("transaction_type", real_spend_breaker._REAL_SPEND_TRANSACTION_TYPES)
def test_charter_realspend_cap_registered_types_are_counted(conn, spender, transaction_type):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    assert real_spend_breaker._settled_spend_since(conn, since) == 0

    _post_spend(conn, spender.cell_id, transaction_type)

    assert real_spend_breaker._settled_spend_since(conn, since) == _AMOUNT, (
        f"{transaction_type!r} is registered but the global hour/day/month window does not "
        "count it — the caps would fail open on this spend"
    )
    assert (
        real_spend_breaker._settled_spend_for_provider_since(conn, _PROVIDER, since) == _AMOUNT
    ), (
        f"{transaction_type!r} is registered but the per-provider window does not count it. "
        "Registration alone is not enough for a direct-posting type: its idempotency key must "
        f"be '{transaction_type}:{{model_call_id}}' for the model_calls join to find it."
    )
