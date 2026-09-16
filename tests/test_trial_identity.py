"""The trial's legal identity (SPEC.md §0.3, §3.6, §16.3, §28 Phase 9; ADR-100).

Phase 9 trades under one legal identity, and every sale, refund and fee the
colony has been able to record since ADR-097 attributes to it. Two things matter
here and the tests are shaped around them: **only a person may state it** (§0.3,
§16.3 — it is non-inheritable and the genome already refuses a gene for it), and
**the payment account is a label, never an account**, which the schema enforces
so that no caller, present or future, can put a card number in this database.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sqlite3

import pytest

from mitosis import genome, trial_identity

SRC = pathlib.Path(trial_identity.__file__).parent

#: The only modules that may write one: the operator's CLI, the golden run that
#: replays an operator's actions, and the module that owns the table.
IDENTITY_WRITERS = {"cli.py", "golden.py", "trial_identity.py"}

_LABEL = "Stripe account: personal"


def _attest(conn, **overrides):
    kwargs = dict(
        legal_entity="M. Master, sole trader",
        jurisdiction="GB",
        payment_account_label=_LABEL,
        basis="the operator's own registration and account",
        attested_by="operator",
    )
    kwargs.update(overrides)
    return trial_identity.attest(conn, **kwargs)


# --- the record ---------------------------------------------------------------


def test_an_attestation_records_who_trades_and_on_what_account(conn):
    identity = _attest(conn)

    assert identity.legal_entity == "M. Master, sole trader"
    assert identity.jurisdiction == "GB"
    assert identity.payment_account_label == _LABEL
    assert not identity.is_withdrawal
    assert trial_identity.current(conn).attestation_id == identity.attestation_id
    assert trial_identity.in_force(conn).attestation_id == identity.attestation_id


def test_nothing_is_in_force_until_someone_says_so(conn):
    assert trial_identity.current(conn) is None
    assert trial_identity.in_force(conn) is None


def test_the_latest_attestation_wins_and_the_record_keeps_the_earlier_one(conn):
    first = _attest(conn)
    second = _attest(conn, legal_entity="Master Software Ltd", basis="incorporated")

    assert trial_identity.in_force(conn).legal_entity == "Master Software Ltd"
    assert [i.attestation_id for i in trial_identity.history(conn)] == [
        second.attestation_id,
        first.attestation_id,
    ]


def test_a_withdrawal_is_a_new_row_that_leaves_why_in_the_record(conn):
    """§3.6: a retraction is an adjustment, not a deletion. A deleted row leaves
    an absence; this leaves a reason."""
    _attest(conn)

    withdrawal = trial_identity.attest(
        conn, withdraw=True, basis="trading paused pending advice", attested_by="operator"
    )

    assert withdrawal.is_withdrawal
    assert trial_identity.in_force(conn) is None
    assert trial_identity.current(conn).basis == "trading paused pending advice"
    assert len(trial_identity.history(conn)) == 2


def test_a_withdrawal_carries_no_identity(conn):
    with pytest.raises(trial_identity.TrialIdentityError, match="carries no entity"):
        trial_identity.attest(
            conn, withdraw=True, legal_entity="someone", basis="b", attested_by="operator"
        )


def test_half_an_identity_is_not_a_state(conn):
    with pytest.raises(trial_identity.TrialIdentityError, match="jurisdiction"):
        _attest(conn, jurisdiction="")


@pytest.mark.parametrize("field", ["basis", "attested_by"])
def test_an_attestation_names_its_basis_and_its_author(conn, field):
    with pytest.raises(trial_identity.TrialIdentityError):
        _attest(conn, **{field: "   "})


def test_attesting_is_audited_with_what_it_displaced(conn):
    _attest(conn)
    _attest(conn, legal_entity="Master Software Ltd", basis="incorporated")

    rows = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE event_type = 'trial_identity_attested' "
        "ORDER BY rowid"
    ).fetchall()
    assert len(rows) == 2
    assert '"supersedes":null' in rows[0]["metadata_json"]
    assert '"previous_legal_entity":"M. Master, sole trader"' in rows[1]["metadata_json"]


# --- a label, never an account ------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "4111111111111111",
        "GB29 NWBK 6016 1331 9268 19",
        "sort code 60-16-13 account 31926819",
        "sk_live_abc123",
        "stripe password hunter2",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_an_account_number_or_credential_is_refused(conn, label):
    """The boundary this module exists to hold. A person's card, bank account or
    key has no use anywhere in this colony, so it must not be storable — not
    "discouraged", not "redacted on display"."""
    with pytest.raises(trial_identity.TrialIdentityError):
        _attest(conn, payment_account_label=label)
    assert trial_identity.current(conn) is None


@pytest.mark.parametrize(
    "label",
    ["Stripe account: personal", "Gumroad (2026 trial)", "PayPal — business, ending 4242"],
)
def test_a_name_for_an_account_is_exactly_what_belongs_here(conn, label):
    assert _attest(conn, payment_account_label=label).payment_account_label == label


def test_a_grouped_account_number_is_caught_by_the_rule_the_schema_cannot_see(conn):
    """The schema refuses eight *consecutive* digits, which an IBAN written in
    groups of four slips past — so the total-digit rule in
    `_refuse_account_numbers` is the only thing standing between this label and
    the database. The two rules are not redundant, and this pins the one with no
    backstop."""
    grouped = "GB29 NWBK 6016 1331 9268 19"
    assert max(len(run) for run in re.findall(r"\d+", grouped)) < 8, (
        "if this ever contains a run of eight digits the schema would catch it too, "
        "and this test would no longer pin the Python rule"
    )
    with pytest.raises(trial_identity.TrialIdentityError, match="looks like an account number"):
        _attest(conn, payment_account_label=grouped)


def test_the_schema_refuses_an_account_number_whatever_the_caller_does(conn):
    """The Python check explains; the CHECK constraint is the guarantee. A future
    caller that forgets to validate still cannot write a number."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            """
            INSERT INTO trial_identity_attestations (
                attestation_id, legal_entity, jurisdiction, payment_account_label,
                basis, attested_by, attested_at_utc
            ) VALUES ('a', 'E', 'GB', '4111111111111111', 'b', 'operator', '2026-01-01T00:00:00+00:00')
            """
        )


def test_the_schema_refuses_half_an_identity(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            """
            INSERT INTO trial_identity_attestations (
                attestation_id, legal_entity, jurisdiction, payment_account_label,
                basis, attested_by, attested_at_utc
            ) VALUES ('a', 'E', NULL, NULL, 'b', 'operator', '2026-01-01T00:00:00+00:00')
            """
        )


def test_a_label_that_is_too_long_is_refused(conn):
    with pytest.raises(trial_identity.TrialIdentityError, match="not a document"):
        _attest(conn, payment_account_label="x" * 201)


# --- §0.3 and §16.3: the identity is the colony's, and a person states it ------


def test_no_cell_reachable_module_writes_a_trial_identity():
    """§0.3 structurally, the shape `test_rights.py` uses. Who the colony trades
    as decides who is liable for a trade; it is exactly the fact a Cell may never
    define. An AST walk over every module but the operator surfaces, so the next
    module cannot quietly fall outside a hand-picked list."""
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        if path.name in IDENTITY_WRITERS:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "attest"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "trial_identity"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = " ".join(node.value.upper().split())
                if "TRIAL_IDENTITY_ATTESTATIONS" in sql and "INSERT" in sql:
                    offenders.append(f"{path.name}:{node.lineno} (raw INSERT)")
    assert not offenders, (
        "only the operator may state the colony's legal identity (§0.3); found: "
        + ", ".join(offenders)
    )


def test_no_module_updates_or_deletes_an_attestation():
    """§3.6 — append-only, withdrawal is a new row. Includes the owning module,
    which is the one most worth checking."""
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = " ".join(node.value.upper().split())
                if "TRIAL_IDENTITY_ATTESTATIONS" in sql and (
                    "UPDATE " in sql or "DELETE " in sql
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"the record is append-only (§3.6); found: {offenders}"


def test_the_genome_still_refuses_a_legal_identity_gene():
    """§16.3 makes legal identity non-inheritable, and `genome.py`'s tripwire
    refused the gene — "Phase 9 has exactly one, and it is the colony's" — before
    anything could declare one. This module is that clause's other half, so the
    two are pinned together: if the gene ever became a real field, a Cell could
    inherit an identity the colony is liable for, and reproduction would be
    §16.4's liability escape."""
    assert "legal_identity" in genome.NON_INHERITABLE_SENSE
    assert "legal_identity" not in genome.GENOME_FIELDS, (
        "the genome gained a legal_identity field; §16.3 says the colony has exactly one "
        "identity and `trial_identity` is where it lives"
    )
    assert "platform_account" in genome.NON_INHERITABLE_SENSE, (
        "the payment account is the same clause: a real platform account is not heritable"
    )
