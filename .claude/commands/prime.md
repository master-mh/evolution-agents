---
description: Warm-start after a context clear — reconstruct the active thread from the tracking files without loading the spec wholesale
argument-hint: [focus]
---

# Prime

Warm-start after a context clear. Reconstruct just enough state to resume the active thread —
reading only the small tracking files, never the ~1,300-line spec wholesale. The goal is a tight
orientation and a proposed next action, not a re-read of the repo.

**Run this right after `/clear` (or at the top of a fresh session) before picking up work.**

## Variables

focus: $ARGUMENTS  (optional — a hint to narrow the prime, e.g. `reservation FSM`, `ledger`,
`the approval queue`, `ADR-049`. Default: auto-detect the active thread from git + BUILD_RECORD.)

## What's already in context — do NOT re-read

- **CLAUDE.md** — auto-loaded as project instructions, and it is the densest orientation document
  in the repo: layering and dependency direction, the three-book money model, the `_*_locked`
  transaction split, the golden-run contract, and a running list of precedents where SPEC.md forbade
  the obvious design. Parse it in place; it is not a placeholder and has not been one since Phase 1.
- **MEMORY.md index** — the one-line-per-memory index is injected if the memory feature is active.
  Individual memory files under
  `/Users/mohammadmaster/.claude/projects/-Users-mohammadmaster-Developer-Evolution-Agents/memory/`
  are NOT loaded — pull them by name only in Phase 4.

This project has **no SessionStart hook** — so `PRIORITIES.md` and `BUILD_RECORD.md` are NOT
auto-injected. Prime reads them itself in Phase 1, but only `BUILD_RECORD.md` is small enough to
read whole; see Phase 1 for how to read the other.

## Instructions

### Phase 1 — Load the small tracking files

These ARE the map for this project — but **only one of them is small enough to read whole.**
- `BUILD_RECORD.md` (~5 KB, one entry by design) — read in full. Its last line states the "Next".
- `PRIORITIES.md` (**~75 KB and growing** — completed items keep their full write-up rather than
  being deleted) — **never `cat` it.** Doing so has blown a prime's output past the tool limit and
  truncated it to a file. Read it as:
  ```bash
  grep -n "^## \|^- \[ \]" PRIORITIES.md
  ```
  That returns ~20 lines instead of 75 KB. Then `sed -n` only the unchecked items that matter.
  **The `Now` bucket has been fully checked off since the kernel was finished, so the front is the
  top unchecked item in `Next`** — and several entries there are explicitly blocked on an unbuilt
  phase, so read down until you find one that is actually actionable.
- Note `FUTURE_BUILD_HOOKS.md` (~95 KB) and `docs/DECISIONS.md` (~190 KB, 49 ADRs) exist and are
  **not** prime reading. Grep them in Phase 4 if the thread needs one.

If `focus` was passed, treat it as the target and skip the guesswork in Phase 3.

### Phase 2 — Orient on live git state

Read-only, in parallel:
1. `git branch --show-current` + `git status -sb` — where we are, what's uncommitted, AND
   whether the branch is ahead/behind its remote. Use `-sb`, not plain `--short`: `--short` alone
   suppresses the ahead/behind line, which has caused a prime to call an unpushed branch "clean."
2. `git log --oneline -12` — recent landings.
3. `git diff --stat` — uncommitted working-tree changes (in-flight work).
4. If not on `main`: `git diff main...HEAD --stat`.
5. `git stash list` — anything parked.
6. If a remote exists: `git rev-list --left-right --count origin/main...HEAD` to state the
   ahead/behind count explicitly in the brief, not just imply it from `-sb`'s `##` line.

**A clean tree is now the normal state**, not a sign nothing happened: each finished slice is
committed and pushed to `main` under a standing authorization, so the usual result of Phase 2 is
"clean, in sync" and the active thread comes from `BUILD_RECORD.md`'s "Next" line instead. An
uncommitted diff means a slice was interrupted mid-flight — that is the exception worth
investigating, not the default. Reconcile git against the top unchecked `Next` item.

### Phase 3 — Name the single active thread

