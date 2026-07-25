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
`Phase 0 artifacts`, `DECISIONS.md`. Default: auto-detect the active thread from git + PRIORITIES.)

## What's already in context — do NOT re-read

- **CLAUDE.md** — auto-loaded as project instructions. It is currently a placeholder (the project
  is pre-code), so it carries little — don't expect a roadmap or architecture from it yet.
- **MEMORY.md index** — the one-line-per-memory index is injected if the memory feature is active.
  Individual memory files under
  `/Users/mohammadmaster/.claude/projects/-Users-mohammadmaster-Developer-Evolution-Agents/memory/`
  are NOT loaded — pull them by name only in Phase 4.

Unlike the Varen repo, this project has **no SessionStart hook** — so `PRIORITIES.md` and
`BUILD_RECORD.md` are NOT auto-injected. Prime reads them itself in Phase 1; they're tiny.

## Instructions

### Phase 1 — Load the small tracking files

Read in full — each is well under 2 KB, and they ARE the map for this project:
- `PRIORITIES.md` — the `Now` / `Next` / `Later` list; the top unchecked `Now` item is the front.
- `BUILD_RECORD.md` — the latest dated entry names what just landed and the stated "Next".

If `focus` was passed, treat it as the target and skip the guesswork in Phase 3.

### Phase 2 — Orient on live git state

Read-only, in parallel — this repo is young, so expect a short history:
1. `git branch --show-current` + `git status -sb` — where we are, what's uncommitted, AND
   whether the branch is ahead/behind its remote. Use `-sb`, not plain `--short`: `--short` alone
   suppresses the ahead/behind line, which has caused a prime to call an unpushed branch "clean."
2. `git log --oneline -12` — recent landings.
3. `git diff --stat` — uncommitted working-tree changes (in-flight work).
4. If not on `main`: `git diff main...HEAD --stat`.
5. `git stash list` — anything parked.
6. If a remote exists: `git rev-list --left-right --count origin/main...HEAD` to state the
   ahead/behind count explicitly in the brief, not just imply it from `-sb`'s `##` line.

This project is spec-stage — a lot of work has historically sat uncommitted. An uncommitted
`docs/` diff is the likely active thread. Reconcile git against the PRIORITIES `Now` item.

### Phase 3 — Name the single active thread

Synthesize one sentence: *"We are mid-`X`; last landed `Y`; the gating next step is `Z`."*
- Prefer the top unchecked item in PRIORITIES `Now` unless git shows something else in flight.
- If uncommitted files exist, the active thread is almost certainly them — reconcile with PRIORITIES.
- If git and PRIORITIES disagree (something landed but isn't recorded, or vice versa), flag it
  rather than guessing.

### Phase 4 — Pull only what the thread needs (narrow reads)

`docs/SPEC.md` is the big object (~1,300 lines, the normative v0.2 spec). NEVER read it wholesale.
On the critical path, smallest slice that answers the question:

- **Spec slice**: `grep -n` for the section the thread touches (a section number, `reservation`,
  `ledger`, `Colony Charter`, `Phase 0`, an amendment) and Read only that range.
- **In-flight code/docs**: `git diff <specific files>` for the uncommitted files.
- **One relevant memory file**: `project-mitosis.md` holds the locked decisions, the 4 accepted
  pushbacks, 3-book accounting, and the plan path — Read it if the thread needs the rationale.
  Not the whole memory dir.
- **The full plan**: `~/.claude/plans/users-mohammadmaster-downloads-mitosis-cheeky-stardust.md` —
  `grep` it for the relevant phase rather than loading it whole. Do NOT touch the Downloads
  originals (`~/Downloads/mitosis_full_build_spec.md`, `MITOSIS_v0.2_revision_directive.md`).

Skip anything off the critical path.

### Phase 5 — Brief + confirm the target

Output a tight orientation (no preamble):

```
── Primed ───────────────────────────────────────

Branch:     <branch>  (<clean | N files uncommitted>, <N commits unpushed to origin | in sync with origin>)
Last landed: <one line from BUILD_RECORD / git>
Active thread: <the one sentence from Phase 3>

Next action (proposed):
  <the single most likely next step — the top Now item, the next Phase 0 artifact, finishing
   in-flight work>

Watch-outs:
  - <blocker / open question / locked decision from memory, if any>

────────────────────────────────────────────────
Proceed on this, or point me elsewhere?
```

Then stop and wait. Do not start editing until the user confirms the target or redirects.

## Rules

- **Never re-read what's already injected.** CLAUDE.md and the MEMORY index are in context — parse
  them in place.
- **Read the tracking files, not the spec.** PRIORITIES.md + BUILD_RECORD.md are tiny — read them
  whole. `docs/SPEC.md` and the plan file are large — `grep` to the section and read only that range.
- **Memory files are pulled by name, on demand.** One at a time, only when the active thread needs it.
- **Prime is read-only.** No edits, no commits. It orients; it doesn't act. (Do not edit the
  Downloads spec originals under any circumstance.)
- **One thread, not a status report.** Surface the single active thread and its next action. If
  truly ambiguous, list at most 2–3 candidates and ask which.
- **Flag drift, don't paper over it.** If git and the tracking files disagree about what landed,
  say so.
- **End on a question.** The last line hands control back — confirm the target before doing work.
