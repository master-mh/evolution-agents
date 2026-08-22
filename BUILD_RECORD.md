# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, and Auditor Cells, 2026-07-21 through 2026-08-22):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).
## 2026-08-22 — Genome content: a Cell that knows what business it is in

`genome.py` rewritten + `lifecycle`/`lineage`/`approval`/`cli` (ADR-033). **No migration** —
`cell_genomes` has carried every §16.2 column since slice 2; what was missing was content and
semantics. §16.2's v0.1 fields (market, problem, product, revenue_model, acquisition_channel,
workflow, model_policy, mutation_rate, allowed_tools, risk_class) had never been populated, so a
Cell's prompt described its balances and its own forecast record and nothing else. Its only
possible decisions were meta-decisions about its own standing — which is exactly what the one live
paid deliberation made when it abstained citing its unresolved predictions. Correct reasoning about
the only subject it had data on.

### The slice was not "add fields" — inheritance did not exist

`_get_or_create_genome` built a child's content from its cell_type and the caller's mutation. **The
parent's content was never read.** While every genome was `{"cell_type": ...}` this was invisible:
parent and child collided into one content-addressed row, so ADR-018's "an unmutated child reuses
its parent's genome" *looked* true. It was true by coincidence, and with real content it is false in
two directions at once — the child is born a blank slate, losing everything its lineage learned, and
that blank addresses to the **same row as every other bare Cell of its type**, handing unrelated
lineages one shared genome along with the mutation distance and counterfactual comparison §16.1
depends on. Found by reading §16.3 before writing anything, not by a failing test; nothing in the
suite could have caught it while genomes were placeholders.

### §16.4 closed the schema

> Without exact inheritance semantics, Cells could reproduce to *escape liabilities while keeping
> profitable assets*.

So only §16.2's fields are accepted and everything else is refused by name. A blocklist of
credential-shaped keys was the obvious alternative and fails open on every spelling nobody thought
of; closure makes §16.3's non-inheritable categories — credentials, customer identity, real platform
account access, legal identity — **unrepresentable** rather than merely rejected, which is the right
posture for an object whose hash is a public dedup key. Validation runs on the *merged* content, not
the overlay, because checking only the mutation lets anything already sitting in a parent's genome
propagate unchecked forever.

### Two of §16.2's own fields are permission-shaped

`risk_class` and `allowed_tools` sit in the genome, and a genome is Cell-mutable. A lineage able to
write `risk_class: LOW` into its children buys them cheap approvals for as long as it survives — a
far more durable version of the per-proposal gaming ADR-027 already refused. So both are **claims
and requests, never grants**: `risk_class` folds into `approval._assessed_tier` through the *same
`max`* that governs `claimed_tier`, and `allowed_tools` grants nothing, with no `has_tool` helper
offered for a caller to mistake for one. `genome.RISK_CLASSES` mirrors `proposal.RiskTier` by
structural test rather than import, because `genome` sits far below `proposal` and drift would
silently stop a claim escalating — in the direction that favours the Cell.

### Who writes the content

Operator-seeded founders (`create-cell --genome`, inline JSON or a file), with §14's mutation
operators exploring outward. A Cell proposing its own genome through the §23 queue is coherent and
was deliberately not built: rewriting the content that defines you is self-modification, and it is
also how a Cell learns to describe itself as low-risk.

### Verification

- **719 tests passing** (23 new, 0 removed; up from 696).
- **Golden expectation 12 → 13.** The auditor founder is seeded and its child now inherits. Five
  sections move, each explained in the migration note; the load-bearing one is
  `approval_requests`: the child's assessed tier goes MEDIUM → HIGH **above the MEDIUM its own
  proposal claimed**, because it inherited `risk_class: HIGH` — inheritance and the `max` fold
  visible in a single line. The seeded class is deliberately not LOW, since a LOW claim is
  indistinguishable from the claim being ignored. `balances` and `reservations` are byte-identical
  and **no USD_REAL moves**; the unseeded explorer's request is unchanged, which is the control
  against a claim leaking onto a Cell that never made one.
- **Teeth-checked eleven ways**, each failing its named test: inheritance not read, mutation
  replacing instead of overlaying, the closed schema opened, the non-inheritable refusal removed,
  the genome claim ignored, the genome claim allowed to *lower* a tier, only the mutation validated,
  the founder seed dropped, a field added without classifying it, `RISK_CLASSES` drifting from
  `RiskTier`, and a grant-shaped helper appearing.
- **One new test was vacuous and was rewritten.** `unclassified_fields()` mirrored
  `accounts.unclassified_accounts()` in shape but derived `GENOME_FIELDS` *from* the classification
  dicts, so it was empty by construction and could never fire. `accounts.py` works because
  `FIXED_ACCOUNTS` is declared independently; §16.2's field list is now declared the same way, and
  the guard has teeth in both directions.
- **Charter C14's canary caught the first draft**: `NON_INHERITABLE_SENSE` spelled a credential
  identifier in kernel source. The canary was right and the doc string changed, not the test.
- **Hand-verified on a live colony:** a founder seeded from a JSON file; a `channel_mutation` child
  that kept market, problem, product, revenue_model and risk_class while changing only the channel,
  at genome version 2 with a real parentage edge; the closed schema, the non-inheritable refusal
  (from both the founder and the child side) and a bad `risk_class` each refused with the clause
  that explains why; conservation OK and hash chain valid throughout; and the inherited business
  rendered into the Cell's prompt as data.
- Next: nothing gives a Cell a way to *act* on the business its genome names — no artifact store, no
  tool surface, and `allowed_tools` names capabilities the kernel does not have. §16.3's
  liability-linked class stays unenforced until something provisions a reserve.
