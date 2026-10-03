# Plan 3 lane-planning brief (shared by all lane planners)

You are planning ONE lane of Plan 3 of "universal agent support" for the X4 toolkit
(`$X4_TOOLKIT` = `$X4_TOOLKIT`, branch `master`, HEAD `0cb667f`).
Goal: the toolkit works as well under OpenAI Codex (and unknown agents) as under Claude Code, ships
as "X4 AI Assistant Toolkit" v4.0.0. Plans 1 and 2 are DONE and merged.

## READ FIRST (authoritative, in this order)
1. Plan 3 itself: `docs/superpowers/plans/2026-10-02-plan-3/PLAN.md` -- your lane's row, the user
   decisions (BINDING), the known traps.
2. Spec v2: `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (D1-D14; §11 =
   ADAPTING.md; D13 Codex = three layers + disclosure).
3. Measurements: `docs/superpowers/measurements/2026-09-30-codex-spike.md` (Codex hooks fail OPEN --
   only a JSON deny blocks; exit 2 fails open; a hook command starting with `"` never runs; changed
   hook definitions are inert until re-trusted, and the hooks.json template is FROZEN for that
   reason; Codex "Bash" runs PowerShell; AGENTS.md truncated past 32,768 bytes).
4. Plan 2 lanes + DECISIONS (format exemplar and what exists): `docs/superpowers/plans/2026-10-02-plan-2/`.
5. Repo rules: `CLAUDE.md` (toolkit root). Key: test-first (watch it fail); evidence tiers
   (MEASURED/READ/INFERRED/ASSUMED); one falsification twin per clause; CLAUDE.md <= 40,000 chars
   (no headroom); NEVER edit generated files (edit `agent/`, run `gen-agent-trees.py`); hooks
   deny/advise the agent and never prompt the user except X4 profile edits, saves, broken guard.

## Lessons from Plan 2 integration (plan around them)
- Editing a line anchored by `scripts/verify-hook-tests.py` makes that mutant stale: name every
  anchored line you touch and plan the re-anchor (same mutation, exactly one matching line).
- Two lanes defining a helper with the same name and different behaviour collided at merge: prefix
  new helpers with your lane letter or make them local.
- A test pinning an old policy breaks when another lane changes the policy: say which existing
  tests encode behaviour you change.
- Redundant mechanisms make mutants survive: one mechanism per behaviour.
- File content with backslashes: Write/Edit tools, never heredocs.

## Your deliverable
ONE plan file at the path in your task, format: Context, Global constraints, Interfaces
(produces/consumes), numbered tasks each with exact files, the failing test(s) first (real code),
implementation, exact commands with an `Expected:` line, commit message. Then:
- **Files touched (union)** -- flat list for merge-conflict checks against lanes J, G, L, H, I.
- **Verify-hook-tests anchors touched** -- list, or "none".
- **Cross-lane dependencies**.
- **Questions for the user** -- ONLY genuine design/policy decisions, each with a recommendation.
- **Confidence** per task (0-100%), and for every task under 90% the measurement that raises it.
- **Gate plan** -- focused tests only; the orchestrator runs ONE full gate per wave.

## Constraints
- PLAN ONLY. Do not edit/create/delete anything in the repo. Write only your plan file.
- Measure cheaply where you can (read code, read-only commands) and label claims; ASSUMED claims get
  a measuring task before anything builds on them.
- Never run long jobs (full pytest, verify-hook-tests, corpus). Machine memory is limited: no more
  than one focused test process at a time.
- Never push, never touch the real `reference` tree, the game install, or the X4 profile.
- Return a SHORT summary (<= 25 lines): task count, files union, anchors, dependencies, questions,
  lowest-confidence task.
