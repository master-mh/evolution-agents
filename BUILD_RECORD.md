# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, and genome content,
2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).## 2026-08-23 — The tool surface: a Cell reads the world, under grant

`tools.py` + `tool_registry.py` + `fetchers.py` + migration 0019 (ADR-034). A Cell could think, be
reviewed and be funded, and could do nothing else. ADR-033 sharpened the gap rather than closing it:
a Cell could describe a business it had no way to act on.

### §25.1 says this is a rung the colony skipped, not a step up

The ladder puts "read-only real-world observation" at rung 4 and "shadow prediction with no action"
at rung 5, and the agent loop has been at rung 5 since ADR-025. **Reading the world is *below* where
the colony already stood.** Getting that right changed the gating: the instinct is to treat "the
kernel can reach the internet" as the biggest step yet and armour it accordingly, when the genuinely
large step is *acting*, which is rungs 8-9 and has no registry entry. `ToolSpec.read_only` makes the
split structural — an acting tool has to break a named test.

### §19.4 shaped everything, and its sharpest consequence is easy to miss

> no webpage content treated as a trusted tool command

The obvious readings — label the content, fence it in the prompt — are necessary and insufficient.
The one that actually holds is: **a tool result can never cause another tool call.** Execution needs
a grant, a grant needs a human decision on a §23 request, so a fetched page saying "now fetch
evil.example" can at most produce a *proposal*, whose URL a person reads. The human is the
loop-breaker. That is why the proposal → approval → grant route was chosen over letting a Cell call
tools inline while it thinks: inline tool use puts fetched content in the same conversation as the
instructions, which is the exact configuration §19.4 exists to prevent.

### The layering constraint and the safety constraint wanted the same cut

`context` has to render what a Cell may request and what a previous call returned — but `tools`
imports `approval` → `deliberation` → `context`, so a direct import closed a loop. Splitting
`tool_registry` (readable by both layers) from `tools` (the executor) resolves the cycle, and it is
*exactly* the boundary §19.4 needs: reading is not executing. When a dependency-order problem and a
prompt-injection rule independently demand the same seam, the seam is real rather than convenient.

### Three things the build found that the design did not

- **Redirects defeat the allowlist.** Charter C12 is checked against the URL a human approved, and
  `urllib` follows redirects by default — so an allowlisted page answering `302` would carry the
  fetch off the allowlist *after* the check passed. An open redirect on an otherwise reputable host
  is enough. `fetchers.py` refuses redirects, which turns it into a failed call the Cell may propose
  to follow explicitly.
- **The review payload never printed the tool's arguments.** Found by hand-verification, not by any
  test: the field was on the payload and the CLI rendered a summary. For a tool request **the URL is
  the decision** — approving "read the wholesaler's price list" without seeing which host is
  approving nothing in particular.
- **A third copy of the §13/liability error.** The audit two commits ago corrected `PRIORITIES.md`
  and `approval.py`; the same wrong claim was also in `cli.py`, twice. Corrected.

### Better than the gateway on purpose

The `tool_calls` row is written **before** the external call, in the transaction that consumes the
grant and reserves the RESOURCE. That is the forward recovery ADR-022 deferred: a crash mid-call
leaves a diagnosable row instead of a reservation with nothing explaining it. Cheap to do here
because the module is new and has no in-flight state to migrate.

### Verification

- **756 tests passing** (36 new, 0 removed; up from 719), including the **first
  `charter_sandbox_isolation` (C12) property test** — generated hostnames rather than examples,
  because the two plausible wrong allowlist implementations (substring, bare `endswith`) both pass a
  hand-picked case. C13 `charter_taint_quarantine` is now the only Charter clause without a test,
  honestly so: §18.2 is about adversarial lineages and the shadow economy is Phase 6.
- **Golden expectation 13 → 14.** The scenario gains the whole arc — propose, approve, fetch, wake —
  with a deterministic offline fetcher. **No USD_REAL moves and `external_expense` is unchanged in
  every book**; the only balance movement is 9 RESOURCE. The USD_REAL reservations reserve and
  *release* in pairs, which is the tell that the new model calls cost nothing. `egress_allowlist` and
  `autonomy` are pinned because both start closed — a colony that ever shipped either open by
  default diffs there, which is the most valuable regression in the section.
- **The taint flag is pinned non-uniformly** (`[false, false, false, true]`), which needed an extra
  wake *after* the fetch. A uniformly-false column passes just as happily against a kernel that
  hardcodes false — the trap ADR-031's `born_in_epoch` nearly shipped with.
- **Teeth-checked twenty ways**, each failing its named test: allowlist bypassed, substring match,
  bare `endswith` match, autonomy gate skipped, grant never consumed, expiry unchecked, any proposal
  kind executing, a dead Cell executing, errors unredacted, a refused fetch stranding its
  reservation, an uncertain outcome released, results untruncated, the taint flag hardcoded, the
  fence gutted, `context` importing the executor, a tool marked non-read-only, the default fetcher
  answering, an unreadable robots.txt read as consent, and redirects followed.
- **One MISS was the mutation's fault and one test was genuinely weak** — both true at once. The
  fence mutation replaced half the warning, and the assertions passed anyway *via the section
  title*, so a fence with a gutted body and a reassuring heading would have passed. The test now
  asserts against the section body; re-run with a complete mutation, it has teeth.
- **Hand-verified on a live colony**, offline throughout: both gates refusing independently, a
  prompt-injection payload arriving fenced and labelled as data, the attacker URL in it unreachable
  because it is not allowlisted, conservation green in all three books, both chains valid,
  `external_expense` 0, one grant consumed of one, and the Cell woken.
- **Not verified live: an actual network request.** `run-tool --live` is wired and unit-tested
  (redirects, robots.txt, size cap) but was never pointed at a real host — that is one command and
  the operator's call to make.
- Next: nothing schedules a tool call, `browser_control`/`external_publish`/`external_message` have
  columns and no tools behind them, and §21.2's external-action registry must exist before any tool
  that changes the world does.
