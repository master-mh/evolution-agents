"""§12.3's beta-binomial stage-conversion posteriors (SPEC.md §12.3, §12.1, §10.5).

Every test is named for the property it defends. The recurring theme is that a
conversion is a **realised fact** — a rung-8 promotion naming a rung-7 one as
the predecessor it expanded — never a read of §25.2's evidence verdict, which
can support an expansion nobody ever asked for.
"""

import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mitosis import (
    approval,
    db,
    deliberation,
    ledger,
    lifecycle,
    models,
    outcome,
    population,
    posteriors,
    prediction,
    promotion,
    providers,
)
from mitosis.models import Book, CellType, EntrySpec

BASE = {
    "market": "independent bookshops",
    "problem": "stock decisions are guesswork",
    "product": "a weekly stock digest",
    "revenue_model": "monthly subscription per shop",
    "acquisition_channel": "trade newsletters",
    "workflow": "ingest sales, rank slow movers, publish",
}


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = db.connect_and_migrate()
    population.set_limits_if_absent(connection, models.DEFAULT_POPULATION_LIMITS)
    ledger.post_transaction(
        connection,
        book=Book.USD_SIM,
        currency="USD",
        transaction_type="external_capital_in",
        idempotency_key="seed",
        description="test seed",
        entries=[
            EntrySpec(account_id="external_capital", amount_minor_units=-1_000_000),
            EntrySpec(account_id="seed_bank", amount_minor_units=1_000_000),
        ],
    )
    promotion.fund_pool(
        connection,
        book=Book.USD_SIM,
        amount_minor_units=100_000,
        funding_account="seed_bank",
        idempotency_key="pool",
    )
    yield connection
    connection.close()


def _cell(conn, tag, **genome_overrides):
    content = {**BASE, **genome_overrides}
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=200,
        book=Book.USD_SIM,
        idempotency_key=f"cell:{tag}",
        genome_content=content,
    )
    # §15.4: a Cell pays for its own thinking.
    for fund_book, currency, amount in (
        (Book.USD_REAL, "USD", 50),
        (Book.RESOURCE, "RESOURCE", 5_000),
    ):
        ledger.post_transaction(
            conn,
            book=fund_book,
            currency=currency,
            transaction_type="cell_funding",
            idempotency_key=f"fund:{tag}:{fund_book.value}",
            description="fund thinking",
            entries=[
                EntrySpec(
                    account_id="seed_bank", amount_minor_units=-amount, cell_id=cell.cell_id
                ),
                EntrySpec(
                    account_id=f"cell:{cell.cell_id}:cash",
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )
    return cell


def _forecast(conn, cell, claim, probability, *, days=30, key=None):
    return prediction.register(
        conn,
        cell_id=cell.cell_id,
        claim=claim,
        probability=probability,
        resolves_by=datetime.now(timezone.utc) + timedelta(days=days),
        idempotency_key=key,
    )


_seen_requests: set = set()


@pytest.fixture(autouse=True)
def _reset_seen():
    _seen_requests.clear()
    yield
    _seen_requests.clear()


def _grant(conn, cell, tag, *, cost=30):
    deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=providers.MockProvider(
            reply=json.dumps(
                {
                    "kind": "spend_request",
                    "summary": f"test request {tag}",
                    "rationale": "exists to produce a promotion",
                    "risk_tier": "MEDIUM",
                    "estimated_cost_minor_units": cost,
                    "predictions": [],
                },
                sort_keys=True,
            )
        ),
        wake_key=f"wake:{tag}",
        model="mock-1",
        proposal_sink=approval.QueueSink(),
    )
    request = next(
        r for r in approval.queue(conn)
        if r.cell_id == cell.cell_id and r.request_id not in _seen_requests
    )
    _seen_requests.add(request.request_id)
    return approval.approve(
        conn, request_id=request.request_id, decided_by="operator", reason="test approval"
    )


def _rung_7(conn, cell, tag):
    """A plain rung-7 promotion with no resolved forecasts — never converts."""
    grant = _grant(conn, cell, f"{tag}-7")
    return promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="rung 7"
    )


def _earned_rung_7(conn, cell, tag):
    """A rung-7 promotion whose §25.2 evidence supports an expansion."""
    sloppy = [_forecast(conn, cell, f"{tag} sloppy {i}", 0.6, key=f"{tag}s{i}") for i in range(3)]
    for item in sloppy:
        prediction.resolve(conn, item.prediction_id, occurred=True, source="test")
    funding_set = [
        _forecast(conn, cell, f"{tag} funded {i}", 0.95, key=f"{tag}f{i}") for i in range(3)
    ]
    grant = _grant(conn, cell, f"{tag}-7")
    record = promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="rung 7"
    )
    for item in funding_set:
        prediction.resolve(conn, item.prediction_id, occurred=True, source="test")
    return record


