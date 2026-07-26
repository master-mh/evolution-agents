"""Genome content addressing (SPEC.md §16.1, Charter C11).

Phase 1 genomes are minimal placeholders — just enough to give a Cell a
canonical identity and satisfy "every genome has a canonical hash". The full
v0.1 genome fields (market, problem, product, revenue_model,
acquisition_channel, workflow, model_policy, mutation_rate, allowed_tools,
risk_class — §16.2) are populated by real strategy content starting in
Phase 5 (sandboxed code evolution); until then `canonical_genome_json` only
carries `cell_type`, plus whatever a caller-supplied `mutation` overlays.

**Mutation and content addressing (ADR-018, ADR-019).** A genome is
identified *by its content*: identical canonical content always yields the
same hash and therefore the same `cell_genomes` row. That has a direct
consequence for reproduction — a child whose genome content is identical to
its parent's is not a new genome, it *is* the parent's genome, and recording
a parent_genome_hashes edge for it would be a self-loop. So genome parentage
edges exist only where a `mutation` actually changed the content. Cell
parentage (`cells.parent_cell_id`) is tracked separately and unconditionally;
see lineage.py's docstring for why that split is the faithful reading of
Amendment A10 while Phase 1 genomes are placeholders.

Parentage deliberately lives *outside* the canonical content (it's a column
on `cell_genomes`, not a key in `canonical_genome_json`): §16.1 wants the
hash usable for deduplication, mutation distance, and counterfactual
comparison, all of which require two structurally identical strategies to
hash identically regardless of who produced them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import CellType


class GenomeError(Exception):
    pass


def canonical_genome_json(
    cell_type: CellType, mutation: dict[str, Any] | None = None
) -> dict:
    """The canonical content for a Cell's genome. `mutation` overlays
    additional (or replacement) fields — the Phase 1 stand-in for real
    mutation operators, which arrive with genuine strategy content in
    Phase 5."""
    canonical: dict[str, Any] = {"cell_type": cell_type.value}
    if mutation:
        _validate_mutation(mutation)
        canonical.update(mutation)
    return canonical


def _validate_mutation(mutation: dict[str, Any]) -> None:
    if not isinstance(mutation, dict):
        raise GenomeError("mutation must be a dict")
    for key in mutation:
        if not isinstance(key, str):
            raise GenomeError(f"mutation keys must be strings, got {type(key).__name__}")
    try:
        # The hash is computed over json.dumps output, so anything that
        # can't serialize deterministically can't be part of a genome.
        json.dumps(mutation, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise GenomeError(f"mutation must be JSON-serializable: {exc}") from exc


def compute_genome_hash(canonical_genome: dict) -> str:
    canonical = json.dumps(canonical_genome, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
