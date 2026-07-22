import pytest

from mitosis import lifecycle, population
from mitosis.models import Book, CellStatus, CellType, DEFAULT_POPULATION_LIMITS, PopulationLimits


def make_cell(conn, key, status=CellStatus.ALIVE):
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=10,
        book=Book.USD_SIM, idempotency_key=key,
    )
    if status != CellStatus.ALIVE:
        conn.execute("UPDATE cells SET status = ? WHERE cell_id = ?", (status.value, cell.cell_id))
    return cell


def test_get_limits_returns_defaults_when_unconfigured(conn):
    assert population.get_limits(conn) == DEFAULT_POPULATION_LIMITS


def test_set_limits_if_absent_configures_once(conn):
    requested = PopulationLimits(
        max_living_cells=5, max_active_cells=3, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=0.5,
    )
    result = population.set_limits_if_absent(conn, requested)
    assert result == requested
    assert population.get_limits(conn) == requested


def test_set_limits_if_absent_does_not_override_existing(conn):
    first = PopulationLimits(
        max_living_cells=5, max_active_cells=3, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=0.5,
    )
    second = PopulationLimits(
        max_living_cells=999, max_active_cells=999, max_parallel_experiments=999,
        max_births_per_epoch=999, max_lineage_population_fraction=0.99,
    )
    population.set_limits_if_absent(conn, first)
    result = population.set_limits_if_absent(conn, second)
    assert result == first
    assert population.get_limits(conn) == first


def test_living_count_excludes_only_dead(conn):
    make_cell(conn, "c1", CellStatus.ALIVE)
    make_cell(conn, "c2", CellStatus.DORMANT)
    make_cell(conn, "c3", CellStatus.QUARANTINED)
    make_cell(conn, "c4", CellStatus.DEAD)
    assert population.living_count(conn) == 3


def test_active_count_only_counts_alive(conn):
    make_cell(conn, "c1", CellStatus.ALIVE)
    make_cell(conn, "c2", CellStatus.DORMANT)
    make_cell(conn, "c3", CellStatus.QUARANTINED)
    make_cell(conn, "c4", CellStatus.DEAD)
    assert population.active_count(conn) == 1


def test_check_birth_licence_allows_under_limit(conn):
    limits = PopulationLimits(
        max_living_cells=2, max_active_cells=2, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=1.0,
    )
    population.set_limits_if_absent(conn, limits)
    make_cell(conn, "c1")
    population.check_birth_licence(conn)  # should not raise, 1 < 2


def test_check_birth_licence_denies_at_max_living_cells(conn):
    limits = PopulationLimits(
        max_living_cells=1, max_active_cells=99, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=1.0,
    )
    population.set_limits_if_absent(conn, limits)
    make_cell(conn, "c1", CellStatus.DORMANT)  # living but not active
    with pytest.raises(population.CarryingCapacityError, match="living"):
        population.check_birth_licence(conn)


def test_check_birth_licence_denies_at_max_active_cells(conn):
    limits = PopulationLimits(
        max_living_cells=99, max_active_cells=1, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=1.0,
    )
    population.set_limits_if_absent(conn, limits)
    make_cell(conn, "c1", CellStatus.ALIVE)
    with pytest.raises(population.CarryingCapacityError, match="active"):
        population.check_birth_licence(conn)


def test_dead_cells_never_block_births(conn):
    limits = PopulationLimits(
        max_living_cells=1, max_active_cells=1, max_parallel_experiments=1,
        max_births_per_epoch=1, max_lineage_population_fraction=1.0,
    )
    population.set_limits_if_absent(conn, limits)
    make_cell(conn, "c1", CellStatus.DEAD)
    population.check_birth_licence(conn)  # should not raise
