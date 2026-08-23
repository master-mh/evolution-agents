# MITOSIS / Evolution Agents — Build Record

Keeps only the current entry so this file stays small enough to read in full every session.
Earlier slices (1–10, plus CI wiring, seeded ids, reproduction/lineage, the full Phase 4 gateway
arc, real-spend type registration, the first real paid call, revenue + Ollama, the `spend_by_book`
account fix, the prediction register, death criteria, §9.3 displacement, the agent loop, the
scheduler, the §23 approval queue, the dead-Cell estate, the rung-7 promotion path, the §25.2
read-back, §9.2's birth cap, Auditor Cells, genome content, the tool surface, and the artifact
store, 2026-07-21 through 2026-08-23):
[docs/BUILD_RECORD_ARCHIVE.md](docs/BUILD_RECORD_ARCHIVE.md).

## 2026-08-23 — The external-action registry: what the colony did outside itself

`channel_registry.py` + `external_actions.py` + migration 0021 (ADR-036). A Cell could decide, be
funded, read the world and produce a deliverable. What it could not do was put that deliverable in
front of anyone — `artifacts.export` recorded that a human took something outside the colony, and
there was no channel behind it. `external_action_registry` had been sitting in §31's table list
since the spec was written.

### §21.2's verbs are *track* and *prevent*, and neither is *send*

§28's Phase 8 acceptance is "all external action remains manual", so **nothing here transmits**. A
person performs the action; the kernel records what was done and refuses what would collide. That
refusal is Phase 9's acceptance criterion — "no duplicate or conflicting customer contact" — built
a phase early, because a guarantee that arrives with the first real customer has never been tested
against anything.

`test_nothing_in_the_registry_transmits` is structural: neither module may import anything that
opens a socket. The behavioural version of that test ("assert no email was sent") passes trivially
against code that would send one.

### The counterparty is a salted hash, and the do-not-contact list is the argument

§16.3 makes customer identity non-inheritable; §20.1 tracks personal data because holding it is a
liability. Everything §21.2 asks is a question about **equality** — have we contacted this person,
did a sibling get there first, did they ask us to stop — and equality survives hashing. A
`customers` table is the obvious design and the one the spec warns about.

The strongest argument is not privacy in the abstract, it is that **"never contact this person
again" is honoured permanently without the colony ever holding a list of the people who asked** —
which a customers table with an opt-out flag cannot do. Said plainly in the migration: a salt
beside the hashes does not defeat someone holding the file with a particular person in mind. It
defeats the colony enumerating its own contacts, which is what §16.3 is about.

`test_no_table_in_the_colony_holds_the_counterparty` is deliberately blunt — after a real claim the
plaintext must appear in no text column of any table. A label "just for the operator", a
counterparty echoed into an audit description, an intent quoting the address: each is a plausible
convenience and each rebuilds the customer list.

### §23.4's aggregation splits in two, each keyed where its dimension is knowable

A Cell names a channel and a purpose; the **operator** names the person. So the counterparty does
not exist at approval time, the queue keys an `external_action` on `channel:{id}`, and the
counterparty aggregation lives at claim time. ADR-027's lineage key was an explicit stand-in "until
counterparty/domain/channel exist" — and the gap it left is not cosmetic: §21.2's worry is *many
lineages, one counterparty*, and every splitter a lineage-keyed window can catch shares a founder
by construction.

### Claim before acting, so that "prevent" can mean something

Recording completed actions is the obvious shape and makes prevention impossible — the second email
is already sent by the time the kernel can object. So the row is written first and holds the
counterparty and the channel while a person works. Abandoning releases the claim but **not the
grant**: claiming took a slot another lineage could have used.

### The first guard in this kernel that bounds something money cannot repair

