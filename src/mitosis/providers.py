"""Model providers (SPEC.md §24; Charter C14: Cells never receive raw API keys).

This module is the only place in the kernel that touches an external model
API. Charter C14 is enforced structurally rather than by a runtime check:

- A provider reads its credential from the process environment at call time
  and holds it in a local, never on `self`, never in a return value, never in
  a `metadata` dict, and never in anything the gateway persists. Nothing in
  `ModelResponse` can carry it.
- `redact` scrubs anything key-shaped out of provider error text before that
  text reaches the `model_calls` row or an audit event — an SDK exception
  message is the realistic way a credential leaks into a database.
- Cells have no code-execution capability in this kernel (that is Phase 5),
  so there is no Cell-facing path that reaches a provider at all. When that
  changes, this module is the boundary that must stay on the kernel side.

`MockProvider` exists so that the whole gateway path — reserve, execute,
settle, mirror, meter — is exercised in tests and in the golden run without
spending real money (§30.1 "mock before paid APIs"). It is deterministic:
the same request always yields the same response and the same token counts,
which is what keeps `mitosis verify-golden-run` reproducible.

`AnthropicProvider` is the real, paid one. It is imported lazily so the
`anthropic` SDK stays an optional dependency — the kernel, its tests, and
the golden run all run without it installed.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

MOCK_PROVIDER = "mock"
ANTHROPIC_PROVIDER = "anthropic"

# Anthropic keys are `sk-ant-...`; the generic `sk-` form covers the shape most
# other providers use. Deliberately broad: a false-positive redaction in an
# error message costs nothing, a missed key is a persisted credential.
_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b[A-Za-z0-9_\-]{0,8}(?:api[_-]?key|token|secret)[\"'\s:=]+[A-Za-z0-9_\-.]{8,}", re.I),
)

_REDACTED = "[redacted]"


class ProviderError(Exception):
    """Base class. `message` is already redacted by construction."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class ProviderConfigError(ProviderError):
    """The provider cannot be used at all — missing credential, missing SDK,
    unknown model. Raised **before** any external call, so the caller knows
    with certainty that nothing was billed."""


class ProviderCallError(ProviderError):
    """The external call was attempted and failed.

    `execution_unknown` distinguishes the two cases §4.4 cares about: a clean
    rejection (the provider refused the request; nothing was billed) from a
    timeout or dropped connection (the call may or may not have been executed
    and billed). The gateway maps the latter onto the reservation FSM's
    `execution_unknown` state rather than releasing the funds.
    """

    def __init__(self, message: str, *, execution_unknown: bool) -> None:
        super().__init__(message)
        self.execution_unknown = execution_unknown


def redact(text: str) -> str:
    """Scrub anything credential-shaped out of free text before it is stored
    or logged (Charter C14)."""
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class ModelRequest(BaseModel):
    """What a Cell asks the gateway for. Carries no credential — a Cell has no
    way to supply one, which is the point (Charter C14)."""

    model_config = ConfigDict(frozen=True)

    model: str
    messages: tuple[dict[str, Any], ...]
    max_tokens: int
    system: str | None = None


class ModelResponse(BaseModel):
    """What a provider returns. Every field here is safe to persist.

    `resolved_model` and `api_version` are §24.1's `resolved model version` /
    `API version`: what the provider actually served, which may differ from
    what was requested and is how §24.2 provider drift becomes visible.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    resolved_model: str
    api_version: str | None = None
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
    latency_ms: int


class ModelProvider(Protocol):
    """§30.1's "provider-agnostic interfaces" rule. The gateway knows only
    this shape; adding a provider is adding a class and a pricing entry."""

    name: str

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class MockProvider:
    """Deterministic, free, no network. The default provider everywhere except
    an explicit real call."""

    name = MOCK_PROVIDER

    def __init__(self, *, reply: str = "mock reply") -> None:
        self._reply = reply

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.max_tokens <= 0:
            raise ProviderConfigError("max_tokens must be positive")
        # Token counts are a deterministic function of the request, so the same
        # scenario always produces the same cost and the same ledger movement.
        input_tokens = _estimate_tokens(_request_text(request))
        output_tokens = min(_estimate_tokens(self._reply), request.max_tokens)
        return ModelResponse(
            text=self._reply,
            resolved_model=request.model,
            api_version="mock",
            input_tokens=input_tokens,
            output_tokens=max(output_tokens, 1),
            stop_reason="end_turn",
            latency_ms=0,
        )


class AnthropicProvider:
    """The real, paid provider. Spends actual money on every successful call.

    The API key is read from the environment at call time and never leaves
    this method's local scope (Charter C14). `api_key_env` exists so a
    deployment can point at a differently-named variable; the *value* is
    never accepted as an argument, so there is no call site anywhere in the
    kernel that has a key in hand to pass.
    """

    name = ANTHROPIC_PROVIDER

    def __init__(
        self,
        *,
        api_key_env: str = "ANTHROPIC_API_KEY",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def complete(self, request: ModelRequest) -> ModelResponse:
        client = self._client()
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [dict(m) for m in request.messages],
        }
        if request.system is not None:
            kwargs["system"] = request.system

        started = time.monotonic()
        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — mapped onto the reservation FSM below
            raise ProviderCallError(
                f"{type(exc).__name__}: {exc}",
                execution_unknown=_is_execution_unknown(exc),
            ) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return ModelResponse(
            text=text,
            resolved_model=response.model,
            api_version="2023-06-01",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
        )

    def _client(self) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderConfigError(
                "the 'anthropic' package is not installed — "
                "install it with: pip install 'mitosis[anthropic]'"
            ) from exc

        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderConfigError(
                f"{self.api_key_env} is not set — the gateway holds provider "
                "credentials in its own environment, never in the database or "
                "in Cell state (Charter C14)"
            )
        # `api_key` dies with this frame: it is passed straight into the client
        # and never stored on self, returned, or logged.
        return anthropic.Anthropic(api_key=api_key, timeout=self.timeout_seconds)


def _is_execution_unknown(exc: Exception) -> bool:
    """True when the call may have reached the provider and been billed.

    Conservative by design: anything that isn't a clean, definitely-unbilled
    rejection is treated as unknown, because wrongly releasing a reservation
    for a call that *was* billed loses real money silently, while wrongly
    holding one is visible and reconcilable (§4.4, Charter C7).
    """
    name = type(exc).__name__
    definitely_not_billed = {
        "BadRequestError",  # 400 — provider rejected the request outright
        "AuthenticationError",  # 401
        "PermissionDeniedError",  # 403
        "NotFoundError",  # 404 — e.g. unknown model id
        "UnprocessableEntityError",  # 422
    }
    return name not in definitely_not_billed


def _request_text(request: ModelRequest) -> str:
    parts = [request.system or ""]
    for message in request.messages:
        content = message.get("content", "")
        parts.append(content if isinstance(content, str) else str(content))
    return "\n".join(parts)


def _estimate_tokens(text: str) -> int:
    """A deliberately **conservative over-estimate** of the token count, used
    for pre-call budgeting only (never for billing — billing uses the
    provider's reported usage).

    Real tokenizers average roughly 4 characters per token; this assumes 2,
    plus a fixed per-call overhead. Over-estimating is the safe direction: the
    gateway reserves more than the call can cost, and the excess is released
    at settlement. Under-estimating would let a call settle above its
    reservation, which Charter C4 forbids.

    Deferred: the provider's own `count_tokens` endpoint gives an exact
    figure and would tighten the reservation considerably. It is a second
    network round-trip per call, so it is out of scope for this slice.
    """
    return max(len(text) // 2, 1) + 16
