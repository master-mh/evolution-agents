"""A deterministic, seeded, non-LLM Cell-policy family (SPEC.md §7.1, §7.3;
implementation brief Slice F's "deterministic Cell policies").

`SimulationPolicyProvider` implements `providers.ModelProvider` so it plugs
into `deliberation.deliberate()`/`scheduler.tick()` completely unchanged
(this repo's own dependency-inversion seam, confirmed by reading
`deliberation.py`: it holds zero references to any concrete provider class).
It is a sibling of `MockProvider`, not an extension of it -- `MockProvider`
has no seed and returns the same fixed reply forever (`providers.py`), which
is exactly wrong for a policy whose whole point is to vary its decision.

**Deliberately stateless with respect to *which Cell* is calling.** The
`ModelProvider` Protocol carries no Cell identity: `ModelRequest` has no
`cell_id` field, and the rendered prompt names no Cell identifier either --
only its genome content (`context._genome_section`), which two Cells can
share right after birth, before either has mutated. Keying every decision on
the genome content actually shown *this call*, plus a monotonic per-provider
call counter, gives the reproducibility the brief actually asks for (same
seed -> same sequence of calls -> same replies) without needing an identity
the interface does not provide.
"""

from __future__ import annotations

import json
import random

from .. import genome as genome_module
from ..deliberation import WAKE_SCHEDULED_RESEARCH
from ..proposal import MAX_HYPOTHESIS_CHARS
from ..providers import ModelRequest, ModelResponse

SIMULATION_PROVIDER = "simulation"
POLICY_MODEL_ID = "policy-v1"
#: "2" (ADR-095): proposes on its research cycle only and abstains on every
#: other wake. Version 1 proposed on every wake, and every approval earns a
#: `human decision` wake (§17.2), so each approval bred another proposal: 20
#: deliberations in epoch 0 became 116 by epoch 6, and the flood tripped
#: §23.4's queue-flooding signal on every lineage.
POLICY_VERSION = "2"

#: The exact section headers `context` renders (verbatim strings, not regexes)
#: -- see `_genome_section`'s and `_wake_section`'s `Section(name=...)`.
_GENOME_SECTION_HEADER = "## Your genome (immutable; this is who you are)\n"
_WAKE_SECTION_HEADER = "## Why you were woken\n"
_SECTION_BOUNDARY = "\n\n## "


class PolicyError(Exception):
    pass


def _request_text(request: ModelRequest) -> str:
    return "\n".join(str(m.get("content", "")) for m in request.messages)


def _section_body(prompt_text: str, header: str, *, renderer: str) -> str:
    start = prompt_text.find(header)
    if start == -1:
        raise PolicyError(
            f"rendered context carries no {header.strip()!r} section -- "
            f"context.{renderer}'s header text must have changed"
        )
    body_start = start + len(header)
    end = prompt_text.find(_SECTION_BOUNDARY, body_start)
    return prompt_text[body_start:] if end == -1 else prompt_text[body_start:end]


def _extract_genome(prompt_text: str) -> dict:
    return json.loads(_section_body(prompt_text, _GENOME_SECTION_HEADER, renderer="_genome_section"))


def _extract_wake_reason(prompt_text: str) -> str:
    return _section_body(prompt_text, _WAKE_SECTION_HEADER, renderer="_wake_section").strip()


def _abstain(wake_reason: str) -> dict:
    """What a mock Cell says on any wake but its research cycle. A follow-up
    wake (`human decision`, an expiry, an allocation) tells the Cell something
    happened; it is not an invitation to ask for more, and the research cycle
    one epoch later asks again anyway. ADR-055 measured a live model treating an
    unjustified wake as a reason to act; this policy is simply not built to."""
    return {
        "kind": "abstain",
        "summary": "nothing new to propose on this wake",
        "rationale": (
            f"flight-simulator policy: woken for {wake_reason!r}, not a research cycle -- "
            "proposals come from the research cycle only"
        )[:200],
        "estimated_cost_minor_units": 0,
        "predictions": [],
    }


def _label(value: object, field: str) -> str | None:
    if isinstance(value, dict):
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _propose(canonical_genome: dict, rng: random.Random) -> dict:
    """One `ProposalKind.EXPERIMENT` reply (SPEC.md §25.1 rung 1, "flight
    simulator" -- `experiment_grants.FLIGHT_SIMULATOR_RUNG`, a label that has
    sat unused since migration 0013 and is exactly what this policy fills).

    Deliberately not a `spend_request`: `approval._kernel_tier` floors that
    kind at MEDIUM regardless of claimed tier (established while wiring
    ADR-071's auto-promotion into `tick`), so it can never be `batchable` and
    would need a second, hand-rolled approval decider. `_kernel_tier` never
    touches EXPERIMENT, so a LOW-claimed, reversible, signal-free one already
    satisfies `RequestStatus.batchable` and is auto-approved by the exact
    `autopromotion.sweep()` batch step ADR-071 wired into `scheduler.tick` --
    reusing that wiring rather than inventing a parallel one.
    """
    market_label = _label(canonical_genome.get("market"), "segment") or "the market"
    product_label = _label(canonical_genome.get("product"), "name") or "the product"
    hypothesis = (
        f"selling {product_label} to {market_label} produces a sale this epoch "
        f"(policy draw {rng.random():.6f})"
    )[:MAX_HYPOTHESIS_CHARS]
    return {
        "kind": "experiment",
        "summary": f"probe {market_label} for {product_label}",
        "rationale": "flight-simulator policy: probe the genome's declared market/product pairing",
        "risk_tier": "LOW",
        "estimated_cost_minor_units": 0,
        "predictions": [],
        "experiment": {"hypothesis": hypothesis},
    }


class SimulationPolicyProvider:
    name = SIMULATION_PROVIDER

    def __init__(self, *, master_seed: int) -> None:
        self._master_seed = master_seed
        self._call_index = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        prompt_text = _request_text(request)
        canonical_genome = _extract_genome(prompt_text)
        wake_reason = _extract_wake_reason(prompt_text)
        genome_hash = genome_module.compute_genome_hash(canonical_genome)
        # A tuple is not an accepted `random.Random` seed type -- a stable
        # string is, and (unlike `hash()`) its seeding does not depend on
        # `PYTHONHASHSEED`, so this reproduces across separate processes.
        rng = random.Random(f"{self._master_seed}:policy:{genome_hash}:{self._call_index}")
        self._call_index += 1

        reply = (
            _propose(canonical_genome, rng) if wake_reason == WAKE_SCHEDULED_RESEARCH
            else _abstain(wake_reason)
        )
        text = json.dumps(reply)
        return ModelResponse(
            text=text,
            resolved_model=request.model,
            api_version=f"simulation-policy-{POLICY_VERSION}",
            input_tokens=max(len(prompt_text) // 4, 1),
            output_tokens=max(len(text) // 4, 1),
            stop_reason="end_turn",
            latency_ms=0,
        )
