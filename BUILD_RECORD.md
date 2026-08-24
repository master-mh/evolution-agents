# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, the external-action registry, the §27.1 autonomy decisions, grant regeneration, and the
expiry sweep, 2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-24 — Rights a person can establish

`rights.py` + migration 0024 + `set-rights`/`rights` (ADR-041). ADR-035 built §20.2's inheritance
in one direction: rights tighten and never loosen, `fetchers.py` cannot read a licence, so **an
artifact built on a fetched page was `commercial_use: unknown` forever** and ADR-037's
`real_commerce` flag could be opened with every listing still refused at the export gate. Flagged
by four consecutive slices. `check_exportable` had already written the instruction it could not
carry out — *"Establish the rights position on its sources first."*

### The subject is a source, and that is the whole design

Stamping a position onto an artifact is the obvious build and it is §20.2's laundering path with a
person holding the pen: it does not compose, it does not reach the next artifact from the same
page, and it asks someone to rule on a derived work when what a person can actually read is a
licence. So the operator attests a **source**, and the existing fold does the rest.

**Two subject kinds, both real today.** `domain` for external sources. `colony` for the colony's
own output — `inherit_provenance` starts a source-less artifact at `unknown` and says outright
that whether the colony may sell what it wrote "is a question for a person, not a default", and
**nothing could ask the person**. That case was half the gap and was nearly missed: the entry
that flagged this described only fetched pages, but a report the colony wrote unaided was equally
unsellable, and no domain attestation can reach it because there is no domain.

**Matching is exact host, deliberately unlike the egress allowlist it sits beside.** Over-matching
on the allowlist means *reading* a page the operator did not picture; over-matching here means
*selling* material under a licence that never covered it — §20.3's legal liability. Same-shaped
key, opposite consequence, so the looser rule is not inherited. ADR-036 had already recorded the
mirror of this: "scope it the same way as the neighbouring query" is not a safe default here.

### Retroactive without rewriting anything — §3.6 decides it, not taste

The natural build cascades the new position into the `artifacts` rows. That would mean an artifact
exported non-commercially under `unknown` afterwards reads as having been `permitted` at the time,
which is not what happened. §3.6's "never edit history to correct something — post a new, signed
adjustment" is the ledger's rule and it is the right one here, so `check_exportable` re-derives
against current attestations (`effective_provenance`) and the stored columns stay the record. The
attestation *is* the adjustment; withdrawal is an attestation of `unknown` with its own basis,
which keeps *why* on the record where a `revoked` flag would leave an absence.

The cost is two notions of one artifact's rights — the drift shape this repo keeps finding in its
own prose — contained by making the division explicit: **the effective fold is load-bearing in
exactly one place**, and `mitosis artifact` prints it only when it differs, labelled.

### §0.3 at both ends, and a socket that would have made a new invariant true by accident

No Cell-reachable module writes an attestation — an AST walk over *every* module except `cli.py`,
`golden.py` and `rights.py`, rather than a hand-picked subset the next module could fall outside.
At the other end `inherit_provenance` now **refuses an `own_provenance` carrying `permitted`**:
with no sources that declaration alone decides the artifact, so a producer able to make it would
be defining the one canonical fact between the colony and revenue. `unknown` and `prohibited`
remain — the asymmetry §23.5 already forces on `claimed_tier`.

**Filing this through the §23 queue was the alternative and it inverts §0.3**: the queue is where
a *Cell* asks to act, so rights would arrive as a Cell nominating its own position for a human to
countersign, and §23.5 warns the queue will be optimised against.

`artifacts.create` has taken an `own_provenance` since ADR-035 and **nothing has ever passed one**
— the eleventh reserved socket found half-built. It was folded into the stored columns and then
unrecoverable, harmless while the fold was the only answer and not harmless once the position is
re-derived. Now stored (`own_provenance_json`), so the recomputation is exact by construction
rather than by accident.

### Verification

- **869 tests passing** (30 new, 0 removed; up from 839). **Golden expectation 18 → 19**: one
  `rights_attestations` row, `rights_attested: 1`, and the `artifacts` section **byte-identical** —
  the attestation is made after the artifact is exported precisely so that what does *not* move is
  the assertion. A kernel that cascaded passes one scenario assertion and fails the other; one that
  read the stored column at the gate fails the reverse. Five of thirteen `model_calls` gain exactly
  one input token (see below); **`balances` is identical across every account in every book.**
- **Teeth-checked fourteen ways**, each failing its named test: the cascade, the export gate reading
  the stored column (the state before this slice), dotted-suffix matching, least-restrictive-wins
  inverted, the §0.3 clamp removed, an attestation waiving Charter C13, wall-clock ordering, the
  named-licence guard removed, the colony position leaking into sourced artifacts, the effective
  fold not recursing, `own_provenance` not stored, and a Cell-reachable module calling `attest`.
  plus the two below. **One MISSed on the first attempt and the mutation was at fault** — it added
  an import rather than a call, and the test is about calls.
- **A self-review found two defects the suite and the golden run both passed over**, and the first
  is the more serious. **§15.2's artifact index was feeding the Cell the creation-time position**,
  so an operator could establish a source's rights and the Cell whose work had just become sellable
  would still read `unknown` and never propose selling it — the gap moved one step upstream and
  somewhere quieter, with the export gate open and nothing ever reaching it. The index now shows the
  effective position (reading one is not §0.3-sensitive; defining one is). That is the whole of the
  golden run's token diff: `permitted` is two characters longer than `unknown`, the estimator is
  2 chars/token, and the five affected calls are exactly the deliberations after the attestation.
  Second, `rights.history()` given a `subject_kind` and no `subject` **silently returned the whole
  table** — the worst shape for a query an operator runs to check what they attested. Both are
  fixed, tested and teeth-checked.
- **Hand-verified end to end on a live colony.** A source-less artifact refused commercial export;
  `set-rights --colony` opened the gate while the stored row still read `unknown`; withdrawing
  closed it again and `rights --history` showed both positions with both reasons. Two message bugs
  surfaced only here and are fixed: `Attested colony colony`, and a refusal telling the operator of
  an artifact that read nothing to "establish the rights position on its sources" — advice with no
  route. The refusal now names the remedy that exists for the artifact in hand, with a test.
- Next: the nearest open work is that **nothing runs the scheduler** — `tick` is composable with
  cron per §30.1, but no supervision, no restart-on-failure and no alert when ticks stop.
