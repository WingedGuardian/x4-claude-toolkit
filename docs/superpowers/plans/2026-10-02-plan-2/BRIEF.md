# Plan 2 lane-planning brief (shared by all lane planners)

You are planning ONE lane of Plan 2 of "universal agent support" for the X4 toolkit
(`$X4_TOOLKIT`, env `X4_TOOLKIT`, branch `master`). Goal of the
whole project: the toolkit works as well under OpenAI Codex (and unknown agents) as under Claude
Code, in the PUBLIC release. Plan 1 is DONE (neutral source tree `agent/` -> generator
`tools/x4validate/scripts/gen-agent-trees.py` -> CLAUDE.md, AGENTS.md (stopgap), `.claude/`;
`x4guard check` front door at `agent/guards/claude-hooks/x4guard.py`).

## READ FIRST (authoritative, in this order)
1. Spec v2: `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (decisions D1-D14;
   D13 = Codex gets three layers + disclosure instead of full hook parity; D14 = OS deny-delete on
   `reference` only; D10 = wrap; D11 = .rules `prompt`).
2. Measurements: `docs/superpowers/measurements/2026-09-30-codex-spike.md` (Codex 0.159.2: hooks FAIL
   OPEN -- only a JSON deny blocks; changed hook definitions are silently inert until re-trusted;
   `.rules` prefix_rule forbidden/prompt are fail-CLOSED; Codex "Bash" runs PowerShell; apply_patch
   carries the patch in tool_input.command; AGENTS.md silently truncated past 32,768 bytes).
3. Plan 1 (format exemplar + what exists): `docs/superpowers/plans/2026-09-30-universal-agent-support-plan-1.md`.
4. Framework audit: `docs/AUDIT-framework-2026-10-01.md` (open: F1 interpreter writes, F8/F9
   installers/x4lock omit AGENTS.md and agent/, guard-health telemetry).
5. Repo rules: `CLAUDE.md` (toolkit root) and the game-root rules it references. Key ones: test-first
   (watch it fail), evidence tiers (MEASURED/READ/INFERRED/ASSUMED), a check that cannot go red is
   decoration (one falsification twin per clause), CLAUDE.md <= 40,000 chars (currently ~39,971 --
   effectively NO headroom), never edit generated files (edit `agent/`, regenerate), hooks must
   advise/deny Claude and never prompt the user except for profile edits / deletes in X4 dirs.

## Your deliverable
Write ONE plan file at the path given in your task, in the Plan 1 format: Context, Global
constraints, Interfaces (what this lane produces/consumes), then numbered tasks, each with: files
touched (exact paths), the failing test(s) to write first (real code, not prose), the
implementation, exact commands with an `Expected:` line, and the commit message. Then:
- **Files touched (union)** -- a flat list, so lanes can be checked for merge conflicts.
- **Cross-lane dependencies** -- what you need from other lanes (A instruction split, B Codex
  adapter, C installers/x4doctor, D Layer 2 OS protection, E x4guard hardening), and what they need from you.
- **Questions for the user** -- ONLY genuine decisions (design/policy), each with your recommended answer.
- **Confidence** per task (0-100%) and what measurement would raise any task below 90%.
- **Gate plan** -- focused tests per task; the FULL gate set runs once at lane end (do not plan
  full-suite runs per task: under load the mutation gate takes ~29 min and pytest ~30 min).

## Constraints
- PLAN ONLY. Do not edit, create or delete anything in the repo. Read freely. Write only your plan file.
- Measure, don't assume: if a claim the plan rests on can be checked cheaply by reading code or
  running a read-only command, check it and label it MEASURED/READ; otherwise label it ASSUMED and add
  a task that measures it before building on it.
- Never run the long gates (pytest full, verify-hook-tests, corpus jobs). Focused reads only.
- Keep the plan executable by a competent implementer with no other context.
- Return a SHORT summary (<= 25 lines): task count, files-touched union, dependencies, user questions.
