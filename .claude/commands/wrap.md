# Wrap

End-of-session retrospective. Convert what happened in this session into compounding
documentation — `BUILD_RECORD.md` entries, `PRIORITIES.md` updates, memory entries,
`FUTURE_BUILD_HOOKS.md` entries — so the next session starts warm.

**Run this before the session ends, after shipping something, or when context starts feeling full.**

## Variables

scope: $ARGUMENTS  (optional — "quick" for a lightweight pass, "full" for everything, default "full")

## Instructions

### Phase 1 — Gather

Pull recent state so the proposal is grounded in actual changes, not vibes.

1. `git log --oneline -20` — recent commits
2. `git status` — uncommitted state
3. `git diff main --stat` if on a branch — what's pending merge
4. Walk through the current session's conversation in order, listing every distinct work item,
   decision, and surface-level fact. Capture:
   - Architecture or design decisions made (and the rationale, including alternatives considered)
   - Bugs fixed and how they were diagnosed
   - Things explicitly flagged for later
   - Decisions deferred (and why)
   - Operational state that changed (deployments, infrastructure, external services)
   - Files that materially changed and what they do now vs before

### Phase 2 — Propose

Output a single structured proposal. Use these section headers verbatim. Empty sections get
"Nothing this session." Aim for accuracy, not brevity — cover everything, even if sections are long.

**Shipped this session:**
- One bullet per concrete thing that landed (commit, fix, feature, file added)
- Include the user-facing impact, not just the change
- Reference commit hashes when relevant
- Include negative outcomes too (things attempted that didn't work, dead ends, reverts)

**Decisions made:**
- Each design call with rationale
- Especially the non-obvious ones — these are the most valuable to capture
- Include alternatives that were considered and why they were rejected
- Include decisions that were deferred and what's gating them

**Updates to propose:**

For `BUILD_RECORD.md` — show the exact markdown to add: a new dated entry
(`## YYYY-MM-DD — <title>`) with one bullet per concrete change, appended below the latest entry.
If the session only continues an existing day's work, propose extending that day's entry instead
of adding a new one.

For `PRIORITIES.md` — show diffs as before/after against the `Now` / `Next` / `Later` lists:
items to check off (`- [ ]` → `- [x]`), items to add, items to promote/demote between the three
buckets, items to drop. If the bucket structure itself should change, propose that too.

For memory entries — for each candidate, show:
  - Proposed filename (e.g. `feedback_strict_sequential.md`)
  - Type: user / feedback / project / reference
  - Full frontmatter + body content

Only propose memory entries that pass the "would a future session genuinely need this?" test.
Skip ephemeral context (current task state, in-progress decisions, things derivable from git log).
When in doubt, propose it — the user can drop it in the confirmation step.

For `FUTURE_BUILD_HOOKS.md` — sweep the session for suggestions, ideas, or deferred calls that
came up (in plans, in conversation) but were never appended in real time. Show the exact entry
to add, dated, under a header naming the session/plan it came from. Most sessions this is empty
if entries were already appended as they happened — that's expected, not a miss.

**Outstanding / queued for next session:**
- Things in progress, including partial state
- Known gaps with concrete next actions
- Blockers waiting on user input
- Tasks left in_progress in the TaskList
- Tech debt observed but not addressed

**Open questions for the user:**
- Decisions that need input before next session can proceed
- Things flagged for confirmation
- Choices we deferred
- Anything where an assumption was made that should be validated

**Risk / debt notes:**
- Known fragile points introduced or surfaced this session
- Tests that should exist but don't yet
- Documentation that's now out of date
- Operational footguns (deployment gotchas, credential handling, etc.)

### Phase 3 — Confirm

Ask the user: *"Approve all, edit, drop specific items, or skip?"*

Wait for explicit approval before writing. If they say edit, take the changes and re-show the proposal.

### Phase 4 — Apply

Only after approval:

1. Edit `BUILD_RECORD.md` — append the dated entry (or extend the current day's entry).
2. Edit `PRIORITIES.md` — apply the diffs (check off completed items, add new ones, move items
   between `Now` / `Next` / `Later`).
3. Write memory entries to `/Users/mohammadmaster/.claude/projects/-Users-mohammadmaster-Developer-Evolution-Agents/memory/`
   with frontmatter:
   ```
   ---
   name: {short-kebab-case-slug}
   description: {one-line summary}
   metadata:
     type: {user|feedback|project|reference}
   ---

   {body}
   ```
4. Add a one-line entry to `MEMORY.md` index for each new memory file:
   `- [Title](filename.md) — one-line hook`
5. Append approved entries to `FUTURE_BUILD_HOOKS.md`, newest at the bottom, under a dated header.

Do NOT commit any of these changes — the user handles git commits explicitly.

### Phase 5 — Confirm complete

Tell the user:
```
── Session wrapped ──────────────────────────────

BUILD_RECORD:        N entries added
PRIORITIES:          M items updated
Memory:              K new entries saved
Future Build Hooks:  J entries added

Open for next session:
  - [first outstanding item]
  - [second outstanding item]
  - ...

────────────────────────────────────────────────
```

## Rules

- **Propose specifically, not narratively.** "Add X" not "we should think about Y."
- **Show the actual edits before applying.** Diffs, not summaries.
- **Never apply without explicit approval.** Even single-word approval ("yes") counts;
  ambiguous responses don't.
- **Memory entries earn their place.** A new memory file should explain *why* a future
  session needs it — not just record what happened.
- **No padding, no preamble, no sign-off.** Direct output, structured for fast review.
- **Skip the things git already tells us.** Don't memory-entry "we committed X on date Y" —
  git log has that. Memory is for non-obvious context, not activity logs.
- **Accuracy over brevity.** Long sections are fine if they capture real signal. The goal is
  that next session starts warm, not that this output looks tidy.
