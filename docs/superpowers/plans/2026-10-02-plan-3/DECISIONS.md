# Plan 3 -- binding user decisions (2026-10-02)

These SUPERSEDE anything in a lane plan that disagrees. A lane's "Questions for the user" are
answered here; do not re-ask them.

From the planning session (also in PLAN.md):
1. Installers SET `X4_TOOLKIT` at OS level; `--no-env` opts out; NEVER silently overwrite a different
   existing value (report it, leave it). The comparison is canonical (slashes/case on Windows).
2. OpenCode: best effort from online docs/source only, CLI ONLY (desktop app unsupported, issue
   anomalyco/opencode#38604), no local install, labelled "from docs, not measured".
3. Codex Linux/macOS: best effort, no WSL work.
4. `x4-paths.env` move to the toolkit root is IN v4.0 (lane I, after J/G/L/H merge, alone).
5. Toy-agent test: BOTH a committed toy adapter run by conformance in CI AND a once-per-release
   cold-subagent exercise.
6. A `ci/` branch was pushed for early CI (`ci/plan2`); no other push.
7. `gh repo rename` is done by the orchestrator at release, after the user's explicit go-ahead.

Answers to the lane planners' questions:
- J-Q1: YES -- a bare `git clean -x/-d` or `git reset --hard` whose cwd is the game folder (or an X4
  dir) becomes a DENY with a reason (never ask/prompt).
- J-Q2: YES -- reword the Codex banner after the pinned prefix so it does not claim every shell
  command is checked (`write_stdin`, `workdir` are not).
- J-Q3: YES -- add the 4 other measured disclosures to the README.
- J-Q4: ONE `codex exec` run for M10, in a scratch dir. The orchestrator runs it (not the lane);
  the lane prepares the exact command and the doc section with a placeholder.
- G-Q1: the per-release cold exercise lives in `docs/ADAPTING-COLD-TEST.md`; the orchestrator adds a
  one-line pointer to the user-level releasing skill (not the lane).
- G-Q2: YES -- the neutral extra cases run for every adapter by default.
- H-Q1: `--agent auto` with no agent detected installs `all` and prints that nothing was detected.
- H-Q2: YES -- ONE live Windows check with a throwaway variable `X4_LANEH_PROBE` (set, read back,
  delete). The real `X4_TOOLKIT` must never be written by any test or probe.
- H-Q3: shipped versions = release TAGS only.
- L-Q1: YES -- `--agent all` INCLUDES OpenCode (and therefore so does `auto` with nothing detected).
  Lane H: `all` and the auto-fallback must include opencode once L merges; write it table-driven.
- L-Q2: YES -- deny rules also block shell DELETE commands aimed at reference/, never reads.
- L-Q3: YES -- the game-install block is plugin-only for OpenCode; README says so.
- L-Q4: YES -- vendor OpenCode's MIT path matcher into the tests (with its licence header).

Orchestrator finding (MEASURED 2026-10-02, assigned to LANE J): 0 files under `.agents/` or
`agent/` contain the `{{TOOLKIT}}` token, while 7 `.agents/` files contain a literal `$X4_TOOLKIT`;
the installers' per-OS rewrite (`install.sh:530`, `install.ps1:334`) therefore never fires, and Codex
on Windows (PowerShell) sees an empty `$X4_TOOLKIT`. The installer test misses it because it builds a
fake source containing the token. Fix in the generator so the generated Codex/generic skills carry
`{{TOOLKIT}}`, and make the installer test use the REAL generated tree. Test-first.
