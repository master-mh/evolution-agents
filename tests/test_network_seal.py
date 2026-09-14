"""A simulated run cannot reach outside the interpreter (SPEC.md §7.1, §0.4,
§19.3; ADR-085).

The flight simulator's zero-external-effect claim used to rest on which
provider `runner.run` happened to construct. These tests put a real listener on
the loopback interface and try to reach it from inside a run through three
paths — an epoch hook, a child process, and a model provider — and require that
**no connection ever arrives**. Asserting on the listener rather than on an
exception is the point: a refusal that was caught and retried somewhere would
still pass an exception test, but not this one.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import urllib.request

import pytest

from mitosis import db, network_seal
from mitosis.simulation import policy, runner
from mitosis.simulation.environment import EnvironmentSuite, UtilityMaximizingMarket


@pytest.fixture
def listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(0.3)
    yield server
    server.close()


def _connections_received(server: socket.socket) -> int:
    received = 0
    while True:
        try:
            conn, _ = server.accept()
        except (socket.timeout, TimeoutError):
            return received
        conn.close()
        received += 1


def _run(epoch_hook=None, *, epochs=3):
    conn = db.connect_and_migrate()
    try:
        return runner.run(
            conn,
            runner.RunConfig(scenario_name="sealed", master_seed=3, epochs=epochs, population=3),
            suite=EnvironmentSuite.training_only(UtilityMaximizingMarket()),
            epoch_hook=epoch_hook,
        )
    finally:
        conn.close()


def test_an_epoch_hook_cannot_open_a_connection_from_inside_a_run(listener):
    port = listener.getsockname()[1]

    def reach_out(_conn, _epoch):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()

    manifest = _run(reach_out)
    assert _connections_received(listener) == 0
    assert len(manifest.failures) == 3
    assert all("network sealed" in failure for failure in manifest.failures)


def test_a_run_cannot_start_a_child_process():
    def shell_out(_conn, _epoch):
        subprocess.run([sys.executable, "-c", "pass"], check=True)

    manifest = _run(shell_out, epochs=1)
    assert manifest.failures and "subprocess.Popen" in manifest.failures[0]


def test_a_model_provider_that_reaches_the_network_gets_nothing_through(listener, monkeypatch):
    """The incident's shape: the component that should have been offline is
    wired to something real. Here the simulator's own provider is replaced by
    one that makes an HTTP call before answering — and the run is still sealed,
    because the seal does not care which object was wired in."""
    port = listener.getsockname()[1]
    original = policy.SimulationPolicyProvider.complete

    def calls_home(self, request):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
        return original(self, request)

    monkeypatch.setattr(policy.SimulationPolicyProvider, "complete", calls_home)
    manifest = _run(epochs=2)
    assert _connections_received(listener) == 0
    assert all(manifest.conservation_ok.values())
    assert manifest.usd_real_spend_unchanged


def test_the_seal_lifts_when_the_run_ends(listener):
    port = listener.getsockname()[1]
    _run(epochs=1)
    assert not network_seal.is_sealed()
    socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert _connections_received(listener) == 1
    subprocess.run([sys.executable, "-c", "pass"], check=True)


def test_seals_nest_and_lift_on_exception(listener):
    port = listener.getsockname()[1]
    with pytest.raises(ValueError):
        with network_seal.sealed(reason="outer"):
            with network_seal.sealed(reason="inner"):
                pass
            # The inner block ending must not unseal the outer one.
            with pytest.raises(network_seal.NetworkSealed, match="outer"):
                socket.create_connection(("127.0.0.1", port), timeout=1)
            raise ValueError("leaving by exception")
    assert not network_seal.is_sealed()
    socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert _connections_received(listener) == 1


def test_an_unsealed_process_is_untouched(listener):
    """The hook is installed for the life of the process once any run seals —
    it must be inert outside a sealed block, or every later test and CLI verb
    in the same interpreter would inherit the refusal."""
    with network_seal.sealed(reason="install the hook"):
        pass
    port = listener.getsockname()[1]
    socket.create_connection(("127.0.0.1", port), timeout=1).close()
    assert _connections_received(listener) == 1


# --- a sealed refusal is known to be unbilled ---------------------------------


class _SocketProvider:
    """Priced like the real paid provider, and reaches for the network
    without catching anything — the worst-behaved provider a run could be
    wired to by mistake."""

    name = "anthropic"

    def __init__(self, port: int) -> None:
        self.port = port

    def complete(self, request):
        socket.create_connection(("127.0.0.1", self.port), timeout=1)
        raise AssertionError("the seal should have refused the connection")


def _funded_cell(conn):
    from mitosis import ledger, lifecycle, real_spend_breaker
    from mitosis.accounts import cell_cash
    from mitosis.models import Book, CellType, EntrySpec, RealSpendLimits

    real_spend_breaker.configure_if_absent(conn)
    real_spend_breaker.set_limits(conn, RealSpendLimits(
        per_request_minor_units=500, per_hour_minor_units=5_000, per_day_minor_units=50_000,
        per_month_minor_units=500_000, max_concurrent_reserved_minor_units=5_000, provider_limits={},
    ))
    cell = lifecycle.create_cell(
        conn, cell_type=CellType.EXPLORER, budget_minor_units=1_000, book=Book.USD_REAL,
        idempotency_key="sealed-cell",
    )
    ledger.post_transaction(
        conn, book=Book.RESOURCE, currency="RESOURCE", transaction_type="test_funding",
        idempotency_key="fund:sealed:RESOURCE",
        entries=[EntrySpec(account_id="seed_bank", amount_minor_units=-10_000_000),
                 EntrySpec(account_id=cell_cash(cell.cell_id), amount_minor_units=10_000_000)],
    )
    return cell


def test_a_sealed_refusal_releases_both_reservations_instead_of_stranding_them(listener):
    """Uncaught, the refusal would escape `gateway.call_model` with both
    reservations committed, and the sweeper would later have to guess at an
    outcome that was never in doubt. The gateway maps it onto the one
    definitely-unbilled path instead (ADR-085)."""
    from mitosis import gateway, ledger, providers
    from mitosis.accounts import cell_committed
    from mitosis.models import Book, ModelCallStatus, ReservationStatus

    conn = db.connect_and_migrate()
    try:
        cell = _funded_cell(conn)
        with network_seal.sealed(reason="test"):
            call = gateway.call_model(
                conn, cell_id=cell.cell_id, provider=_SocketProvider(listener.getsockname()[1]),
                request=providers.ModelRequest(
                    model="claude-opus-5", messages=({"role": "user", "content": "hi"},), max_tokens=50,
                ),
                idempotency_key="sealed-call",
            )
        assert call.status is ModelCallStatus.FAILED
        statuses = {row["status"] for row in conn.execute("SELECT status FROM reservations")}
        assert statuses == {ReservationStatus.RELEASED.value}
        for book in (Book.USD_REAL, Book.RESOURCE):
            assert ledger.get_balance(conn, cell_committed(cell.cell_id), book) == 0
        assert all(ledger.verify_conservation(conn, book) for book in Book)
    finally:
        conn.close()
    assert _connections_received(listener) == 0


def test_an_sdk_wrapped_sealed_refusal_is_definitely_unbilled_and_nothing_else_changes():
    """A paid SDK may wrap the refusal in its own connection error. Only the
    seal's cause is exempted from the conservative default — an unrelated
    connection error still counts as possibly billed."""
    from mitosis import providers

    class APIConnectionError(Exception):
        pass

    try:
        try:
            raise network_seal.NetworkSealed("network sealed (test): refused socket.connect")
        except network_seal.NetworkSealed as inner:
            raise APIConnectionError("Connection error.") from inner
    except APIConnectionError as wrapped:
        assert providers._is_execution_unknown(wrapped) is False

    assert providers._is_execution_unknown(APIConnectionError("Connection error.")) is True