Charter C4, C5, the real-spend breaker, the promotion pool and the metabolic alarm all bound money.
§21.1's shared assets — sending reputation, merchant identity, brand — are the first thing at risk
that a refund does not fix. So the caps are rate and quota, and they are the **colony's** rather
than the Cell's, since §9 reproduction makes a per-Cell cap free to escape. A `complaint` freezes
the channel colony-wide until a person clears it with a stated reason (§23.3's alarm shape) and
blocks that counterparty forever. `negative_reply` is pointedly not damage — being told no is a
normal commercial outcome, and the control test is what keeps the guard from freezing on every
disappointment.

### Human minutes, metered for the first time since Phase 1

`ResourceType.HUMAN_MINUTES` had been declared since migration 0008 and consumed by nothing, while
§1 says autonomy-adjusted profit exists "to expose hidden human labour and subsidy" and
`outcome.py` counts intervention *events* but never time. A Cell now pays for the attention it
consumes. **Minutes past its channel's billable ceiling are recorded as subsidy, not refused** —
the minutes were already spent, so refusing to write them down does not un-spend them, it only
makes the colony's account of its own human cost quieter than reality.

### Three things found while building, each of which changed the design

- **A ceiling that reads as prudent can be an off switch.** Reserving a theoretical worst case
  (240 minutes) made one email cost more RESOURCE than a Cell has. No unit test could see it —
  every fixture funds generously — and the **golden run caught it**. Hence a per-channel billable
  ceiling and a test that asserts a claim costs a fraction of a real budget.
- **A §23.4 signal that fires unconditionally distinguishes nothing.** The first draft had the Cell
  claim MEDIUM against a kernel that assesses every external action HIGH, so `understated_risk`
  fired on every external action ever proposed — which looks like a working detector and is its
  opposite. The §15 context now states the tier outright.
- **A refusal that misidentifies what went wrong is worse than a blunter one.** Found on a live
  colony: `external-check` supplies no lineage, the sibling query was NULL-safe and matched the
  asker's *own* claim, and the message accused a second lineage of interference. The strictness was
  right and is unchanged; only the diagnosis moved.

### Verification

- **815 tests passing** (34 new, 0 removed; up from 781).
- **Golden expectation 15 → 16.** The scenario gains two completed external actions on `email` —
  one `no_response` and one `complaint` — plus a third whose claim is **required to be refused** as
  a §21.3 sibling collision. A run in which nothing ever went wrong would pass identically against
  a kernel that recorded damage and acted on none of it. `human_minutes: {reported: 38, billed:
  34}` differ on purpose: a snapshot with one figure could not tell a colony that measures its
  human cost from one that quietly truncates it. **No USD_REAL balance moves and `external_expense`
  is unchanged in both books (20 / 1550)**; `USD_REAL::reservation_reserve` 8 → 11 and `release`
  6 → 9 move as a pair, which is the tell that the three new wakes cost nothing.
- **Teeth-checked thirty-one ways**, each failing its named test: the counterparty stored in
  plaintext, the hash unnormalised, the duplicate and sibling checks removed, the rate cap scoped
  per Cell, a complaint that neither freezes nor blocks, `negative_reply` treated as damage,
  abandon stranding its reservation, the autonomy gate removed, any approved kind claiming a
  channel, a dead Cell acting, the export gate bypassed *and* the export gate refusing everything,
  another Cell's work delivered, human minutes unmetered, zero minutes accepted, over-ceiling
  minutes silently truncated, subsidy logged unconditionally, the reservation remainder stranded,
  an external action read as reversible, the aggregation key left on the lineage, an unknown
  channel not failed closed, the hash reaching the Cell's context, a Cell naming a counterparty,
  the claim ceiling back to a whole budget, the Cell not told its tier, the registry gaining a way
  to transmit, the scheduler reaching the registry, a fourth module quietly consuming a grant, and
  the misattributed refusal above.
- **Hand-verified on a live colony**, end to end: the closed flag refuses, the check passes once it
  is opened, a differently-cased address deduplicates, the plaintext appears nowhere in the
  database file, a 45-minute action bills 30 and records 15 as subsidy, the complaint freezes the
  channel for *every* counterparty, unfreezing restores it for a new one, and the blocked one stays
  refused. Conservation green in all three books, hash chain valid, USD_REAL settled 0.00.
- `context.py` gains two sections. The channels section cost **318 of a 1200-token budget** in its
  first draft — a quarter of every wake, on a capability whose flags ship off — and was cut to
  ~150; §15.1's budget is why `ChannelSpec` carries a `short_description` at all.
- Next: `external_publish` has two registered channels and no §0.4 decision behind it. §11.2's
  five-condition downstream credit and §11.4's decay still need experiment tracking, which still
  does not exist.
