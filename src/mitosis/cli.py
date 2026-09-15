"""MITOSIS CLI (SPEC.md §30).

argparse (stdlib) rather than a CLI framework, per §30.1 "avoid unnecessary
frameworks". Money commands take --book, defaulting to USD_SIM (Amendment
A7). Decimal strings are parsed via money.parse_minor_units, or
pricing.parse_micro_usd where cents are too coarse (an invoice line) —
never binary float (§30 dollar-string rule).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (
    approval,
    auditor,
    autopromotion,
    channel_registry,
    clock,
    content_audit,
    context,
    counterparty,
    db,
    death,
    deliberation,
    displacement,
    events,
    experiment_grants,
    experiments,
    external_actions,
    gateway,
    genome,
    golden,
    ids,
    ledger,
    lifecycle,
    lineage,
    money,
    outcome,
    population,
    prediction,
    pricing,
    promotion,
    providers,
    real_spend_breaker,
    reconciliation,
    reservations,
    resource_metering,
    novelty,
    posteriors,
    rights,
    selection,
    artifacts as artifacts_module,
    revenue,
    tool_registry,
    tools,
    scheduler,
    sweeper,
)
from .simulation import batch as simulation_batch
from .simulation import environment as simulation_environment
from .simulation import paired as simulation_paired
from .simulation import runner as simulation_runner
from .simulation import selection_policy as simulation_selection_policy
from .accounts import cell_cash
from .models import (
    DEFAULT_POPULATION_LIMITS,
    DEFAULT_REAL_SPEND_LIMITS,
    Book,
    CellType,
    ClockMode,
    EntrySpec,
    PopulationLimits,
    RealSpendLimits,
)

DEFAULT_DB_PATH = os.environ.get("MITOSIS_DB", "mitosis.db")


class CliError(Exception):
    pass


def _require_existing_db(path: str) -> None:
    if not Path(path).exists():
        raise CliError(f"no MITOSIS database found at {path!r} — run `mitosis init` first")


def _require_experiment(conn, experiment_id: str | None) -> str | None:
    """An operator-supplied `--experiment` must name one that exists.

    Migration 0026's own comment complained that "`mitosis predict --experiment
    <id>` has always accepted any string and validated nothing", and creating
    the table did not by itself change that — nothing joined the two. A typo
    here does not fail; it silently detaches the prediction or the revenue from
    every report that would have counted it, and §2.6's report then shows a
    smaller number with nothing anywhere saying why (ADR-044).

    Existence only. A *concluded* experiment is still a legitimate target:
    revenue lands after the work ends, and refusing it would push the operator
    toward attaching the money to nothing at all.
    """
    if experiment_id is None:
        return None
    if experiments.get(conn, experiment_id) is None:
        raise CliError(
            f"no such experiment: {experiment_id!r} — `mitosis experiments` lists them"
        )
    return experiment_id


def cmd_init(args: argparse.Namespace) -> None:
    path = args.db
    already_existed = Path(path).exists()
    conn = db.connect(path)
    applied = db.migrate(conn)

    if args.seed_capital is not None:
        book = Book(args.book)
        amount = money.parse_minor_units(args.seed_capital, book.value)
        ledger.post_transaction(
            conn,
            book=book,
            currency="USD" if book != Book.RESOURCE else "RESOURCE",
            transaction_type="colony_seed_capital",
            idempotency_key=f"init_seed_capital:{book.value}",
            description=f"seed capital into {args.seed_account}",
            entries=[
                EntrySpec(account_id="external_capital", amount_minor_units=-amount),
                EntrySpec(account_id=args.seed_account, amount_minor_units=amount),
            ],
        )
        print(f"Seeded {args.seed_capital} {book.value} into {args.seed_account}")

    requested_limits = PopulationLimits(
        max_living_cells=args.max_living_cells,
        max_active_cells=args.max_active_cells,
        max_parallel_experiments=DEFAULT_POPULATION_LIMITS.max_parallel_experiments,
        max_births_per_epoch=DEFAULT_POPULATION_LIMITS.max_births_per_epoch,
        max_lineage_population_fraction=DEFAULT_POPULATION_LIMITS.max_lineage_population_fraction,
    )
    active_limits = population.set_limits_if_absent(conn, requested_limits)
    if already_existed and active_limits != requested_limits:
        print(
            f"Population limits already configured (living={active_limits.max_living_cells}, "
            f"active={active_limits.max_active_cells}) — not changed"
        )
    else:
        print(
            f"Population limits: max_living_cells={active_limits.max_living_cells}, "
            f"max_active_cells={active_limits.max_active_cells}"
        )

    baseline_spend_limits = real_spend_breaker.configure_if_absent(conn)
    spend_flag_names = (
        "per_request_cents",
        "per_hour_cents",
        "per_day_cents",
        "per_month_cents",
        "max_concurrent_reserved_cents",
    )
    if any(getattr(args, name) is not None for name in spend_flag_names):
        updated_spend_limits = RealSpendLimits(
            per_request_minor_units=args.per_request_cents
            if args.per_request_cents is not None
            else baseline_spend_limits.per_request_minor_units,
            per_hour_minor_units=args.per_hour_cents
            if args.per_hour_cents is not None
            else baseline_spend_limits.per_hour_minor_units,
            per_day_minor_units=args.per_day_cents
            if args.per_day_cents is not None
            else baseline_spend_limits.per_day_minor_units,
            per_month_minor_units=args.per_month_cents
            if args.per_month_cents is not None
            else baseline_spend_limits.per_month_minor_units,
            max_concurrent_reserved_minor_units=args.max_concurrent_reserved_cents
            if args.max_concurrent_reserved_cents is not None
            else baseline_spend_limits.max_concurrent_reserved_minor_units,
            provider_limits=baseline_spend_limits.provider_limits,
        )
        active_spend_limits = real_spend_breaker.set_limits(conn, updated_spend_limits)
        print(
            f"Real-spend limits (USD_REAL cents) updated: per_request={active_spend_limits.per_request_minor_units}, "
            f"per_hour={active_spend_limits.per_hour_minor_units}, per_day={active_spend_limits.per_day_minor_units}, "
            f"per_month={active_spend_limits.per_month_minor_units}, "
            f"max_concurrent_reserved={active_spend_limits.max_concurrent_reserved_minor_units}"
        )
    else:
        print(
            f"Real-spend limits (USD_REAL cents): per_request={baseline_spend_limits.per_request_minor_units}, "
            f"per_hour={baseline_spend_limits.per_hour_minor_units}, per_day={baseline_spend_limits.per_day_minor_units}, "
            f"per_month={baseline_spend_limits.per_month_minor_units}, "
            f"max_concurrent_reserved={baseline_spend_limits.max_concurrent_reserved_minor_units}"
        )

    requested_mode = ClockMode(args.clock_mode)
    baseline_clock = clock.initialize_if_absent(
        conn, mode=requested_mode, simulated_seconds_per_wall_second=args.clock_rate
    )
    if already_existed and (
        baseline_clock.mode != requested_mode
        or baseline_clock.simulated_seconds_per_wall_second != args.clock_rate
    ):
        print(
            f"Simulated clock already configured (mode={baseline_clock.mode.value}, "
            f"rate={baseline_clock.simulated_seconds_per_wall_second}) — not changed"
        )
    else:
        print(
            f"Simulated clock: mode={baseline_clock.mode.value}, "
            f"rate={baseline_clock.simulated_seconds_per_wall_second} sim-sec/wall-sec, "
            f"at {baseline_clock.checkpoint_simulated_at_utc.isoformat()}"
        )

    scheduler.configure_epochs_if_absent(conn, duration_seconds=args.epoch_seconds)
    operator = scheduler.initialize_operator_if_absent(conn)
    conn.commit()
    genesis, epoch_seconds = scheduler.epoch_settings(conn)
    print(
        f"Epochs: {epoch_seconds}s of simulated time each, genesis "
        f"{genesis.isoformat()} (currently epoch {scheduler.current_epoch(conn)})"
    )
    print(
        f"Operator (§23.3): real_spending={'on' if operator.real_spending_enabled else 'off'}, "
        f"vacation_pause_after={operator.vacation_pause_after_seconds}s, "
        f"metabolic_alarm={operator.metabolic_alarm_cents_per_epoch} cents/epoch, "
        f"acceleration_factor={operator.metabolic_acceleration_factor}x"
    )

    if already_existed:
        print(f"MITOSIS database already existed at {path}")
    else:
        print(f"Initialized MITOSIS database at {path}")
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Schema already up to date")
    conn.close()


def cmd_status(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    migration_count = conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"]

    print(f"MITOSIS colony status — {args.db}")
    print(f"  migrations applied: {migration_count}")
    print()
    print("  ledger:")
    for book in Book:
        txn_count = conn.execute(
            "SELECT COUNT(*) AS n FROM ledger_transactions WHERE book = ?", (book.value,)
        ).fetchone()["n"]
        if txn_count == 0:
            continue
        conserved = ledger.verify_conservation(conn, book)
        print(f"    {book.value}: {txn_count} transactions, conservation={'OK' if conserved else 'FAILED'}")
    print(f"    hash chain valid: {ledger.verify_chain(conn)}")
    print()
    print("  cells:")
    limits = population.get_limits(conn)
    living, active = population.living_count(conn), population.active_count(conn)
    print(f"    living: {living}/{limits.max_living_cells}   active: {active}/{limits.max_active_cells}")
    by_status = lifecycle.count_by_status(conn)
    by_type = lifecycle.count_by_type(conn)
    if by_status:
        print(f"    by status: {by_status}")
        print(f"    by type:   {by_type}")
        print(f"    coroner reports filed: {lifecycle.count_coroner_reports(conn)}")
    else:
        print("    none yet")
    print()
    print("  lineage (SPEC.md §9.4, founder-effect control):")
    summary = lineage.lineage_summary(conn)
    if summary:
        print(
            f"    lineages: {len(summary)}   "
            f"max share: {summary[0]['fraction']:.2f}/{limits.max_lineage_population_fraction}"
        )
        for entry in summary[:5]:
            # A NULL founder is unreachable through the kernel, but a
            # corrupted or hand-edited DB shouldn't produce a traceback —
            # the integrity line just below is what flags it.
            founder = (entry["founder_cell_id"] or "<none>")[:8]
            print(
                f"    {founder}: {entry['living']} living "
                f"({entry['fraction']:.2f}), {entry['total']} total, "
                f"depth {entry['max_generation']}"
            )
        if len(summary) > 5:
            print(f"    ... and {len(summary) - 5} more")
        print(f"    integrity: {lineage.verify_lineage_integrity(conn)}")
    else:
        print("    none yet")
    print()
    print("  reservations:")
    r_by_status = reservations.count_by_status(conn)
    print(f"    by status: {r_by_status}" if r_by_status else "    none yet")
    print()
    print("  resource usage (RESOURCE book, Amendment A6):")
    usage_totals = resource_metering.total_quantity_by_type(conn)
    if usage_totals:
        print(f"    by type: {usage_totals}")
        print(f"    linkage complete: {resource_metering.verify_linkage(conn)}")
    else:
        print("    none yet")
    print()
    print("  real-spend breaker (USD_REAL):")
    snap = real_spend_breaker.snapshot(conn)
    print(
        f"    concurrent reserved: {snap.concurrent_reserved_minor_units}/"
        f"{snap.limits.max_concurrent_reserved_minor_units}"
    )
    print(f"    spend last hour:  {snap.spend_last_hour_minor_units}/{snap.limits.per_hour_minor_units}")
    print(f"    spend last day:   {snap.spend_last_day_minor_units}/{snap.limits.per_day_minor_units}")
    print(f"    spend last ~30d:  {snap.spend_last_month_minor_units}/{snap.limits.per_month_minor_units}")
    print()
    print("  simulated clock:")
    clock_state = clock.get_state(conn)
    print(
        f"    mode: {clock_state.mode.value}   rate: {clock_state.simulated_seconds_per_wall_second} sim-sec/wall-sec"
    )
    print(f"    current simulated time: {clock.now(conn).isoformat()}")
    print()
    print("  events:")
    e_by_status = events.count_by_status(conn)
    print(f"    inbox by status: {e_by_status}" if e_by_status else "    inbox: none yet")
    print(f"    outbox unpublished: {events.outbox_unpublished_count(conn)}")
    print()
    print(f"  model gateway (pricing table {pricing.PRICING_TABLE_VERSION}):")
    by_provider = gateway.spend_by_provider(conn)
    if not by_provider:
        print("    no calls yet")
    else:
        mc_by_status = gateway.count_by_status(conn)
        print(f"    calls by status: {mc_by_status}")
        for name, stats in by_provider.items():
            cap = snap.limits.provider_limits.get(name)
            cap_text = (
                f"   cap: {real_spend_breaker.provider_exposure(conn, name)}/{cap}"
                if cap is not None
                else "   cap: unset"
            )
            print(
                f"    {name}: {stats['calls']} calls   "
                f"{stats['input_tokens']} in / {stats['output_tokens']} out tokens   "
                f"{stats['micro_usd']} micro-USD   "
                f"settled {money.format_minor_units(stats['settled_minor_units'], 'USD_REAL')} USD_REAL"
                f"{cap_text}"
            )

    conn.close()


def _print_displacement(conn, cell_id: str) -> None:
    """Report any Cell this birth displaced, read back from the audit trail —
    which is where §9.3 requires it to be recorded, so printing it from
    anywhere else would be reporting something the colony didn't durably say."""
    row = conn.execute(
        "SELECT metadata_json FROM audit_events WHERE cell_id = ? "
        "AND event_type = 'cell_lifecycle_transition' ORDER BY rowid LIMIT 1",
        (cell_id,),
    ).fetchone()
    if row is None:
        return
    metadata = json.loads(row["metadata_json"] or "{}")
    displaced = metadata.get("displaced_cell_id")
    if not displaced:
        return
    print(f"  displaced: {displaced} (SPEC.md §9.3)")
    print(f"    it was already failing: {metadata.get('displaced_criterion')}")
    for key, value in sorted((metadata.get("displaced_evidence") or {}).items()):
        print(f"      {key}: {value}")


def cmd_create_cell(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    book = Book(args.book)
    budget_minor_units = money.parse_minor_units(args.budget, book.value)
    cell_type = CellType(args.type)
    idempotency_key = args.idempotency_key or f"cli_create_cell:{ids.new_id()}"

    genome_content = _parse_genome_content(args.genome)

    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=budget_minor_units,
        book=book,
        idempotency_key=idempotency_key,
        funding_account_id=args.funding_account,
        displacer=displacement.ObjectiveDisplacer() if args.displace else None,
        genome_content=genome_content,
    )

    print(f"Created cell {cell.cell_id}")
    print(f"  type:   {cell.cell_type.value}")
    print(f"  status: {cell.status.value}")
    print(f"  book:   {cell.book.value}")
    print(f"  budget: {args.budget} ({budget_minor_units} minor units)")
    print(f"  genome: {cell.genome_hash}")
    if genome_content:
        print("  genome content (§16.2):")
        for field in sorted(genome_content):
            print(f"    {field}: {json.dumps(genome_content[field])}")
    else:
        print("  (no genome content — this Cell can only reason about its own books)")
    _print_displacement(conn, cell.cell_id)

    conn.close()


def _parse_genome_content(raw: str | None) -> dict | None:
    """`--genome` takes inline JSON or a path to a JSON file.

    A file is the expected form: §16.2's fields are prose hypotheses about a
    market, and shell-quoting a paragraph is how a seed genome ends up
    truncated. The value is treated as a path when it names an existing file,
    and as literal JSON otherwise, so the two never need distinguishing flags.
    """
    if raw is None:
        return None
    candidate = Path(raw)
    try:
        source = candidate.read_text() if candidate.is_file() else raw
    except OSError as exc:
        raise CliError(f"could not read --genome file {raw!r}: {exc}") from exc
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError as exc:
        raise CliError(f"--genome must be valid JSON (or a path to it): {exc}") from exc
    if not isinstance(parsed, dict):
        raise CliError(f"--genome must be a JSON object, got {type(parsed).__name__}")
    return parsed


def cmd_reproduce(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    parent = lifecycle.get_cell(conn, args.parent)
    if parent is None:
        raise CliError(f"unknown parent cell: {args.parent}")

    budget_minor_units = money.parse_minor_units(args.budget, parent.book.value)
    idempotency_key = args.idempotency_key or f"cli_reproduce:{ids.new_id()}"
    mutation = None
    if args.mutation:
        try:
            mutation = json.loads(args.mutation)
        except json.JSONDecodeError as exc:
            raise CliError(f"--mutation must be valid JSON: {exc}") from exc

    child = lineage.reproduce(
        conn,
        parent_cell_id=parent.cell_id,
        budget_minor_units=budget_minor_units,
        idempotency_key=idempotency_key,
        cell_type=CellType(args.type) if args.type else None,
        mutation=mutation,
        mutation_operator=args.mutation_operator,
        displacer=displacement.ObjectiveDisplacer() if args.displace else None,
    )

    print(f"Cell {parent.cell_id} reproduced -> {child.cell_id}")
    print(f"  type:       {child.cell_type.value}")
    print(f"  generation: {child.generation}")
    print(f"  founder:    {child.founder_cell_id}")
    print(f"  book:       {child.book.value}")
    print(f"  budget:     {args.budget} ({budget_minor_units} minor units, from parent's cash)")
    print(f"  genome:     {child.genome_hash}")
    if mutation:
        print("  (mutated genome — distinct from parent's)")
    else:
        print("  (unmutated — shares the parent's genome, per content addressing)")
    _print_displacement(conn, child.cell_id)

    conn.close()


def cmd_reap(args: argparse.Namespace) -> None:
    """Kill Cells meeting an objective §10.5 death criterion.

    Dry-run by default. A death is irreversible — a coroner report is filed and
    Charter C8 makes the Cell permanently inert — so ending Cells requires
    saying so explicitly.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    found = death.reap(conn, dry_run=not args.execute)
    if not found:
        print("No Cell meets an objective death criterion (SPEC.md §10.5).")
        print("Losing money is not a criterion; having none left is.")
        return

    verb = "Killed" if args.execute else "Would kill"
    print(f"{verb} {len(found)} Cell(s):")
    for finding in found:
        print(f"  {finding.cell_id}")
        print(f"    criterion: {finding.criterion.value}")
        for key, value in sorted(finding.evidence.items()):
            print(f"      {key}: {value}")
    if not args.execute:
        print("\nDry run — nothing was killed. Re-run with --execute to act.")


def cmd_displacement_candidates(args: argparse.Namespace) -> None:
    """Which Cells a birth could displace right now (§9.3). Read-only — this
    is the look-before-you-evict command, the same posture `reap` takes by
    defaulting to a dry run."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    found = displacement.candidates(
        conn,
        require_active=args.require_active,
        exclude=frozenset({args.exclude}) if args.exclude else frozenset(),
    )
    if not found:
        print("No Cell may currently be displaced (SPEC.md §9.3).")
        print("A birth at capacity would wait, not evict.")
        return

    print(f"{len(found)} Cell(s) could be displaced, in the order they would be taken:")
    for index, (cell, finding) in enumerate(found, start=1):
        print(f"  {index}. {cell.cell_id} ({cell.cell_type.value}, {cell.status.value})")
        print(f"     criterion: {finding.criterion.value}")
        for key, value in sorted(finding.evidence.items()):
            print(f"       {key}: {value}")
    print("\nOrder is birth order, not a ranking — §10.2 forbids collapsing")
    print("fitness into one scalar, and 'pick the worst' would be exactly that.")
    print("At most one Cell is displaced per birth.")

    conn.close()


def cmd_cell_fitness(args: argparse.Namespace) -> None:
    """A Cell's realised record. Not a score — §10.2 forbids collapsing the
    dimensions into one, so they are printed side by side."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    cell = lifecycle.get_cell(conn, args.cell)
    if cell is None:
        raise CliError(f"unknown cell: {args.cell}")

    record = death.contribution(conn, cell)
    print(f"Cell {cell.cell_id} ({cell.cell_type.value}, {cell.status.value})")
    print(f"  book:              {cell.book.value}")
    print(f"  revenue:           {record.revenue_minor_units} minor units")
    taken_back = revenue.reversed_revenue(conn, cell.cell_id, cell.book)
    if taken_back:
        # Net above, because domination reads net (ADR-097); what was received
        # and what was taken back are printed beside it so a refund reads as a
        # refund rather than as a smaller sale.
        print(f"    received {revenue.gross_revenue(conn, cell.cell_id, cell.book)}, "
              f"refunded or charged back {taken_back}")
    print(f"  spend:             {record.spend_minor_units} minor units")
    print(f"  net contribution:  {record.net_contribution} minor units")
    if record.mean_brier is None:
        print(f"  calibration:       no resolved predictions "
              f"({record.unresolved_predictions} outstanding)")
    else:
        print(f"  calibration:       mean Brier {record.mean_brier:.4f} "
              f"over {record.resolved_predictions} resolved "
              f"({record.unresolved_predictions} outstanding)")

    found = death.findings(conn, cell.cell_id)
    if found:
        print("\n  meets objective death criteria (§10.5):")
        for finding in found:
            print(f"    {finding.describe()}")
    else:
        print("\n  meets no objective death criterion")


def cmd_predict(args: argparse.Namespace) -> None:
    """Register a prediction before its outcome is known (SPEC.md §8.5)."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    resolves_by = datetime.now(timezone.utc) + timedelta(days=args.resolves_in_days)
    try:
        record = prediction.register(
            conn,
            cell_id=args.cell,
            claim=args.claim,
            probability=args.probability,
            resolves_by=resolves_by,
            experiment_id=_require_experiment(conn, args.experiment),
            idempotency_key=args.idempotency_key,
        )
    except prediction.PredictionError as exc:
        raise CliError(str(exc)) from exc

    print(f"Registered prediction {record.prediction_id}")
    print(f"  cell:        {record.cell_id}")
    print(f"  claim:       {record.claim}")
    print(f"  probability: {record.probability}")
    print(f"  resolves by: {record.resolves_by_utc.isoformat()}")
    print(f"  hash:        {record.prediction_hash}")


def cmd_resolve_prediction(args: argparse.Namespace) -> None:
    """Record what actually happened, and score it."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        record = prediction.resolve(
            conn, args.prediction, occurred=args.occurred, source=args.source
        )
    except prediction.PredictionError as exc:
        raise CliError(str(exc)) from exc

    print(f"Resolved prediction {record.prediction_id}")
    print(f"  claim:       {record.claim}")
    print(f"  predicted:   {record.probability}")
    print(f"  outcome:     {'occurred' if record.outcome else 'did not occur'}")
    print(f"  brier score: {record.brier_score:.4f}  (0 perfect, 0.25 = always guessing 0.5)")
    print(f"  log score:   {record.log_score:.4f}   (lower is better)")


def cmd_calibration(args: argparse.Namespace) -> None:
    """§8.5's reality gap as a calibration curve rather than a vibe."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    stats = prediction.scores(conn, args.cell)
    scope = f"cell {args.cell}" if args.cell else "colony-wide"
    print(f"Prediction calibration — {scope}")
    print(f"  registered: {stats['total']}   resolved: {stats['resolved']}   "
          f"unresolved: {stats['unresolved']}   overdue: {stats['overdue']}")
    if stats["mean_brier"] is None:
        print("  no resolved predictions yet — nothing to score")
    else:
        print(f"  mean Brier: {stats['mean_brier']:.4f}   mean log: {stats['mean_log']:.4f}")

    if stats["overdue"]:
        print(f"\n  WARNING: {stats['overdue']} prediction(s) past their deadline and unresolved.")
        print("  A calibration curve built only from resolved predictions is self-selected;")
        print("  treat the scores above as unreliable until these are resolved.")

    curve = prediction.calibration(conn, cell_id=args.cell, buckets=args.buckets)
    if curve:
        print("\n  predicted -> observed:")
        for bucket in curve:
            print(
                f"    {bucket['bucket_low']:.1f}–{bucket['bucket_high']:.1f}: "
                f"predicted {bucket['mean_predicted']:.2f}, "
                f"observed {bucket['observed_frequency']:.2f}  (n={bucket['count']})"
            )

    print(f"\n  register hash chain valid: {prediction.verify_chain(conn)}")


def cmd_record_revenue(args: argparse.Namespace) -> None:
    """Credit a Cell with money it earned.

    The counterpart to `call-model`: that verb is the only one that can spend
    real money, this is the only one that can bring it in. Together they are
    what makes a Cell's profitability a measurable number rather than an
    aspiration.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    book = Book(args.book)
    amount = money.parse_minor_units(args.amount, book.value)
    try:
        transaction = revenue.record_revenue(
            conn,
            cell_id=args.cell,
            amount_minor_units=amount,
            source=args.source,
            book=book,
            note=args.note,
            artifact_id=args.artifact,
            experiment_id=_require_experiment(conn, args.experiment),
            counterparty=args.counterparty,
            idempotency_key=args.idempotency_key,
        )
    except revenue.RevenueError as exc:
        raise CliError(str(exc)) from exc

    earned = revenue.net_revenue(conn, args.cell, book)
    print(f"Recorded revenue for cell {args.cell}")
    print(f"  amount:    {args.amount} ({amount} minor units) {book.value}")
    print(f"  source:    {args.source}")
    # Whether, never who. Printing the digest would put a linkable key on a
    # terminal and into whatever captures it, for no benefit to the operator,
    # who typed the party in and already knows.
    print(f"  counterparty recorded: {args.counterparty is not None}")
    if args.note:
        print(f"  note:      {args.note}")
    print(f"  txn:       {transaction.transaction_id}")
    print(f"  cell earned to date: {earned} minor units {book.value}")
    print(f"  cell cash now:       {ledger.get_balance(conn, cell_cash(args.cell), book)}")


def cmd_record_refund(args: argparse.Namespace) -> None:
    """Take back some or all of one revenue payment: a refund, or a chargeback
    (SPEC.md §1.1, §16.3; ADR-097).

    Names the payment, never the Cell. The Cell, book, experiment and artifact
    are the payment's own, so there is nothing here an operator could use to
    land a refund on a Cell that did not make the sale.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    payment = ledger.get_transaction(conn, args.payment)
    if payment is None:
        raise CliError(f"no such transaction: {args.payment}")
    book = payment.book
    amount = money.parse_minor_units(args.amount, book.value)
    kind = revenue.ReversalKind.CHARGEBACK if args.chargeback else revenue.ReversalKind.REFUND
    try:
        transaction = revenue.record_reversal(
            conn,
            revenue_transaction_id=args.payment,
            amount_minor_units=amount,
            source=args.source,
            kind=kind,
            note=args.note,
            idempotency_key=args.idempotency_key,
        )
    except revenue.RevenueError as exc:
        raise CliError(str(exc)) from exc

    cell_id = next(e.cell_id for e in transaction.entries if e.cell_id is not None)
    print(f"Recorded {kind.value} of payment {args.payment}")
    print(f"  amount:    {args.amount} ({amount} minor units) {book.value}")
    print(f"  cell:      {cell_id}")
    print(f"  source:    {args.source}")
    if args.note:
        print(f"  note:      {args.note}")
    print(f"  txn:       {transaction.transaction_id}")
    print(f"  still reversible on that payment: "
          f"{revenue.reversible_amount(conn, args.payment)} minor units")
    print(f"  cell earned to date (net): {revenue.net_revenue(conn, cell_id, book)} "
          f"minor units {book.value}")
    print(f"  cell cash now:       {ledger.get_balance(conn, cell_cash(cell_id), book)}")


def cmd_fund_cell(args: argparse.Namespace) -> None:
    """Credit an existing Cell in a given book.

    `create-cell` funds a Cell in exactly one book, but a Cell that makes
    model calls needs balances in three: USD_REAL for the provider charge,
    RESOURCE for token metering (Amendment A6), and USD_SIM if the §2.4
    mirror is to be funded. This is the verb that tops up the others.

    Funding is capital allocation, not spend: it moves money from a colony
    account into the Cell and is deliberately not gated by the real-spend
    breaker (see real_spend_breaker's module docstring).
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    cell = lifecycle.get_cell(conn, args.cell)
    if cell is None:
        raise CliError(f"unknown cell: {args.cell}")

    book = Book(args.book)
    amount = money.parse_minor_units(args.amount, book.value)
    if amount <= 0:
        raise CliError("amount must be positive")

    ledger.post_transaction(
        conn,
        book=book,
        currency=book.value,
        transaction_type="cell_funding",
        idempotency_key=args.idempotency_key or f"cli_fund_cell:{ids.new_id()}",
        description=f"fund cell {cell.cell_id} with {args.amount} {book.value}",
        entries=[
            EntrySpec(
                account_id=args.funding_account,
                amount_minor_units=-amount,
                cell_id=cell.cell_id,
            ),
            EntrySpec(
                account_id=f"cell:{cell.cell_id}:cash",
                amount_minor_units=amount,
                cell_id=cell.cell_id,
            ),
        ],
    )

    balance = ledger.get_balance(conn, f"cell:{cell.cell_id}:cash", book)
    print(f"Funded cell {cell.cell_id}")
    print(f"  book:    {book.value}")
    print(f"  amount:  {args.amount} ({amount} minor units)")
    print(f"  balance: {money.format_minor_units(balance, book.value)}")

    conn.close()


def _build_provider(args: argparse.Namespace) -> providers.ModelProvider:
    """Shared by every verb that can drive a model call, so the paid-provider
    confirmation is enforced in exactly one place. A second copy of this
    `if` is how one verb eventually ships without the gate."""
    if args.provider == providers.ANTHROPIC_PROVIDER:
        if not args.yes_spend_real_money:
            raise CliError(
                "provider 'anthropic' makes a paid API call that spends real "
                "money — re-run with --yes-spend-real-money to confirm"
            )
        return providers.AnthropicProvider()
    if args.provider == providers.OLLAMA_PROVIDER:
        # Local inference: no credential, no invoice, no --yes-spend-real-money
        # gate. Its models are priced at zero (see pricing.PRICING_TABLE), so
        # the USD_REAL path settles at 0 while RESOURCE metering still applies.
        return providers.OllamaProvider()
    if args.provider == providers.MOCK_PROVIDER:
        return providers.MockProvider()
    raise CliError(
        f"unknown provider: {args.provider!r} (known: "
        f"{providers.MOCK_PROVIDER}, {providers.ANTHROPIC_PROVIDER}, "
        f"{providers.OLLAMA_PROVIDER})"
    )


def cmd_wake(args: argparse.Namespace) -> None:
    """Wake one Cell and let it deliberate (SPEC.md §17.2).

    The Cell thinks and proposes. It does not act — §25.1's ladder puts this
    at rung 5, "shadow prediction with no action", so the output is a recorded
    proposal for the operator to read.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    cell = lifecycle.get_cell(conn, args.cell)
    if cell is None:
        raise CliError(f"unknown cell: {args.cell}")

    result = deliberation.deliberate(
        conn,
        cell_id=cell.cell_id,
        provider=_build_provider(args),
        wake_key=args.wake_key or f"cli_wake:{ids.new_id()}",
        wake_reason=args.reason,
        model=args.model,
        context_budget_tokens=args.context_budget,
        max_tokens=args.max_tokens,
        proposal_sink=approval.QueueSink(),
    )
    _print_deliberation(conn, result)
    conn.close()


def cmd_run_wakes(args: argparse.Namespace) -> None:
    """Drain ready wake events from the inbox (§17.1's deterministic order)."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    results = deliberation.run_ready_wakes(
        conn,
        provider=_build_provider(args),
        model=args.model,
        limit=args.limit,
        context_budget_tokens=args.context_budget,
        max_tokens=args.max_tokens,
        proposal_sink=approval.QueueSink(),
    )
    if not results:
        print("No wake events are ready.")
        return
    print(f"Ran {len(results)} wake(s):")
    for result in results:
        print()
        _print_deliberation(conn, result)
    conn.close()


def cmd_enqueue_wake(args: argparse.Namespace) -> None:
    """Schedule a wake without running it."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    cell = lifecycle.get_cell(conn, args.cell)
    if cell is None:
        raise CliError(f"unknown cell: {args.cell}")

    event = deliberation.enqueue_wake(
        conn,
        cell_id=cell.cell_id,
        wake_reason=args.reason,
        dedupe_key=args.dedupe_key or f"cli_wake:{ids.new_id()}",
    )
    print(f"Queued wake {event.event_id} for cell {cell.cell_id}")
    print(f"  reason: {args.reason}")
    print("Run it with `mitosis run-wakes`.")
    conn.close()


def _print_deliberation(conn, result) -> None:
    print(f"Deliberation {result.deliberation_id} ({result.status})")
    print(f"  cell:    {result.cell_id}")
    print(f"  woken:   {result.wake_reason}")
    print(f"  context: {result.context_tokens} tokens")
    if result.repair_model_call_id:
        print(f"  repaired: yes (second call {result.repair_model_call_id}, ADR-069)")
    if result.failure_reason:
        print(f"  reason:  {result.failure_reason}")
    if result.proposal_id:
        stored = deliberation.get_proposal(conn, result.proposal_id)
        print(f"  proposal [{stored['kind']}] risk={stored['risk_tier']}")
        print(f"    {stored['summary']}")
        print(f"    rationale: {stored['rationale']}")
        print(f"    estimated cost: {stored['estimated_cost_minor_units']} minor units")
    for prediction_id in result.prediction_ids:
        registered = prediction.get(conn, prediction_id)
        if registered is not None:
            print(
                f"  predicted p={registered.probability}: {registered.claim} "
                f"(by {registered.resolves_by_utc.date()})"
            )
    if result.proposal_id:
        print("\n  Nothing here executes. A proposal is a record for you to read (SPEC.md §25.1).")


def cmd_tick(args: argparse.Namespace) -> None:
    """Run one epoch's scheduled wakes (SPEC.md §17.2, §23.3).

    Idempotent per epoch — safe to run from cron as often as you like, since a
    second tick inside the same epoch enqueues nothing.

    Always supplies the §25.1 auto-promotion sweep (ADR-063); it is a no-op
    while §27.1's `auto_promotion` autonomy flag is off, which is the same
    switch `mitosis set-autonomy --auto-promotion` and `auto-promote` already
    read — `autopromotion.sweep` checks it first and does nothing else if it
    is unset. This is what makes the flag actually reach the scheduled path
    instead of only the standalone `auto-promote` verb.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    result = scheduler.tick(
        conn,
        provider=_build_provider(args),
        model=args.model,
        max_cells=args.max_cells,
        promoter=autopromotion.EvidencePromoter(),
    )

    print(f"Tick {result.tick_id} — epoch {result.epoch_number} — {result.outcome}")
    if result.detail:
        print(f"  {result.detail}")
    if result.halted:
        print("\n  No Cell was woken. Run `mitosis scheduler-status` for the guard state.")
        if result.requests_expired or result.grants_expired:
            # §23.3's sweep runs before the guards (ADR-040): a halt stops the
            # colony *doing* things, and expiring only ever takes permission
            # away. Worth saying so, because "halted" otherwise reads as
            # "nothing happened" and a stale approval did just lose its force.
            print(
                "  Expiry still ran — it removes authority rather than using it. "
                "The regenerated wakes stay pending until a tick is allowed to run."
            )
    for deliberated in result.deliberations:
        print()
        _print_deliberation(conn, deliberated)
    conn.close()


def cmd_simulate(args: argparse.Namespace) -> None:
    """Run the Phase 2 flight simulator (SPEC.md §7, §8, §28 Phase 2; the
    implementation brief's Slice F).

    Synthetic economy only: `USD_SIM` and `RESOURCE`, plus the one `USD_REAL`
    sliver every Cell needs to be scheduler-eligible at all (a pre-existing
    `scheduler.eligible_cells` rule this verb does not introduce) and the
    zero-amount reserve/release pairs every model call posts against it
    regardless of provider — the manifest records that no `external_expense`
    (real spend, as opposed to that internal bookkeeping) was ever posted.
    Deterministic: the same `--seed` reproduces the same manifest byte for
    byte, since ids and every environment/policy/selection draw are seeded
    from it.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    manifest = simulation_runner.run(
        conn,
        simulation_runner.RunConfig(
            scenario_name=args.scenario, master_seed=args.seed,
            epochs=args.epochs, population=args.population, output_path=args.output,
        ),
        suite=simulation_environment.EnvironmentSuite.training_only(
            simulation_environment.build_environment(args.environment)
        ),
        selection=simulation_batch.build_selection(
            args.selection_policy, environment_name=args.environment,
            validation_environment=args.validation_environment,
        ),
    )
    print(manifest.summary())
    if args.output:
        print(f"  manifest written to {args.output}")
    for failure in manifest.failures:
        print(f"  FAILURE: {failure}")
    conn.close()


def _parse_seed_list(text: str) -> list[int]:
    """`1-8`, `1,2,5` or a mix (`1-4,9`) — in the order written."""
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low_text, high_text = part.split("-", 1)
            low, high = int(low_text), int(high_text)
            if high < low:
                raise CliError(f"seed range {part!r} runs backwards")
            seeds.extend(range(low, high + 1))
        else:
            seeds.append(int(part))
    if not seeds:
        raise CliError("--seeds named no seeds")
    return seeds


def cmd_simulate_batch(args: argparse.Namespace) -> None:
    """Every `--arm` at every seed, each in its own process and its own
    in-memory colony (SPEC.md §7.1 batch experiments, §28 Phase 3; ADR-084).

    Takes no `--db`: a batch run records nothing in any colony. Its retained
    artifact is the directory of manifests plus `batch.json`, which is what
    `simulate-compare` reads.
    """
    out_dir = Path(args.out_dir)
    jobs = simulation_batch.plan(
        arms=[arm.strip() for arm in args.arms.split(",") if arm.strip()],
        seeds=_parse_seed_list(args.seeds),
        epochs=args.epochs, population=args.population, scenario=args.scenario,
        environment=args.environment, validation_environment=args.validation_environment,
        out_dir=out_dir,
    )
    workers = args.workers or min(len(jobs), os.cpu_count() or 1)
    print(f"{len(jobs)} run(s) across {workers} worker process(es) -> {out_dir}", flush=True)
    results = simulation_batch.run_batch(jobs, out_dir=out_dir, workers=workers)
    for result in results:
        failure_note = f"  {result.failures} FAILURE(S)" if result.failures else ""
        print(f"  {result.arm:20s} seed {result.seed:<6d} {result.wall_seconds:8.2f}s{failure_note}")
    print(f"  index written to {out_dir / simulation_batch.INDEX_FILENAME}")


def cmd_simulate_compare(args: argparse.Namespace) -> None:
    """A seed-paired comparison of two arms from one batch (ADR-084)."""
    comparison = simulation_paired.compare_batch(
        Path(args.dir), baseline=args.baseline, treatment=args.treatment, metric=args.metric,
        resamples=args.resamples, confidence=args.confidence,
    )
    print(comparison.summary())


def _schedule_line(db_path: str) -> str:
    """The crontab entry for this colony, with this executable and this
    database — the part that is actually easy to get wrong."""
    executable = Path(sys.argv[0]).resolve()
    if not executable.exists() or executable.name.endswith(".py"):
        executable = Path(sys.executable).resolve().parent / "mitosis"
    # Quoted, because this repo lives at a path with a space in it and an
    # unquoted crontab line would fail in a way cron reports to nobody — which
    # is precisely the failure `health` exists to make visible.
    return (
        f"* * * * * {shlex.quote(str(executable))} "
        f"--db {shlex.quote(str(Path(db_path).resolve()))} "
        "tick >> /tmp/mitosis-tick.log 2>&1"
    )


def cmd_set_tick_cadence(args: argparse.Namespace) -> None:
    """The wall-clock liveness rule, when the epoch-based default is too loose."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    state = scheduler.set_tick_expectation(conn, args.seconds)
    if state.tick_expected_every_seconds:
        print(f"`health` now expects a tick every {state.tick_expected_every_seconds}s "
              f"(overdue after {state.tick_expected_every_seconds * scheduler.OVERDUE_SLACK}s).")
    else:
        print("`health` is back to the epoch-based default: overdue at "
              f"{scheduler.OVERDUE_SLACK} epochs behind.")
    conn.close()


def cmd_health(args: argparse.Namespace) -> int:
    """Is anything still running this colony? (SPEC.md §23.3, §30.1; ADR-042)

    Exits 0 healthy, 1 when nothing is running the scheduler or every run dies,
    2 when it is running and has deliberately halted for a person. The exit code
    is the point — it is what cron's MAILTO, systemd, monit or an uptime check
    can act on without knowing anything about MITOSIS.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    state = scheduler.liveness(conn)

    print(f"{state.verdict.upper()}  (exit {state.exit_code})")
    for reason in state.reasons:
        print(f"  {reason}")
    if state.healthy and not state.reasons:
        print("  the scheduler is running and nothing is waiting for you")

    print()
    if state.last_tick_at_utc is None:
        print("  last tick:   never")
    else:
        print(f"  last tick:   {state.last_tick_at_utc.isoformat()}  "
              f"({state.last_outcome}, epoch {state.last_tick_epoch})")
        print(f"  now:         epoch {state.current_epoch} "
              f"({state.epochs_since_last_tick} epoch(s) later)")
    print(f"  deadline:    {state.deadline_rule}")

    # §23.3's fail-safes are reported but do not fail the check: they resolve
    # when the operator returns, and paging someone because the pause they
    # configured engaged is how a fail-safe gets switched off.
    if scheduler.is_on_vacation(conn):
        print("  vacation:    ACTIVE — external work paused (§23.3). Not an outage.")

    if state.verdict in (scheduler.Verdict.NEVER_RAN, scheduler.Verdict.NOT_RUNNING):
        print()
        print("  Nothing is running `mitosis tick`. Install this, or the launchd/systemd")
        print("  equivalent — `tick` is idempotent per epoch, so a per-minute cadence")
        print("  costs nothing until the epoch turns:")
        print()
        print(f"    {_schedule_line(args.db)}")

    conn.close()
    return state.exit_code


def cmd_scheduler_status(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    genesis, epoch_seconds = scheduler.epoch_settings(conn)
    epoch = scheduler.current_epoch(conn)
    state = scheduler.operator_state(conn)
    metabolic = scheduler.metabolic_status(conn)

    limits = population.get_limits(conn)
    print(f"Epoch {epoch}  ({epoch_seconds}s simulated each, genesis {genesis.isoformat()})")
    print(f"  eligible cells now: {len(scheduler.eligible_cells(conn, epoch))}")
    print(
        f"  births this epoch:  {population.births_in_epoch(conn, epoch)}"
        f"/{limits.max_births_per_epoch} (SPEC.md §9.2)"
    )
    if not clock.epochs_configured(conn):
        print("  NOTE: epoch zero is not anchored, so every birth lands in epoch 0 "
              "and §9.2's cap is acting as a lifetime total.")
    print("\nGuards (SPEC.md §23.3, §27.1):")
    print(f"  real_spending:   {'ENABLED' if state.real_spending_enabled else 'disabled'}")
    on_vacation = scheduler.is_on_vacation(conn)
    print(
        f"  vacation mode:   {'ACTIVE' if on_vacation else 'inactive'} "
        f"(operator last seen {state.last_heartbeat_utc.isoformat()})"
    )
    print(
        f"  metabolic alarm: {'RAISED' if state.alarm_active else 'clear'}"
        + (f" — {state.metabolic_alarm_reason}" if state.alarm_active else "")
    )
    print("\nMetabolic rate:")
    print(f"  this epoch:      {metabolic['spend_this_epoch_minor_units']} minor units "
          f"(alarm at {state.metabolic_alarm_cents_per_epoch})")
    print(f"  last wall hour:  {metabolic['spend_last_wall_hour_minor_units']} minor units")
    baseline = metabolic["baseline_minor_units"]
    accel = metabolic["acceleration"]
    print(f"  baseline:        {'n/a' if baseline is None else f'{baseline:.1f}'}")
    print(f"  acceleration:    {'n/a' if accel is None else f'{accel:.1f}x'} "
          f"(alarm above {state.metabolic_acceleration_factor}x)")
    for breach in metabolic["breached"]:
        print(f"  ! {breach}")

    ticks = scheduler.recent_ticks(conn, limit=args.limit)
    if ticks:
        print(f"\nLast {len(ticks)} tick(s):")
        for t in ticks:
            print(f"  epoch {t['epoch_number']:<4} {t['outcome']:<18} "
                  f"{t['provider']:<10} woke {t['cells_woken']}  {t['detail'] or ''}")
    conn.close()


def cmd_heartbeat(args: argparse.Namespace) -> None:
    """Tell the colony the operator is present (§23.3 vacation mode)."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    state = scheduler.heartbeat(conn)
    print(f"Operator present as of {state.last_heartbeat_utc.isoformat()}")
    if state.alarm_active:
        print("  Note: a metabolic alarm is still raised — a heartbeat does not clear it.")
        print("  Use `mitosis ack-alarm --note '...'` once you know why it fired.")
    conn.close()


def cmd_set_autonomy(args: argparse.Namespace) -> None:
    """§27.1's `autonomy:` block. Each flag is turned on separately, because
    §0.4 grants autonomy "tool by tool, phase by phase" — there is deliberately
    no switch that opens more than one."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    if args.real_spending is not None:
        enabled = args.real_spending == "on"
        if enabled and not args.yes_spend_real_money:
            raise CliError(
                "enabling real_spending lets the scheduler spend real money with no "
                "human in the loop — re-run with --yes-spend-real-money to confirm"
            )
        state = scheduler.set_real_spending(conn, enabled)
        print(
            f"autonomy.real_spending = "
            f"{'ENABLED' if state.real_spending_enabled else 'disabled'}"
        )

    for flag in (
        "public_web_read",
        "browser_control",
        "external_publish",
        "external_message",
        "real_commerce",
        "auto_promotion",
    ):
        value = getattr(args, flag)
        if value is None:
            continue
        tools.set_autonomy(conn, flag=flag, enabled=value == "on", changed_by="cli")
        print(f"autonomy.{flag} = {'ENABLED' if value == 'on' else 'disabled'}")

    if all(
        getattr(args, f) is None
        for f in (
            "real_spending", "auto_promotion", "public_web_read", "browser_control",
            "external_publish", "external_message", "real_commerce",
        )
    ):
        raise CliError("name at least one flag to change, e.g. --public-web-read on")
    conn.close()


def cmd_start_experiment(args: argparse.Namespace) -> None:
    """§9.2/§25.1 — begin an experiment (ADR-043), by hand or from an approved
    proposal (ADR-045).

    Two provenances for one act, deliberately one verb: the experiment that
    results is the same object either way, and the difference is who asked. The
    Cell-proposed path takes no `--rung` — that is derived from what the colony
    promoted the Cell to, and offering the flag would suggest otherwise.
    """
    _require_existing_db(args.db)
    if args.grant:
        if args.cell or args.hypothesis:
            raise CliError(
                "--grant already names the cell and the hypothesis (from the approved "
                "proposal); drop --cell/--hypothesis"
            )
        if args.rung is not None:
            raise CliError(
                "--rung cannot be given with --grant: §25.1's rung for a Cell-proposed "
                "experiment is derived from its promotions, never chosen (§23.5)"
            )
    elif not (args.cell and args.hypothesis):
        raise CliError("give either --grant, or both --cell and --hypothesis")

    conn = db.connect_and_migrate(args.db)
    try:
        if args.grant:
            experiment = experiment_grants.start_from_grant(
                conn, grant_id=args.grant, started_by=args.started_by
            )
        else:
            experiment = experiments.start(
                conn,
                cell_id=args.cell,
                hypothesis=args.hypothesis,
                expected_cost_minor_units=args.expected_cost,
                ladder_rung=args.rung if args.rung is not None else 1,
            )
    except (experiments.ExperimentError, experiment_grants.ExperimentGrantError) as exc:
        raise CliError(str(exc)) from exc
    print(f"Experiment {experiment.experiment_id}")
    print(f"  cell:       {experiment.cell_id}")
    print(f"  hypothesis: {experiment.hypothesis}")
    print(f"  §25.1 rung: {experiment.ladder_rung} ({experiment.rung_name})")
    if args.grant:
        print(f"  from:       proposal {experiment.proposal_id} (grant {args.grant})")
        print("  The rung is what this Cell has been promoted to, not what it asked for.")
    limits = population.get_limits(conn)
    print(f"  running:    {experiments.running_count(conn)}"
          f"/{limits.max_parallel_experiments} (§9.2)")
    if experiment.ladder_rung == 1:
        print("  Rung 1 is the flight simulator — no real money should reach this.")
    conn.close()


def cmd_startable_experiments(args: argparse.Namespace) -> None:
    """Approved experiment proposals waiting to be started, and the rung each
    would run at (ADR-045)."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    startable = experiment_grants.startable_grants(conn)
    if not startable:
        print("No approved experiment proposals are ready to start.")
        print("  `mitosis approvals` shows what is still waiting on a decision.")
        conn.close()
        return
    print(f"{len(startable)} approved experiment proposal(s) ready to start:")
    for item in startable:
        print(f"  grant {item['grant_id']}")
        print(f"      cell:  {item['cell_id']}")
        print(f"      asks:  {item['summary']}")
        print(f"      would run at rung {item['ladder_rung']} ({item['rung_name']}) "
              f"— derived from its promotions, not requested")
        print(f"      expires: {item['expires_at_utc']}")
    conn.close()


def cmd_conclude_experiment(args: argparse.Namespace) -> None:
    """End an experiment and free its §9.2 slot."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        experiment = experiments.conclude(
            conn,
            experiment_id=args.experiment_id,
            concluded_by=args.by,
            note=args.note,
            abandoned=args.abandon,
        )
    except experiments.ExperimentError as exc:
        raise CliError(str(exc)) from exc
    print(f"{experiment.status.upper()}: {experiment.experiment_id}")
    print(f"  {experiment.conclusion_note}")
    print(f"  Slot freed — {experiments.running_count(conn)} still running.")
    print("  Nothing here is an outcome. `mitosis experiment <id>` derives that.")
    conn.close()


def cmd_experiments(args: argparse.Namespace) -> None:
    """What the colony is testing."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    if args.cell:
        rows = experiments.list_for(conn, args.cell)
    else:
        rows = [
            experiments.get(conn, r["experiment_id"])
            for r in conn.execute("SELECT experiment_id FROM experiments ORDER BY rowid")
        ]
    if not rows:
        print("No experiments.")
        conn.close()
        return
    limits = population.get_limits(conn)
    print(f"{len(rows)} experiment(s); "
          f"{experiments.running_count(conn)}/{limits.max_parallel_experiments} running (§9.2)")
    for experiment in rows:
        marker = "RUNNING" if experiment.is_running else experiment.status
        print(f"  [{marker}] {experiment.experiment_id}  rung {experiment.ladder_rung}"
              f" ({experiment.rung_name})")
        print(f"      cell: {experiment.cell_id}")
        print(f"      {experiment.hypothesis}")
        if experiment.conclusion_note:
            print(f"      -> {experiment.conclusion_note}  (by {experiment.concluded_by})")
    conn.close()


def cmd_experiment(args: argparse.Namespace) -> None:
    """§2.6's experiment report, derived on read and stored nowhere (§2.5)."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        report = experiments.report(conn, args.experiment_id)
    except experiments.ExperimentError as exc:
        raise CliError(str(exc)) from exc

    print(f"Experiment {report.experiment_id}  [{report.status}]")
    print(f"  cell:       {report.cell_id}")
    print(f"  hypothesis: {report.hypothesis}")
    print(f"  §25.1 rung: {report.ladder_rung} ({report.rung_name})")
    print()
    print("  Report (SPEC.md §2.6 — derived from the books, not reported by the Cell)")
    print(f"    Synthetic net profit:          {report.synthetic_net_profit_minor_units} USD_SIM"
          f"  (revenue {report.synthetic_revenue_minor_units}, "
          f"spend {report.synthetic_spend_minor_units})")
    print(f"    Real API and cloud spend:      {report.real_spend_minor_units} USD_REAL")
    print(f"    Resource consumed:             {report.resource_spend_minor_units} RESOURCE")
    print(f"    Model calls:                   {report.model_calls} "
          f"({report.input_tokens} in / {report.output_tokens} out)")
    cpu = "unmeasurable" if report.sandbox_cpu_seconds is None else report.sandbox_cpu_seconds
    print(f"    Sandbox CPU:                   {cpu}")
    # §1.1 subtracts shadow-priced human labour *and* founder subsidy to get
    # autonomy-adjusted profit, so the subsidised part is printed beside the
    # total rather than inside it. A colony run on unpaid minutes should read as
    # expensive here, not as cheap.
    human = f"{report.human_minutes} minutes"
    if report.subsidised_human_minutes:
        human += f"  ({report.subsidised_human_minutes} of them subsidised — §1.1)"
    print(f"    Human labour:                  {human}")
    gap = ("no resolved forecasts" if report.reality_gap_mean_brier is None
           else f"{report.reality_gap_mean_brier:.3f} mean Brier")
    print(f"    Reality gap (§8.5):            {gap}"
          f"  ({report.resolved_predictions} resolved, "
          f"{report.unresolved_predictions} open)")
    if report.expected_cost_minor_units:
        print(f"    You estimated:                 {report.expected_cost_minor_units}")
    # §13.1's whole purpose is unit consistency — "never subtract raw dollars
    # from scores in [0,1]" — so the ratio is printed beside the two raw figures
    # it came from rather than instead of them. Numerator is the Cell's own
    # estimate; denominator is what a person allocated (§23.2). Nothing is
    # gated on it: §13.2 puts experiment cost on a Pareto frontier, and this
    # kernel has no business turning one dimension into a verdict.
    if report.normalised_cost is not None:
        print(f"    Normalised cost (§13.1):       {report.normalised_cost:.2f}x"
              f"  ({report.expected_cost_minor_units} estimated / "
              f"{report.stage_tranche_minor_units} allotted at the Cell's "
              f"current stage, rung {report.stage_tranche_rung})")
        if report.normalised_cost > 1:
            print("      ^ asks for more than this stage was allotted — a claim to weigh, "
                  "not a rule that was broken")
    print()
    for note in report.unmeasured:
        print(f"  not measured — {note}")
    if report.ladder_rung == 1 and report.spent_real_money:
        print()
        print("  NOTE: §25.1 rung 1 is the flight simulator and this experiment moved "
              "USD_REAL.")
    conn.close()


def cmd_artifacts(args: argparse.Namespace) -> None:
    """What the colony has made."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    where, params = ("WHERE created_by_cell_id = ?", (args.cell,)) if args.cell else ("", ())
    rows = conn.execute(
        f"SELECT * FROM artifacts {where} ORDER BY created_at_utc DESC LIMIT ?",
        (*params, args.limit),
    ).fetchall()
    if not rows:
        print("No artifacts.")
        conn.close()
        return
    for row in rows:
        taints = json.loads(row["taint_labels_json"]) or ["none"]
        state = "EXPORTED" if row["exported_at_utc"] else "internal"
        print(f"{row['artifact_id']}  [{row['kind']}] {row['title']}")
        print(f"    hash:  {row['artifact_hash'][:16]}…  ({row['content_bytes']} bytes, {state})")
        print(f"    cell:  {row['created_by_cell_id']}")
        print(f"    §20.1: licence={row['licence']}  commercial_use={row['commercial_use']}  "
              f"personal_data={row['contains_personal_data']}")
        print(f"    §18.1: {', '.join(taints)}")
    conn.close()


def cmd_artifact(args: argparse.Namespace) -> None:
    """One artifact in full, with its §11.4 lineage."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    artifact = artifacts_module.get(conn, args.artifact_id)
    if artifact is None:
        raise CliError(f"no such artifact: {args.artifact_id}")

    print(f"Artifact {artifact.artifact_id}")
    print(f"  kind:     {artifact.kind}")
    print(f"  title:    {artifact.title}")
    print(f"  hash:     {artifact.artifact_hash}")
    print(f"  made by:  {artifact.created_by_cell_id}")
    print(f"  size:     {artifact.content_bytes} bytes")
    print()
    print("  Data rights (§20.1) — inherited most-restrictive-wins from sources")
    print(f"    licence:        {artifact.licence}")
    print(f"    permitted uses: {artifact.permitted_uses}")
    print(f"    commercial use: {artifact.commercial_use}")
    print(f"    personal data:  {artifact.contains_personal_data}")
    print(f"    retention:      {artifact.retention_rule}")
    print(f"    sources:        {artifact.source_summary}")
    print(f"    §18.1 taint:    {', '.join(artifact.taint_labels) or 'none'}")

    # ADR-041. Shown only when it differs, and labelled — the stored row is the
    # position at creation and stays that way, so a divergence is the record
    # working rather than a bug. Printing both unconditionally would suggest the
    # colony holds two rights positions for every artifact; it holds one belief
    # and one memory.
    effective = artifacts_module.effective_provenance(conn, artifact.artifact_id)
    if effective.commercial_use != artifact.commercial_use or effective.licence != artifact.licence:
        print()
        print("    Position now in force (an operator has attested since — ADR-041)")
        print(f"      licence:        {effective.licence}")
        print(f"      permitted uses: {effective.permitted_uses}")
        print(f"      commercial use: {effective.commercial_use}")
        print("      The row above is what it was born with and was not rewritten (§3.6).")
    print()
    lineage = artifacts_module.lineage_of(conn, artifact.artifact_id)
    print(f"  Built from (§11.4 contribution graph) — {len(lineage)} source(s)")
    for edge in lineage:
        which = edge["source_artifact_id"] or edge["source_tool_call_id"]
        kind = "artifact" if edge["source_artifact_id"] else "tool call"
        print(f"    {kind}: {which}")
    print()
    print("  Export (§19.3 gateway)")
    if artifact.is_exported:
        print(f"    exported {artifact.exported_at_utc.isoformat()} by {artifact.exported_by}")
        print(f"    commercial: {'yes' if artifact.export_is_commercial else 'no'}")
    else:
        for commercial, label in ((False, "non-commercial"), (True, "commercial")):
            try:
                artifacts_module.check_exportable(conn, artifact.artifact_id, commercial=commercial)
                print(f"    {label}: allowed")
            except artifacts_module.ExportRefused as exc:
                print(f"    {label}: REFUSED — {exc}")
    if args.content:
        print()
        print("  --- content ---")
        print(artifact.content)
    conn.close()


def cmd_export_artifact(args: argparse.Namespace) -> None:
    """§19.3's artifact-export gateway. §28 Phase 8: all external use is manual."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        artifact = artifacts_module.export(
            conn,
            artifact_id=args.artifact_id,
            exported_by=args.by,
            reason=args.reason,
            commercial=args.commercial,
        )
    except artifacts_module.ArtifactError as exc:
        raise CliError(str(exc)) from exc
    print(f"Exported {artifact.artifact_id}")
    print(f"  {artifact.kind}: {artifact.title}")
    print(f"  commercial:     {'yes' if artifact.export_is_commercial else 'no'}")
    print(f"  commercial_use: {artifact.commercial_use}")
    print("  Recorded. Nothing was delivered — §28 Phase 8 keeps external action manual.")
    conn.close()


def cmd_set_rights(args: argparse.Namespace) -> None:
    """§20.1/§20.2 — a person establishes a rights position (ADR-041).

    The only writer of `rights_attestations`, and deliberately a CLI verb: §0.3
    makes a canonical rights position an operator's to state, so there is no
    path to this from a proposal, a tool or a grant.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    subject_kind = rights.SUBJECT_COLONY if args.colony else rights.SUBJECT_DOMAIN
    subject = rights.SUBJECT_COLONY if args.colony else (args.domain or "")
    try:
        attestation = rights.attest(
            conn,
            subject_kind=subject_kind,
            subject=subject,
            licence=args.licence,
            permitted_uses=args.permitted_uses,
            commercial_use=args.commercial_use,
            basis=args.basis,
            attested_by=args.by,
        )
    except rights.RightsError as exc:
        raise CliError(str(exc)) from exc

    subject_label = (
        "the colony's own output"
        if attestation.subject_kind == rights.SUBJECT_COLONY
        else f"domain {attestation.subject}"
    )
    print(f"Attested {subject_label}")
    print(f"  licence:        {attestation.licence}")
    print(f"  permitted uses: {attestation.permitted_uses}")
    print(f"  commercial use: {attestation.commercial_use}")
    print(f"  basis:          {attestation.basis}")
    print(f"  by:             {attestation.attested_by}")
    if attestation.is_withdrawal:
        print("  This withdraws any earlier position — §3.6, an adjustment rather than a delete.")
    print()
    print("  Nothing was rewritten. Artifacts keep the rights they were born with;")
    print("  the export gate reads the position in force (`mitosis artifact <id>`).")
    conn.close()


def cmd_set_buyer_type(args: argparse.Namespace) -> None:
    """Classify a buyer. Operator-only (§12.1, §0.3; ADR-062).

    The counterparty is named here and **stored only as a salted hash** (§16.3),
    the same digest `record-revenue --counterparty` writes. Nothing about the
    party survives this command except the ability to recognise them again.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    try:
        attestation = counterparty.attest_buyer_type(
            conn,
            counterparty=args.counterparty,
            # `--withdraw` asserts no position, carrying its own basis (ADR-041).
            buyer_type=None if args.withdraw else args.type,
            basis=args.basis,
            attested_by=args.by,
        )
    except counterparty.CounterpartyError as exc:
        raise CliError(str(exc)) from exc

    if attestation.buyer_type is None:
        print("Withdrew the buyer type for that counterparty.")
        print("  The party is now unclassified — §12.1's dimension abstains for")
        print("  any genome they paid, rather than falling back to a default bin.")
    else:
        print(f"Attested buyer type: {attestation.buyer_type}")
    print(f"  by:    {attestation.attested_by}")
    print(f"  basis: {attestation.basis}")
    print("  the counterparty itself was not stored (§16.3)")
    conn.close()


def cmd_buyers(args: argparse.Namespace) -> None:
    """Buyer types in force, and the record of how they changed."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    if args.history:
        rows = counterparty.buyer_history(conn)
        if not rows:
            print("No buyer attestations. §12.1's `buyer_type` abstains everywhere.")
            conn.close()
            return
        print(f"Every attestation, newest first ({len(rows)}). Nothing is removed (§3.6).")
        for a in rows:
            shown = a.buyer_type or "(withdrawn)"
            print(f"  {a.attested_at_utc}  {a.counterparty_hash[:12]}…  {shown}")
            print(f"      by {a.attested_by} — {a.basis}")
        conn.close()
        return

    positions = counterparty.current_buyer_types(conn)
    if not positions:
        print("No buyer types established.")
        print("§12.1's `buyer_type` cannot be derived — a digest gives equality, never")
        print("identity (§16.3). `mitosis set-buyer-type --counterparty <who> ...` to")
        print("declare one; the party is hashed, never stored.")
        conn.close()
        return
    named = {d: b for d, b in positions.items() if b is not None}
    print(f"Buyer types in force ({len(named)} of {len(positions)} party/parties) — §12.1")
    for digest, bin_ in sorted(positions.items()):
        print(f"  {digest[:12]}…  {bin_ or '(withdrawn)'}")
    conn.close()


def cmd_rights(args: argparse.Namespace) -> None:
    """What the colony currently believes about its sources' rights, and how it
    came to believe it."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    if args.history:
        rows = rights.history(conn)
        if not rows:
            print("No attestations. Every source is `unknown` — §20.2 refuses commercial export.")
            conn.close()
            return
        print(f"Every attestation, newest first ({len(rows)}). Nothing is ever removed (§3.6).")
        for a in rows:
            print(f"  {a.attested_at_utc.isoformat()}  {a.subject_kind}:{a.subject}")
            print(f"      commercial_use={a.commercial_use}  licence={a.licence}")
            print(f"      by {a.attested_by} — {a.basis}")
        conn.close()
        return

    rows = rights.in_force(conn)
    if not rows:
        print("No rights established.")
        print("Every fetched page is `commercial_use: unknown` (§20.2), so nothing may be")
        print("exported commercially. `mitosis set-rights --domain <host> ...` to establish one.")
        conn.close()
        return
    print(f"Rights in force ({len(rows)} subject(s)) — §20.1")
    for a in rows:
        print(f"  {a.subject_kind}:{a.subject}")
        print(f"      commercial use: {a.commercial_use}")
        print(f"      licence:        {a.licence}")
        print(f"      permitted uses: {a.permitted_uses}")
        print(f"      basis:          {a.basis}  (by {a.attested_by})")
    print()
    print("  `--history` shows superseded positions too.")
    conn.close()


def cmd_tools(args: argparse.Namespace) -> None:
    """What the colony can do, and which gates stand in front of each."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    print("Registered tools (SPEC.md §19, §0.4):")
    for spec in sorted(tool_registry.REGISTRY.values(), key=lambda s: s.tool_id):
        on = tool_registry.autonomy_enabled(conn, spec.autonomy_flag)
        print(f"  {spec.tool_id}")
        print(f"    {spec.description}")
        print(f"    read-only (§25.1 rung 4): {'yes' if spec.read_only else 'NO — rung 8+'}")
        print(f"    autonomy.{spec.autonomy_flag}: {'on' if on else 'OFF'}")
        for name, description in sorted(spec.parameters.items()):
            print(f"    arg {name}: {description}")

    domains = tool_registry.allowed_domains(conn)
    print()
    print("Egress allowlist (§19.3, Charter C12):")
    if not domains:
        print("  (empty — the network is disabled by default)")
    for domain in domains:
        print(f"  {domain}")
    conn.close()


def cmd_allow_domain(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        if args.remove:
            tool_registry.deny_domain(conn, domain=args.domain, removed_by="cli")
            print(f"Removed {args.domain} from the egress allowlist")
        else:
            tool_registry.allow_domain(
                conn, domain=args.domain, added_by="cli", reason=args.reason
            )
            print(f"Added {args.domain} to the egress allowlist")
    except tool_registry.ToolError as exc:
        raise CliError(str(exc)) from exc
    print(f"  now allowed: {', '.join(tool_registry.allowed_domains(conn)) or '(nothing)'}")
    conn.close()


def cmd_run_tool(args: argparse.Namespace) -> None:
    """Execute an approved tool grant.

    Operator-invoked, and that is rung 4's "a human runs each execution" — the
    scheduler is structurally forbidden from reaching this path.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    fetcher = None
    if args.live:
        from .fetchers import UrlLibFetcher

        fetcher = UrlLibFetcher()

    try:
        call = tools.execute_grant(
            conn,
            grant_id=args.grant,
            executed_by="cli",
            reason=args.reason,
            fetcher=fetcher,
        )
    except tools.ToolError as exc:
        raise CliError(str(exc)) from exc

    print(f"Tool call {call.tool_call_id}")
    print(f"  tool:      {call.tool}")
    print(f"  arguments: {json.dumps(call.arguments)}")
    print(f"  status:    {call.status}")
    print(f"  taint:     {call.taint_label} (§18.1 — data, never instruction)")
    print(f"  bytes:     {call.result_bytes}")
    print(f"  http:      {call.http_status}")
    print("  The Cell has been woken; the result enters its next context fenced.")
    conn.close()


def cmd_channels(args: argparse.Namespace) -> None:
    """What the colony can do to the outside world, and what stands in front."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    print("Channels (SPEC.md §21, §28 Phase 8). A PERSON performs every action:")
    for spec in sorted(channel_registry.REGISTRY.values(), key=lambda c: c.channel_id):
        on = tool_registry.autonomy_enabled(conn, spec.autonomy_flag)
        frozen, reason = channel_registry.channel_frozen(conn, spec.channel_id)
        print(f"  {spec.channel_id}")
        print(f"    {spec.description}")
        print(f"    autonomy.{spec.autonomy_flag}: {'on' if on else 'OFF'}")
        print(f"    collides on: {spec.target_kind.value} (§21.2's aggregation key)")
        print(
            f"    colony-wide caps: {spec.max_actions_per_window} per "
            f"{channel_registry.CONTACT_WINDOW_SECONDS}s, "
            f"{spec.max_open_claims} unfinished at once"
        )
        if frozen:
            print(f"    FROZEN (§21.1): {reason}")

    open_claims = channel_registry.open_claims(conn)
    print()
    print(f"Open claims: {len(open_claims)}")
    for claim in open_claims:
        print(
            f"  {claim['action_id']}  {claim['channel']}  {claim['intent']}  "
            f"(claimed by {claim['claimed_by']} at {claim['claimed_at_utc']})"
        )
    print()
    print(f"Human minutes recorded (§28 Phase 8): {channel_registry.human_minutes_total(conn)}")
    conn.close()


def cmd_external_check(args: argparse.Namespace) -> None:
    """§21.2's "prevent", asked *before* anything is done.

    The whole point of a registry that claims before it acts: this answers
    "would this collide" while the answer can still change what happens.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    # The lineage, not the Cell: §21.3's question is which *lineage* is already
    # on this target, and ADR-027 keyed exposure on the founder for the same
    # reason — §9 reproduction is the cheapest way this colony splits anything.
    founder_cell_id = None
    if args.cell is not None:
        cell = lifecycle.get_cell(conn, args.cell)
        if cell is None:
            raise CliError(f"no such cell: {args.cell}")
        founder_cell_id = cell.founder_cell_id

    try:
        channel_registry.check_action(
            conn,
            channel=args.channel,
            counterparty=args.counterparty,
            domain=args.domain,
            platform_account=args.account,
            artifact_id=args.artifact,
            founder_cell_id=founder_cell_id,
        )
    except channel_registry.ChannelError as exc:
        print(f"REFUSED: {exc}")
        conn.close()
        raise SystemExit(1)
    print(f"Allowed: nothing on record collides with a {args.channel} action.")
    print("  This is a check, not a claim — run claim-external-action to hold it.")
    conn.close()


def cmd_claim_external_action(args: argparse.Namespace) -> None:
    """Hold a channel (and a counterparty) before a person acts.

    Operator-invoked, and structurally so: §28's Phase 8 acceptance is "all
    external action remains manual", and the scheduler is forbidden from
    importing this path at all.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        action = external_actions.claim(
            conn,
            grant_id=args.grant,
            claimed_by="cli",
            counterparty=args.counterparty,
            domain=args.domain,
            platform_account=args.account,
        )
    except channel_registry.ChannelError as exc:
        raise CliError(str(exc)) from exc

    print(f"External action {action.action_id} CLAIMED — nothing has been sent.")
    print(f"  channel:  {action.channel}")
    print(f"  intent:   {action.intent}")
    print(f"  artifact: {action.artifact_id or '(none)'}")
    print(f"  cell:     {action.cell_id} (lineage {action.founder_cell_id})")
    if args.counterparty:
        print("  counterparty: recorded as a salted hash only (§16.3) — not stored")
    print()
    print("  Now do it by hand, then run complete-external-action with the outcome")
    print("  and the minutes it took. Abandon it if you decide not to.")
    conn.close()


def cmd_complete_external_action(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        action = external_actions.complete(
            conn,
            action_id=args.action,
            completed_by="cli",
            outcome=args.outcome,
            human_minutes=args.minutes,
            reference=args.reference,
        )
    except channel_registry.ChannelError as exc:
        raise CliError(str(exc)) from exc

    print(f"External action {action.action_id} completed")
    print(f"  outcome:       {action.outcome}")
    print(f"  human minutes: {action.human_minutes} (metered as HUMAN_MINUTES, §2.2)")
    frozen, reason = channel_registry.channel_frozen(conn, action.channel)
    if frozen:
        print(f"  §21.1: channel {action.channel} is now FROZEN — {reason}")
        print("         nothing else goes out on it until unfreeze-channel is run")
        print("         the counterparty is permanently on the do-not-contact list")
    print("  The Cell has been woken; it will see the outcome in its next context.")
    conn.close()


def cmd_abandon_external_action(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        action = external_actions.abandon(
            conn, action_id=args.action, abandoned_by="cli", reason=args.reason
        )
    except channel_registry.ChannelError as exc:
        raise CliError(str(exc)) from exc
    print(f"External action {action.action_id} abandoned — the claim is released.")
    print("  The grant is NOT restored: claiming took a slot another lineage could use.")
    conn.close()


def cmd_unfreeze_channel(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    try:
        channel_registry.acknowledge_channel(
            conn, channel=args.channel, acknowledged_by="cli", note=args.note
        )
    except channel_registry.ChannelError as exc:
        raise CliError(str(exc)) from exc
    print(f"Channel {args.channel} unfrozen. Recorded with your stated reason.")
    conn.close()


def cmd_external_actions(args: argparse.Namespace) -> None:
    """The registry itself (§21.2). Note what it cannot show you: who."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    rows = conn.execute(
        """
        SELECT action_id, cell_id, channel, intent, status, outcome, human_minutes,
               claimed_at_utc, artifact_id
          FROM external_action_registry ORDER BY claimed_at_utc DESC LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    if not rows:
        print("No external actions on record.")
        conn.close()
        return
    for row in rows:
        print(f"{row['action_id']}  [{row['channel']}] {row['status']}")
        print(f"    cell {row['cell_id']} · {row['claimed_at_utc']}")
        print(f"    {row['intent']}")
        if row["outcome"]:
            print(f"    outcome: {row['outcome']} · {row['human_minutes']} human minutes")
        if row["artifact_id"]:
            print(f"    delivered artifact {row['artifact_id']}")
    blocks = conn.execute(
        "SELECT COUNT(*) AS n FROM counterparty_blocks"
    ).fetchone()["n"]
    print()
    print(f"Do-not-contact list: {blocks} counterparties (hashes only — §16.3)")
    conn.close()


def cmd_ack_alarm(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)
    state = scheduler.acknowledge_metabolic_alarm(conn, note=args.note)
    print("Metabolic alarm acknowledged and cleared.")
    print(f"  real_spending remains {'ENABLED' if state.real_spending_enabled else 'disabled'}")
    conn.close()


def cmd_proposals(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    found = deliberation.list_proposals(conn, cell_id=args.cell)
    if not found:
        print("No proposals recorded.")
        return
    print(f"{len(found)} proposal(s):")
    for stored in found:
        print(f"  {stored['proposal_id']}  [{stored['kind']}] risk={stored['risk_tier']}")
        print(f"    cell: {stored['cell_id']}")
        print(f"    {stored['summary']}")
    conn.close()


def _tier_marker(request) -> str:
    """Overdue items surface distinctly (§23.3) — in a terminal that means a
    marker in the left margin, not a colour, because the operator may well be
    reading this over ssh or out of a cron mail."""
    return "!" if request.is_overdue() else " "


def cmd_approvals(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    if args.queue_missing:
        queued = approval.enqueue_missing(conn)
        if queued:
            print(f"Queued {len(queued)} previously unqueued proposal(s).")

    pending = approval.queue(conn, status=args.status)
    if not pending:
        print(f"No {args.status} approval requests.")
        conn.close()
        return

    overdue = [r for r in pending if r.is_overdue()]
    header = f"{len(pending)} {args.status} request(s)"
    if overdue:
        header += f", {len(overdue)} overdue"
    print(header + ":")
    for request in pending:
        flags = []
        if not request.reversible:
            flags.append("irreversible")
        if request.batchable:
            flags.append("batchable")
        for signal in request.signals:
            flags.append(signal.signal)
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f" {_tier_marker(request)} {request.request_id}  {request.assessed_tier.value:<8}"
            f" exposure={request.exposure_minor_units}{suffix}"
        )
        print(f"     cell {request.cell_id}  claimed {request.claimed_tier.value}")
        if request.is_overdue():
            print(f"     OVERDUE since {request.sla_due_at_utc.isoformat()}")
        print(f"     expires {request.expires_at_utc.isoformat()}")
    conn.close()


def cmd_approval_show(args: argparse.Namespace) -> None:
    """§23.2's payload, in full. Everything the clause requires an operator be
    shown before deciding — including the two elements that cannot honestly be
    produced yet, which print as unavailable rather than being omitted."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    detail = approval.payload(conn, args.request_id)
    request = detail.request
    proposal = detail.proposal

    print(f"Request {request.request_id}   [{request.status}]")
    if detail.overdue:
        print("  ** OVERDUE — past its SLA and still unreviewed **")
    print()
    print("  Proposed action (§23.2)")
    print(f"    kind:        {proposal['kind']}")
    print(f"    summary:     {proposal['summary']}")
    print(f"    cell:        {request.cell_id}  (currently {detail.current_cell_status.value})")
    print(f"    book:        {detail.book.value}")
    if detail.tool_request:
        # Verbatim, and above the risk block. For a tool request the arguments
        # *are* the decision — approving "read the wholesaler's price list"
        # without seeing which URL is approving nothing in particular.
        print(f"    TOOL:        {detail.tool_request.get('tool')}")
        for name, value in sorted((detail.tool_request.get("arguments") or {}).items()):
            print(f"      {name}: {value}")
    if detail.derived_from_untrusted:
        print(
            "    NOTE:        this proposal was made from a context containing "
            "UNTRUSTED_EXTERNAL content (§18/§19.4) — the Cell may be repeating "
            "something it read"
        )
    print()
    print("  Risk classification")
    print(f"    cell claimed:    {request.claimed_tier.value}")
    print(f"    kernel assessed: {request.assessed_tier.value}")
    print(f"    reversible:      {'yes' if request.reversible else 'NO'}")
    print(f"    batchable:       {'yes' if request.batchable else 'no (individual review)'}")
    print()
    print("  Cost and exposure (§23.2)")
    print(f"    cell's estimate:      {detail.estimated_cost_minor_units} minor units")
    if detail.deliberation_cost_micro_usd is not None:
        print(f"    this deliberation:    {detail.deliberation_cost_micro_usd} micro-USD (actual)")
    print(
        f"    cumulative exposure:  {detail.exposure_minor_units} minor units "
        f"across {detail.related_request_count} request(s) on {request.aggregation_key}"
    )
    liability = (
        "not modelled (the liability_reserve account exists per §31; no policy "
        "provisions one yet)"
        if detail.liability_minor_units is None
        else str(detail.liability_minor_units)
    )
    print(f"    liability:            {liability}")
    print()
    print("  Evidence — from the hash-chained register, not from the Cell (§23.2, §8.5)")
    print(f"    resolved predictions:   {detail.resolved_prediction_count}")
    print(f"    unresolved:             {detail.unresolved_prediction_count}")
    print(f"    overdue past horizon:   {detail.overdue_prediction_count}")
    brier = (
        "n/a (nothing resolved yet)"
        if detail.mean_brier_score is None
        else f"{detail.mean_brier_score:.4f}"
    )
    print(f"    mean Brier score:       {brier}")
    print()
    print("  Cell explanation (§23.2)")
    for line in textwrap.wrap(detail.cell_explanation, width=76):
        print(f"    {line}")
    print()
    print("  Independent Auditor summary (§23.2)")
    if detail.auditor_summary is None:
        print("    UNAVAILABLE — no Auditor Cell has reviewed this.")
        print("    The clause requires an *independent* summary, so this can never")
        print("    be filled by the proposing Cell (§0.3). Absent is the honest value.")
    else:
        for line in textwrap.wrap(detail.auditor_summary, width=76):
            print(f"    {line}")
    print()
    print("  Policy classification (§23.4)")
    if not detail.signals:
        print("    no anti-gaming signals")
    for signal in detail.signals:
        print(f"    {signal.signal}: {signal.detail}")
    print()
    print("  Timing (§23.3)")
    print(f"    created:  {request.created_at_utc.isoformat()}")
    print(f"    SLA due:  {request.sla_due_at_utc.isoformat()}  ({request.sla_seconds}s)")
    print(f"    expires:  {request.expires_at_utc.isoformat()}")
    if request.status == approval.RequestStatus.EXPIRED:
        print(f"    regenerated as wake: {request.regenerated_wake_key or 'none (cell unwakeable)'}")
    conn.close()


def cmd_approve(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    grant = approval.approve(
        conn,
        request_id=args.request_id,
        decided_by=args.by,
        reason=args.reason,
    )
    print(f"Approved. Grant {grant.grant_id}")
    print(f"  tier:     {grant.tier.value}")
    print(f"  exposure: {grant.exposure_at_grant_minor_units} minor units")
    print(f"  expires:  {grant.expires_at_utc.isoformat()}")
    print()
    print("  Nothing acts on this automatically. §25.1 rung 7 requires a human to")
    print("  run the allocation as well as the approval:")
    print(f"    mitosis allocate {grant.grant_id} --by <you> --reason <why>")
    conn.close()


def cmd_reject(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    request = approval.reject(
        conn,
        request_id=args.request_id,
        decided_by=args.by,
        reason=args.reason,
    )
    print(f"Rejected {request.request_id}: {request.decision_reason}")
    conn.close()


def cmd_approve_batch(args: argparse.Namespace) -> None:
    """§23.1's batch path. Only LOW, reversible, signal-free, low-exposure items
    qualify — everything else stays queued for individual review."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    batch_id, grants = approval.approve_batch(
        conn, decided_by=args.by, reason=args.reason, limit=args.limit
    )
    if not grants:
        print("Nothing is batchable. §23.1 permits batching only low-risk")
        print("reversible actions, and any anti-gaming signal forces individual review.")
        conn.close()
        return
    print(f"Batch {batch_id}: approved {len(grants)} request(s).")
    for grant in grants:
        print(f"  {grant.request_id} -> grant {grant.grant_id}")
    conn.close()


def cmd_expire_approvals(args: argparse.Namespace) -> None:
    """§23.3's sweep: expire, then regenerate."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    # Both sides of §23.3's clock: a request nobody decided, and an approval
    # nobody consumed. Requests first — expiring one can only *reduce* the
    # grants in play, never create one, so the two sweeps cannot race to
    # produce a grant this run then immediately expire it.
    expired = approval.expire_due(conn)
    expired_grants = approval.expire_grants_due(conn)

    if not expired and not expired_grants:
        print("Nothing is past its expiry — no pending requests, no unconsumed grants.")
        conn.close()
        return

    def _regenerated(key: str | None) -> str:
        return (
            f"regenerated as {key}" if key else "not regenerated (cell is not wakeable)"
        )

    if expired:
        print(f"Expired {len(expired)} request(s) nobody decided:")
        for request in expired:
            print(
                f"  {request.request_id}  [{request.assessed_tier.value}]  "
                f"{_regenerated(request.regenerated_wake_key)}"
            )
    if expired_grants:
        if expired:
            print()
        print(f"Expired {len(expired_grants)} approved grant(s) nobody consumed:")
        for grant in expired_grants:
            print(
                f"  {grant.grant_id}  [{grant.tier.value}]  "
                f"{_regenerated(grant.regenerated_wake_key)}"
            )
    print()
    print("§23.3: expired actions are regenerated and re-evaluated, never")
    print("executed on stale terms. Regeneration is a wake, never a fresh grant —")
    print("the Cell proposes again and a person approves again.")
    print("Run `mitosis run-wakes` to re-derive them.")
    conn.close()


def cmd_fund_pool(args: argparse.Namespace) -> None:
    """Stage capital for §25 promotion. Always an operator action.

    The pool's balance is the ceiling on everything the promotion path can ever
    allocate — no Cell can raise it, and nothing scheduled draws on it without a
    human running `allocate`.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    book = Book(args.book)
    amount = money.parse_minor_units(args.amount, book.value)
    balance = promotion.fund_pool(
        conn,
        book=book,
        amount_minor_units=amount,
        funding_account=args.funding_account,
        idempotency_key=args.idempotency_key or f"fund_pool:{ids.new_id()}",
    )
    print(f"Promotion pool funded: +{amount} {book.value}")
    print(f"  balance: {balance} minor units")
    print(f"  source:  {args.funding_account}")
    conn.close()


def cmd_allocations(args: argparse.Namespace) -> None:
    """Approved grants that could be allocated right now."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    ready = promotion.allocatable_grants(conn)
    for book in Book:
        balance = promotion.pool_balance(conn, book)
        if balance:
            print(f"Promotion pool ({book.value}): {balance} minor units")
    if not ready:
        print("No grants are ready to allocate.")
        conn.close()
        return
    print(f"{len(ready)} grant(s) ready:")
    for grant in ready:
        print(f"  {grant.grant_id}  {grant.tier.value:<8} cell {grant.cell_id}")
        print(f"    expires {grant.expires_at_utc.isoformat()}")
    conn.close()


def cmd_archive(args: argparse.Namespace) -> None:
    """§12's MAP-Elites archive, derived on every read and stored nowhere.

    Prints niches and their occupancy. A genome with no measured dimension is
    listed as unbinned rather than pooled — a niche called "unknown" would go on
    reporting itself as occupied long after the colony stopped measuring.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    result = novelty.archive(conn)
    print(f"{result.occupied} niche(s) occupied")
    print(f"  measured dimensions:   {', '.join(result.measured_dimensions) or 'none'}")
    print(f"  unmeasured dimensions: {', '.join(result.unmeasured_dimensions) or 'none'}")
    print()
    for niche in result.niches:
        print(f"  {niche.label:44s} {len(niche.genome_hashes):3d} genome(s), "
              f"{niche.living_cells:3d} living cell(s)")
    if result.unbinned_genome_hashes:
        print(f"\n  {len(result.unbinned_genome_hashes)} genome(s) unbinned — nothing earlier "
              "to be novel against, or no dimension measurable")
    conn.close()


def cmd_posteriors(args: argparse.Namespace) -> None:
    """§12.3's beta-binomial `P(next stage)`, one posterior per §12 niche.

    A conversion is a realised fact — a rung-8 promotion naming a rung-7 one as
    the predecessor it expanded — never a read of §25.2's evidence verdict,
    which can support an expansion nobody ever allocated.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    result = posteriors.posteriors(conn)
    if not result.niches and not result.unbinned_trials:
        print("No niches and no rung-7 promotions yet.")
        conn.close()
        return

    for niche in result.niches:
        print(f"  {niche.label:44s} {niche.conversions:3d}/{niche.trials:<3d} converted  "
              f"P(next stage) = {niche.posterior_mean:.3f}  "
              f"(Beta({niche.alpha:g}, {niche.beta:g}))")
    if result.unbinned_trials:
        print(f"\n  unbinned: {result.unbinned_conversions}/{result.unbinned_trials} converted "
              "— genomes with no measured §12.1 dimension")
    print()
    print("Beta(1, 1) prior; a posterior over a realised rung-7 -> rung-8 conversion, "
          "not over §25.2's evidence verdict. Nothing in the kernel acts on it.")
    conn.close()


def cmd_frontier(args: argparse.Namespace) -> None:
    """§13.2 over the grants waiting on the pool: gates, then a Pareto frontier.

    Prints a **set**, not an order. `allocations` lists the same grants by grant
    time, which is first-come-first-funded; this says which of them nothing else
    beats on every axis at once. Neither is a decision — a human still allocates.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    result = selection.evaluate(conn)
    if not result.candidates:
        print("No grants are waiting on the promotion pool.")
        conn.close()
        return

    print(f"{len(result.candidates)} candidate(s); "
          f"{len(result.rejected_grant_ids)} rejected by a §13.2 gate")
    print(f"  measured dimensions:   {', '.join(result.measured_dimensions) or 'none'}")
    print(f"  unmeasured dimensions: {', '.join(result.unmeasured_dimensions) or 'none'}")
    print()
    for candidate in result.candidates:
        if candidate.grant_id in result.frontier_grant_ids:
            standing = "ON FRONTIER"
        elif candidate.rejected_by:
            standing = "REJECTED"
        else:
            standing = "dominated"
        print(f"  {candidate.grant_id}  {standing}")
        print(f"    cell {candidate.cell_id}  "
              f"estimate {candidate.estimated_cost_minor_units} minor units")
        for gate in candidate.gates:
            if gate.outcome is not selection.GateOutcome.PASSED:
                print(f"    gate {gate.dimension}: {gate.outcome.value} — {gate.reason}")
        for axis in candidate.axes:
            if axis.measured:
                print(f"    {axis.dimension}: {axis.value:.4f} ({axis.reason})")
    print()
    print("§13.2 forbids a single weighted scalar, so this is unordered on purpose, "
          "and nothing in the kernel acts on it.")
    conn.close()


def cmd_allocate(args: argparse.Namespace) -> None:
    """§25.1 rung 7: consume an approved grant and fund the Cell."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    # The rung is *derived*, never typed. §23.5 warns the review path "will be
    # optimised against", and an operator flag naming a rung would be the one
    # place a person could hand a Cell an expansion its evidence had not earned
    # — the same reasoning that keeps `ExperimentSpec` rung-free.
    rung, why = autopromotion.entitled_rung_for(
        conn,
        cell_id=promotion_cell_of(conn, args.grant_id),
        evidence=outcome.AssessmentEvidence(),
    )
    result = promotion.allocate(
        conn,
        grant_id=args.grant_id,
        allocated_by=args.by,
        reason=args.reason,
        rung=rung,
        evidence=outcome.AssessmentEvidence(),
    )
    print(f"§25.1 rung {rung}: {why}")
    print(f"Allocated {result.allocated_minor_units} {result.book.value} to {result.cell_id}")
    print(f"  promotion: {result.promotion_id}  (§25.1 rung {result.rung})")
    print(f"  approved by {result.approved_by}, allocated by {result.allocated_by}")
    print(f"  pool now:  {promotion.pool_balance(conn, result.book)} minor units")
    print()
    print("  §25.2 promotion evidence recorded:")
    gap = (
        "n/a (nothing resolved yet)"
        if result.reality_gap_mean_brier is None
        else f"{result.reality_gap_mean_brier:.4f}"
    )
    print(f"    reality gap (mean Brier):  {gap}")
    print(f"    predictions:               {result.resolved_predictions} resolved, "
          f"{result.unresolved_predictions} unresolved")
    print(
        "    liability:                 not modelled (account exists per §31; "
        "no policy provisions one)"
    )
    degradation = (
        "n/a (no earlier promotion to degrade from)"
        if result.transfer_degradation is None
        else f"{result.transfer_degradation:+.4f}"
    )
    print(f"    transfer degradation:      {degradation}")
    if result.wake_key:
        print()
        print(f"  Cell woken: {deliberation.WAKE_CAPITAL_ALLOCATION} ({result.wake_key})")
        print("  Run `mitosis run-wakes` to let it deliberate on its new balance.")
    conn.close()


def promotion_cell_of(conn, grant_id: str) -> str:
    """The Cell a grant belongs to, for deriving the rung before allocating."""
    grant = approval.get_grant(conn, grant_id)
    if grant is None:
        raise CliError(f"no such grant: {grant_id}")
    return grant.cell_id


def cmd_auto_promote(args: argparse.Namespace) -> None:
    """§25.1 climbed unattended (ADR-063). Bounded by §27.1's `auto_promotion`
    flag, §23.1's `batchable` predicate and the `promotion_pool` ceiling."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    result = autopromotion.sweep(
        conn, approve_batchable=not args.no_approve, limit=args.limit
    )
    if not result.ran:
        print(result.detail)
        print()
        print("  Turn it on with: mitosis set-autonomy --auto-promotion on")
        conn.close()
        return

    print(result.detail)
    if result.approved:
        print()
        print(f"  §23.1 batch {result.batch_id}: approved {len(result.approved)} "
              "low-tier reversible request(s)")
    for item in result.promotions:
        marker = "rung 8 EXPANDED PILOT" if item.rung == 8 else "rung 7"
        print(f"    {item.cell_id}: {item.allocated_minor_units} "
              f"{item.book.value} — §25.1 {marker}")
        if item.evidence_verdict:
            print(f"      evidence: {item.evidence_verdict} "
                  f"(supersedes {item.supersedes_promotion_id})")
    for grant_id, why in result.skipped:
        print(f"    skipped {grant_id}: {why}")
    conn.close()


def cmd_promotions(args: argparse.Namespace) -> None:
    """§25.2's promotion record."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    found = promotion.list_promotions(conn, cell_id=args.cell)
    if not found:
        print("No promotions recorded.")
        conn.close()
        return
    print(f"{len(found)} promotion(s):")
    for item in found:
        print(f"  {item.promotion_id}  rung {item.rung}  "
              f"{item.allocated_minor_units} {item.book.value}")
        print(f"    cell {item.cell_id}")
        print(f"    approved by {item.approved_by}, allocated by {item.allocated_by}")
        print(f"    {item.reason}")
    conn.close()


def _print_assessment(result: outcome.Assessment, *, indent: str = "  ") -> None:
    """§25.2's evidence list, in the order the spec enumerates it."""
    pad = indent
    print(f"{pad}verdict: {result.verdict.value.upper()}")
    for reason in result.reasons:
        print(f"{pad}  - {reason}")
    print()
    print(f"{pad}predicted vs observed (forecasts open when the capital moved):")
    print(f"{pad}  open at funding:   {result.forecasts_open_at_funding}")
    print(f"{pad}  resolved since:    {result.forecasts_resolved_since}")
    print(f"{pad}  still open:        {result.forecasts_still_open} "
          f"({result.forecasts_overdue} past deadline)")
    print(f"{pad}  observed Brier:    {_or_na(result.observed_mean_brier)}")
    print(f"{pad}  observed log:      {_or_na(result.observed_mean_log)}")
    print(f"{pad}reality gap (§8.5):  {_or_na(result.reality_gap)}"
          f"   (funded on {_or_na(result.funded_mean_brier)})")
    print(f"{pad}transfer degradation: {_or_na(result.transfer_degradation)}")
    print(f"{pad}cost since funding:")
    print(f"{pad}  allocated:         {result.allocated_minor_units} {result.book.value}")
    print(f"{pad}  consumed:          {result.spend_since_minor_units} "
          f"({result.unspent_minor_units} never drawn on)")
    print(f"{pad}  revenue:           {result.revenue_since_minor_units}")
    print(f"{pad}  net contribution:  {result.net_contribution_minor_units} "
          "(recorded, not judged — §10.3: Explorers need no immediate revenue)")
    print(f"{pad}liability:           not modelled (§13's reserve is Phase 6+)")
    print(f"{pad}human intervention:  {result.human_interventions}")
    for kind, count in sorted(result.intervention_kinds.items()):
        print(f"{pad}  {kind}: {count}")
    print(f"{pad}forecasts made while funded: {result.forecasts_made_while_funded} "
          f"({result.forecasts_made_while_funded_resolved} resolved, "
          f"mean Brier {_or_na(result.mean_brier_made_while_funded)})")
    print(f"{pad}  excluded from the verdict on purpose — §23.5: a Cell optimises "
          "against anything it can arrange after the fact.")


def _or_na(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def cmd_assess(args: argparse.Namespace) -> None:
    """§25.2's read-back: did an allocation work?

    Reports only. Nothing here promotes a Cell to rung 8 or kills one at rung 7
    — §25.1 wants a human for the first and §10.5 forbids the second without an
    independent Auditor, which does not exist yet.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    try:
        result = outcome.assess(conn, args.promotion_id)
    except outcome.OutcomeError as error:
        conn.close()
        raise CliError(str(error)) from error

    print(f"Promotion {result.promotion_id}  (§25.1 rung {result.rung})")
    print(f"  cell {result.cell_id}, funded {result.funded_at_utc.isoformat()}")
    print()
    _print_assessment(result)
    print()
    if result.verdict is outcome.Verdict.SUPPORTS_PROMOTION:
        print(f"  The evidence supports considering rung {result.next_rung}. "
              "A human decides — nothing in the kernel acts on this.")
    conn.close()


def cmd_assessments(args: argparse.Namespace) -> None:
    """One line per promotion: what the colony can actually show for its rungs."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    results = outcome.assess_all(conn, cell_id=args.cell)
    if not results:
        print("No promotions to assess.")
        conn.close()
        return

    print(f"{len(results)} promotion(s):")
    for result in results:
        print(f"  {result.promotion_id}  rung {result.rung}  "
              f"{result.allocated_minor_units} {result.book.value}  "
              f"-> {result.verdict.value}")
        print(f"    cell {result.cell_id}  "
              f"{result.forecasts_resolved_since}/{result.forecasts_open_at_funding} "
              f"funding forecasts resolved, Brier {_or_na(result.observed_mean_brier)}")
        if args.verbose:
            print()
            _print_assessment(result, indent="    ")
            print()
    conn.close()


def cmd_audit(args: argparse.Namespace) -> None:
    """§23.2's independent Auditor summary: have an Auditor Cell review a request.

    Operator-invoked, and only that. An audit costs a model call, so a colony
    that audited on a timer would be spending money unattended — which is the
    thing §23.3's whole guard set exists to prevent.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    provider = _build_provider(args)
    try:
        result = auditor.audit_request(
            conn,
            request_id=args.request_id,
            auditor_cell_id=args.auditor,
            provider=provider,
            model=args.model,
            max_tokens=args.max_tokens,
            idempotency_key=args.idempotency_key,
        )
    except (auditor.AuditError, approval.ApprovalError) as error:
        conn.close()
        raise CliError(str(error)) from error

    if not result.is_recorded:
        # The model call was already bought and committed (ADR-022), so this is
        # a recorded fact rather than an error: real spend that produced no
        # usable opinion is exactly what should be visible.
        print(f"Audit {result.audit_id}  (REJECTED — no usable opinion)")
        print(f"  auditor {result.auditor_cell_id} reviewing {result.subject_cell_id}")
        print(f"  request {result.request_id}")
        print()
        for line in textwrap.wrap(result.failure_reason or "", width=76):
            print(f"  {line}")
        print()
        print("  The Auditor paid for this call and produced nothing usable, so it")
        print("  is recorded rather than discarded — `mitosis auditor-record` counts")
        print("  it. No prediction was registered: there was no probability to stake.")
        conn.close()
        return

    print(f"Audit {result.audit_id}  ({result.verdict.value.upper()})")
    print(f"  auditor {result.auditor_cell_id} reviewing {result.subject_cell_id}")
    print(f"  request {result.request_id}")
    print()
    for line in textwrap.wrap(result.summary or "", width=76):
        print(f"  {line}")
    print()
    print(f"  probability the request achieves what it claims: {result.probability}")
    print(f"  registered as prediction {result.prediction_id} (§8.5)")
    print("  §10.4: this flag is scored. A wrongful one costs the Auditor its")
    print("  calibration, which is what stops flagging everything being free.")
    print()
    print("  This audit advises; it does not block. Run `mitosis approval "
          f"{result.request_id}` to see it in the §23.2 payload.")
    conn.close()


