"""Prediction register (SPEC.md §8.5, Amendment A14; §31 `prediction_register`).

§8.5's requirement in full: predictions are appended *before* outcomes are
known, each hashed and timestamped; when the outcome arrives it is scored with a
proper scoring rule (Brier or log score); reality gap becomes a calibration
curve rather than a vibe; the register is append-only and feeds the promotion
ladder (§25).

**Why this is worth building before an agent loop exists.** Selection needs a
fitness signal, and revenue is the obvious one — but revenue requires a
customer, and there isn't one yet. Calibration does not. A Cell that predicts
its own outcomes badly is demonstrably worse than one that predicts them well,
*whatever* it is doing and whether or not anyone pays for it. So the register is
the cheapest real selection pressure available: it can start discriminating
between Cells on day one, on a few dollars, before the colony earns anything.

**Binary claims, because §8.5 names Brier and log score specifically.** Both are
defined over binary outcomes. A continuous quantity is therefore predicted by
stating a threshold claim — "revenue >= 50 minor units" — rather than a point
estimate. This is a real constraint and it is the spec's, not an implementation
shortcut: a point estimate cannot be scored by either named rule. Scoring point
estimates properly needs CRPS or an interval rule, which §8.5 does not authorise
and which is logged rather than invented here.

**Probabilities are strictly between 0 and 1.** The log score of a
confident-and-wrong prediction is infinite. One such prediction would pin a
Cell's mean log score at -inf permanently, and selection cannot order a
population where several Cells are all infinitely bad. Rejecting certainty is
also the honest position: a Cell that is certain is not predicting.

**Hash-chained, like the ledger.** A per-row hash proves nothing on its own —
anyone editing the row can recompute it. Chaining means altering any prediction
invalidates every prediction appended after it, which is what turns
"register-before-outcome" from a convention into something checkable
(`verify_chain`).

**Resolution is not the Cell's to choose.** A register where a Cell resolves
only its successful predictions produces a self-selected calibration curve that
looks excellent and means nothing. `overdue` exists so unresolved-past-deadline
predictions are visible and countable, and `scores` reports them alongside the
means rather than quietly omitting them. Nothing here *forces* resolution —
that is a policy question for whatever drives selection — but it makes the
omission impossible to miss.

Deliberately out of scope: the promotion ladder's consumption of this (§25.2
records reality gap per rung; the ladder does not exist); `reality_gap` against
*simulated* outcomes specifically, which needs the flight simulator (Phase 2);
and automatic resolution from ledger state — the operator or caller supplies the
outcome, exactly as with an invoice figure.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from . import audit, ids, lifecycle

# Below this, a probability is treated as certainty and refused. Also the clamp
# that keeps a log score finite if a stored row ever sits outside the CHECK.
_EPSILON = 1e-9


class PredictionError(Exception):
    pass


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    cell_id: str
    experiment_id: str | None
    claim: str
    probability: float
    resolves_by_utc: datetime
    created_at_utc: datetime
    prediction_hash: str
    outcome: bool | None
    resolved_at_utc: datetime | None
    resolution_source: str | None
    brier_score: float | None
    log_score: float | None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at_utc is not None


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(
    *,
    prediction_id: str,
    cell_id: str,
    experiment_id: str | None,
    claim: str,
    probability: float,
    resolves_by_utc: str,
    created_at_utc: str,
    idempotency_key: str,
    previous_hash: str | None,
) -> str:
    """Commits to the prediction and nothing else. The outcome is deliberately
    absent: the hash exists to prove what was claimed *before* the outcome was
    known, so including the outcome would defeat its only purpose."""
    return hashlib.sha256(
        _canonical(
            {
                "prediction_id": prediction_id,
                "cell_id": cell_id,
                "experiment_id": experiment_id,
                "claim": claim,
                "probability": probability,
                "resolves_by_utc": resolves_by_utc,
                "created_at_utc": created_at_utc,
                "idempotency_key": idempotency_key,
                "previous_hash": previous_hash,
            }
        ).encode()
    ).hexdigest()


def _last_hash(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT prediction_hash FROM prediction_register ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    return row["prediction_hash"] if row else None


def _row_to_prediction(row: sqlite3.Row) -> Prediction:
    return Prediction(
        prediction_id=row["prediction_id"],
        cell_id=row["cell_id"],
        experiment_id=row["experiment_id"],
        claim=row["claim"],
        probability=row["probability"],
        resolves_by_utc=datetime.fromisoformat(row["resolves_by_utc"]),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
        prediction_hash=row["prediction_hash"],
        outcome=None if row["outcome"] is None else bool(row["outcome"]),
        resolved_at_utc=(
            datetime.fromisoformat(row["resolved_at_utc"]) if row["resolved_at_utc"] else None
        ),
        resolution_source=row["resolution_source"],
        brier_score=row["brier_score"],
        log_score=row["log_score"],
    )


def register(
    conn: sqlite3.Connection,
    *,
    cell_id: str,
    claim: str,
    probability: float,
    resolves_by: datetime,
    experiment_id: str | None = None,
    idempotency_key: str | None = None,
) -> Prediction:
    """Append a prediction, before its outcome is known.

    `claim` must be unambiguously true or false once resolved — Brier and log
    scores are defined over binary outcomes. Predict a continuous quantity by
    stating a threshold: "revenue >= 50 minor units by epoch 4".
    """
    if not claim.strip():
        raise PredictionError("claim is required — an unstated prediction cannot be scored")
    if not (_EPSILON < probability < 1 - _EPSILON):
        raise PredictionError(
            f"probability must be strictly between 0 and 1, got {probability}. "
            "Certainty is refused: the log score of a confident-and-wrong "
            "prediction is infinite, which would pin a Cell's mean score at "
            "-inf permanently and destroy the ordering selection depends on"
        )

    now = datetime.now(timezone.utc)
    if resolves_by <= now:
        raise PredictionError(
            f"resolves_by must be in the future, got {resolves_by.isoformat()} — "
            "a prediction registered after its own deadline is not a prediction"
        )

    conn.execute("BEGIN IMMEDIATE")
    try:
        cell = lifecycle.get_cell(conn, cell_id)
        if cell is None:
            raise PredictionError(f"no such cell: {cell_id}")

        prediction_id = ids.new_id()
        key = idempotency_key or f"prediction:{prediction_id}"
        created_at = now.isoformat()
        resolves_at = resolves_by.astimezone(timezone.utc).isoformat()
        previous = _last_hash(conn)
        prediction_hash = _compute_hash(
            prediction_id=prediction_id,
            cell_id=cell_id,
            experiment_id=experiment_id,
            claim=claim.strip(),
            probability=probability,
            resolves_by_utc=resolves_at,
            created_at_utc=created_at,
            idempotency_key=key,
            previous_hash=previous,
        )
        conn.execute(
            """
            INSERT INTO prediction_register (
                prediction_id, cell_id, experiment_id, claim, probability,
                resolves_by_utc, created_at_utc, previous_hash, prediction_hash,
                idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                cell_id,
                experiment_id,
                claim.strip(),
                probability,
                resolves_at,
                created_at,
                previous,
                prediction_hash,
                key,
            ),
        )
        audit.record(
            conn,
            event_type="prediction_registered",
            cell_id=cell_id,
            description=claim.strip(),
            metadata={
                "prediction_id": prediction_id,
                "probability": probability,
                "resolves_by_utc": resolves_at,
                "prediction_hash": prediction_hash,
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return get(conn, prediction_id)  # type: ignore[return-value]


def resolve(
    conn: sqlite3.Connection,
    prediction_id: str,
    *,
    occurred: bool,
    source: str,
) -> Prediction:
    """Record what actually happened and score it.

    Refused if already resolved: re-resolving would let a Cell's calibration be
    rewritten after the fact, which is the one thing this register exists to
    prevent.
    """
    if not source.strip():
        raise PredictionError("source is required — an unattributable outcome is not evidence")

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM prediction_register WHERE prediction_id = ?", (prediction_id,)
        ).fetchone()
        if row is None:
            raise PredictionError(f"no such prediction: {prediction_id}")
        if row["resolved_at_utc"] is not None:
            raise PredictionError(
                f"prediction {prediction_id} was already resolved at "
                f"{row['resolved_at_utc']} against {row['resolution_source']!r} — "
                "re-resolving would rewrite a Cell's calibration after the fact"
            )

        probability = row["probability"]
        outcome = 1 if occurred else 0
        conn.execute(
            """
            UPDATE prediction_register
               SET outcome = ?, resolved_at_utc = ?, resolution_source = ?,
                   brier_score = ?, log_score = ?
             WHERE prediction_id = ?
            """,
            (
                outcome,
                datetime.now(timezone.utc).isoformat(),
                source.strip(),
                brier_score(probability, occurred),
                log_score(probability, occurred),
                prediction_id,
            ),
        )
        audit.record(
            conn,
            event_type="prediction_resolved",
            cell_id=row["cell_id"],
            description=row["claim"],
            metadata={
                "prediction_id": prediction_id,
                "probability": probability,
                "outcome": outcome,
                "source": source.strip(),
                "brier_score": brier_score(probability, occurred),
            },
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.commit()
    return get(conn, prediction_id)  # type: ignore[return-value]


def brier_score(probability: float, occurred: bool) -> float:
    """(p - o)^2. Lower is better; 0 is perfect, 1 is maximally wrong, and 0.25
    is what you get by always saying 0.5 — the score to beat."""
    return (probability - (1.0 if occurred else 0.0)) ** 2


def log_score(probability: float, occurred: bool) -> float:
    """-ln(probability assigned to what actually happened). Lower is better.

    Clamped at `_EPSILON` so a row that somehow escaped the 0<p<1 CHECK scores
    very badly rather than infinitely — a single inf would make a Cell's mean
    score uncomparable, and an unorderable population cannot be selected on.
    """
    assigned = probability if occurred else 1.0 - probability
    return -math.log(max(assigned, _EPSILON))


def get(conn: sqlite3.Connection, prediction_id: str) -> Prediction | None:
    row = conn.execute(
        "SELECT * FROM prediction_register WHERE prediction_id = ?", (prediction_id,)
    ).fetchone()
    return _row_to_prediction(row) if row else None


def overdue(conn: sqlite3.Connection, *, now: datetime | None = None) -> list[Prediction]:
    """Unresolved predictions past their own deadline, oldest first.

    The anti-gaming surface. A Cell that resolves only its winners has a
    beautiful calibration curve and a pile of these behind it.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT * FROM prediction_register
         WHERE resolved_at_utc IS NULL AND resolves_by_utc < ?
         ORDER BY resolves_by_utc
        """,
        (now.astimezone(timezone.utc).isoformat(),),
    ).fetchall()
    return [_row_to_prediction(r) for r in rows]


def scores(conn: sqlite3.Connection, cell_id: str | None = None) -> dict[str, object]:
    """Calibration summary, for one Cell or the whole colony.

    `unresolved` and `overdue` are reported next to the means deliberately: a
    mean Brier score over three cherry-picked resolutions is worse than
    useless, and a consumer that sees only the mean has no way to know.
    """
    where, params = ("WHERE cell_id = ?", (cell_id,)) if cell_id else ("", ())
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN resolved_at_utc IS NOT NULL THEN 1 ELSE 0 END), 0) AS resolved,
          AVG(brier_score) AS mean_brier,
          AVG(log_score) AS mean_log
        FROM prediction_register {where}
        """,
        params,
    ).fetchone()
    now_iso = datetime.now(timezone.utc).isoformat()
    overdue_row = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM prediction_register
        {where + ' AND' if where else 'WHERE'} resolved_at_utc IS NULL AND resolves_by_utc < ?
        """,
        (*params, now_iso),
    ).fetchone()
    return {
        "total": row["total"],
        "resolved": row["resolved"],
        "unresolved": row["total"] - row["resolved"],
        "overdue": overdue_row["n"],
        "mean_brier": row["mean_brier"],
        "mean_log": row["mean_log"],
    }


