# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, the artifact
store, and the external-action registry, 2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-23 — One flag per capability: `external_publish`, argued and left shut

`channel_registry.py` + migration 0022 (ADR-037). PRIORITIES carried this as *"one autonomy flag
has a column and nothing behind it; one has channels and no decision"*, and ADR-036 closed with
"the flag is one §0.4 decision per capability". This is that decision — and the answer turned out
to be that the question could not be asked in the shape the flag was in.

### The question is narrower than it sounds

Nothing in the registry transmits. Enabling the flag would not let a Cell publish anything; it
would let a Cell *propose* a publish action, an operator approve it, and a person publish by hand
while the kernel records it. So the real question was never "may the colony publish unattended" —
it was **whether the record-and-refuse machinery is adequate for a channel that addresses nobody**.
It was not, on two counts, and the first is the one that settled it.

### One flag was opening two capabilities from two different phases

`external_publish` gated both `web_publish` and `marketplace_listing`, which made it the only flag
in the kernel opening more than one: `public_web_read` gates one tool, `external_message` one
channel. `cmd_set_autonomy`'s own docstring — "there is deliberately no switch that opens more than
one" — was **false as written**.

And the two are not peers. A page published by hand on a colony domain is §28 Phase 8, whose
deliverables name "landing-page drafts" and whose acceptance is "humans review all external use".
A marketplace listing is an **offer to sell**: Phase 9's "one narrow product class, one merchant
channel", with the legal identity and full liability reserves that phase requires and this colony
does not have. One flag collapsed a phase boundary, so **the defensible half could not be granted
without the indefensible one** — which is why the honest answer was not "not yet" but "not in this
shape".

The alternative it displaced is a serious one and worth recording: turn it on for Phase 8 landing
pages. Nothing transmits, a human approves and a human acts, the rate cap and the complaint freeze
are both live. That argument is strong for `web_publish` alone and weak for `marketplace_listing`
— exactly the split the flag forbade.

### The split is §0.4's own list, not an invention

§0.4 names six prohibitions — "no network from generated code, no real commerce, no external
communication, no real payments, no public publishing, no direct secret access" — and §27.1's
defaults block carries five keys. **"No real commerce" is the one that never got one**, and a
marketplace listing is real commerce rather than publishing: it had been filed under the wrong
prohibition all along. So `marketplace_listing` moved behind a new `real_commerce` key and
`external_publish` keeps its spec-given name over `web_publish` alone.

No spec-named key is removed, §27.1 is headed "development defaults, not economic recommendations",
and the precedent for extending it is `metabolic_acceleration_factor` — in `operator_state` since
migration 0014 and absent from that block. `real_commerce` is deliberately not `real_spending`,
which is §0.4's "no real payments" and governs unattended spend: a colony can be forbidden to sell
and still permitted to buy.

### The registry's central guarantee was vacuous for both channels

ADR-036 built §21.2's prevention half a phase early so it would be tested before the first real
customer. That half is counterparty-keyed, and `check_action` skipped **all three** of its checks —
duplicate contact, sibling collision, do-not-contact — whenever a channel addressed nobody. What
survived was the autonomy gate, the freeze and the rate/quota caps.

Meanwhile `marketplace_listing`'s own description promised what the code could not do: "two
lineages listing against each other is §21.2's bidding war", detected by nothing. This is the
inverse of the `understated_risk` bug the last slice caught — a signal that fires unconditionally
distinguishes nothing, and **a check that can never fire looks like a working registry and is its
opposite**.

The key that would work was already there. §21.2's aggregation keys are "counterparty/**domain**/
channel"; migration 0021 carried `domain` and `platform_account`, described there as "§21.2's
'domain used' and 'platform account'". They were written at claim time, read back on the row, and
**named in no predicate anywhere** — the eighth reserved socket found half-built.

### `target_kind`, and three places where mirroring the counterparty would have been wrong

`ChannelSpec.target_kind` replaces `requires_counterparty` with the §21.2 dimension the channel
actually collides on — `COUNTERPARTY` for email, `DOMAIN` for `web_publish`, `PLATFORM_ACCOUNT` for
`marketplace_listing` — and the target is **required**, so a publish channel fails closed instead
of skipping its checks. The boolean was not wrong so much as it only described the email case:
everything it said "no" to fell out of §21.2 altogether.

