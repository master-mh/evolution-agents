"""Prediction register (SPEC.md §8.5, Amendment A14).

The register's whole value is that a prediction cannot be changed once the
outcome is known, and that a Cell cannot improve its record by resolving only
its winners. These tests lean on exactly those two properties, plus the scoring
rules §8.5 names.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from mitosis import lifecycle, prediction
from mitosis.models import Book, CellType

FUTURE = timedelta(days=1)


@pytest.fixture()
def cell(conn):
    return lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=1_000,
        book=Book.USD_SIM,
        idempotency_key="prediction-cell",
    )


def _register(conn, cell, *, claim="revenue >= 50", probability=0.7, days=1.0, key=None):
    return prediction.register(
        conn,
        cell_id=cell.cell_id,
        claim=claim,
        probability=probability,
        resolves_by=datetime.now(timezone.utc) + timedelta(days=days),
        idempotency_key=key,
    )


# --- scoring rules (§8.5 names Brier and log score specifically) -------------


@pytest.mark.parametrize(
    "probability,occurred,expected",
    [
        (0.7, True, 0.09),      # (0.7 - 1)^2
        (0.7, False, 0.49),     # (0.7 - 0)^2
        (0.5, True, 0.25),      # the always-guessing baseline
        (0.5, False, 0.25),
        (0.99, True, 0.0001),
    ],
)
def test_brier_score(probability, occurred, expected):
    assert prediction.brier_score(probability, occurred) == pytest.approx(expected)


def test_log_score_matches_negative_log_of_the_assigned_probability():
    assert prediction.log_score(0.7, True) == pytest.approx(-math.log(0.7))
    assert prediction.log_score(0.7, False) == pytest.approx(-math.log(0.3))


def test_log_score_is_finite_even_for_a_stored_extreme():
    """A single infinity makes a Cell's mean score uncomparable, and a
    population that cannot be ordered cannot be selected on."""
    assert math.isfinite(prediction.log_score(1.0, False))
    assert math.isfinite(prediction.log_score(0.0, True))


def test_certainty_is_refused_at_registration(conn, cell):
    for probability in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(prediction.PredictionError, match="strictly between 0 and 1"):
            _register(conn, cell, probability=probability)


# --- register-before-outcome ------------------------------------------------


def test_a_prediction_cannot_be_registered_after_its_own_deadline(conn, cell):
    with pytest.raises(prediction.PredictionError, match="must be in the future"):
        _register(conn, cell, days=-1)


def test_resolution_records_outcome_and_both_scores(conn, cell):
    registered = _register(conn, cell, probability=0.8)
    assert registered.outcome is None
    assert not registered.is_resolved

    resolved = prediction.resolve(
        conn, registered.prediction_id, occurred=True, source="ledger"
    )
    assert resolved.outcome is True
    assert resolved.is_resolved
    assert resolved.resolution_source == "ledger"
    assert resolved.brier_score == pytest.approx(0.04)
    assert resolved.log_score == pytest.approx(-math.log(0.8))


def test_a_prediction_cannot_be_resolved_twice(conn, cell):
    """Re-resolving would let a Cell rewrite its calibration after the fact —
    the one thing this register exists to prevent."""
    registered = _register(conn, cell)
    prediction.resolve(conn, registered.prediction_id, occurred=False, source="ledger")
    with pytest.raises(prediction.PredictionError, match="already resolved"):
        prediction.resolve(conn, registered.prediction_id, occurred=True, source="ledger")

    still = prediction.get(conn, registered.prediction_id)
    assert still.outcome is False, "the original outcome survived the second attempt"


def test_resolution_requires_a_source(conn, cell):
    registered = _register(conn, cell)
    with pytest.raises(prediction.PredictionError, match="source is required"):
        prediction.resolve(conn, registered.prediction_id, occurred=True, source="  ")


def test_claim_is_required(conn, cell):
    with pytest.raises(prediction.PredictionError, match="claim is required"):
        _register(conn, cell, claim="   ")


def test_prediction_for_unknown_cell_is_refused(conn):
    with pytest.raises(prediction.PredictionError, match="no such cell"):
        prediction.register(
            conn,
            cell_id="not-a-cell",
            claim="x",
            probability=0.5,
            resolves_by=datetime.now(timezone.utc) + FUTURE,
        )


# --- tamper evidence --------------------------------------------------------


def test_chain_is_valid_across_many_predictions(conn, cell):
    for index in range(5):
        _register(conn, cell, claim=f"claim {index}", key=f"k{index}")
    assert prediction.verify_chain(conn)


def test_editing_a_registered_prediction_breaks_the_chain(conn, cell):
    """A per-row hash proves nothing against an editor who recomputes it.
    Chaining is what makes register-before-outcome checkable."""
    first = _register(conn, cell, probability=0.6, key="a")
    _register(conn, cell, probability=0.4, key="b")
    assert prediction.verify_chain(conn)

    # Improve the first prediction after the fact.
    conn.execute(
        "UPDATE prediction_register SET probability = 0.95 WHERE prediction_id = ?",
        (first.prediction_id,),
    )
    conn.commit()
    assert not prediction.verify_chain(conn)


def test_resolving_does_not_break_the_chain(conn, cell):
    """The hash covers the prediction, never the outcome — otherwise recording
    what happened would look like tampering."""
    registered = _register(conn, cell)
    prediction.resolve(conn, registered.prediction_id, occurred=True, source="ledger")
    assert prediction.verify_chain(conn)


# --- anti-gaming: resolution is not the Cell's to choose --------------------


def test_overdue_surfaces_predictions_left_unresolved(conn, cell):
    """A Cell that resolves only its winners has a beautiful calibration curve
    and a pile of these behind it."""
    stale = _register(conn, cell, claim="will pay off", days=1, key="stale")
    _register(conn, cell, claim="not due yet", days=30, key="fresh")

    # Nothing overdue yet.
    assert prediction.overdue(conn) == []

    later = datetime.now(timezone.utc) + timedelta(days=2)
    overdue = prediction.overdue(conn, now=later)
    assert [p.prediction_id for p in overdue] == [stale.prediction_id]


def test_scores_report_unresolved_and_overdue_beside_the_means(conn, cell):
    """A mean Brier score over cherry-picked resolutions is worse than useless,
    and a consumer that sees only the mean cannot know."""
    good = _register(conn, cell, probability=0.9, key="good")
    _register(conn, cell, probability=0.9, days=1, key="ignored")
    prediction.resolve(conn, good.prediction_id, occurred=True, source="ledger")

    stats = prediction.scores(conn, cell.cell_id)
    assert stats["total"] == 2
    assert stats["resolved"] == 1
    assert stats["unresolved"] == 1
    assert stats["mean_brier"] == pytest.approx(0.01)


def test_scores_are_empty_rather_than_zero_when_nothing_is_resolved(conn, cell):
    """Zero would read as a perfect score. None reads as no evidence."""
    _register(conn, cell)
    stats = prediction.scores(conn, cell.cell_id)
    assert stats["mean_brier"] is None
    assert stats["mean_log"] is None
    assert stats["resolved"] == 0


def test_scores_are_scoped_per_cell(conn, cell):
    other = lifecycle.create_cell(
        conn,
        cell_type=CellType.BUILDER,
        budget_minor_units=100,
        book=Book.USD_SIM,
        idempotency_key="other-cell",
    )
    mine = _register(conn, cell, probability=0.9, key="mine")
    theirs = prediction.register(
        conn,
        cell_id=other.cell_id,
        claim="theirs",
        probability=0.1,
        resolves_by=datetime.now(timezone.utc) + FUTURE,
        idempotency_key="theirs",
    )
    prediction.resolve(conn, mine.prediction_id, occurred=True, source="s")
    prediction.resolve(conn, theirs.prediction_id, occurred=True, source="s")

    assert prediction.scores(conn, cell.cell_id)["mean_brier"] == pytest.approx(0.01)
    assert prediction.scores(conn, other.cell_id)["mean_brier"] == pytest.approx(0.81)
    assert prediction.scores(conn)["total"] == 2


# --- calibration curve (§8.5's "not a vibe") --------------------------------


def test_calibration_curve_separates_confidence_from_accuracy(conn, cell):
    """The shape is the diagnosis: systematic overconfidence and systematic
    underconfidence can produce the same mean Brier score but call for opposite
    corrections."""
    # Ten claims at p=0.9 that come true only half the time: overconfident.
    for index in range(10):
        registered = _register(conn, cell, probability=0.9, key=f"over{index}")
        prediction.resolve(
            conn, registered.prediction_id, occurred=index % 2 == 0, source="s"
        )

    curve = prediction.calibration(conn, cell_id=cell.cell_id)
    bucket = next(b for b in curve if b["bucket_low"] == pytest.approx(0.9))
    assert bucket["count"] == 10
    assert bucket["mean_predicted"] == pytest.approx(0.9)
    assert bucket["observed_frequency"] == pytest.approx(0.5), "predicted 0.9, delivered 0.5"


def test_calibration_omits_unresolved_predictions(conn, cell):
    _register(conn, cell, probability=0.7)
    assert prediction.calibration(conn, cell_id=cell.cell_id) == []


def test_a_well_calibrated_cell_tracks_the_diagonal(conn, cell):
    for index in range(10):
        registered = _register(conn, cell, probability=0.7, key=f"cal{index}")
        prediction.resolve(conn, registered.prediction_id, occurred=index < 7, source="s")

    bucket = prediction.calibration(conn, cell_id=cell.cell_id)[0]
    assert bucket["mean_predicted"] == pytest.approx(0.7)
    assert bucket["observed_frequency"] == pytest.approx(0.7)


def test_registration_and_resolution_are_both_audited(conn, cell):
    registered = _register(conn, cell)
    prediction.resolve(conn, registered.prediction_id, occurred=True, source="inv-9")

    types = [
        r["event_type"]
        for r in conn.execute(
            "SELECT event_type FROM audit_events WHERE cell_id = ? ORDER BY rowid", (cell.cell_id,)
        )
    ]
    assert "prediction_registered" in types
    assert "prediction_resolved" in types
