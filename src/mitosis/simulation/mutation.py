"""Seeded mutation operators over the genome schema (SPEC.md §14.1, §16.3;
implementation brief Slice F's "mutation and reproduction").

`lineage.reproduce()` has accepted `mutation: dict | None` and
`mutation_operator: str | None` since migration 0002 and already threads the
operator name through to a real, tested column
(`cell_genomes.mutation_operator`) -- every existing caller just passes
`None` or a fixed one-off string. This module is what finally exercises that
socket with real seeded content: one function per brief-required operator,
each returning `(mutation, operator_name)` for `reproduce()` to consume
unchanged.

Only the control operator ships in this slice (F1). The remaining five
(market/customer, product/delivery, acquisition-channel, pricing/revenue-
model, workflow, model-policy temperature) are F3's addition, each following
this file's exact shape.
"""

from __future__ import annotations

from typing import Any

#: The one required control/no-op mutation. An empty overlay collapses to the
#: parent's own genome hash by construction (ADR-018) -- the baseline every
#: real variation operator is compared against.
NO_OP_OPERATOR = "control_noop"


def no_op(parent_content: dict[str, Any], *, seed: int) -> tuple[dict[str, Any], str]:
    del parent_content, seed  # unused: a no-op reads nothing and changes nothing
    return {}, NO_OP_OPERATOR