- **A same-lineage repeat is not a collision.** Contacting one person twice is §21.2's duplicate;
  publishing twice to your own domain is a business publishing twice. Only a *different* lineage on
  the same target is refused — the distinction ADR-036's live-run misattribution already
  established.
- **Duplicate is keyed on the artifact**, because a target channel has no person to key it on: the
  same content-addressed artifact to the same target, any lineage. ADR-035 made "duplicated
  artifacts with new names" unrepresentable, and this is the first check to spend that identity.
- **A target-keyed check refuses to answer without a lineage.** The counterparty path answers the
  strictest way it can when the asker is unknown; for a domain the strictest reading refuses the
  *normal* case. ADR-036's finding was that the operator acts on the diagnosis, so this produces
  none rather than a wrong one. `external-check` grew `--cell`.

`domain` and `platform_account` stay plaintext, and the asymmetry with the counterparty hash is
deliberate: they are the colony's *own* shared assets under §21.1, not a third party's identity
under §16.3.

### Three things found while building

- **The duplicate check had to be channel-scoped.** Designing the fixed scenario surfaced it: the
  existing email action records `domain` as a §21.2 fact, so an unscoped query refused the publish
  that followed — emailing a write-up from a domain and then publishing it there is one business
  doing two normal things.
- **The duplicate window is not optional.** Unwindowed, it is a permanent lock with no release: an
  artifact could never be republished after a listing expired, and this kernel has no unpublish to
  pair with it. §21.2's own words are "over a rolling window".
- **A normalisation is two changes, not one.** `counterparty_hash` strips and casefolds before
  hashing, and the first draft of `target_of` did neither — `Colony.Test` and `colony.test` would
  have been two domains, which is the defect the module argues against one function above. The fix
  after that was still half a fix: normalising for the *query* while the claim wrote the raw string
  left every later check looking for a value the row did not contain. Found writing the parking-lot
  note about it, and fixed rather than parked.

### Verification

- **826 tests passing** (11 new, 0 removed; up from 815).
- **Golden expectation 16 → 17.** The scenario gains a completed `web_publish` and three claims
  that are *required* to be refused — a second lineage on the same domain, the same artifact
  republished, and a `marketplace_listing` while `real_commerce` is shut. **That last one is the
  point of the slice: `external_publish` is open and `real_commerce` closed in one colony, so a
  kernel that re-merged the two flags passes every other assertion in the run and fails there.** It
  also pins that approval is not permission — the refused grant is real and was approved by a
  person. `human_minutes` 38/34 → 58/54, both moving by exactly 20, so the email action's 4-minute
  subsidy gap survives intact. **No USD_REAL balance moves and `external_expense` is unchanged in
  both books (20 / 1550)**; `USD_REAL::reservation_reserve` 11 → 15 and `release` 9 → 13 move as a
  pair with `settle` fixed at 1, the tell that the four new wakes cost nothing.
- **Teeth-checked ten ways**, each failing its named test: the flag re-merged, the original
  skip-every-check-for-a-channel-with-no-counterparty bug, a missing target tolerated instead of
  failing closed, a same-lineage republish refused as a sibling collision, the duplicate check
  unscoped from its channel, the duplicate check unwindowed, a counterparty accepted on a publish
  channel, the check guessing instead of refusing to answer without a lineage, the target left
  unnormalised, and the target normalised for the query but written raw.
- **Hand-verified on a live colony**: both flags shut refuses; opening `external_publish` allows a
  `web_publish` check while `marketplace_listing` stays refused on `real_commerce`; a check with no
  lineage and a check with no target each refuse with the right diagnosis. Migration 22 applied,
  six flags present, three new indexes created, conservation green and hash chain valid.
- Next: `browser_control` is the last undecided flag and is not the same question — it gates §25.1
  rung 8–9 automation, so there is nothing yet for a §0.4 argument to be about. The publish path
  now makes the missing `set-rights` verb bite harder: an artifact built on a fetched page is
  `commercial_use: unknown` forever, so `real_commerce` could be opened and still sell nothing.
