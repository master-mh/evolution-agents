"""OllamaProvider: locally-hosted inference (SPEC.md §30.1 provider-agnostic
interfaces; Charter C14).

No live Ollama is required — every test drives the HTTP layer through a stub,
the same way the paid provider is tested without spending money. What matters
here is the mapping: Ollama names things differently from every hosted API
(`num_predict`, `prompt_eval_count`, `eval_count`), and getting that wrong
silently corrupts A6 metering rather than failing loudly.
"""

from __future__ import annotations

import io
import json
import urllib.error
from contextlib import contextmanager
from unittest import mock

import pytest

from mitosis import pricing, providers


def _request(**kwargs):
    return providers.ModelRequest(
        **{
            "model": "llama3.2",
            "messages": ({"role": "user", "content": "hello"},),
            "max_tokens": 128,
            **kwargs,
        }
    )


@contextmanager
def _ollama_returns(body: dict, capture: list | None = None):
    """Stub urlopen with a canned Ollama response, capturing the request."""

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture.append({"url": req.full_url, "payload": json.loads(req.data.decode())})
        return _Response(json.dumps(body).encode())

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        yield


@contextmanager
def _ollama_raises(exc):
    def fake_urlopen(req, timeout=None):
        raise exc

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        yield


_OK_BODY = {
    "model": "llama3.2:latest",
    "message": {"role": "assistant", "content": "hi there"},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 17,
    "eval_count": 5,
}


def test_maps_ollama_usage_fields_onto_the_model_response():
    with _ollama_returns(_OK_BODY):
        response = providers.OllamaProvider().complete(_request())

    assert response.text == "hi there"
    assert response.input_tokens == 17
    assert response.output_tokens == 5
    assert response.stop_reason == "stop"
    assert response.api_version == "ollama"
    # §24.2 drift: the tag Ollama actually served, not the alias requested.
    assert response.resolved_model == "llama3.2:latest"


def test_max_tokens_becomes_num_predict():
    """The gateway reserves against `max_tokens`; if this does not reach Ollama
    the model can generate past its metered RESOURCE budget."""
    seen: list = []
    with _ollama_returns(_OK_BODY, capture=seen):
        providers.OllamaProvider().complete(_request(max_tokens=64))

    assert seen[0]["payload"]["options"]["num_predict"] == 64
    assert seen[0]["payload"]["stream"] is False


def test_temperature_reaches_ollamas_options_only_when_the_request_carries_one():
    """§14.1's sampling mutation, read from a Cell's genome (ADR-067), maps
    onto Ollama's `options` the same way `max_tokens` already does. Its
    absence must not send a `temperature: null` that overrides Ollama's own
    default (0.8) with something that reads as 0."""
    seen: list = []
    with _ollama_returns(_OK_BODY, capture=seen):
        providers.OllamaProvider().complete(_request(temperature=0.2))
    assert seen[0]["payload"]["options"]["temperature"] == 0.2

    seen.clear()
    with _ollama_returns(_OK_BODY, capture=seen):
        providers.OllamaProvider().complete(_request())
    assert "temperature" not in seen[0]["payload"]["options"]


def test_system_prompt_is_prepended_as_a_message():
    seen: list = []
    with _ollama_returns(_OK_BODY, capture=seen):
        providers.OllamaProvider().complete(_request(system="be terse"))

    messages = seen[0]["payload"]["messages"]
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert messages[1]["content"] == "hello"


def test_missing_usage_counters_meter_as_zero_rather_than_crashing():
    """Ollama omits `prompt_eval_count` on a fully cached prompt. Zero recorded
    tokens is true and lets the RESOURCE reservation release; a crash here would
    strand it."""
    with _ollama_returns({"message": {"content": "cached"}, "done": True}):
        response = providers.OllamaProvider().complete(_request())

    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.text == "cached"


def test_unreachable_server_is_a_config_error_naming_the_fix():
    with _ollama_raises(urllib.error.URLError("Connection refused")):
        with pytest.raises(providers.ProviderConfigError) as exc:
            providers.OllamaProvider().complete(_request())

    assert "ollama serve" in str(exc.value)


def test_unpulled_model_is_a_config_error_naming_the_pull():
    err = urllib.error.HTTPError("u", 404, "not found", {}, io.BytesIO(b"model not found"))
    with _ollama_raises(err):
        with pytest.raises(providers.ProviderConfigError) as exc:
            providers.OllamaProvider().complete(_request(model="mistral"))

    assert "ollama pull mistral" in str(exc.value)


@pytest.mark.parametrize("status", [400, 500, 503])
def test_no_ollama_failure_is_ever_execution_unknown(status):
    """A local provider cannot bill, so its USD_REAL exposure is structurally
    zero. Freezing funds pending reconciliation would park money against an
    invoice that can never exist — a deliberate departure from
    `_is_execution_unknown`'s conservatism, and the reason it is pinned here."""
    err = urllib.error.HTTPError("u", status, "boom", {}, io.BytesIO(b"boom"))
    with _ollama_raises(err):
        with pytest.raises(providers.ProviderCallError) as exc:
            providers.OllamaProvider().complete(_request())

    assert exc.value.execution_unknown is False