def calibration(
    conn: sqlite3.Connection, *, cell_id: str | None = None, buckets: int = 10
) -> list[dict[str, object]]:
    """§8.5's calibration curve: predicted probability against observed
    frequency, bucketed.

    A well-calibrated Cell's claims made at p≈0.7 come true about 70% of the
    time. Returned as buckets rather than a single number because the *shape* is
    the diagnosis — systematic overconfidence and systematic underconfidence can
    produce the same mean Brier score and call for opposite corrections.
    """
    where, params = ("AND cell_id = ?", (cell_id,)) if cell_id else ("", ())
    rows = conn.execute(
        f"""
        SELECT probability, outcome FROM prediction_register
         WHERE resolved_at_utc IS NOT NULL {where}
        """,
        params,
    ).fetchall()

    out: list[dict[str, object]] = []
    for index in range(buckets):
        low, high = index / buckets, (index + 1) / buckets
        # Top bucket takes its upper edge so p=1.0-epsilon is not dropped.
        in_bucket = [
            r for r in rows
            if low <= r["probability"] < high or (index == buckets - 1 and r["probability"] == high)
        ]
        if not in_bucket:
            continue
        out.append(
            {
                "bucket_low": low,
                "bucket_high": high,
                "count": len(in_bucket),
                "mean_predicted": sum(r["probability"] for r in in_bucket) / len(in_bucket),
                "observed_frequency": sum(r["outcome"] for r in in_bucket) / len(in_bucket),
            }
        )
    return out


def verify_chain(conn: sqlite3.Connection) -> bool:
    """Recompute the hash chain. False means a registered prediction was altered
    after the fact — the single thing that would make this register worthless."""
    previous: str | None = None
    for row in conn.execute("SELECT * FROM prediction_register ORDER BY rowid"):
        expected = _compute_hash(
            prediction_id=row["prediction_id"],
            cell_id=row["cell_id"],
            experiment_id=row["experiment_id"],
            claim=row["claim"],
            probability=row["probability"],
            resolves_by_utc=row["resolves_by_utc"],
            created_at_utc=row["created_at_utc"],
            idempotency_key=row["idempotency_key"],
            previous_hash=previous,
        )
        if row["previous_hash"] != previous or row["prediction_hash"] != expected:
            return False
        previous = row["prediction_hash"]
    return True
