# Plan 3 implementation brief (every lane)

You implement ONE lane of Plan 3. Folder of this file = PLAN3 (the scratch plan3 folder). Read in
order: `PLAN3/DECISIONS.md` (binding; it answers your plan's user questions), your lane plan
`PLAN3/lane-<X>.md`, and `PLAN3/BRIEF.md` (lessons). The plan is your spec; any deviation needs a
written reason in your report.

## Workspace -- non-negotiable
- Create your OWN worktree from master:
  `git -C "$X4_TOOLKIT" worktree add "~/Projects/x4-p3-<lane>" -b session/p3-<lane> master`
  (lowercase lane letter). Do ALL work there. Never edit, stage or commit in the main checkout,
  never touch the game root `C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations`, the X4
  profile, or the real `reference` tree.
- `X4_TOOLKIT` in your environment points at the MAIN checkout. Prefix every command that runs
  toolkit code with `X4_TOOLKIT="<your worktree>"` (Git Bash). Prove it once at the start.
- Never `deploy-claude-dir.py --apply`, never push, never merge into master, never rebase onto it.
  Merge order (orchestrator): J -> G -> L -> H.
- Steps needing the USER or spending Codex quota are NOT yours: prepare them, mark PENDING-USER /
  PENDING-ORCHESTRATOR with the exact command.

## Method
- Test-first: write the test, run it, SEE it fail for the right reason, implement, see it pass.
  A test that passes before the implementation is a finding -- report it.
- One falsification twin per clause of a compound condition. Label claims MEASURED/READ/INFERRED.
- Edit `agent/` sources, then `cd tools/x4validate && uv run python scripts/gen-agent-trees.py`;
  never hand-edit generated files.
- Small commits, each gated on its focused tests run BARE with `rc=$?` captured (never
  `cmd | tail && git commit`). Stage explicit paths; never `git add -A`/`.`. End each commit message
  with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- File content containing `\`: Write/Edit tool or `chr(92)`, never a heredoc.
- Never `rm` with a glob or variable target (it prompts the user); delete explicit paths or use a
  Python helper inside your scratch folder. Multi-line scripts go in a file you Write, then run.
- **Machine memory is limited (4 lanes run at once). Run ONE test process at a time, focused tests
  only. NEVER run full pytest or `scripts/verify-hook-tests.py`** -- the orchestrator runs those once
  per wave. Foreground Bash caps at 10 min; longer goes to the background.

## Lane-end checks (ONCE, at the end; each bare with rc captured, X4_TOOLKIT = your worktree)
Your focused test files; plus the fast gates: `bash scripts/test-hooks.sh`;
`bash .claude/hooks/test-protect-bash.sh`; `uv run --no-project python .claude/hooks/test_hook_facts.py`;
`uv run --no-project python scripts/fuzz-guard.py`; `uv run --no-project python scripts/scan-identifiers.py`;
`cd tools/x4validate && uv run python scripts/gen-agent-trees.py --check`. If you edited a line that
`scripts/verify-hook-tests.py` anchors, re-anchor it (same mutation, exactly one matching line) and
say so -- do not run the gate itself.

## Report (final message, <= 30 lines)
Branch + commits; tasks done / skipped / PENDING-*; every deviation with its reason; each check's rc
and counts; files touched; existing tests whose expectations you changed and why; anything
surprising. Never claim a check passed that you did not run.