def _convert(conn, cell, tag):
    grant = _grant(conn, cell, f"{tag}-8")
    return promotion.allocate(
        conn, grant_id=grant.grant_id, allocated_by="operator", reason="expand",
        rung=8, evidence=outcome.AssessmentEvidence(),
    )


def _niche(result: posteriors.Posteriors, label: str) -> posteriors.StageConversionPosterior:
    return next(n for n in result.niches if n.label == label)


# --- the prior, and when it is all there is ------------------------------------


def test_an_empty_niche_gets_the_uninformative_prior(conn):
    """A niche with genomes but no rung-7 promotion still gets a posterior —
    Beta(1, 1), the prior alone — rather than being withheld as unmeasurable.
    §12.3 asks for a distribution to sample from, and an unfunded niche is
    exactly the one Thompson sampling should sometimes explore."""
    _cell(conn, "founder")  # nothing earlier: unbinned, not a niche
    _cell(conn, "second", market="a different market entirely")  # radical

    result = posteriors.posteriors(conn)

    niche = _niche(result, "novelty_distance=radical")
    assert niche.trials == 0
    assert niche.conversions == 0
    assert niche.alpha == posteriors.PRIOR_ALPHA
    assert niche.beta == posteriors.PRIOR_BETA
    assert niche.posterior_mean == 0.5
    assert "uninformative prior" in niche.reason


# --- the realised fact, not the verdict -----------------------------------------


def test_a_realised_conversion_counts_as_success(conn):
    _cell(conn, "founder")
    cell = _cell(conn, "second", market="a different market entirely")
    earned = _earned_rung_7(conn, cell, "s")
    expansion = _convert(conn, cell, "s")
    assert expansion.supersedes_promotion_id == earned.promotion_id

    result = posteriors.posteriors(conn)

    niche = _niche(result, "novelty_distance=radical")
    assert niche.trials == 1
    assert niche.conversions == 1
    assert niche.alpha == posteriors.PRIOR_ALPHA + 1
    assert niche.beta == posteriors.PRIOR_BETA
    assert niche.posterior_mean == pytest.approx(2 / 3)


def test_an_unconverted_rung_7_promotion_is_a_trial_not_a_success(conn):
    _cell(conn, "founder")
    cell = _cell(conn, "second", market="a different market entirely")
    _rung_7(conn, cell, "s")

    result = posteriors.posteriors(conn)

    niche = _niche(result, "novelty_distance=radical")
    assert niche.trials == 1
    assert niche.conversions == 0
    assert niche.posterior_mean == pytest.approx(1 / 3)


def test_supporting_evidence_without_an_actual_conversion_does_not_count(conn):
    """The property this module exists to get right. `outcome.assess` will call
    this promotion's evidence `SUPPORTS_PROMOTION` — that a rung-8 grant would
    be earned if allocated — but nobody has allocated one. §10.5's discipline
    (decide on realised facts, not estimates) means the posterior must not
    move on a verdict nobody acted on."""
    _cell(conn, "founder")
    cell = _cell(conn, "second", market="a different market entirely")
    earned = _earned_rung_7(conn, cell, "s")
    assessment = outcome.assess(conn, earned.promotion_id)
    assert assessment.verdict is outcome.Verdict.SUPPORTS_PROMOTION  # sanity

    result = posteriors.posteriors(conn)

    niche = _niche(result, "novelty_distance=radical")
    assert niche.trials == 1
    assert niche.conversions == 0, (
        "supporting evidence is not a conversion; only an actual rung-8 "
        "promotion naming this one as its predecessor is"
    )


# --- aggregation -----------------------------------------------------------------


def test_niches_aggregate_across_genomes_sharing_a_coordinate(conn):
    """§12.2: the archive groups genomes, not Cells. Two different genomes that
    land in the same niche pool their promotions into one posterior."""
    _cell(conn, "founder")
    winner = _cell(conn, "winner", market="a market nobody else touched")
    loser = _cell(conn, "loser", market="a wholly separate other market")

    _earned_rung_7(conn, winner, "w")
    _convert(conn, winner, "w")
    _rung_7(conn, loser, "l")

    result = posteriors.posteriors(conn)

    niche = _niche(result, "novelty_distance=radical")
    assert niche.trials == 2
    assert niche.conversions == 1
    assert niche.posterior_mean == pytest.approx((posteriors.PRIOR_ALPHA + 1) / (posteriors.PRIOR_ALPHA + posteriors.PRIOR_BETA + 2))


def test_unbinned_genomes_are_counted_separately_not_dropped(conn):
    """A founder genome abstains on every §12.1 dimension and has no niche
    (`Archive.unbinned_genome_hashes`). Its promotions must not silently
    disappear — they are counted alongside the archive, matching the posture
    `Archive` itself takes toward unbinned genomes."""
    founder = _cell(conn, "founder")
    _rung_7(conn, founder, "f")

    result = posteriors.posteriors(conn)

    assert result.niches == ()
    assert result.unbinned_trials == 1
    assert result.unbinned_conversions == 0


