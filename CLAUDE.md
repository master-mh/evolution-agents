# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Evolution Agents

This project's purpose and architecture are still being defined — no code exists yet. This
file will be filled in as the project takes shape. (Once there's a real codebase to document,
the `init` skill can generate a full architecture writeup from it — better than a hand-written
guess now.)

---

## Future Build Hooks

`FUTURE_BUILD_HOOKS.md` is an append-only parking lot for suggestions, ideas, and deferred
calls that come up mid-session — a plan's "out of scope" or "assumptions to confirm" notes, a
tangent worth remembering — so they don't die in a throwaway plan file under `~/.claude/plans/`.
It is **not** a roadmap. Append to it in real time whenever a plan or session produces one of
these; `/wrap` also sweeps for anything missed at end of session.
