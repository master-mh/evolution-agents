"""§12.3's Thompson-sampling target: beta-binomial stage-conversion posteriors,
one per §12 niche (SPEC.md §12.3, §12.1, §12.2, §10.5, §2.5; ADR-063, ADR-064).

    Within each niche maintain posteriors for `P(next stage)`, expected net
    value if successful, expected time to stage conversion, probability of
    reproducibility, and probability of large loss. **First implementation may
    use beta-binomial stage-conversion posteriors**; schemas must allow
    hierarchical/non-stationary models later.

**This module builds exactly the sentence the clause permits as a first
implementation, and no more.** `P(next stage)` is a beta-binomial posterior
over one realised event per niche: did a rung-7 "tiny capped live experiment"
convert into a rung-8 "expanded pilot" (§25.1, ADR-063)? The other four —
expected net value, expected time to conversion, probability of
reproducibility, probability of large loss — need machinery this colony does
not have yet (§11.2's adoption record for reproducibility; a liability model
for large loss; a survival-style time-to-event model for the second). Logged
in FUTURE_BUILD_HOOKS rather than approximated.

## Why this is a realised-facts count, not a read of §25.2's verdict

`outcome.assess` already computes a verdict for a rung-7 promotion —
`SUPPORTS_PROMOTION` — and it is *tempting* to count that as the Bernoulli
trial. It is the wrong signal here. `outcome.py`'s verdict answers "does this
promotion's own evidence currently support an expansion", which is a live
judgment that can flip as forecasts resolve and that an operator can simply
decline to act on. §10.5's discipline — decide on *realised* facts, not
estimates — generalises: a niche's stage-conversion rate is about whether a
Cell actually **climbed** the ladder, not about whether the kernel currently
thinks it could. FUTURE_BUILD_HOOKS said it plainly before this module
existed: "Every one of them needs stage-*conversion* events — Cells moving
between §25.1 rungs — and `promotion.allocate` only ever issued rung 7, so the
colony has produced no conversions at all." ADR-063 is what makes a
conversion representable; this module is what counts it.

The realised fact is `promotions.supersedes_promotion_id`: a rung-7 promotion
converted if and only if some rung-8 promotion names it as the predecessor it
expanded. Migration 0030's unique partial index guarantees at most one such
rung-8 row per rung-7 promotion, so "converted" is unambiguous.

## The niche is the coordinate, not the Cell

§12.3 asks for a posterior "within each niche", and `novelty.archive` already
answers what a niche is — a group of *genomes* sharing a measured §12.1
coordinate (§12.2: the archive is a derived view). A rung-7 promotion is
attributed to the niche of the Cell's genome at the moment of the query, the
same posture `novelty.archive` takes toward `living_cells`. Genomes that
abstain on every §12.1 dimension have no niche; their promotions are counted
separately (`unbinned_trials`/`unbinned_conversions`) rather than silently
dropped, matching `Archive.unbinned_genome_hashes`.

## The prior, and why an empty niche still gets a defined posterior

`PRIOR_ALPHA = PRIOR_BETA = 1.0` — the uniform Beta(1, 1) — is a choice, not a
law, exactly as `novelty.DESCRIPTOR_SENSE` says of its own bins. It is *not*
the abstain-on-no-data posture the rest of this codebase takes toward a
dimension with no formula (§13.2's `economic_potential`, §12.1's `buyer_type`
with no attestation): those dimensions have no computation to fall back on
without data. A beta-binomial posterior does — Beta(1, 1) is itself the
answer at zero trials, and reporting it (rather than withholding a "measured"
verdict) is the entire reason a Bayesian posterior is the tool §12.3 asked
for: an empty niche is exactly the one Thompson sampling should sometimes
explore, and it can only be drawn from if it has a distribution.

## No table, and no future migration to write

**Derived on every read, stored nowhere** — the same posture `novelty.py` and
`selection.py` take toward §2.5's "balances are derived" and §12.2's "the
archive is a derived view". This is also §12.3's own future-proofing clause
answered for free: "schemas must allow hierarchical/non-stationary models
later" is trivially true of a module that owns no schema. A richer model
later is a different function body, not a migration.

## What this deliberately does not do

**No elite per niche and no ranking of niches.** §12.4 exists because a
high-dimensional archive stays nearly empty at realistic population sizes,
not because a niche needs a champion. This module reports a posterior per
niche; nothing here compares one niche's posterior to another's or decides
what to fund next. That decision — which niches to send the colony's
attention toward — is the Thompson-sampling *policy* §12.3 names in its
title, and it is deliberately absent: sampling from these distributions to
choose is a consumer this module does not have yet, the same gap `selection.py`
left between "a frontier" and "an allocation decision".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import novelty
from .promotion import LADDER_RUNG_CAPPED_LIVE_EXPERIMENT

#: The uniform prior. Beta(1, 1) assigns no niche an advantage before any
#: evidence exists — see the module docstring for why an empty niche still
#: gets a defined (and explorable) posterior rather than an abstention.
PRIOR_ALPHA: float = 1.0
PRIOR_BETA: float = 1.0


@dataclass(frozen=True)
class StageConversionPosterior:
    """§12.3's `P(next stage)` for one §12 niche: a beta-binomial posterior
    over rung-7 promotions converting to rung 8.

    `trials` and `conversions` are the realised counts the posterior was
    built from; `alpha`/`beta` are the full distribution (what a Thompson
    sample would draw from); `posterior_mean` is the one number §12.3 names.
    """

    coordinate: tuple[tuple[str, str], ...]
    trials: int
    conversions: int
    alpha: float
    beta: float
    posterior_mean: float
    reason: str

    @property
    def label(self) -> str:
        return "/".join(f"{k}={v}" for k, v in self.coordinate) or "(unbinned)"


@dataclass(frozen=True)
class Posteriors:
    """§12.3 over the whole archive."""

    niches: tuple[StageConversionPosterior, ...]
    unbinned_trials: int
    unbinned_conversions: int


def _rung_7_outcomes(conn: sqlite3.Connection) -> list[tuple[str, bool]]:
    """Every rung-7 promotion ever issued, as `(genome_hash, converted)`.

    `converted` is `True` iff some rung-8 promotion names this one as the
    predecessor it expanded (`supersedes_promotion_id`) — the realised fact
    ADR-063 made representable. A Cell's current status is irrelevant: a
    conversion (or its absence) is a historical fact about the niche, not a
    claim about the Cell today.
    """
    rows = conn.execute(
        """
        SELECT c.genome_hash AS genome_hash,
               EXISTS(
                   SELECT 1 FROM promotions x
                    WHERE x.supersedes_promotion_id = p.promotion_id
               ) AS converted
          FROM promotions p
          JOIN cells c ON c.cell_id = p.cell_id
         WHERE p.rung = ?
         ORDER BY p.rowid
        """,
        (LADDER_RUNG_CAPPED_LIVE_EXPERIMENT,),
    ).fetchall()
    return [(row["genome_hash"], bool(row["converted"])) for row in rows]


def _posterior(*, trials: int, conversions: int) -> tuple[float, float, float]:
    alpha = PRIOR_ALPHA + conversions
    beta = PRIOR_BETA + (trials - conversions)
    return alpha, beta, alpha / (alpha + beta)


def posteriors(conn: sqlite3.Connection) -> Posteriors:
    """§12.3's beta-binomial `P(next stage)`, one posterior per niche.

    Composes `novelty.archive` for the coordinates (§12.2: the archive is
    derived, never stored) with the realised rung-7/rung-8 record. A niche
    with genomes but no rung-7 promotion yet still gets a posterior — the
    uninformative prior — rather than being reported as unevaluable; see the
    module docstring on why that is the correct behaviour for a Thompson
    sampling target rather than a widening of what this kernel is willing to
    claim it measured.
    """
    archive = novelty.archive(conn)
    outcomes = _rung_7_outcomes(conn)

    by_genome: dict[str, list[bool]] = {}
    for genome_hash, converted in outcomes:
        by_genome.setdefault(genome_hash, []).append(converted)

    niches = []
    for niche in archive.niches:
        results = [c for h in niche.genome_hashes for c in by_genome.get(h, ())]
        trials = len(results)
        conversions = sum(results)
        alpha, beta, mean = _posterior(trials=trials, conversions=conversions)
        reason = (
            f"{conversions} of {trials} rung-7 promotion(s) in this niche converted "
            "to rung 8"
            if trials
            else "no rung-7 promotion has been issued to a Cell in this niche yet; "
            "the posterior is the uninformative prior"
        )
        niches.append(
            StageConversionPosterior(
                coordinate=niche.coordinate,
                trials=trials,
                conversions=conversions,
                alpha=alpha,
                beta=beta,
                posterior_mean=mean,
                reason=reason,
            )
        )

    unbinned = {
        genome_hash: results
        for genome_hash, results in by_genome.items()
        if genome_hash in set(archive.unbinned_genome_hashes)
    }
    unbinned_results = [c for results in unbinned.values() for c in results]

    return Posteriors(
        niches=tuple(niches),
        unbinned_trials=len(unbinned_results),
        unbinned_conversions=sum(unbinned_results),
    )