def cmd_auditor_record(args: argparse.Namespace) -> None:
    """§10.4's precision-weighted Auditor record."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    record = auditor.precision(conn, args.cell)
    print(f"Auditor {record.auditor_cell_id} (SPEC.md §10.4)")
    print(f"  audits given:      {record.audits} ({record.resolved_audits} resolved)")
    print(f"  rejected replies:  {record.rejected}  "
          "(paid for, produced nothing usable)")
    print(f"  flags raised:      {record.flags_raised} ({record.flags_resolved} resolved)")
    print(f"    vindicated:      {record.flags_vindicated}  (valid detected errors)")
    print(f"    wrongful:        {record.wrongful_flags}  (§29.10 penalises these)")
    precision_value = record.flag_precision
    print(
        "  flag precision:    "
        + ("n/a (nothing resolved yet — unmeasured, not perfect)"
           if precision_value is None else f"{precision_value:.4f}")
    )
    print(
        "  mean Brier:        "
        + ("n/a" if record.mean_brier is None else f"{record.mean_brier:.4f}")
        + "   (0.25 is what always answering 0.5 scores)"
    )
    print()
    print("  Reported unreduced on purpose (§10.2): precision alone is maximised")
    print("  by never flagging anything, which would rank a silent Auditor top.")
    conn.close()


def cmd_audit_genome(args: argparse.Namespace) -> None:
    """§13.3 (and §13.4's "ordinary freelancing described exotically"): have
    an Auditor Cell judge whether a genome genuinely has program-native
    advantage.

    Operator-invoked, and only that — the same reason `mitosis audit` is: an
    audit costs a model call, and a colony that audited on a timer would be
    spending money unattended.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    provider = _build_provider(args)
    try:
        result = content_audit.audit_genome(
            conn,
            genome_hash=args.genome_hash,
            auditor_cell_id=args.auditor,
            provider=provider,
            model=args.model,
            max_tokens=args.max_tokens,
            idempotency_key=args.idempotency_key,
        )
    except content_audit.ContentAuditError as error:
        conn.close()
        raise CliError(str(error)) from error

    _print_content_audit(result, subject_line=f"  genome {result.genome_hash}")
    conn.close()


def cmd_audit_genome_pair(args: argparse.Namespace) -> None:
    """§13.4: have an Auditor Cell judge whether two genomes are genuinely
    distinct mechanisms, or the same one renamed. `mitosis archive` is where
    an operator finds a candidate pair worth asking about — the kernel never
    guesses which pair is suspicious."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    provider = _build_provider(args)
    try:
        result = content_audit.audit_genome_pair(
            conn,
            genome_hash=args.genome_hash,
            compared_genome_hash=args.compared_genome_hash,
            auditor_cell_id=args.auditor,
            provider=provider,
            model=args.model,
            max_tokens=args.max_tokens,
            idempotency_key=args.idempotency_key,
        )
    except content_audit.ContentAuditError as error:
        conn.close()
        raise CliError(str(error)) from error

    _print_content_audit(
        result,
        subject_line=f"  genome A {result.genome_hash}\n  genome B {result.compared_genome_hash}",
    )
    conn.close()


def _print_content_audit(result: content_audit.GenomeContentAudit, *, subject_line: str) -> None:
    if not result.is_recorded:
        # The model call was already bought and committed (ADR-022), so this
        # is a recorded fact rather than an error.
        print(f"Content audit {result.audit_id}  (REJECTED — no usable opinion)")
        print(subject_line)
        print()
        for line in textwrap.wrap(result.failure_reason or "", width=76):
            print(f"  {line}")
        print()
        print("  The Auditor paid for this call and produced nothing usable, so it")
        print("  is recorded rather than discarded — `mitosis content-audit-record`")
        print("  counts it. No prediction was registered: nothing to stake.")
        return

    print(f"Content audit {result.audit_id}  ({result.kind.value}, {result.verdict.value.upper()})")
    print(subject_line)
    print()
    for line in textwrap.wrap(result.summary or "", width=76):
        print(f"  {line}")
    print()
    print(f"  probability the genuine-claim holds: {result.probability}")
    print(f"  registered as prediction {result.prediction_id} (§8.5)")
    print("  §10.4: this flag is scored. A wrongful one costs the Auditor its")
    print("  calibration, which is what stops flagging everything being free.")
    print()
    print("  Nothing in the kernel consumes this yet — it is read, not acted on.")


def cmd_content_audit_record(args: argparse.Namespace) -> None:
    """§10.4's precision-weighted record for one Auditor's content judgments
    — §13.3/§13.4 only. `mitosis auditor-record` reports request audits."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    record = content_audit.precision(conn, args.cell)
    print(f"Auditor {record.auditor_cell_id}, content judgments (SPEC.md §10.4)")
    print(f"  audits given:      {record.audits} ({record.resolved_audits} resolved)")
    print(f"  rejected replies:  {record.rejected}  "
          "(paid for, produced nothing usable)")
    print(f"  flags raised:      {record.flags_raised} ({record.flags_resolved} resolved)")
    print(f"    vindicated:      {record.flags_vindicated}  (valid detected errors)")
    print(f"    wrongful:        {record.wrongful_flags}  (§29.10 penalises these)")
    precision_value = record.flag_precision
    print(
        "  flag precision:    "
        + ("n/a (nothing resolved yet — unmeasured, not perfect)"
           if precision_value is None else f"{precision_value:.4f}")
    )
    print(
        "  mean Brier:        "
        + ("n/a" if record.mean_brier is None else f"{record.mean_brier:.4f}")
        + "   (0.25 is what always answering 0.5 scores)"
    )
    conn.close()


def cmd_call_model(args: argparse.Namespace) -> None:
    """The one CLI verb that can spend real money.

    `--provider anthropic` requires `--yes-spend-real-money` because every
    other verb in this CLI moves synthetic or internal balances and this one
    does not. An interactive typo here has a bill attached, so the confirmation
    is a required flag rather than a prompt — it survives being run from a
    script, where a prompt would either block forever or be auto-answered.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    cell = lifecycle.get_cell(conn, args.cell)
    if cell is None:
        raise CliError(f"unknown cell: {args.cell}")

    provider = _build_provider(args)

    request = providers.ModelRequest(
        model=args.model,
        messages=({"role": "user", "content": args.prompt},),
        max_tokens=args.max_tokens,
        system=args.system,
    )

    try:
        call = gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=provider,
            request=request,
            idempotency_key=args.idempotency_key or f"cli_call_model:{ids.new_id()}",
            mirror_multiplier=args.mirror_multiplier,
        )
    except (pricing.PricingError, providers.ProviderError) as exc:
        raise CliError(str(exc)) from exc

    print(f"Model call {call.model_call_id}")
    print(f"  status:    {call.status.value}")
    print(f"  provider:  {call.provider}   requested: {call.requested_model}")
    if call.resolved_model:
        print(f"  resolved:  {call.resolved_model}   api: {call.api_version}")
    print(f"  tokens:    {call.input_tokens} in / {call.output_tokens} out")
    print(
        f"  cost:      {call.cost_actual_micro_usd} micro-USD "
        f"(settled {money.format_minor_units(call.settled_minor_units, 'USD_REAL')} USD_REAL)"
    )
    if call.mirror_skipped_reason:
        print(f"  sim mirror: skipped — {call.mirror_skipped_reason}")
    else:
        print(
            f"  sim mirror: {money.format_minor_units(call.mirror_minor_units, 'USD_SIM')} USD_SIM"
        )
    if call.error_text:
        print(f"  error:     {call.error_text}")
    if call.response_text:
        print()
        print(call.response_text)

    conn.close()


def cmd_advance_time(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    new_time = clock.advance(conn, timedelta(days=args.days))
    print(f"Simulated time advanced by {args.days} day(s) to {new_time.isoformat()}")

    conn.close()


def cmd_sweep(args: argparse.Namespace) -> None:
    """SPEC.md §4.4 / Charter C7. Resolve expired reservations, bring any
    `model_calls` row stranded by a crash back into agreement with them, then
    finish the estate of any Cell that died while one was in flight.

    Three steps in this order because each reads the last one's output: the
    sweeper decides what an expired reservation meant, only then can a stranded
    call be resolved from it, and only then is a dead Cell's residual capital
    genuinely free to return to the colony.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    swept = sweeper.sweep(conn, checker=gateway.GatewayOperationChecker(conn))
    print(f"Reservations swept: {len(swept)}")
    for reservation in swept:
        print(
            f"  {reservation.reservation_id}  {reservation.book.value:<9} "
            f"-> {reservation.status.value}"
        )

    resolved = gateway.resolve_stranded_calls(conn)
    print(f"Stranded model calls resolved: {len(resolved)}")
    for call in resolved:
        print(f"  {call.model_call_id}  {call.provider} -> {call.status.value}")

    estates = lifecycle.reclaim_settled_estates(conn)
    print(f"Dead-Cell estates settled: {len(estates)}")
    for estate in estates:
        reclaimed = ", ".join(
            f"{book} {amount}" for book, amount in sorted(estate.reclaimed_by_book.items())
        )
        print(f"  {estate.cell_id}  reclaimed {reclaimed or 'nothing'}")

    still_open = lifecycle.outstanding_estates(conn)
    if still_open:
        print()
        print(
            f"{len(still_open)} dead Cell(s) still hold capital or open reservations — "
            "their external operations are unresolved, so the estate stays incomplete "
            "rather than assuming what a provider did (ADR-022)."
        )
        for entry in still_open:
            print(f"  {entry['cell_id']}  cash={entry['residual_cash']} "
                  f"reservations={len(entry['open_reservations'])}")

    unknown = reservations.count_by_status(conn).get("execution_unknown", 0)
    if unknown:
        print()
        print(
            f"{unknown} reservation(s) sit in 'execution_unknown' — real money is "
            "still committed against external operations whose outcome the kernel "
            "cannot determine. Charter C7: these are reconciled, never "
            "auto-released."
        )

    conn.close()


def cmd_reconcile(args: argparse.Namespace) -> None:
    """SPEC.md §24.1 / §3.6. Apply a provider invoice figure to one call.

    `--invoiced` is a dollar string parsed at micro-USD precision, not cents:
    a single call's true cost is a fraction of a cent, and rounding the
    operator's own evidence before it reaches the ledger would defeat the
    purpose of reconciling against it.
    """
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    invoiced_micro = pricing.parse_micro_usd(args.invoiced)
    call = reconciliation.reconcile_model_call(
        conn,
        args.call,
        invoiced_micro_usd=invoiced_micro,
        source=args.source,
        note=args.note or "",
    )
    ledger_minor = pricing.micro_usd_to_minor_units(invoiced_micro)
    # A call that never returned has no actual cost — that is the whole
    # reason it needed reconciling — so say so rather than printing "None".
    estimated = (
        f"{call.cost_actual_micro_usd} micro-USD"
        if call.cost_actual_micro_usd is not None
        else "unknown (the call never returned a usage report)"
    )
    print(f"Reconciled model call {call.model_call_id}")
    print(f"  provider:  {call.provider}")
    print(f"  estimated: {estimated}")
    print(f"  invoiced:  {invoiced_micro} micro-USD ({args.invoiced} USD)")
    print(f"  on ledger: {ledger_minor} minor units")
    print(f"  source:    {call.reconciliation_source}")
    net = reconciliation.net_adjustment_minor_units(conn)
    print(f"  colony net reconciliation adjustment to date: {net:+d} minor units")

    conn.close()


def cmd_dispute(args: argparse.Namespace) -> None:
    """SPEC.md §4.4 `execution_unknown -> disputed`. No money moves."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    call = reconciliation.dispute_model_call(conn, args.call, reason=args.reason)
    print(f"Disputed model call {call.model_call_id} ({call.provider})")
    print("  funds stay committed; resolve with `mitosis reconcile` once settled")

    conn.close()


def cmd_outstanding(args: argparse.Namespace) -> None:
    """Every call that has not been checked against an invoice, worst first."""
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    stats = reconciliation.summary(conn)
    print(
        f"Model calls: {stats['calls']} billable, {stats['reconciled']} reconciled, "
        f"{stats['outstanding']} outstanding"
    )
    print(
        f"Real money frozen in unreconciled open reservations: "
        f"{stats['frozen_minor_units']} minor units"
    )
    print()

    calls = reconciliation.outstanding(conn)
    if not calls:
        print("Nothing outstanding.")
        conn.close()
        return

    for call in calls:
        reservation = reservations.get_reservation(conn, call.real_reservation_id)
        # Only an *open* reservation still holds money. A released one has a
        # non-zero `maximum_amount - settled_amount` too — that is precisely
        # the amount it handed back — so subtracting without checking status
        # reports freed money as frozen.
        frozen = (
            reservation.maximum_amount - reservation.settled_amount
            if reservation is not None
            and reservation.status in reconciliation.OPEN_RESERVATION_STATUSES
            else 0
        )
        estimated = (
            call.cost_actual_micro_usd
            if call.cost_actual_micro_usd is not None
            else "unknown"
        )
        print(
            f"  {call.model_call_id}  {call.provider:<10} {call.status.value:<18} "
            f"reservation={reservation.status.value if reservation else '?':<18} "
            f"estimated={estimated} micro-USD  frozen={frozen}"
        )

    conn.close()


def cmd_verify_golden_run(args: argparse.Namespace) -> None:
    """SPEC.md §26. Runs against its own fresh in-memory colony — never the
    --db path, since a golden run must not depend on (or disturb) whatever
    state a real colony happens to be in."""
    if args.update_expectations:
        expectations = golden.build_expectations()
        path = golden.write_expectations(expectations)
        print("Golden-run expectations REGENERATED (Amendment A12 migration path).")
        print(f"  file:    {path}")
        print(f"  version: {expectations['expectation_version']}")
        print(f"  hash:    {expectations['semantic_hash']}")
        print()
        print("Review the diff before committing: an expectation change that wasn't")
        print("a deliberate, reviewed schema migration means kernel behaviour drifted.")
        return

    result = golden.verify()
    print(f"Golden-run replay (expectation version {result.expectation_version})")
    print()
    print("  semantic invariants:")
    for name, value in result.invariants.items():
        print(f"    {name}: {value}")
    print()
    print(f"  expected hash: {result.expected_hash}")
    print(f"  actual hash:   {result.actual_hash}")
    print()

    if result.matched:
        print("PASS — the kernel reproduces the golden run exactly.")
        return

    if result.invariant_failures:
        print("FAIL — semantic invariants diverged:")
        for failure in result.invariant_failures:
            print(f"    {failure}")
    if not result.hash_matched:
        print("FAIL — semantic hash mismatch. Sections that differ:")
        expectations = golden.load_expectations()
        for difference in golden.diff_snapshots(
            expectations.get("snapshot", {}), result.snapshot
        ):
            print(f"    {difference}")
    print()
    raise CliError(
        "golden run did not match its expectations — kernel economic behaviour changed. "
        "If the change was intended, re-run with --update-expectations and review the diff."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mitosis", description="MITOSIS colony kernel CLI")
    parser.add_argument(
        "--db", default=DEFAULT_DB_PATH, help=f"path to the SQLite database (default: {DEFAULT_DB_PATH})"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create and migrate the MITOSIS database")
    init_parser.add_argument(
        "--seed-capital", default=None, help='fund the colony with real capital, e.g. "1000.00"'
    )
    init_parser.add_argument(
        "--book", default="USD_SIM", choices=[b.value for b in Book], help="book for --seed-capital"
    )
    init_parser.add_argument(
        "--seed-account", default="seed_bank", help="account credited by --seed-capital"
    )
    init_parser.add_argument(
        "--max-living-cells",
        type=int,
        default=DEFAULT_POPULATION_LIMITS.max_living_cells,
        help=f"carrying capacity, living Cells (default: {DEFAULT_POPULATION_LIMITS.max_living_cells}). "
        "Only applied on first init; re-running init never changes an existing colony's limits.",
    )
    init_parser.add_argument(
        "--max-active-cells",
        type=int,
        default=DEFAULT_POPULATION_LIMITS.max_active_cells,
        help=f"carrying capacity, active Cells (default: {DEFAULT_POPULATION_LIMITS.max_active_cells})",
    )
    init_parser.add_argument(
        "--per-request-cents",
        type=int,
        default=None,
        help=f"real-spend cap per request, USD_REAL cents (default: {DEFAULT_REAL_SPEND_LIMITS.per_request_minor_units}). "
        "Omit to leave unchanged on re-init; passing it always adjusts (and audits) the limit.",
    )
    init_parser.add_argument(
        "--per-hour-cents", type=int, default=None,
        help=f"real-spend cap per rolling hour, USD_REAL cents (default: {DEFAULT_REAL_SPEND_LIMITS.per_hour_minor_units})",
    )
    init_parser.add_argument(
        "--per-day-cents", type=int, default=None,
        help=f"real-spend cap per rolling day, USD_REAL cents (default: {DEFAULT_REAL_SPEND_LIMITS.per_day_minor_units})",
    )
    init_parser.add_argument(
        "--per-month-cents", type=int, default=None,
        help=f"real-spend cap per rolling ~30 days, USD_REAL cents (default: {DEFAULT_REAL_SPEND_LIMITS.per_month_minor_units})",
    )
    init_parser.add_argument(
        "--max-concurrent-reserved-cents", type=int, default=None,
        help=f"max concurrently reserved USD_REAL cents (default: {DEFAULT_REAL_SPEND_LIMITS.max_concurrent_reserved_minor_units})",
    )
    init_parser.add_argument(
        "--clock-mode",
        default=ClockMode.PAUSED.value,
        choices=[m.value for m in ClockMode],
        help="simulated clock starting mode (default: paused). Only applied on first init.",
    )
    init_parser.add_argument(
        "--clock-rate",
        type=float,
        default=clock.DEFAULT_ACCELERATED_RATE,
        help=f"simulated seconds per wall second, used in accelerated mode "
        f"(default: {clock.DEFAULT_ACCELERATED_RATE})",
    )
    init_parser.add_argument(
        "--epoch-seconds",
        type=int,
        default=scheduler.DEFAULT_EPOCH_DURATION_SECONDS,
        help=f"length of one epoch in simulated seconds — the unit §9.2's "
        f"max_births_per_epoch and §23.3's metabolic alarm are measured in "
        f"(default: {scheduler.DEFAULT_EPOCH_DURATION_SECONDS})",
    )
    init_parser.set_defaults(func=cmd_init)

    status_parser = subparsers.add_parser("status", help="show colony status")
    status_parser.set_defaults(func=cmd_status)

    create_cell_parser = subparsers.add_parser("create-cell", help="birth a new Cell")
    create_cell_parser.add_argument(
        "--type", required=True, choices=[t.value for t in CellType], help="Cell taxonomy type"
    )
    create_cell_parser.add_argument("--budget", required=True, help='initial budget, e.g. "5.00"')
    create_cell_parser.add_argument(
        "--book", default="USD_SIM", choices=[b.value for b in Book], help="book for --budget (Amendment A7)"
    )
    create_cell_parser.add_argument(
        "--funding-account", default="seed_bank", help="account debited for the Cell's budget"
    )
    create_cell_parser.add_argument(
        "--genome", default=None,
        help="§16.2 genome content as JSON, or a path to a JSON file — the market, "
             "problem, product and revenue_model this Cell reasons from. Founders are "
             "the only entry point for genome content (§14: seed diverse founders, let "
             "mutation explore). Fields: " + ", ".join(sorted(genome.GENOME_FIELDS)),
    )
    create_cell_parser.add_argument(
        "--idempotency-key", default=None, help="explicit idempotency key, for safe script retries"
    )
    create_cell_parser.add_argument(
        "--displace",
        action="store_true",
        help="if the colony is at carrying capacity, evict one objectively-failing "
        "Cell to make room instead of being denied (SPEC.md §9.3). This kills a "
        "Cell; run `displacement-candidates` first to see which.",
    )
    create_cell_parser.set_defaults(func=cmd_create_cell)

    reproduce_parser = subparsers.add_parser(
        "reproduce", help="birth a child of an existing Cell, funded from its own cash"
    )
    reproduce_parser.add_argument("--parent", required=True, help="parent cell_id")
    reproduce_parser.add_argument(
        "--budget", required=True, help='child budget, e.g. "10.00" (debited from the parent)'
    )
    reproduce_parser.add_argument(
        "--type", default=None, choices=[t.value for t in CellType],
        help="child cell type (default: inherit the parent's)",
    )
    reproduce_parser.add_argument(
        "--mutation", default=None,
        help='JSON object overlaid on the inherited genome, e.g. \'{"strategy":"v2"}\'. '
        "Omit to inherit the parent's genome exactly.",
    )
    reproduce_parser.add_argument(
        "--mutation-operator", default=None, help="name of the mutation operator, recorded on the genome"
    )
    reproduce_parser.add_argument("--idempotency-key", default=None)
    reproduce_parser.add_argument(
        "--displace",
        action="store_true",
        help="if the colony is at carrying capacity, evict one objectively-failing "
        "Cell to make room instead of being denied (SPEC.md §9.3). The parent is "
        "never a candidate. This kills a Cell; run `displacement-candidates` first.",
    )
    reproduce_parser.set_defaults(func=cmd_reproduce)

    candidates_parser = subparsers.add_parser(
        "displacement-candidates",
        help="Cells a birth could displace right now (SPEC.md §9.3) — read-only",
    )
    candidates_parser.add_argument(
        "--require-active",
        action="store_true",
        help="only Cells whose death would free an *active* slot (i.e. alive ones)",
    )
    candidates_parser.add_argument(
        "--exclude", default=None, help="cell_id to exclude, e.g. a prospective parent"
    )
    candidates_parser.set_defaults(func=cmd_displacement_candidates)

    fund_cell_parser = subparsers.add_parser(
        "fund-cell", help="credit an existing Cell in a given book"
    )
    fund_cell_parser.add_argument("--cell", required=True, help="cell_id to fund")
    fund_cell_parser.add_argument(
        "--amount", required=True, help="decimal amount, e.g. 5.00"
    )
    fund_cell_parser.add_argument(
        "--book", default=Book.USD_SIM.value, choices=[b.value for b in Book]
    )
    fund_cell_parser.add_argument(
        "--funding-account", default="seed_bank", help="colony account to draw from"
    )
    fund_cell_parser.add_argument("--idempotency-key", default=None)
    fund_cell_parser.set_defaults(func=cmd_fund_cell)

    revenue_parser = subparsers.add_parser(
        "record-revenue",
        help="credit a Cell with money it earned (the only verb that brings money in)",
    )
    revenue_parser.add_argument("--cell", required=True, help="cell_id that earned it")
    revenue_parser.add_argument("--amount", required=True, help="decimal amount, e.g. 5.00")
    revenue_parser.add_argument(
        "--source",
        required=True,
        help="what the payment was for — an invoice id or 'manual'. Not the place "
             "for the buyer's name: this text goes into the hash-chained "
             "description. Use --counterparty for who paid.",
    )
    revenue_parser.add_argument(
        "--counterparty", default=None,
        help="who paid (§12.1, §16.3). Stored only as a salted hash — the same "
             "digest §21.2 uses outbound — so the colony can tell a repeat buyer "
             "from a new one and can never say who either is.",
    )
    revenue_parser.add_argument(
        "--book", default=Book.USD_REAL.value, choices=[Book.USD_REAL.value, Book.USD_SIM.value]
    )
    revenue_parser.add_argument(
        "--artifact", default=None,
        help="artifact_id of what was sold (Amendment A3). Optional: a retainer or "
             "a correction has no deliverable behind it.",
    )
    revenue_parser.add_argument(
        "--experiment", default=None,
        help="experiment_id this was earned under (§2.6). Optional, and the report "
             "for an experiment that earned nothing is a fact rather than a gap.",
    )
    revenue_parser.add_argument("--note", default="")
    revenue_parser.add_argument("--idempotency-key", default=None)
    revenue_parser.set_defaults(func=cmd_record_revenue)

    refund_parser = subparsers.add_parser(
        "record-refund",
        help="take back some or all of one revenue payment — a refund, or with "
             "--chargeback a chargeback (§1.1; ADR-097)",
    )
    refund_parser.add_argument(
        "--payment", required=True,
        help="transaction id of the revenue payment (record-revenue prints it as "
             "`txn:`). The Cell, book, experiment and artifact are that payment's own.",
    )
    refund_parser.add_argument("--amount", required=True, help="decimal amount, e.g. 2.50")
    refund_parser.add_argument(
        "--source", required=True,
        help="the processor's reference for the refund. Not the customer: this text "
             "goes into the hash-chained description.",
    )
    refund_parser.add_argument(
        "--chargeback", action="store_true",
        help="the payer's bank took the money back, rather than the colony refunding it",
    )
    refund_parser.add_argument("--note", default="")
    refund_parser.add_argument("--idempotency-key", default=None)
    refund_parser.set_defaults(func=cmd_record_refund)

    predict_parser = subparsers.add_parser(
        "predict", help="register a prediction before its outcome is known (SPEC.md §8.5)"
    )
    predict_parser.add_argument("--cell", required=True, help="predicting cell_id")
    predict_parser.add_argument(
        "--claim",
        required=True,
        help='a claim that is unambiguously true or false once resolved, e.g. "revenue >= 50"',
    )
    predict_parser.add_argument(
        "--probability",
        required=True,
        type=float,
        help="P(claim is true), strictly between 0 and 1 — certainty is refused",
    )
    predict_parser.add_argument(
        "--resolves-in-days", type=float, default=7.0, help="deadline for knowing the outcome"
    )
    predict_parser.add_argument("--experiment", default=None)
    predict_parser.add_argument("--idempotency-key", default=None)
    predict_parser.set_defaults(func=cmd_predict)

    resolve_parser = subparsers.add_parser(
        "resolve-prediction", help="record what actually happened and score it"
    )
    resolve_parser.add_argument("--prediction", required=True, help="prediction_id")
    outcome_group = resolve_parser.add_mutually_exclusive_group(required=True)
    outcome_group.add_argument(
        "--occurred", dest="occurred", action="store_true", help="the claim came true"
    )
    outcome_group.add_argument(
        "--did-not-occur", dest="occurred", action="store_false", help="the claim did not come true"
    )
    resolve_parser.add_argument(
        "--source", required=True, help="where the outcome came from — ledger, invoice, manual"
    )
    resolve_parser.set_defaults(func=cmd_resolve_prediction)

    calibration_parser = subparsers.add_parser(
        "calibration", help="predicted vs observed, the §8.5 reality gap"
    )
    calibration_parser.add_argument("--cell", default=None, help="scope to one cell_id")
    calibration_parser.add_argument("--buckets", type=int, default=10)
    calibration_parser.set_defaults(func=cmd_calibration)

    reap_parser = subparsers.add_parser(
        "reap", help="kill Cells meeting an objective death criterion (SPEC.md §10.5)"
    )
    reap_parser.add_argument(
        "--execute",
        action="store_true",
        help="actually kill them; without this the command only reports what it would do",
    )
    reap_parser.set_defaults(func=cmd_reap)

    fitness_parser = subparsers.add_parser(
        "cell-fitness", help="a Cell's realised record: revenue, spend, calibration"
    )
    fitness_parser.add_argument("--cell", required=True)
    fitness_parser.set_defaults(func=cmd_cell_fitness)

    def _add_model_args(parser, *, default_max_tokens: int) -> None:
        """Shared by every verb that drives a model call, so a new verb cannot
        acquire a provider without also acquiring the paid-provider gate."""
        parser.add_argument(
            "--provider", default=providers.MOCK_PROVIDER,
            choices=[providers.MOCK_PROVIDER, providers.ANTHROPIC_PROVIDER, providers.OLLAMA_PROVIDER],
        )
        parser.add_argument("--model", default="mock-1", help="model id to request")
        parser.add_argument("--max-tokens", type=int, default=default_max_tokens)
        parser.add_argument(
            "--yes-spend-real-money", action="store_true",
            help="required for a paid provider; every other provider is free",
        )
        parser.add_argument(
            "--context-budget", type=int,
            default=context.DEFAULT_CONTEXT_TOKEN_BUDGET,
            help="per-wake context token budget (SPEC.md §15.1)",
        )

    wake_parser = subparsers.add_parser(
        "wake", help="wake one Cell to deliberate and propose (SPEC.md §17.2)"
    )
    wake_parser.add_argument("--cell", required=True, help="cell_id to wake")
    wake_parser.add_argument(
        "--reason", default=deliberation.WAKE_SCHEDULED_RESEARCH,
        help="why it was woken (§17.2's wake events)",
    )
    wake_parser.add_argument(
        "--wake-key", default=None,
        help="idempotency key for this wake; a repeat returns the existing deliberation",
    )
    _add_model_args(wake_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    wake_parser.set_defaults(func=cmd_wake)

    enqueue_wake_parser = subparsers.add_parser(
        "enqueue-wake", help="schedule a wake event without running it"
    )
    enqueue_wake_parser.add_argument("--cell", required=True)
    enqueue_wake_parser.add_argument(
        "--reason", default=deliberation.WAKE_SCHEDULED_RESEARCH
    )
    enqueue_wake_parser.add_argument("--dedupe-key", default=None)
    enqueue_wake_parser.set_defaults(func=cmd_enqueue_wake)

    run_wakes_parser = subparsers.add_parser(
        "run-wakes", help="drain ready wake events from the inbox"
    )
    run_wakes_parser.add_argument("--limit", type=int, default=None)
    _add_model_args(run_wakes_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    run_wakes_parser.set_defaults(func=cmd_run_wakes)

    tick_parser = subparsers.add_parser(
        "tick", help="run one epoch's scheduled wakes (SPEC.md §17.2; idempotent per epoch)"
    )
    tick_parser.add_argument(
        "--max-cells", type=int, default=None, help="cap how many Cells this tick wakes"
    )
    _add_model_args(tick_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    tick_parser.set_defaults(func=cmd_tick)

    simulate_parser = subparsers.add_parser(
        "simulate",
        help=(
            "run the Phase 2 flight simulator: a synthetic population, "
            "deterministic by seed, zero real spend (SPEC.md §28 Phase 2)"
        ),
    )
    simulate_parser.add_argument(
        "--scenario", default="smoke", help="named scenario (default: a small smoke run)"
    )
    simulate_parser.add_argument(
        "--seed", type=int, required=True,
        help="master seed; the same seed reproduces the same manifest byte for byte",
    )
    simulate_parser.add_argument("--epochs", type=int, required=True)
    simulate_parser.add_argument(
        "--population", type=int, required=True, help="number of founder Cells"
    )
    simulate_parser.add_argument(
        "--output", default=None, help="path to write the machine-readable run manifest"
    )
    simulate_parser.add_argument(
        "--environment",
        choices=[
            simulation_environment.UtilityMaximizingMarket.name,
            simulation_environment.RuleBasedMarket.name,
        ],
        default=simulation_environment.UtilityMaximizingMarket.name,
        help="market family (SPEC.md §8.3; default: utility_maximizing_market)",
    )
    simulate_parser.add_argument(
        "--selection-policy",
        choices=[
            simulation_selection_policy.RandomEligibleSelection.name,
            simulation_selection_policy.SingleLeaderboardSelection.name,
            simulation_selection_policy.ParetoSelection.name,
            simulation_selection_policy.MapElitesSelection.name,
            simulation_selection_policy.StagedFundingSelection.name,
        ],
        default=simulation_selection_policy.RandomEligibleSelection.name,
        help=(
            "which Cell reproduces each epoch (implementation brief Slice G; "
            "default: random_eligible)"
        ),
    )
    simulate_parser.add_argument(
        "--validation-environment",
        choices=[
            simulation_environment.UtilityMaximizingMarket.name,
            simulation_environment.RuleBasedMarket.name,
        ],
        default=None,
        help=(
            "market family staged_funding probes an elite against before funding it "
            "(SPEC.md §8.1; only meaningful with --selection-policy staged_funding; "
            "default: the other family from --environment)"
        ),
    )
    simulate_parser.set_defaults(func=cmd_simulate)

    simulate_batch_parser = subparsers.add_parser(
        "simulate-batch",
        help=(
            "run every --arms selection policy at every --seeds seed, each in its own process "
            "and in-memory colony; writes manifests + batch.json (SPEC.md §28 Phase 3; ADR-084)"
        ),
    )
    simulate_batch_parser.add_argument(
        "--arms", required=True,
        help=(
            "comma-separated arms: a selection policy name, or LABEL=POLICY with any of "
            "+static_market and +lineage_cap=F, e.g. "
            "map_elites,static=map_elites+static_market,uncapped=map_elites+lineage_cap=1.0 "
            "(ADR-094)"
        ),
    )
    simulate_batch_parser.add_argument(
        "--seeds", required=True, help="seeds to run every arm at, e.g. 1-8 or 1,2,5",
    )
    simulate_batch_parser.add_argument("--epochs", type=int, required=True)
    simulate_batch_parser.add_argument("--population", type=int, required=True)
    simulate_batch_parser.add_argument("--scenario", default="batch")
    simulate_batch_parser.add_argument(
        "--environment",
        choices=[
            simulation_environment.UtilityMaximizingMarket.name,
            simulation_environment.RuleBasedMarket.name,
        ],
        default=simulation_environment.UtilityMaximizingMarket.name,
    )
    simulate_batch_parser.add_argument(
        "--validation-environment",
        choices=[
            simulation_environment.UtilityMaximizingMarket.name,
            simulation_environment.RuleBasedMarket.name,
        ],
        default=None,
        help="as for `simulate`; only read by the staged_funding arm",
    )
    simulate_batch_parser.add_argument(
        "--workers", type=int, default=None,
        help="worker processes (default: one per run, capped at the CPU count)",
    )
    simulate_batch_parser.add_argument("--out-dir", required=True)
    simulate_batch_parser.set_defaults(func=cmd_simulate_batch)

    simulate_compare_parser = subparsers.add_parser(
        "simulate-compare",
        help="seed-paired effect and bootstrap CI of one arm against another (ADR-084)",
    )
    simulate_compare_parser.add_argument("--dir", required=True, help="a simulate-batch --out-dir")
    simulate_compare_parser.add_argument("--baseline", required=True)
    simulate_compare_parser.add_argument("--treatment", required=True)
    simulate_compare_parser.add_argument(
        "--metric", required=True, choices=sorted(simulation_paired.METRICS),
    )
    simulate_compare_parser.add_argument(
        "--resamples", type=int, default=simulation_paired.DEFAULT_RESAMPLES,
    )
    simulate_compare_parser.add_argument(
        "--confidence", type=float, default=simulation_paired.DEFAULT_CONFIDENCE,
    )
    simulate_compare_parser.set_defaults(func=cmd_simulate_compare)

    health_parser = subparsers.add_parser(
        "health",
        help="is anything still running the scheduler? exits 0/1/2 for a monitor (§23.3)",
    )
    health_parser.set_defaults(func=cmd_health)

    tick_expect_parser = subparsers.add_parser(
        "set-tick-cadence",
        help="how often cron runs `tick`, for a wall-clock liveness rule (§23.3)",
    )
    tick_expect_parser.add_argument(
        "--seconds", type=int, default=None,
        help="omit to restore the default, which is expressed in epochs",
    )
    tick_expect_parser.set_defaults(func=cmd_set_tick_cadence)

    sched_status_parser = subparsers.add_parser(
        "scheduler-status", help="epoch, guards, metabolic rate, recent ticks (§23.3)"
    )
    sched_status_parser.add_argument("--limit", type=int, default=10)
    sched_status_parser.set_defaults(func=cmd_scheduler_status)

    heartbeat_parser = subparsers.add_parser(
        "heartbeat", help="record that the operator is present (§23.3 vacation mode)"
    )
    heartbeat_parser.set_defaults(func=cmd_heartbeat)

    autonomy_parser = subparsers.add_parser(
        "set-autonomy", help="enable/disable unattended real spending (§27.1)"
    )
    autonomy_parser.add_argument("--real-spending", default=None, choices=["on", "off"])
    for flag in (
        "public-web-read",
        "browser-control",
        "external-publish",
        "external-message",
        "real-commerce",
        "auto-promotion",
    ):
        autonomy_parser.add_argument(
            f"--{flag}", default=None, choices=["on", "off"],
            help=f"§27.1 autonomy.{flag.replace('-', '_')} (ships off)",
        )
    autonomy_parser.add_argument(
        "--yes-spend-real-money", action="store_true",
        help="required to turn real_spending on — this removes the human from the loop",
    )
    autonomy_parser.set_defaults(func=cmd_set_autonomy)

    auto_promote_parser = subparsers.add_parser(
        "auto-promote",
        help="climb §25.1 unattended: batch-approve and allocate (§27.1 gated)",
    )
    auto_promote_parser.add_argument(
        "--no-approve", action="store_true",
        help="allocate already-approved grants only; do not batch-approve (§23.1)",
    )
    auto_promote_parser.add_argument(
        "--limit", type=int, default=None,
        help="stop after this many allocations",
    )
    auto_promote_parser.set_defaults(func=cmd_auto_promote)

    start_exp_parser = subparsers.add_parser(
        "start-experiment", help="begin an experiment (SPEC.md §9.2, §25.1)"
    )
    start_exp_parser.add_argument(
        "--grant", default=None,
        help="approved experiment grant to start from (§23, §25.1). The cell, the "
             "hypothesis and the rung all come from the approved proposal and the "
             "Cell's promotions — give this OR --cell/--hypothesis",
    )
    start_exp_parser.add_argument("--cell", default=None)
    start_exp_parser.add_argument(
        "--hypothesis", default=None, help="what is being tested"
    )
    start_exp_parser.add_argument(
        "--rung", type=int, default=None,
        help="§25.1 ladder rung 1-9 (default 1, the flight simulator). Operator path "
             "only: a Cell never chooses its own rung",
    )
    start_exp_parser.add_argument(
        "--expected-cost", type=int, default=0, dest="expected_cost",
        help="§13.1's expected cost, in minor units. Recorded, not enforced",
    )
    start_exp_parser.add_argument(
        "--started-by", default="operator", dest="started_by",
        help="who started it, recorded in the audit log",
    )
    start_exp_parser.set_defaults(func=cmd_start_experiment)

    startable_parser = subparsers.add_parser(
        "startable-experiments",
        help="approved experiment proposals ready to start, and the rung each would run at",
    )
    startable_parser.set_defaults(func=cmd_startable_experiments)

    conclude_exp_parser = subparsers.add_parser(
        "conclude-experiment", help="end an experiment and free its §9.2 slot"
    )
    conclude_exp_parser.add_argument("experiment_id")
    conclude_exp_parser.add_argument("--by", default="operator")
    conclude_exp_parser.add_argument("--note", required=True, help="what was learned")
    conclude_exp_parser.add_argument(
        "--abandon", action="store_true",
        help="stopped without an answer, rather than reaching one",
    )
    conclude_exp_parser.set_defaults(func=cmd_conclude_experiment)

    experiments_parser = subparsers.add_parser(
        "experiments", help="what the colony is testing"
    )
    experiments_parser.add_argument("--cell", default=None)
    experiments_parser.set_defaults(func=cmd_experiments)

    experiment_parser = subparsers.add_parser(
        "experiment", help="§2.6's experiment report, derived from the books"
    )
    experiment_parser.add_argument("experiment_id")
    experiment_parser.set_defaults(func=cmd_experiment)

    artifacts_parser = subparsers.add_parser(
        "artifacts", help="what the colony has made (SPEC.md §20, §31)"
    )
    artifacts_parser.add_argument("--cell", default=None, help="only this Cell's artifacts")
    artifacts_parser.add_argument("--limit", type=int, default=20)
    artifacts_parser.set_defaults(func=cmd_artifacts)

    artifact_parser = subparsers.add_parser(
        "artifact", help="one artifact: provenance, lineage, and export status"
    )
    artifact_parser.add_argument("artifact_id")
    artifact_parser.add_argument(
        "--content", action="store_true", help="also print the content itself"
    )
    artifact_parser.set_defaults(func=cmd_artifact)

    export_parser = subparsers.add_parser(
        "export-artifact", help="§19.3's export gateway — record taking one outside"
    )
    export_parser.add_argument("artifact_id")
    export_parser.add_argument("--by", default="operator")
    export_parser.add_argument("--reason", required=True, help="why — §28 measures human review")
    export_parser.add_argument(
        "--commercial", action="store_true",
        help="this export is for commercial use, which §20.2 gates on established rights",
    )
    export_parser.set_defaults(func=cmd_export_artifact)

    set_rights_parser = subparsers.add_parser(
        "set-rights",
        help="establish a §20.1 rights position on a source (operator-only; ADR-041)",
    )
    rights_subject = set_rights_parser.add_mutually_exclusive_group(required=True)
    rights_subject.add_argument(
        "--domain", help="bare host the position applies to, e.g. example.com"
    )
    rights_subject.add_argument(
        "--colony", action="store_true",
        help="the colony's own output — artifacts that read nothing",
    )
    set_rights_parser.add_argument(
        "--licence", required=True,
        help="the licence, e.g. CC-BY-4.0. 'unknown' is allowed and withdraws a claim",
    )
    set_rights_parser.add_argument(
        "--permitted-uses", required=True, dest="permitted_uses",
        help="what the licence actually allows, in words (§20.1)",
    )
    set_rights_parser.add_argument(
        "--commercial-use", required=True, dest="commercial_use",
        choices=sorted(rights.COMMERCIAL_USE_VALUES),
        help="§20.2's gate. 'unknown' withdraws an earlier position",
    )
    set_rights_parser.add_argument(
        "--basis", required=True,
        help="where this came from — the publisher's licensing page, an email, counsel. "
             "§20.3 makes an invalid position a liability, so the record has to say",
    )
    set_rights_parser.add_argument("--by", default="operator", help="who is attesting")
    set_rights_parser.set_defaults(func=cmd_set_rights)

    set_buyer_parser = subparsers.add_parser(
        "set-buyer-type",
        help="classify a buyer for §12.1's archive (operator-only; ADR-062)",
    )
    set_buyer_parser.add_argument(
        "--counterparty", required=True,
        help="who paid, as you know them. Stored only as a salted hash (§16.3) — "
             "the same digest record-revenue writes.",
    )
    buyer_position = set_buyer_parser.add_mutually_exclusive_group(required=True)
    buyer_position.add_argument(
        "--type", choices=list(counterparty.BUYER_TYPES),
        help="§12.1's four segments",
    )
    buyer_position.add_argument(
        "--withdraw", action="store_true",
        help="assert no position, superseding an earlier one. Still needs a basis: "
             "a retraction leaves *why* in the record where a flag leaves an absence.",
    )
    set_buyer_parser.add_argument(
        "--basis", required=True,
        help="how you know — the invoice, the contract, the conversation. A buyer "
             "type is a selection input, and an unexplained one fabricates fitness.",
    )
    set_buyer_parser.add_argument("--by", default="operator", help="who is attesting")
    set_buyer_parser.set_defaults(func=cmd_set_buyer_type)

    buyers_parser = subparsers.add_parser(
        "buyers", help="buyer types in force, and the record of how they changed"
    )
    buyers_parser.add_argument(
        "--history", action="store_true", help="every attestation, including superseded ones"
    )
    buyers_parser.set_defaults(func=cmd_buyers)

    rights_parser = subparsers.add_parser(
        "rights", help="rights positions in force, and the record of how they changed"
    )
    rights_parser.add_argument(
        "--history", action="store_true", help="every attestation, including superseded ones"
    )
    rights_parser.set_defaults(func=cmd_rights)

    tools_parser = subparsers.add_parser(
        "tools", help="registered tools, their gates, and the egress allowlist (§19)"
    )
    tools_parser.set_defaults(func=cmd_tools)

    domain_parser = subparsers.add_parser(
        "allow-domain", help="add or remove a domain on the §19.3 egress allowlist"
    )
    domain_parser.add_argument("--domain", required=True, help="bare domain, e.g. example.com")
    domain_parser.add_argument(
        "--reason", default="", help="why this domain may be reached — required to add"
    )
    domain_parser.add_argument("--remove", action="store_true", help="remove instead of add")
    domain_parser.set_defaults(func=cmd_allow_domain)

    run_tool_parser = subparsers.add_parser(
        "run-tool", help="execute an approved tool grant (SPEC.md §19, §23)"
    )
    run_tool_parser.add_argument("--grant", required=True, help="approved grant_id")
    run_tool_parser.add_argument(
        "--reason", required=True, help="why this is being run now — recorded"
    )
    run_tool_parser.add_argument(
        "--live", action="store_true",
        help="actually reach the network. Without it no fetcher is supplied and the "
             "call refuses (§19.3 ships the network disabled)",
    )
    run_tool_parser.set_defaults(func=cmd_run_tool)

    channels_parser = subparsers.add_parser(
        "channels", help="external channels, their gates and caps (§21)"
    )
    channels_parser.set_defaults(func=cmd_channels)

    ext_check_parser = subparsers.add_parser(
        "external-check",
        help="would this external action collide? (§21.2 'prevent' — ask before acting)",
    )
    ext_check_parser.add_argument("--channel", required=True)
    ext_check_parser.add_argument(
        "--counterparty", default=None,
        help="who it would go to. Hashed to ask the question; never stored by this verb",
    )
    ext_check_parser.add_argument("--domain", default=None, help="§21.2 'domain used'")
    ext_check_parser.add_argument("--account", default=None, help="§21.2 'platform account'")
    ext_check_parser.add_argument(
        "--cell", default=None,
        help="which Cell is asking. Required for a channel keyed on a domain or a "
             "platform account, where a repeat by the same lineage is not a collision",
    )
    ext_check_parser.add_argument(
        "--artifact", default=None,
        help="what would be published, if anything — the same content to the same "
             "target twice is §21.2's duplicate for a channel that addresses nobody",
    )
    ext_check_parser.set_defaults(func=cmd_external_check)

    claim_parser = subparsers.add_parser(
        "claim-external-action",
        help="hold a channel against an approved grant, before a person acts (§21.2)",
    )
    claim_parser.add_argument("--grant", required=True, help="approved grant_id")
    claim_parser.add_argument(
        "--counterparty", default=None,
        help="who the action addresses. Stored as a salted hash only (§16.3)",
    )
    claim_parser.add_argument("--domain", default=None, help="§21.2 'domain used'")
    claim_parser.add_argument("--account", default=None, help="§21.2 'platform account'")
    claim_parser.set_defaults(func=cmd_claim_external_action)

    complete_parser = subparsers.add_parser(
        "complete-external-action", help="record what a person did, and what it cost them"
    )
    complete_parser.add_argument("--action", required=True, help="action_id from the claim")
    complete_parser.add_argument(
        "--outcome", required=True,
        choices=sorted(channel_registry.OUTCOMES),
        help="what was observed. 'complaint'/'blocked' freeze the channel (§21.1)",
    )
    complete_parser.add_argument(
        "--minutes", required=True, type=int,
        help="human minutes it actually took — §28 Phase 8 measures human labour",
    )
    complete_parser.add_argument(
        "--reference", default=None, help="your own external reference (message id, URL)"
    )
    complete_parser.set_defaults(func=cmd_complete_external_action)

    abandon_parser = subparsers.add_parser(
        "abandon-external-action", help="release a claim without having acted on it"
    )
    abandon_parser.add_argument("--action", required=True)
    abandon_parser.add_argument("--reason", required=True, help="why — recorded")
    abandon_parser.set_defaults(func=cmd_abandon_external_action)

    unfreeze_parser = subparsers.add_parser(
        "unfreeze-channel", help="clear a channel frozen by §21.1 reputation damage"
    )
    unfreeze_parser.add_argument("--channel", required=True)
    unfreeze_parser.add_argument(
        "--note", required=True, help="why it is safe to continue; recorded"
    )
    unfreeze_parser.set_defaults(func=cmd_unfreeze_channel)

    ext_actions_parser = subparsers.add_parser(
        "external-actions", help="the §21.2 registry: what the colony did outside itself"
    )
    ext_actions_parser.add_argument("--limit", type=int, default=20)
    ext_actions_parser.set_defaults(func=cmd_external_actions)

    ack_parser = subparsers.add_parser(
        "ack-alarm", help="acknowledge and clear a raised metabolic alarm (§23.3)"
    )
    ack_parser.add_argument(
        "--note", required=True, help="why it was safe to clear; recorded in the audit trail"
    )
    ack_parser.set_defaults(func=cmd_ack_alarm)

    proposals_parser = subparsers.add_parser(
        "proposals", help="list recorded proposals (see `approvals` for the review queue they enter)"
    )
    proposals_parser.add_argument("--cell", default=None, help="scope to one cell_id")
    proposals_parser.set_defaults(func=cmd_proposals)

    approvals_parser = subparsers.add_parser(
        "approvals", help="the §23 review queue, most urgent first"
    )
    approvals_parser.add_argument(
        "--status",
        default=approval.RequestStatus.PENDING,
        choices=[
            approval.RequestStatus.PENDING,
            approval.RequestStatus.APPROVED,
            approval.RequestStatus.REJECTED,
            approval.RequestStatus.EXPIRED,
        ],
    )
    approvals_parser.add_argument(
        "--queue-missing",
        action="store_true",
        help="first queue any proposal that has no review entry",
    )
    approvals_parser.set_defaults(func=cmd_approvals)

    approval_show_parser = subparsers.add_parser(
        "approval", help="show one request's full §23.2 payload"
    )
    approval_show_parser.add_argument("request_id")
    approval_show_parser.set_defaults(func=cmd_approval_show)

    approve_parser = subparsers.add_parser("approve", help="approve one request individually")
    approve_parser.add_argument("request_id")
    approve_parser.add_argument("--by", required=True, help="who is deciding")
    approve_parser.add_argument("--reason", required=True, help="why (§25.2 requires it)")
    approve_parser.set_defaults(func=cmd_approve)

    reject_parser = subparsers.add_parser("reject", help="reject one request")
    reject_parser.add_argument("request_id")
    reject_parser.add_argument("--by", required=True, help="who is deciding")
    reject_parser.add_argument("--reason", required=True, help="why (§25.2 requires it)")
    reject_parser.set_defaults(func=cmd_reject)

    batch_parser = subparsers.add_parser(
        "approve-batch", help="§23.1 batch approval of low-risk reversible requests"
    )
    batch_parser.add_argument("--by", required=True, help="who is deciding")
    batch_parser.add_argument("--reason", required=True, help="why (§25.2 requires it)")
    batch_parser.add_argument("--limit", type=int, default=None)
    batch_parser.set_defaults(func=cmd_approve_batch)

    expire_parser = subparsers.add_parser(
        "expire-approvals",
        help="§23.3: expire overdue requests and regenerate their actions",
    )
    expire_parser.set_defaults(func=cmd_expire_approvals)

    fund_pool_parser = subparsers.add_parser(
        "fund-pool", help="stage capital for §25 promotion (the allocation ceiling)"
    )
    fund_pool_parser.add_argument("--amount", required=True, help="decimal amount, e.g. 5.00")
    fund_pool_parser.add_argument(
        "--book", default=Book.USD_SIM.value, choices=[b.value for b in Book]
    )
    fund_pool_parser.add_argument("--funding-account", default="colony_treasury")
    fund_pool_parser.add_argument("--idempotency-key", default=None)
    fund_pool_parser.set_defaults(func=cmd_fund_pool)

    allocations_parser = subparsers.add_parser(
        "allocations", help="approved grants ready to allocate, and the pool balance"
    )
    allocations_parser.set_defaults(func=cmd_allocations)

    frontier_parser = subparsers.add_parser(
        "frontier",
        help="§13.2: gate the waiting grants, then show the Pareto frontier over them",
    )
    frontier_parser.set_defaults(func=cmd_frontier)

    archive_parser = subparsers.add_parser(
        "archive", help="§12's MAP-Elites archive: which niches the colony occupies"
    )
    archive_parser.set_defaults(func=cmd_archive)

    posteriors_parser = subparsers.add_parser(
        "posteriors",
        help="§12.3: beta-binomial P(next stage) per niche, from realised rung-7 -> "
             "rung-8 conversions",
    )
    posteriors_parser.set_defaults(func=cmd_posteriors)

    allocate_parser = subparsers.add_parser(
        "allocate", help="§25.1 rung 7: consume an approved grant and fund the Cell"
    )
    allocate_parser.add_argument("grant_id")
    allocate_parser.add_argument("--by", required=True, help="who is allocating")
    allocate_parser.add_argument("--reason", required=True, help="why (§25.2 requires it)")
    allocate_parser.set_defaults(func=cmd_allocate)

    promotions_parser = subparsers.add_parser(
        "promotions", help="§25.2's promotion record"
    )
    promotions_parser.add_argument("--cell", default=None)
    promotions_parser.set_defaults(func=cmd_promotions)

    audit_parser = subparsers.add_parser(
        "audit",
        help="§23.2: have an Auditor Cell independently review a pending request",
    )
    audit_parser.add_argument("request_id")
    audit_parser.add_argument(
        "--auditor", required=True,
        help="cell_id of the auditing Cell (must be an auditor/immune Cell of a "
             "different lineage from the one under review)",
    )
    audit_parser.add_argument("--idempotency-key", default=None)
    _add_model_args(audit_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    audit_parser.set_defaults(func=cmd_audit)

    auditor_record_parser = subparsers.add_parser(
        "auditor-record", help="§10.4's precision-weighted record for one Auditor"
    )
    auditor_record_parser.add_argument("--cell", required=True)
    auditor_record_parser.set_defaults(func=cmd_auditor_record)

    audit_genome_parser = subparsers.add_parser(
        "audit-genome",
        help="§13.3: have an Auditor Cell judge whether a genome genuinely has "
             "program-native advantage",
    )
    audit_genome_parser.add_argument("genome_hash")
    audit_genome_parser.add_argument(
        "--auditor", required=True,
        help="cell_id of the auditing Cell (must be an auditor/immune Cell that "
             "does not carry this genome and shares no lineage with a Cell that does)",
    )
    audit_genome_parser.add_argument("--idempotency-key", default=None)
    _add_model_args(audit_genome_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    audit_genome_parser.set_defaults(func=cmd_audit_genome)

    audit_genome_pair_parser = subparsers.add_parser(
        "audit-genome-pair",
        help="§13.4: have an Auditor Cell judge whether two genomes are genuinely "
             "distinct mechanisms, or the same one renamed",
    )
    audit_genome_pair_parser.add_argument("genome_hash")
    audit_genome_pair_parser.add_argument("compared_genome_hash")
    audit_genome_pair_parser.add_argument(
        "--auditor", required=True,
        help="cell_id of the auditing Cell (must be an auditor/immune Cell that "
             "carries neither genome and shares no lineage with a Cell that does)",
    )
    audit_genome_pair_parser.add_argument("--idempotency-key", default=None)
    _add_model_args(audit_genome_pair_parser, default_max_tokens=deliberation.DEFAULT_MAX_TOKENS)
    audit_genome_pair_parser.set_defaults(func=cmd_audit_genome_pair)

    content_audit_record_parser = subparsers.add_parser(
        "content-audit-record",
        help="§10.4's precision-weighted record for one Auditor's §13.3/§13.4 "
             "content judgments",
    )
    content_audit_record_parser.add_argument("--cell", required=True)
    content_audit_record_parser.set_defaults(func=cmd_content_audit_record)

    assess_parser = subparsers.add_parser(
        "assess",
        help="§25.2's read-back: did an allocation work? (reports only, promotes nothing)",
    )
    assess_parser.add_argument("promotion_id")
    assess_parser.set_defaults(func=cmd_assess)

    assessments_parser = subparsers.add_parser(
        "assessments", help="every promotion's §25.2 read-back, one line each"
    )
    assessments_parser.add_argument("--cell", default=None)
    assessments_parser.add_argument(
        "--verbose", action="store_true", help="full evidence for each"
    )
    assessments_parser.set_defaults(func=cmd_assessments)

    call_model_parser = subparsers.add_parser(
        "call-model",
        help="make a model call through the gateway (the only verb that can spend real money)",
    )
    call_model_parser.add_argument("--cell", required=True, help="calling cell_id")
    call_model_parser.add_argument("--prompt", required=True, help="user message content")
    call_model_parser.add_argument(
        "--provider",
        default=providers.MOCK_PROVIDER,
        help=f"{providers.MOCK_PROVIDER} (free, deterministic) or "
        f"{providers.ANTHROPIC_PROVIDER} (paid, real money)",
    )
    call_model_parser.add_argument(
        "--model", default="mock-1", help="requested model id (must be in the pricing table)"
    )
    call_model_parser.add_argument("--system", default=None, help="optional system prompt")
    call_model_parser.add_argument("--max-tokens", type=int, default=256)
    call_model_parser.add_argument(
        "--mirror-multiplier",
        type=float,
        default=gateway.DEFAULT_MIRROR_MULTIPLIER,
        help="USD_SIM mirror of the real cost (§2.4); 0 disables mirroring",
    )
    call_model_parser.add_argument(
        "--yes-spend-real-money",
        action="store_true",
        help="required confirmation for any paid provider",
    )
    call_model_parser.add_argument("--idempotency-key", default=None)
    call_model_parser.set_defaults(func=cmd_call_model)

    advance_time_parser = subparsers.add_parser(
        "advance-time", help="advance the simulated clock forward"
    )
    advance_time_parser.add_argument(
        "--days", type=float, required=True, help="number of simulated days to advance (may be fractional)"
    )
    advance_time_parser.set_defaults(func=cmd_advance_time)

    sweep_parser = subparsers.add_parser(
        "sweep",
        help="resolve expired reservations and any model call a crash left in flight",
    )
    sweep_parser.set_defaults(func=cmd_sweep)

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="apply a provider invoice figure to one model call (SPEC.md §24.1)",
    )
    reconcile_parser.add_argument("--call", required=True, help="model_call_id")
    reconcile_parser.add_argument(
        "--invoiced",
        required=True,
        help='what the provider actually billed, in dollars, e.g. "0.003500". '
        "0 means the provider did not bill for this call",
    )
    reconcile_parser.add_argument(
        "--source",
        required=True,
        help="where the figure came from (invoice id, console export, 'manual')",
    )
    reconcile_parser.add_argument("--note", default=None)
    reconcile_parser.set_defaults(func=cmd_reconcile)

    dispute_parser = subparsers.add_parser(
        "dispute", help="contest a charge rather than accepting it (SPEC.md §4.4)"
    )
    dispute_parser.add_argument("--call", required=True, help="model_call_id")
    dispute_parser.add_argument("--reason", required=True)
    dispute_parser.set_defaults(func=cmd_dispute)

    outstanding_parser = subparsers.add_parser(
        "outstanding", help="model calls not yet checked against an invoice"
    )
    outstanding_parser.set_defaults(func=cmd_outstanding)

    golden_parser = subparsers.add_parser(
        "verify-golden-run",
        help="replay the golden scenario and compare it against stored expectations",
    )
    golden_parser.add_argument(
        "--update-expectations",
        action="store_true",
        help="regenerate the stored expectations instead of checking against them "
        "(Amendment A12's deliberate migration path — review the resulting diff)",
    )
    golden_parser.set_defaults(func=cmd_verify_golden_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # A command may return an exit code. `health` is the only one that does
        # and the reason it exists: 0/non-zero is the interface a monitor reads
        # (SPEC.md §30.1 — the same "avoid unnecessary frameworks" that made
        # `tick` a cron-composable command rather than a daemon).
        code = args.func(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (
        lifecycle.LifecycleError,
        lineage.LineageError,
        genome.GenomeError,
        reservations.ReservationError,
        ledger.LedgerError,
        population.PopulationError,
        real_spend_breaker.RealSpendBreakerError,
        clock.ClockError,
        events.EventError,
        resource_metering.ResourceMeteringError,
        reconciliation.ReconciliationError,
        pricing.PricingError,
        approval.ApprovalError,
        promotion.PromotionError,
        golden.GoldenRunError,
        simulation_batch.BatchError,
        simulation_paired.PairedComparisonError,
        simulation_selection_policy.UnknownSelectionPolicyError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    sys.exit(main())
