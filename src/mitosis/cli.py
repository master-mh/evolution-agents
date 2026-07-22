"""MITOSIS CLI (SPEC.md §30). Phase 1 slice: init, status, create-cell.

argparse (stdlib) rather than a CLI framework, per §30.1 "avoid unnecessary
frameworks". Money commands take --book, defaulting to USD_SIM (Amendment
A7). Decimal strings are parsed via money.parse_minor_units — never binary
float (§30 dollar-string rule).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from . import clock, db, events, ledger, lifecycle, money, population, real_spend_breaker, reservations
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
    else:
        print("    none yet")
    print()
    print("  reservations:")
    r_by_status = reservations.count_by_status(conn)
    print(f"    by status: {r_by_status}" if r_by_status else "    none yet")
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

    conn.close()


def cmd_create_cell(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    book = Book(args.book)
    budget_minor_units = money.parse_minor_units(args.budget, book.value)
    cell_type = CellType(args.type)
    idempotency_key = args.idempotency_key or f"cli_create_cell:{uuid.uuid4()}"

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


def cmd_advance_time(args: argparse.Namespace) -> None:
    _require_existing_db(args.db)
    conn = db.connect_and_migrate(args.db)

    new_time = clock.advance(conn, timedelta(days=args.days))
    print(f"Simulated time advanced by {args.days} day(s) to {new_time.isoformat()}")

    conn.close()


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

    advance_time_parser = subparsers.add_parser(
        "advance-time", help="advance the simulated clock forward"
    )
    advance_time_parser.add_argument(
        "--days", type=float, required=True, help="number of simulated days to advance (may be fractional)"
    )
    advance_time_parser.set_defaults(func=cmd_advance_time)

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
        reservations.ReservationError,
        ledger.LedgerError,
        population.PopulationError,
        real_spend_breaker.RealSpendBreakerError,
        clock.ClockError,
        events.EventError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