def test_timeout_is_not_execution_unknown_either():
    with _ollama_raises(TimeoutError("timed out")):
        with pytest.raises(providers.ProviderCallError) as exc:
            providers.OllamaProvider().complete(_request())
    assert exc.value.execution_unknown is False


def test_non_positive_max_tokens_is_rejected_before_any_call():
    called = []
    with _ollama_returns(_OK_BODY, capture=called):
        with pytest.raises(providers.ProviderConfigError):
            providers.OllamaProvider().complete(_request(max_tokens=0))
    assert called == [], "rejected before the request left the process"


def test_host_comes_from_the_environment_and_is_not_a_credential(monkeypatch):
    provider = providers.OllamaProvider()
    assert provider.host == "http://localhost:11434"

    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434/")
    assert provider.host == "http://gpu-box:11434", "trailing slash trimmed"

    seen: list = []
    with _ollama_returns(_OK_BODY, capture=seen):
        provider.complete(_request())
    assert seen[0]["url"] == "http://gpu-box:11434/api/chat"


def test_ollama_carries_no_credential_anywhere_in_its_surface():
    """Charter C14 in its cleanest form: there is no key to leak. Nothing on the
    provider names one, and no argument accepts one."""
    provider = providers.OllamaProvider()
    surface = " ".join(dir(provider)) + " " + json.dumps(provider.__dict__)
    for forbidden in ("api_key", "token", "secret", "password"):
        assert forbidden not in surface.lower()


def test_every_registered_ollama_model_is_priced_at_zero():
    """Local inference has no per-call marginal cost. A nonzero price here would
    be a fiction that the USD_REAL ledger would then treat as real spend."""
    models = pricing.known_models(providers.OLLAMA_PROVIDER)
    assert models, "no ollama models registered"
    for model in models:
        price = pricing.get_price(providers.OLLAMA_PROVIDER, model)
        assert price.input_usd_per_mtok == 0
        assert price.output_usd_per_mtok == 0


def test_a_local_call_costs_no_usd_real_but_still_meters_resource(conn):
    """The whole point of the local provider: the creative loop runs without
    touching Charter C5's caps, while Amendment A6 metering still bounds it.
    Free in money is not free in compute."""
    from mitosis import gateway, ledger, lifecycle, real_spend_breaker, resource_metering
    from mitosis.accounts import cell_cash
    from mitosis.models import Book, CellType, EntrySpec

    real_spend_breaker.configure_if_absent(conn)
    cell = lifecycle.create_cell(
        conn,
        cell_type=CellType.EXPLORER,
        budget_minor_units=100,
        book=Book.USD_REAL,
        idempotency_key="ollama-cell",
    )
    for book, amount in ((Book.RESOURCE, 10_000), (Book.USD_SIM, 500)):
        ledger.post_transaction(
            conn,
            book=book,
            currency=book.value,
            transaction_type="test_funding",
            idempotency_key=f"fund:{book.value}",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount),
                EntrySpec(
                    account_id=cell_cash(cell.cell_id),
                    amount_minor_units=amount,
                    cell_id=cell.cell_id,
                ),
            ],
        )

    cash_before = ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL)
    with _ollama_returns(_OK_BODY):
        call = gateway.call_model(
            conn,
            cell_id=cell.cell_id,
            provider=providers.OllamaProvider(),
            request=_request(),
            idempotency_key="local-1",
        )

    assert call.status.value == "succeeded"
    assert call.cost_actual_micro_usd == 0
    assert call.settled_minor_units == 0
    # Not one cent of USD_REAL moved, and the breaker never saw it.
    assert ledger.get_balance(conn, cell_cash(cell.cell_id), Book.USD_REAL) == cash_before
    assert real_spend_breaker.snapshot(conn).spend_last_hour_minor_units == 0

    # But the provider's *reported* token counts are metered, not estimates.
    usage = resource_metering.usage_by_type(conn, call.resource_reservation_id)
    assert usage["input_tokens"] == 17
    assert usage["output_tokens"] == 5
    assert ledger.verify_conservation(conn, Book.USD_REAL)
    assert ledger.verify_chain(conn)


def test_unregistered_ollama_model_fails_loudly_rather_than_pricing_at_zero():
    """The friction is deliberate: an Ollama-compatible endpoint can front a
    *paid* hosted model, and a zero-by-wildcard rule would blind Charter C5's
    caps to real spend."""
    with pytest.raises(pricing.UnknownModelError, match="no price for model"):
        pricing.get_price(providers.OLLAMA_PROVIDER, "some-unpulled-model")
