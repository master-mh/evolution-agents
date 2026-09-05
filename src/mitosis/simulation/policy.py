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
from ..proposal import MAX_HYPOTHESIS_CHARS
from ..providers import ModelRequest, ModelResponse

SIMULATION_PROVIDER = "simulation"
POLICY_MODEL_ID = "policy-v1"
POLICY_VERSION = "1"

#: The exact section header `context._genome_section` renders (verbatim
#: string, not a regex) -- see that function's `Section(name=..., body=...)`.
_GENOME_SECTION_HEADER = "## Your genome (immutable; this is who you are)\n"
_SECTION_BOUNDARY = "\n\n## "


class PolicyError(Exception):
    pass


def _request_text(request: ModelRequest) -> str:
    return "\n".join(str(m.get("content", "")) for m in request.messages)


def _extract_genome(prompt_text: str) -> dict:
    start = prompt_text.find(_GENOME_SECTION_HEADER)
    if start == -1:
        raise PolicyError(
            "rendered context carries no genome section -- "
            "context._genome_section's header text must have changed"
        )
    body_start = start + len(_GENOME_SECTION_HEADER)
    end = prompt_text.find(_SECTION_BOUNDARY, body_start)
    body = prompt_text[body_start:] if end == -1 else prompt_text[body_start:end]
    return json.loads(body)


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
        genome_hash = genome_module.compute_genome_hash(canonical_genome)
        # A tuple is not an accepted `random.Random` seed type -- a stable
        # string is, and (unlike `hash()`) its seeding does not depend on
        # `PYTHONHASHSEED`, so this reproduces across separate processes.
        rng = random.Random(f"{self._master_seed}:policy:{genome_hash}:{self._call_index}")
        self._call_index += 1

        text = json.dumps(_propose(canonical_genome, rng))
        return ModelResponse(
            text=text,
            resolved_model=request.model,
            api_version=f"simulation-policy-{POLICY_VERSION}",
            input_tokens=max(len(prompt_text) // 4, 1),
            output_tokens=max(len(text) // 4, 1),
            stop_reason="end_turn",
            latency_ms=0,
        )
