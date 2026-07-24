from datetime import datetime, timedelta, timezone

import pytest

from mitosis import lifecycle, reservations, resource_metering
from mitosis.models import Book, CellType, ResourceType

FUTURE = datetime.now(timezone.utc) + timedelta(days=1)


def _cell(conn, idempotency_key="c1", book=Book.RESOURCE, budget=1000):
    return lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=budget,
        book=book, idempotency_key=idempotency_key,
    )


def _reserve(conn, cell_id, *, maximum_amount=500, idempotency_key="r1", book=Book.RESOURCE):
    currency = "RESOURCE" if book == Book.RESOURCE else "USD"
    return reservations.request(
        conn, cell_id=cell_id, book=book, currency=currency, maximum_amount=maximum_amount,
        expires_at=FUTURE, idempotency_key=idempotency_key,
    )


def test_record_usage_and_totals(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=300, minor_units=150,
        idempotency_key="u1",
    )
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.OUTPUT_TOKENS, quantity=100, minor_units=100,
        idempotency_key="u2",
    )
    assert resource_metering.total_minor_units(conn, r.reservation_id) == 250
    assert resource_metering.usage_by_type(conn, r.reservation_id) == {
        "input_tokens": 300, "output_tokens": 100,
    }
    assert resource_metering.count(conn) == 2


def test_record_usage_is_idempotent(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    first = resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=300, minor_units=150,
        idempotency_key="u1",
    )
    second = resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.CPU_SECONDS, quantity=999, minor_units=999,
        idempotency_key="u1",
    )
    assert first.usage_id == second.usage_id
    assert second.resource_type == ResourceType.INPUT_TOKENS  # replay ignored differing args
    assert resource_metering.total_minor_units(conn, r.reservation_id) == 150


def test_non_positive_quantity_or_minor_units_rejected(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.INPUT_TOKENS, quantity=0, minor_units=1,
            idempotency_key="u-bad-qty",
        )
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=0,
            idempotency_key="u-bad-minor",
        )


def test_unknown_reservation_rejected(conn):
    cell = _cell(conn)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id="no-such-reservation",
            resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=1,
            idempotency_key="u1",
        )


def test_reservation_belonging_to_a_different_cell_rejected(conn):
    cell_a = _cell(conn, idempotency_key="a")
    cell_b = _cell(conn, idempotency_key="b")
    r = _reserve(conn, cell_a.cell_id)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell_b.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=1,
            idempotency_key="u1",
        )


def test_non_resource_book_reservation_rejected(conn):
    cell = _cell(conn, book=Book.USD_SIM, budget=500)
    r = _reserve(conn, cell.cell_id, book=Book.USD_SIM, maximum_amount=100)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.CPU_SECONDS, quantity=1, minor_units=1,
            idempotency_key="u1",
        )


# --- Charter C4: cannot overspend the reservation's cap ---------------------


def test_overspend_rejected(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id, maximum_amount=200)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=100, minor_units=150,
        idempotency_key="u1",
    )
    with pytest.raises(resource_metering.ResourceOverspendError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.OUTPUT_TOKENS, quantity=10, minor_units=100,
            idempotency_key="u2",
        )
    # the rejected attempt must not have partially applied
    assert resource_metering.total_minor_units(conn, r.reservation_id) == 150
    assert resource_metering.count(conn) == 1


def test_usage_exactly_at_cap_is_allowed(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id, maximum_amount=200)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=100, minor_units=200,
        idempotency_key="u1",
    )
    assert resource_metering.total_minor_units(conn, r.reservation_id) == 200


# --- usage may only accumulate against an open (reserved) reservation ------


def test_usage_rejected_once_reservation_is_released(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    reservations.release(conn, r.reservation_id)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=1,
            idempotency_key="u1",
        )


def test_usage_rejected_after_full_settlement(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id, maximum_amount=100)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=10, minor_units=100,
        idempotency_key="u1",
    )
    reservations.settle(conn, r.reservation_id, settled_amount=100, destination_account_id="infrastructure_reserve")
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.CPU_SECONDS, quantity=1, minor_units=1,
            idempotency_key="u2",
        )


def test_usage_rejected_after_partial_settlement(conn):
    """partially_settled is not a terminal reservation status, but its FSM
    only permits -> released next (no further settle) — so any usage
    recorded after that point could never be linked to a settlement
    (Amendment A6). This is why record_usage checks for the exact
    `reserved` status rather than excluding only the two terminal ones."""
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id, maximum_amount=500)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=10, minor_units=150,
        idempotency_key="u1",
    )
    settled = reservations.settle(
        conn, r.reservation_id, settled_amount=150, destination_account_id="infrastructure_reserve"
    )
    assert settled.status.value == "partially_settled"
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.CPU_SECONDS, quantity=1, minor_units=1,
            idempotency_key="u2",
        )


def test_usage_rejected_while_execution_unknown(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    reservations.mark_execution_unknown(conn, r.reservation_id)
    with pytest.raises(resource_metering.ResourceMeteringError):
        resource_metering.record_usage(
            conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
            resource_type=ResourceType.CPU_SECONDS, quantity=1, minor_units=1,
            idempotency_key="u1",
        )


# --- verify_linkage (Amendment A6 completeness) -----------------------------


def test_verify_linkage_holds_for_normal_usage(conn):
    cell = _cell(conn)
    r = _reserve(conn, cell.cell_id)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=1,
        idempotency_key="u1",
    )
    assert resource_metering.verify_linkage(conn) is True


def test_verify_linkage_detects_direct_db_corruption(conn):
    cell = _cell(conn, idempotency_key="c1")
    other_cell = _cell(conn, idempotency_key="c2")
    r = _reserve(conn, cell.cell_id)
    resource_metering.record_usage(
        conn, cell_id=cell.cell_id, reservation_id=r.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=1, minor_units=1,
        idempotency_key="u1",
    )
    # simulate corruption bypassing the API (record_usage can't produce this):
    # the usage row now claims a cell_id that doesn't match its reservation's.
    conn.execute(
        "UPDATE resource_usage SET cell_id = ? WHERE idempotency_key = 'u1'",
        (other_cell.cell_id,),
    )
    assert resource_metering.verify_linkage(conn) is False


def test_total_quantity_by_type_is_colony_wide(conn):
    cell_a = _cell(conn, idempotency_key="a")
    cell_b = _cell(conn, idempotency_key="b")
    r_a = _reserve(conn, cell_a.cell_id, idempotency_key="r-a")
    r_b = _reserve(conn, cell_b.cell_id, idempotency_key="r-b")
    resource_metering.record_usage(
        conn, cell_id=cell_a.cell_id, reservation_id=r_a.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=100, minor_units=100,
        idempotency_key="u-a",
    )
    resource_metering.record_usage(
        conn, cell_id=cell_b.cell_id, reservation_id=r_b.reservation_id,
        resource_type=ResourceType.INPUT_TOKENS, quantity=50, minor_units=50,
        idempotency_key="u-b",
    )
    assert resource_metering.total_quantity_by_type(conn) == {"input_tokens": 150}
