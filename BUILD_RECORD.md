# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, the
expiry sweep, establishable rights, scheduler liveness, the experiment, experiment attribution,
proposed experiments, the strategy kind decided, the experiment_id foreign keys, §13.1's
normalised cost, the reply format a model can follow, the temperature/diversity
measurement, §15.1 anchoring and the twins that chose the fix, the proposal log that
shows no wording, the §23.4 repeat, the wake reason, the genome, the human-decision wake,
the +15% that did not survive honesty, §13.4's concreteness measure,
§13.2's selector, and §12's novelty archive, 2026-07-21 through 2026-08-27):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-28 — The counterparty key unblocked one dimension and disproved the claim about the other

`counterparty.py` + **migration 0028** + 19 tests + `record-revenue --counterparty` + golden
expectations **30 -> 31** (ADR-061). §12.1's archive is **two-dimensional**.

Four tracking files said an inbound counterparty key would unblock both of §12.1's remaining
dimensions. It unblocked one, and building it is what proved the other was never blocked on it.

### A digest gives equality, never identity

`revenue_recurrence` asks whether *the same buyer paid again* — a question about equality, which is
exactly what a salted hash answers. `buyer_type` asks who the buyer **is**, and §16.3 puts customer
identity permanently outside this colony. No key can produce it; it needs a **declarer**, which is
ADR-059's missing judge in a second place. The correction is written into `novelty._buyer_type`
itself, not only into the ADR, because that is where the wrong claim was.

### Where it lives, and the one risky part

On `ledger_transactions` as a column, **inside §3.4's hash preimage** — who paid is a fact about the
payment, and this field decides whether a Cell occupies §12.1's `repeat` niche. `metadata_json` was
the tempting home and is not covered by the hash at all.

**The preimage is extended by omission.** Including the key as null on every transaction would
change every hash ever written and make `verify_chain` report every existing colony as tampered
with. Including it only when present leaves pre-0028 rows byte-identical — evidenced by the golden
run passing **unchanged** on the first full run after the ledger change, and pinned by a test that
recomputes the pre-0028 formula by hand.

### The CHECK is the guarantee, not validation

The column is declared `CHECK (length = 64 AND NOT GLOB '*[^0-9a-f]*')`, so it **cannot hold** an
email address — ADR-047's lesson twice over: a seam binds callers that know about it, a constraint
binds callers that do not exist yet. A probe table built from the migration's own text pins
`counterparty.is_hash` against it so the two spellings cannot drift.

### The cadence abstains in one direction only

`repeat` survives a partial record (more data can add a repeat, never remove one); `one_off` does
not. Aggregated across a genome's Cells, because one buyer returning to the same idea is a repeat
customer of that idea. `subscription` is unreachable — telling it from a loyal buyer needs the
service-obligation record §16.3 calls liability-linked — and `UNREACHABLE_BINS` says so rather than
leaving an absent branch.

### Verification

- **Teeth-checked twelve ways, all CAUGHT**, including both directions of the abstention rule and a
  faithful per-Cell aggregation that produces a plausible wrong bin (`one_off`) rather than none.
- **1077 tests and the golden run green.** USD_REAL identical in every account; the replay is pinned
  on `repeat` with the buyer **spelled differently** in the two payments, because `repeat` is the
  only bin whose value depends on two digests being equal.
- Next: §12.1 asks for two or three dimensions and now has two. The third needs a **declared**
  `buyer_type` with its declarer recorded — the same Auditor/human judgment path ADR-059 left
  unbuilt and ADR-060 needs for §13.4's third flag, so it is one build serving three callers. After
  that, §12.3's Thompson posteriors, still blocked on stage *conversions* while `promotion.allocate`
  only ever issues rung 7.
