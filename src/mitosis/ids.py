"""Injectable id generation (PRIORITIES.md "seeded id generation").

Every primary key in this kernel (`transaction_id`, `entry_id`,
`reservation_id`, `cell_id`, `event_id`, `usage_id`, audit `event_id`, ...)
was `str(uuid.uuid4())` called directly at each site. That's fine for a real
colony, but it makes two things impossible by construction:

  - **Amendment A5's ordering tie-break.** `events.next_ready`'s total order
    is `(effective_time, priority, event_id)`; when two events share an
    effective_time and a priority, the tie-break falls to `event_id`. A
    fresh uuid4 makes that tie-break a coin flip that differs run to run.
  - **Golden-run replay (SPEC.md §26, ADR-017).** `golden.py` worked around
    this by hashing a *semantic* snapshot that strips every uuid4 before
    comparison — the right permanent design regardless (ADR-017's real
    rationale is schema-evolution robustness, not id determinism) but it
    left the raw run itself non-reproducible underneath the normalization.

The fix: every call site asks this module for an id instead of calling
`uuid.uuid4()` directly. Default behaviour (`RandomIdGenerator`) is
byte-for-byte what existed before — real, non-deterministic uuid4 strings —
so nothing about a real colony run changes. `seeded()`/`seed()` swap in a
`random.Random(seed)`-backed generator that still emits uuid4-*shaped*
strings (same TEXT primary key format, no schema/format migration needed)
but deterministically: same seed + same call order -> same ids, every time.
That's what makes a scenario's event ids (and therefore its A5 tie-breaks)
and a scenario's raw uuids (not just their semantic snapshot) reproducible.

No thread safety here: nothing in this kernel runs Python threads (its
"concurrency" is SQLite `BEGIN IMMEDIATE` write-lock contention between
separate connections/processes, not in-process threading), so a bare module-
level generator is sufficient — see docs/DECISIONS.md and the concurrency
fixes in slice 10 for the actual concurrency model.
"""

from __future__ import annotations

import random
import uuid
from contextlib import contextmanager
from typing import Iterator, Protocol


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class RandomIdGenerator:
    """Real, non-deterministic uuid4 strings. The default, unchanged from
    every call site's prior direct `str(uuid.uuid4())`."""

    def new_id(self) -> str:
        return str(uuid.uuid4())


class SeededIdGenerator:
    """Deterministic uuid4-shaped strings from a seeded PRNG. Same seed +
    same call order -> same sequence of ids, every run."""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def new_id(self) -> str:
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))


_generator: IdGenerator = RandomIdGenerator()


def new_id() -> str:
    """The single call every module uses in place of `uuid.uuid4()`."""
    return _generator.new_id()


def seed(value: int) -> None:
    """Switch to deterministic id generation from here on, until `reset()`.
    Prefer the `seeded()` context manager where the deterministic window has
    a clear start and end (e.g. a golden-run scenario) — it can't leak into
    unrelated code the way a bare `seed()` call can."""
    global _generator
    _generator = SeededIdGenerator(value)


def reset() -> None:
    """Return to real, non-deterministic uuid4 generation."""
    global _generator
    _generator = RandomIdGenerator()


@contextmanager
def seeded(value: int) -> Iterator[None]:
    """Scope deterministic id generation to the wrapped block, restoring
    whatever generator was active beforehand (not always `reset()`'s
    default — nesting stays correct)."""
    global _generator
    previous = _generator
    _generator = SeededIdGenerator(value)
    try:
        yield
    finally:
        _generator = previous
