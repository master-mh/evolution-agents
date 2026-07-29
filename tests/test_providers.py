"""Providers (SPEC.md §24; Charter C14: Cells never receive raw API keys)."""

from __future__ import annotations

import pytest

from mitosis import providers


class _Boom(Exception):
    pass


def test_mock_provider_is_deterministic():
    """The golden run depends on this: same request, same tokens, same cost."""
    request = providers.ModelRequest(
        model="mock-1", messages=({"role": "user", "content": "hello"},), max_tokens=32
    )
    first = providers.MockProvider().complete(request)
    second = providers.MockProvider().complete(request)
    assert first.model_dump() == second.model_dump()


def test_mock_provider_output_respects_max_tokens():
    request = providers.ModelRequest(
        model="mock-1",
        messages=({"role": "user", "content": "hello"},),
        max_tokens=1,
    )
    assert providers.MockProvider(reply="a very long reply " * 50).complete(
        request
    ).output_tokens <= 1


def test_mock_provider_rejects_non_positive_max_tokens():
    with pytest.raises(providers.ProviderConfigError):
        providers.MockProvider().complete(
            providers.ModelRequest(
                model="mock-1", messages=({"role": "user", "content": "x"},), max_tokens=0
            )
        )


@pytest.mark.parametrize(
    "text",
    [
        "AuthenticationError: invalid key sk-ant-api03-AAAAAAAAAAAAAAAAAAAA",
        "sk-proj-BBBBBBBBBBBBBBBBBBBBBBBB failed",
        'config: {"api_key": "CCCCCCCCCCCCCCCC"}',
        "Bearer token=DDDDDDDDDDDDDDDDDD rejected",
    ],
)
def test_redaction_scrubs_credential_shaped_text(text):
    """Charter C14. An SDK exception message is the realistic way a credential
    reaches the database, so redaction happens before anything is persisted."""
    redacted = providers.redact(text)
    assert "[redacted]" in redacted
    for secret in ("sk-ant-api03-AAAAAAAAAAAAAAAAAAAA", "sk-proj-BBBBBBBBBBBBBBBBBBBBBBBB",
                   "CCCCCCCCCCCCCCCC", "DDDDDDDDDDDDDDDDDD"):
        assert secret not in redacted


def test_provider_errors_redact_their_own_message():
    exc = providers.ProviderCallError(
        "boom sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZ", execution_unknown=True
    )
    assert "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZ" not in str(exc)


def test_redaction_leaves_ordinary_text_alone():
    assert providers.redact("rate limited, retry in 30s") == "rate limited, retry in 30s"


@pytest.mark.parametrize(
    ("exc_name", "expected_unknown"),
    [
        ("BadRequestError", False),
        ("AuthenticationError", False),
        ("PermissionDeniedError", False),
        ("NotFoundError", False),
        ("UnprocessableEntityError", False),
        ("APITimeoutError", True),
        ("APIConnectionError", True),
        ("InternalServerError", True),
        ("RateLimitError", True),
        ("SomethingNobodyAnticipated", True),
    ],
)
def test_execution_unknown_classification_is_conservative(exc_name, expected_unknown):
    """Anything that isn't a definitely-unbilled rejection counts as unknown:
    wrongly releasing a reservation for a call that *was* billed loses real
    money silently (§4.4, Charter C7)."""
    exc = type(exc_name, (Exception,), {})("boom")
    assert providers._is_execution_unknown(exc) is expected_unknown


def test_anthropic_provider_never_stores_the_key_on_itself():
    """Charter C14 structurally: there is no attribute, argument, or return
    value anywhere on this object that can carry a credential."""
    provider = providers.AnthropicProvider()
    assert "api_key" not in vars(provider)
    assert all("key" not in str(v).lower() or v == "ANTHROPIC_API_KEY" for v in vars(provider).values())


def test_anthropic_provider_fails_before_calling_when_key_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pytest.importorskip("anthropic")
    with pytest.raises(providers.ProviderConfigError, match="not set"):
        providers.AnthropicProvider().complete(
            providers.ModelRequest(
                model="claude-opus-5",
                messages=({"role": "user", "content": "x"},),
                max_tokens=8,
            )
        )


def test_model_request_carries_no_credential_field():
    """A Cell builds a ModelRequest; if a credential could ride on one, C14
    would depend on convention rather than on the type."""
    assert "api_key" not in providers.ModelRequest.model_fields
    assert "credential" not in providers.ModelRequest.model_fields


def test_token_estimate_is_an_over_estimate():
    """The gateway reserves against this figure, so it must sit above any
    plausible real tokenization (~4 chars/token) — under-reserving would let a
    call settle above its reservation, which Charter C4 forbids."""
    for text in ("hello", "x" * 400, "the quick brown fox " * 20):
        realistic = len(text) / 4
        assert providers._estimate_tokens(text) > realistic
