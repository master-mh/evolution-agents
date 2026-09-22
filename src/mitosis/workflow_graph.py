"""The self-critique loop's control flow, as a LangGraph state graph (ADR-103).

`deliberation` owns every call a wake makes — each is its own gateway
reservation on its own idempotency key (Charter C4, C6). This module owns only
*which step runs next*. It is handed two step functions and never sees a
connection, a provider, a reservation or a genome, and it imports nothing from
the kernel: `test_the_graph_module_imports_nothing_from_the_kernel` pins that,
so the framework has no path to money even by accident.

    START → critique ─keep / no verdict──────────────→ END
               ↑  └─revise→ revise ─no proposal────────→ END
               │               ├─revision cap reached──→ END
               └───────────────┘ (another round)

**No checkpointer, on purpose.** LangGraph can persist a graph's state
between steps so a crashed run resumes. MITOSIS already has that property, one
level lower and stronger: every step's call is keyed
`deliberation:{wake_key}:workflow:{step}`, so a redelivered wake replays the
calls it already paid for and — the replies being identical — walks the same
path to the same place. A second persistence layer would be a second answer
to "where did this wake get to" (§2.5), and a durable workflow engine is a
deferred hook (§17.5), not a Phase 4 part. The graph runs in memory, once, per
wake.

**Two bounds, not one.** `max_revisions` is the designed bound: at most
`2 * max_revisions` calls. `recursion_limit` is LangGraph's own step budget,
set just above it, so a wiring mistake that loops raises instead of billing.

**LangGraph is optional** (`pip install 'mitosis[langgraph]'`, §19.3's
dependency allowlist): this module imports without it, and `build` raises
`GraphUnavailable` naming the extra — the `anthropic` provider's pattern.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Literal, TypedDict


class GraphUnavailable(Exception):
    pass


KEEP = "keep"
REVISE = "revise"

STOP_KEPT = "kept"
STOP_STEP_FAILED = "step_failed"
STOP_REVISION_CAP = "revision_cap"


@dataclass(frozen=True)
class Verdict:
    verdict: Literal["keep", "revise"]
    issues: tuple[str, ...] = ()


#: `(current proposal, round) -> (verdict or None, opaque step record)`.
Critique = Callable[[Any, int], tuple[Verdict | None, Any]]
#: `(current proposal, issues, round) -> (revised proposal or None, step record)`.
Revise = Callable[[Any, tuple[str, ...], int], tuple[Any | None, Any]]


class _State(TypedDict):
    current: Any
    round: int
    revisions: int
    issues: tuple[str, ...]
    stopped: str | None
    #: A reducer: each node returns only its own step, LangGraph appends.
    steps: Annotated[list, operator.add]


@dataclass(frozen=True)
class LoopResult:
    #: The last revision that validated, or `None` when the draft was kept.
    final: Any | None
    steps: list
    revisions: int
    stopped: str


def build(critique: Critique, revise: Revise, *, max_revisions: int):
    if max_revisions < 1:
        raise ValueError("max_revisions must be at least 1")
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise GraphUnavailable(
            "the 'langgraph' package is not installed — install it with: "
            "pip install 'mitosis[langgraph]'"
        ) from exc

    def critique_node(state: _State) -> dict:
        verdict, step = critique(state["current"], state["round"])
        if verdict is not None and verdict.verdict == REVISE:
            return {"steps": [step], "issues": verdict.issues}
        return {"steps": [step], "stopped": STOP_KEPT if verdict is not None else STOP_STEP_FAILED}

    def revise_node(state: _State) -> dict:
        proposal, step = revise(state["current"], state["issues"], state["round"])
        if proposal is None:
            return {"steps": [step], "stopped": STOP_STEP_FAILED}
        revisions = state["revisions"] + 1
        return {
            "steps": [step],
            "current": proposal,
            "revisions": revisions,
            "round": state["round"] + 1,
            "stopped": STOP_REVISION_CAP if revisions >= max_revisions else None,
        }

    def next_after(node: str) -> Callable[[_State], str]:
        return lambda state: END if state["stopped"] is not None else node

    graph = StateGraph(_State)
    graph.add_node("critique", critique_node)
    graph.add_node("revise", revise_node)
    graph.add_edge(START, "critique")
    graph.add_conditional_edges("critique", next_after("revise"), ["revise", END])
    graph.add_conditional_edges("revise", next_after("critique"), ["critique", END])
    return graph.compile()


def run_critique_loop(
    *, draft: Any, critique: Critique, revise: Revise, max_revisions: int
) -> LoopResult:
    state = build(critique, revise, max_revisions=max_revisions).invoke(
        {"current": draft, "round": 0, "revisions": 0, "issues": (), "stopped": None, "steps": []},
        config={"recursion_limit": 2 * max_revisions + 2, "run_name": "self_critique_loop"},
    )
    return LoopResult(
        final=state["current"] if state["revisions"] else None,
        steps=state["steps"],
        revisions=state["revisions"],
        stopped=state["stopped"],
    )


def mermaid(*, max_revisions: int = 2) -> str:
    """The compiled graph's own diagram — docs draw from this, not a hand copy."""
    return build(lambda *_: (None, None), lambda *_: (None, None), max_revisions=max_revisions
                 ).get_graph().draw_mermaid()
