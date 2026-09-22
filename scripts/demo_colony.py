#!/usr/bin/env python
"""Build a small demo colony for `mitosis dashboard` — free, offline, deterministic.

    .venv/bin/python scripts/demo_colony.py /tmp/demo.db
    .venv/bin/mitosis --db /tmp/demo.db dashboard

Four founder Cells with different workflow structures wake a few times each
against a scripted provider named `mock` (priced at zero, no network), so the
dashboard has wakes, a self-critique loop, a provider outage, predictions and a
pending approval queue to show. Every write goes through the kernel's own
operations — nothing is inserted behind its back.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mitosis import approval, db, deliberation, ledger, lifecycle, prediction, providers
from mitosis.models import Book, CellType, EntrySpec

FOUNDERS = [
    ("single_pass", {"market": "independent UK bookkeepers", "problem": "chasing clients for receipts",
                     "product": "a receipt-request text service"}),
    ("self_critique_loop", {"market": "small accounting firms in the UK", "problem": "month-end close is manual",
                            "product": "a checklist-driven close assistant"}),
    ("iterative_refinement", {"market": "Etsy sellers", "problem": "VAT thresholds are confusing",
                              "product": "a VAT threshold tracker"}),
    ("parallel_review", {"market": "freelance designers", "problem": "late invoice payments",
                         "product": "automated polite payment reminders"}),
]

IDEAS = [
    "Offer a £5/month pilot to 10 {market} found via LinkedIn",
    "Post a free template for {product} in two {market} forums and count sign-ups",
    "Run a 48-hour landing-page test for {product} with a waitlist",
    "Interview 5 {market} about {problem} before building anything",
]


class ScriptedProvider:
    """Replies in whatever shape the kernel's current step asks for."""

    name = providers.MOCK_PROVIDER

    def __init__(self, seed: int, fail_on: set[int] = frozenset()) -> None:
        self._rng = random.Random(seed)
        self._calls = 0
        self._fail_on = fail_on

    def complete(self, request: providers.ModelRequest) -> providers.ModelResponse:
        self._calls += 1
        if self._calls in self._fail_on:
            raise providers.ProviderCallError("demo: the provider is down for this call", execution_unknown=False)
        last = str(request.messages[-1]["content"])
        if "Do not rewrite it here" in last:
            reply = (json.dumps({"verdict": "revise", "issues": ["the cost estimate is a guess",
                                                                 "name how success will be measured"]})
                     if self._rng.random() < 0.6 else json.dumps({"verdict": "keep"}))
        else:
            reply = self._proposal(request, revised="A critique of the proposal above" in last)
        return providers.MockProvider(reply=reply).complete(request)

    def _proposal(self, request, *, revised: bool) -> str:
        text = "\n".join(str(m["content"]) for m in request.messages)
        genome = next((g for _, g in FOUNDERS if g["market"] in text), FOUNDERS[0][1])
        summary = self._rng.choice(IDEAS).format(**genome)
        return json.dumps({
            "kind": "experiment",
            "summary": ("Revised: " if revised else "") + summary,
            "rationale": f"the cheapest way to learn whether {genome['market']} will pay",
            "risk_tier": "LOW",
            "estimated_cost_minor_units": self._rng.choice([0, 200, 500]),
            "predictions": [],
            "experiment": {"hypothesis": f"at least 2 of 10 {genome['market']} sign up"},
        })


def _fund(conn, cell_id: str) -> None:
    for book, currency, amount in ((Book.USD_REAL, "USD", 2_000), (Book.RESOURCE, "RESOURCE", 100_000)):
        ledger.post_transaction(
            conn, book=book, currency=currency, transaction_type="cell_birth_funding",
            idempotency_key=f"demo-fund:{cell_id}:{book.value}", description="demo funding",
            entries=[
                EntrySpec(account_id="seed_bank", amount_minor_units=-amount, cell_id=cell_id),
                EntrySpec(account_id=f"cell:{cell_id}:cash", amount_minor_units=amount, cell_id=cell_id),
            ],
        )


def main(path: str) -> None:
    if Path(path).exists():
        sys.exit(f"{path} already exists — the demo only builds a fresh colony")
    conn = db.connect_and_migrate(path)
    provider = ScriptedProvider(seed=7, fail_on={9})
    for n, (structure, content) in enumerate(FOUNDERS):
        cell = lifecycle.create_cell(
            conn, cell_type=CellType.EXPLORER, budget_minor_units=5_000, book=Book.USD_SIM,
            idempotency_key=f"demo-cell:{n}",
            genome_content={**content, "workflow": {"structure": structure}},
        )
        _fund(conn, cell.cell_id)
        for w in range(3):
            deliberation.deliberate(
                conn, cell_id=cell.cell_id, provider=provider, wake_key=f"demo-wake:{n}:{w}", model="mock-1",
            )
        registered = prediction.register(
            conn, cell_id=cell.cell_id, claim=f"at least 2 of 10 {content['market']} sign up within 14 days",
            probability=round(0.2 + 0.15 * n, 2), resolves_by=datetime.now(timezone.utc) + timedelta(days=14),
            idempotency_key=f"demo-prediction:{n}",
        )
        if n % 2 == 0:
            prediction.resolve(conn, registered.prediction_id, occurred=n == 0, source="demo")
    queued = approval.enqueue_missing(conn)
    print(f"demo colony at {path}: {len(FOUNDERS)} cells, {len(queued)} approval request(s) queued")
    print(f"  view it:  .venv/bin/mitosis --db {path} dashboard")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