Synthesize one sentence: *"We are mid-`X`; last landed `Y`; the gating next step is `Z`."*
- Prefer `BUILD_RECORD.md`'s stated "Next", then the top *actionable* unchecked item in
  PRIORITIES `Next` (`Now` is fully checked). Check any `*Disproved by:*` pointer before
  scheduling — entries are written when a gap is noticed and never re-read when a later slice
  fills it.
- If uncommitted files exist, the active thread is almost certainly them — reconcile with PRIORITIES.
- If git and PRIORITIES disagree (something landed but isn't recorded, or vice versa), flag it
  rather than guessing.

### Phase 4 — Pull only what the thread needs (narrow reads)

`docs/SPEC.md` is the big object (~1,300 lines, the normative v0.2 spec). NEVER read it wholesale.
On the critical path, smallest slice that answers the question:

- **Spec slice**: `grep -n` for the section the thread touches (a section number, `reservation`,
  `ledger`, `Colony Charter`, `Phase 0`, an amendment) and Read only that range.
- **In-flight code/docs**: `git diff <specific files>` for the uncommitted files.
- **One relevant memory file**, by name, never the whole directory. The index in context names
  each one's hook; the four that carry the most per byte are `project-mitosis` (where the build
  actually is, and what is deliberately unbuilt), `feedback-mitosis-slice-workflow` (how a slice is
  run, teeth-checking, live measurement), `feedback-mitosis-reserved-sockets` (grep for the socket
  the spec already reserved — thirteen found so far), and `feedback-mitosis-claim-drift` (the repo's
  comments go stale faster than its code, and absence-claims go stale first).
- **`docs/DECISIONS.md`** is the real rationale store now, not a plan file: `grep -n "^## ADR-"` for
  the list, then read only the one ADR the thread touches. An ADR's *"What it displaced"* section is
  a list of alternatives someone already thought through — worth reading before re-deriving one.
  Note the Downloads originals (`~/Downloads/mitosis_full_build_spec.md`,
  `MITOSIS_v0.2_revision_directive.md`) still exist and must never be edited; there is **no** live
  plan file under `~/.claude/plans/` for this project, and an earlier version of this command
  pointed at one that had been deleted.

Skip anything off the critical path.

### Phase 5 — Brief + confirm the target

Output a tight orientation (no preamble):

```
── Primed ───────────────────────────────────────

Branch:     <branch>  (<clean | N files uncommitted>, <N commits unpushed to origin | in sync with origin>)
Last landed: <one line from BUILD_RECORD / git>
Active thread: <the one sentence from Phase 3>

Next action (proposed):
  <the single most likely next step — BUILD_RECORD's stated "Next", the top actionable `Next`
   item, or finishing interrupted in-flight work>

Watch-outs:
  - <blocker / open question / locked decision from memory, if any>

────────────────────────────────────────────────
Proceed on this, or point me elsewhere?
```

Then stop and wait. Do not start editing until the user confirms the target or redirects.

## Rules

- **Never re-read what's already injected.** CLAUDE.md and the MEMORY index are in context — parse
  them in place.
- **Read the tracking files, not the spec — and only `BUILD_RECORD.md` is small enough to read
  whole.** `PRIORITIES.md`, `FUTURE_BUILD_HOOKS.md`, `docs/DECISIONS.md` and `docs/SPEC.md` are all
  tens of KB: `grep` to the section and read only that range.
- **Memory files are pulled by name, on demand.** One at a time, only when the active thread needs it.
- **Prime is read-only.** No edits, no commits. It orients; it doesn't act. (Do not edit the
  Downloads spec originals under any circumstance.)
- **Verify a tracking claim before repeating it.** Both `PRIORITIES.md` and this file have carried
  confidently wrong statements — that is the documented failure mode of this repo's prose
  (`feedback-mitosis-claim-drift`). If the brief is about to assert something is missing, blocked or
  unbuilt, spend the one `grep` that settles it.
- **One thread, not a status report.** Surface the single active thread and its next action. If
  truly ambiguous, list at most 2–3 candidates and ask which.
- **Flag drift, don't paper over it.** If git and the tracking files disagree about what landed,
  say so.
- **End on a question.** The last line hands control back — confirm the target before doing work.