# --- structural guarantees --------------------------------------------------------


def test_computing_posteriors_writes_nothing(conn):
    """Derived on every read, stored nowhere (§2.5, §12.2's 'derived view'
    posture, applied one layer up). A `stage_conversion_posteriors` table would
    be a second version of a question the promotions table already answers."""
    _cell(conn, "founder")
    cell = _cell(conn, "second", market="a different market entirely")
    _rung_7(conn, cell, "s")
    before = _fingerprint(conn)

    posteriors.posteriors(conn)

    assert _fingerprint(conn) == before
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {t for t in tables if "posterior" in t}


def test_no_kernel_path_acts_on_a_posterior():
    """A per-niche conversion rate is exactly the "estimated negative EV"
    shape §10.5 forbids acting on without an independent Auditor concurring —
    generalised from one Cell to a niche of them. Nothing may fund, kill, or
    displace on it."""
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    allowed = {"posteriors.py", "cli.py", "golden.py"}
    consumers = sorted(
        path.name for path in source_dir.glob("*.py")
        if path.name not in allowed and "posteriors" in _imported_modules(path)
    )
    assert not consumers, (
        f"{consumers} imports §12.3's posteriors. Nothing may act on a niche's "
        "estimated conversion rate without the human §25.1 and the Auditor §10.5 "
        "both put in the loop"
    )
    for forbidden, why in (
        ("death.py", "§10.5 forbids culling on an estimate without a concurring Auditor"),
        ("promotion.py", "an allocation that reads its own posterior funds itself"),
        ("displacement.py", "§10.5's discipline applies to a birth exactly as it does a death"),
        ("scheduler.py", "a posterior that fires on a timer is a decision without a human"),
    ):
        assert "posteriors" not in _imported_modules(source_dir / forbidden), (
            f"{forbidden} must never reach §12.3's posteriors: {why}"
        )


def test_the_posterior_never_reaches_a_cell():
    """§23.5: the review path is part of the environment and will be optimised
    against. A Cell told which niche the colony favours learns to describe
    itself into that niche rather than to be novel."""
    source_dir = Path(__file__).resolve().parents[1] / "src" / "mitosis"
    for module in ("context.py", "deliberation.py"):
        assert "posteriors" not in _imported_modules(source_dir / module), (
            f"{module} can reach §12.3's posteriors; a Cell that learns which "
            "niche is favoured learns to perform it (§23.5)"
        )


def test_sample_draws_from_the_posteriors_own_beta_distribution():
    """A skewed posterior (mean far from 0.5) whose many draws' own mean
    converges close to `posterior_mean` -- proof `sample()` actually draws
    from `(alpha, beta)`, not some unrelated or swapped pair."""
    import random

    posterior = posteriors.StageConversionPosterior(
        coordinate=(("novelty_distance", "radical"),), trials=100, conversions=80,
        alpha=81.0, beta=21.0, posterior_mean=81.0 / 102.0, reason="test fixture",
    )
    rng = random.Random(0)
    draws = [posteriors.sample(posterior, rng=rng) for _ in range(5000)]
    assert sum(draws) / len(draws) == pytest.approx(posterior.posterior_mean, abs=0.02)


def test_sample_is_deterministic_given_the_same_rng_state():
    import random

    posterior = posteriors.StageConversionPosterior(
        coordinate=(), trials=10, conversions=3, alpha=4.0, beta=8.0,
        posterior_mean=4.0 / 12.0, reason="test fixture",
    )
    first = posteriors.sample(posterior, rng=random.Random(42))
    second = posteriors.sample(posterior, rng=random.Random(42))
    assert first == second


def test_sample_uses_the_injected_rng_not_a_hidden_global_source():
    """Two different seeds must be able to produce different draws -- if
    `sample()` silently ignored `rng` and drew from the module-global
    `random` instead, this would still pass by accident some of the time,
    which is exactly why the previous test's determinism check matters too:
    together they pin both that the draw is seeded and that it is seeded by
    the caller's own `rng`."""
    import random

    posterior = posteriors.StageConversionPosterior(
        coordinate=(), trials=10, conversions=3, alpha=4.0, beta=8.0,
        posterior_mean=4.0 / 12.0, reason="test fixture",
    )
    draws = {posteriors.sample(posterior, rng=random.Random(seed)) for seed in range(10)}
    assert len(draws) > 1


def _fingerprint(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def _imported_modules(path: Path) -> set[str]:
    """Module names `path` imports, function-local ones included."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.update(node.module.split("."))
            if node.level:
                imported.update(alias.name for alias in node.names)
    return imported
