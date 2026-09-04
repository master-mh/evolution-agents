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
§13.2's selector, §12's novelty archive, the inbound counterparty key,
§12.1's declared third dimension, rung 8, §12.3's `P(next stage)`, the
Auditor path for §13.3/§13.4's content judgments, the software_native_advantage
gate reading a resolved content audit, model_policy's temperature socket,
risk_tier becoming optional for abstain, the bounded single parse-repair
retry, and the argued refusal to extend it to the Auditors or `call-model`,
2026-07-21 through 2026-09-04):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-09-04 — External audit brief, Slices A–B: distribution hygiene and the egress boundary

An external audit (`MITOSIS_IMPROVEMENT_IMPLEMENTATION_BRIEF`, dated 2026-09-04) reviewed the
repository from outside this session's history and found the kernel's governance/accounting
core sound but flagged concrete, reproducible defects the existing test suite never exercised —
plus a live credential exposure that is the owner's to rotate, not this session's to touch.
Every specific technical claim in the brief was independently verified against the live repo
before acting on it (test/migration/expectation-version counts, the `.env`/`.venv` exposure
path, the exact `fetchers.py` bug) — all checked out, so the brief's own priority order (security
containment first) was followed rather than re-derived.

### Slice A — clean source-distribution archive

`.env` (a live Anthropic key) was never git-tracked, but a manually zipped working directory
would have shipped it anyway — zipping bypasses `.gitignore`, `git archive` cannot.
`scripts/build_source_archive.py` builds from `git archive` (tracked content only) and then
independently opens its own output and refuses to ship it if any forbidden path (`.env`, `*.db`,
`.git/`, a virtualenv, a cache dir, macOS metadata, coverage reports) is present anyway — defense
in depth against a future `git add -f` mistake, not just trust in git's default. `dist/`,
`.coverage`, `.DS_Store` added to `.gitignore`.

### Slice B — the public-web egress boundary, in three parts

1. **Robots.txt transport.** `_robots_allow()` called `RobotFileParser.read()`, which opens its
   own plain `urllib.request.urlopen()` — no redirect refusal, no timeout, no byte cap. A
   robots.txt that 302s carried the *policy check* off Charter C12's allowlist even though the
   page fetch itself never would. Now built on the same bounded, no-redirect transport as the
   page fetch, with explicit tested status semantics (401/403 disallow, 404 means unrestricted,
   an oversized or redirected response fails closed rather than parsing a possibly-truncated
   policy).
2. **SSRF / non-public destinations.** The Charter C12 allowlist only ever compared hostname
   *strings* — nothing resolved one. `_check_destination_safe` now refuses a hostname that
   resolves to loopback, private, link-local (cloud-metadata endpoints included), multicast,
   unspecified, or reserved, before either request. Documented, not closed: DNS rebinding (a
   second resolution at actual-connect time) is a named limitation, not silently assumed away.
3. **Honest personal-data status.** The fetcher wrote `contains_personal_data=False`
   unconditionally — never a determination, always a fabricated negative, and a Cell's own
   context rendered it as fact ("personal data: no") on every fetch. Now tri-state
   (`'yes'/'no'/'unknown'`, migration 0034), matching `commercial_use`'s existing shape in the
   same §20.1 tuple exactly. The artifacts-table data migration preserves the one *real* "no"
   (`COLONY_AUTHORED`, no external sources at all) while correcting every other historical `0` —
   which nothing but the fetcher ever wrote — to `'unknown'`.

### Verification

- **1224 tests and the golden run green**, up from 1175 at the start of this arc — real local
  HTTP servers for the redirect/hang/oversized/status-code cases (a string-level allowlist test
  can't see any of them, which is why the existing C12 suite never caught the robots.txt bug),
  plus synthetic-repo teeth-checks for the archive guard and the migration's data translation.
- **Golden expectations moved 37 → 38.** Full section-by-section diff before regenerating, not
  assumed from the hash mismatch: `tool_calls`/`artifacts` move only on
  `contains_personal_data`; `deliberations`/`model_calls`/`resource_usage` shift by a small
  constant on exactly the 7 rows downstream of the Cell that reads a fetched page back into its
  own context (the honest word is longer than the fabricated one, and `MockProvider` prices
  calls as a function of text length — same mechanism as version 35→36). No `output_tokens`,
  cost, or `balances` row moved.
- **Three separate teeth-checks**, each: mutate, confirm the specific expected test(s) fail with
  no other collateral failures, restore from the pre-mutation copy, confirm byte-identical and
  green again. The robots-transport fix caught its own pre-fix code failing exactly the redirect
  and oversized-response cases ("DID NOT RAISE"); the SSRF guard caught all 16 of its own targeted
  cases with its body stubbed to a no-op; the personal-data precedence order caught the one test
  built to defend it when the tri-state order was swapped.
- Confirmed against a disposable copy of `first-real-call.db` (untouched original): all 34
  migrations apply, `PRAGMA integrity_check` and `foreign_key_check` both clean. No paid provider
  or live network call made — the network tests use only local servers.

- Next: Slice C (documentation/safety-claim reconciliation — README's stale 696-test/18-migration/
  golden-v12 counts and the "two separate humans" claim) per the brief's own priority order, then
  D (a narrow runtime-defect lint gate) and E (wiring auto-promotion into the scheduled `tick`)
  before the Phase 2 flight simulator (Slice F), which is still the gating step for real
  evolutionary evidence — Phases 2 and 3 remain deliberately unbuilt.
