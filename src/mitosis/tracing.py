"""Opt-in LangSmith tracing — a view of what a wake did, never a record of it
(SPEC.md §19.3 "network disabled by default", §2.5; ADR-104).

A trace ships a wake's prompts, replies and proposals to a third-party server.
§19.3 puts network *off by default*, so tracing is off unless the operator
opts in, in their own shell, with both:

    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=<their key>

and `LANGSMITH_PROJECT` names the project (default `my-first-agent`).

**Off is enforced, not assumed.** LangSmith and LangGraph each read several
environment variables of their own (`LANGCHAIN_TRACING_V2` among them), so a
variable exported for some other project would otherwise switch tracing on
here. Every span opens an explicit `tracing_context(enabled=...)` carrying
*this module's* decision, which overrides all of them.

**Three things force it off even when opted in:**

- an active `network_seal.sealed()` block — a sealed run has promised it
  cannot reach outside the interpreter, and LangSmith's uploader is outside;
- a `suppressed()` block — the golden run, whose replay must never depend on
  or leak to an external service;
- the `langsmith` package being absent — every span is then a no-op.

**Why a trace is never read back.** `model_calls`, the ledger and the audit
log are the record. A trace is a copy shipped elsewhere; nothing in the kernel
reads one, so a lost or delayed upload changes no outcome, and a second answer
to "what did this wake cost?" cannot drift from the first (§2.5).

**Why a tracing fault is swallowed.** The gateway opens a span *after* it has
committed a reservation. An observability library raising there would strand
that reservation — so opening or closing a span may fail silently, while an
exception from the traced code itself always propagates unchanged.
"""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from . import network_seal

TRACING_ENV = "LANGSMITH_TRACING"
API_KEY_ENV = "LANGSMITH_API_KEY"
PROJECT_ENV = "LANGSMITH_PROJECT"
DEFAULT_PROJECT = "my-first-agent"

_suppressed: ContextVar[bool] = ContextVar("mitosis_tracing_suppressed", default=False)


def _langsmith():
    try:
        import langsmith
    except ImportError:
        return None
    return langsmith


def enabled() -> bool:
    return (
        os.environ.get(TRACING_ENV, "").strip().lower() == "true"
        and bool(os.environ.get(API_KEY_ENV, "").strip())
        and not network_seal.is_sealed()
        and not _suppressed.get()
        and _langsmith() is not None
    )


def project() -> str:
    return os.environ.get(PROJECT_ENV, "").strip() or DEFAULT_PROJECT


@contextmanager
def suppressed() -> Iterator[None]:
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


class Span:
    def __init__(self, run: Any = None) -> None:
        self._run = run

    @property
    def recording(self) -> bool:
        return self._run is not None

    def finish(self, outputs: dict[str, Any]) -> None:
        if self._run is None:
            return
        try:
            self._run.end(outputs=outputs)
        except Exception:
            pass


@contextmanager
def span(
    name: str,
    *,
    run_type: str = "chain",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """A LangSmith run around the block when tracing is on; otherwise a no-op
    that still pins tracing *off* for anything nested inside (LangGraph)."""
    langsmith = _langsmith()
    if langsmith is None:
        yield Span()
        return
    on = enabled()
    with ExitStack() as stack:
        run = None
        try:
            stack.enter_context(
                langsmith.tracing_context(enabled=on, project_name=project() if on else None)
            )
            if on:
                run = stack.enter_context(
                    langsmith.trace(
                        name, run_type=run_type, inputs=inputs or {}, metadata=metadata or {},
                    )
                )
        except Exception:
            run = None
        yield Span(run)
