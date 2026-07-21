"""Genome content addressing (SPEC.md §16.1, Charter C11).

Phase 1 genomes are minimal placeholders — just enough to give a Cell a
canonical identity and satisfy "every genome has a canonical hash". The full
v0.1 genome fields (market, problem, product, revenue_model,
acquisition_channel, workflow, model_policy, mutation_rate, allowed_tools,
risk_class — §16.2) are populated by real strategy content starting in
Phase 5 (sandboxed code evolution); until then `canonical_genome_json` only
carries `cell_type`.
"""

from __future__ import annotations

import hashlib
import json

from .models import CellType


def canonical_genome_json(cell_type: CellType) -> dict:
    return {"cell_type": cell_type.value}


def compute_genome_hash(canonical_genome: dict) -> str:
    canonical = json.dumps(canonical_genome, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
