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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (
    clock,
    db,
    events,
    gateway,
    genome,
    golden,
    ids,
    ledger,
    lifecycle,
    lineage,
    money,
    population,
    prediction,
    pricing,
    providers,
    real_spend_breaker,
    reconciliation,
    reservations,
    resource_metering,
    revenue,
    sweeper,
)
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


def cmd_create_cell(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    book = Book(args.book)
    budget_minor_units = money.parse_minor_units(args.budget, book.value)
    cell_type = CellType(args.type)
    idempotency_key = args.idempotency_key or f"cli_create_cell:{ids.new_id()}"

    cell = lifecycle.create_cell(
        conn,
        cell_type=cell_type,
        budget_minor_units=budget_minor_units,
        book=book,
        idempotency_key=idempotency_key,
        funding_account_id=args.funding_account,
    )

    print(f"Created cell {cell.cell_id}")
    print(f"  type:   {cell.cell_type.value}")
    print(f"  status: {cell.status.value}")
    print(f"  book:   {cell.book.value}")
    print(f"  budget: {args.budget} ({budget_minor_units} minor units)")
    print(f"  genome: {cell.genome_hash}")

    conn.close()


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

    conn.close()


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
            experiment_id=args.experiment,
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
            idempotency_key=args.idempotency_key,
        )
    except revenue.RevenueError as exc:
        raise CliError(str(exc)) from exc

    earned = revenue.total_revenue(conn, args.cell, book)
    print(f"Recorded revenue for cell {args.cell}")
    print(f"  amount:    {args.amount} ({amount} minor units) {book.value}")
    print(f"  source:    {args.source}")
    if args.note:
        print(f"  note:      {args.note}")
    print(f"  txn:       {transaction.transaction_id}")
    print(f"  cell earned to date: {earned} minor units {book.value}")
    print(f"  cell cash now:       {ledger.get_balance(conn, cell_cash(args.cell), book)}")


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

    if args.provider == providers.ANTHROPIC_PROVIDER:
        if not args.yes_spend_real_money:
            raise CliError(
                "provider 'anthropic' makes a paid API call that spends real "
                "money — re-run with --yes-spend-real-money to confirm"
            )
        provider: providers.ModelProvider = providers.AnthropicProvider()
    elif args.provider == providers.OLLAMA_PROVIDER:
        # Local inference: no credential, no invoice, no --yes-spend-real-money
        # gate. Its models are priced at zero (see pricing.PRICING_TABLE), so
        # the USD_REAL path settles at 0 while RESOURCE metering still applies.
        provider = providers.OllamaProvider()
    elif args.provider == providers.MOCK_PROVIDER:
        provider = providers.MockProvider()
    else:
        raise CliError(
            f"unknown provider: {args.provider!r} (known: "
            f"{providers.MOCK_PROVIDER}, {providers.ANTHROPIC_PROVIDER}, "
            f"{providers.OLLAMA_PROVIDER})"
        )

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
    """SPEC.md §4.4 / Charter C7. Resolve expired reservations, then bring
    any `model_calls` row stranded by a crash back into agreement with them.

    Two steps in this order because the second reads the first's output: the
    sweeper decides what an expired reservation meant, and only then can a
    stranded call be resolved from it.
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
        "--idempotency-key", default=None, help="explicit idempotency key, for safe script retries"
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
    reproduce_parser.set_defaults(func=cmd_reproduce)

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
        help="who paid and for what — an invoice id, customer ref, or 'manual'",
    )
    revenue_parser.add_argument(
        "--book", default=Book.USD_REAL.value, choices=[Book.USD_REAL.value, Book.USD_SIM.value]
    )
    revenue_parser.add_argument("--note", default="")
    revenue_parser.add_argument("--idempotency-key", default=None)
    revenue_parser.set_defaults(func=cmd_record_revenue)

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
        args.func(args)
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
        golden.GoldenRunError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
