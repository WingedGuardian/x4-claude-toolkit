# Finish universal agent support: everything after Plan 2, through the v4.0.0 release

## Context

Plans 1 and 2 are merged on toolkit master `7ed1417` (not pushed) and deployed to the game root
(`ad75ca3`, parity 41/41). Claude Code, Codex (adapter + .rules + conformance) and generic agents
work; OS lock, x4doctor, installers with `--agent`, x4guard hardening and the relative-path fix
landed. The user wants EVERYTHING that remains planned and run with maximum parallelism.

What remains (surveyed read-only 2026-10-02, two Explore agents; evidence in their reports):

| Area | Status |
|---|---|
| `ADAPTING.md`, toy-agent test, universal setup prompt, `x4guard conformance` (spec D7, §11) | NOT DONE |
| Installers: `--agent auto`; set `X4_TOOLKIT` at OS level; 3.x `CLAUDE.md` -> `X4-NOTES.pre-4.0.md` by shipped-version hashes; Codex `project_doc_max_bytes` opt-in | NOT DONE (done: `--agent claude/codex/generic/all`, Codex trust steps printed, global hook-free) |
| `x4-paths.env` -> toolkit root + deprecation read (~325 refs / 86 files); guards silently fall back to `<toolkit>/reference` when no config (`_x4-env.sh:43-93`) | NOT DONE (x4doctor already FAILs it) |
| Rename to "X4 AI Assistant Toolkit": ~15 files + zip prefix `scripts/build-release.sh:33` + `test_build_release.py`; README title; GitHub repo | NOT DONE |
| OpenCode | refused today (`install.sh:543`) |
| Backlog: `gen-cli-reference.py:192` unguarded decode; test-hooks 1/187 flake under load (unidentified, seen twice); x4guard 25 s default vs load; codex.md banner (xfail-strict `test_codex_disclosure.py:31`); README residuals (Codex `workdir`, `write_stdin`, bare `git clean -fdx`); stale CI comment (`ci.yml:47-50`); M10 `additionalContext` cap unmeasured; old `pr2` branch | OPEN |
| Release v4.0.0: full release review since v3.3.1, cold clone, install red-team, push/CI/tag/release/Nexus | NOT STARTED |

User decisions this session (binding): installers SET `X4_TOOLKIT` with `--no-env` opt-out (never
silently overwrite a different value); OpenCode = best effort from online docs only, **CLI only --
the desktop app is NOT supported** (its plugin hooks never fire, issue #38604), no local
install/measurement, labelled "not measured"; Codex Linux/macOS stays best effort (no WSL work);
I run `gh repo rename` at release after an explicit go-ahead; **the `x4-paths.env` move is IN v4.0**
(user: deferring buys nothing -- there is no release urgency; risk is managed by sequencing and
measurement, not by postponing); toy-agent test = BOTH a committed toy adapter in CI AND a
once-per-release cold-subagent exercise; **push a non-release `ci/` branch now** for early CI.

Pre-plan checks (2026-10-02, read-only): master still `7ed1417`, no other worktrees; only
README.md:338/359 name the GitHub repo URL (update them in the rename -- raw/release-download
redirects are undocumented); OpenCode has `tool.execute.before` (block by throwing) and a
permission config where an explicit deny is final (READ, docs + guides).

Known traps to carry into the lane briefs:
- Codex hook TIMEOUT lives in the FROZEN hooks.json template: changing it changes the template
  hash -> every Codex user must re-review hooks (CHANGELOG "Codex users must re-review hooks").
- 3.x migration hashes: installed CLAUDE.md copies are installer-REWRITTEN and CRLF/LF varies --
  hash the normalised, rewritten form of every tagged release, not the raw shipped file.
- M10 measurement spends the user's Codex quota: keep it to the minimum runs.

## How we run it (lessons from Plan 2 applied)

- **Plan, then build, in parallel lanes** -- one opus planner per lane (read-only, writes a plan
  file), my conflict check + ONE batch of user questions, then one opus implementer per lane in
  its own worktree/branch (`session/p3-<lane>`), using the Plan 2 brief
  (`docs/superpowers/plans/2026-10-02-plan-2/` IMPL-BRIEF pattern: test-first, twins, Write tool
  for content, no rm globs, no self-terminating heredocs).
- **No full gate run per lane** (Plan 2: per-lane full gates x5 hit a memory kill). Lanes run
  focused tests only; I run ONE combined gate after each wave's merges, max 2 heavy jobs at once.
- **Expect integration fixes at merge**: stale mutation anchors (re-anchor, same mutation, one
  line each), cross-lane semantic conflicts (tests encoding an old policy), duplicate helper
  names. Rule out each; never "fix" a test without reading what it pins.
- Never push, tag, release, rename the repo, deploy before commit, or touch the real reference
  tree without the user. Commit small, explicit paths.

## Step 0 -- before Wave 1

1. Write this plan + decisions into the toolkit repo (`docs/superpowers/plans/2026-10-02-plan-3/`),
   update memory -- including a feedback memory: **never propose deferring work to a later
   version without a functional reason; there is no release urgency, and risk is managed by
   sequencing + measurement, not postponement** (user, 2026-10-02) -- then **compact**.
2. **Early CI:** push master's commits to a branch `ci/plan2` (no tag/release; GitHub master
   untouched). Read EVERY job's result per test; failures become Wave-1 work (lane J), each
   classified real vs CI-environment. Correct the counted skip ceilings from the real run.

## Wave 1 -- five parallel lanes (lane I runs AFTER the others merge, alone)

| Lane | Scope | Main files |
|---|---|---|
| **J -- hardening backlog** | `gen-cli-reference.py` decode -> rc 2 refusal (+twin); flake hunt (run test-hooks N times under synthetic load, name the probe, fix the instrument or the probe); re-measure the x4guard default timeout vs Codex hook timeout, set both; codex.md banner paragraph (flip the strict xfail); README residual disclosures (Codex `workdir`, `write_stdin` per DECISIONS #20, bare `git clean -fdx`); fix the stale CI comment; measure M10 (`codex exec`, scratch only) and record it; inspect `pr2` and report (no action) | `gen-cli-reference.py`, `x4guard.py`, `agent/guards/adapters/codex.py`, `agent/instructions/codex.md`, `README.md`, `ci.yml`, measurements doc |
| **G -- ADAPTING.md** | `ADAPTING.md` per spec §11 (self-assessment incl. fail-open/closed measurement, the contract, worked Claude + Codex examples, where adapters go, required proof, rules, upstream template); `x4guard conformance` subcommand that drives ANY adapter through the existing case dump (reuse `test_codex_conformance.py` / `codex_testlib.py` machinery, generalised); toy-agent test: a minimal adapter written only from ADAPTING.md must pass conformance; universal setup prompt (`SETUP_PROMPT.txt` successor) | `ADAPTING.md` (new), `x4guard.py` (subcommand), `agent/guards/adapters/`, `tools/x4validate/tests/` |
| **L -- OpenCode best effort, CLI only** | Research OpenCode's official docs online (AGENTS.md/rules, permission config, plugin/hook API, skills); generate an `opencode` target from `agent/`: **primary** = permission config with explicit DENY rules for the hard blocks (final per docs); **secondary** = a plugin whose `tool.execute.before` calls `x4guard check` and throws on deny; desktop app explicitly unsupported (issue #38604); `--agent opencode` installs it best effort instead of refusing; README "best effort, CLI only, from docs, not measured"; every claim labelled READ with the doc URL | `gen-agent-trees.py` (target), `agent/targets/opencode/` (new), `install.sh/.ps1` (small), README |
| **I -- config location + no silent fallback (sequenced LAST, alone)** | `x4-paths.env` moves to the toolkit root; ONE loader per language (`_x4-env.sh`, `_paths.py`) reads new first, old with a deprecation notice; installers/deploy/x4doctor/x4lock/tests follow; the game-root copy placed today migrates; guards with NO config stop falling back silently -> an advisory naming the gap (never a prompt). **Risk controls:** branch from master AFTER J/G/L/H merge; a precedence matrix test (new only / old only / both agree / both differ / neither) for BOTH loaders with `test_config_precedence_agrees`; a guard-verdict replay OLD vs NEW over the historical corpus (lane F's harness) proving 0 changed verdicts for configured roots; live probes in the game root before and after | `_x4-env.sh`, `_paths.py`, `deploy-claude-dir.py`, `x4doctor.py`, `x4lock.py`, installers, many tests/docs |
| **H -- installers + migration** | `--agent auto` (detect installed agents: `claude`/`codex` on PATH, existing `.claude/`/`.codex/`); set `X4_TOOLKIT` (Windows user env via registry/setx, POSIX shell profile line) with `--no-env`, report-don't-overwrite; 3.x -> 4.0: a personalised `CLAUDE.md` (hash matches no shipped version -- derive the set from every git tag) saved as `X4-NOTES.pre-4.0.md`; Codex `project_doc_max_bytes` opt-in flag; both installers agree (`test_installers_agree.py`) | `install.sh`, `install.ps1`, `test_install_over_existing.py`, `test_installers_agree.py` |

Run J, G, L, H in parallel (planners, then implementers); merge **J -> G -> L -> H**, combined
gate; THEN lane I alone on top (its own planner + implementer + replay), merge, combined gate.
Lane H writes the config at the CURRENT location; lane I moves it (installers included).
Shared: `install.sh/.ps1` (L, H, I), `x4guard.py` (J, G), `gen-agent-trees.py` (L),
README/CHANGELOG (all). G's toy-agent test has two parts: a committed toy adapter run by
conformance in CI, and a once-per-release cold-subagent exercise (adapter from ADAPTING.md only).
Then ONE combined gate (hook suites, fuzz, scan, generators, mutation gate, pytest), deploy,
commit game root.

## Wave 2 -- serial (after Wave 1 is merged)

1. **K -- rename** (one agent, mechanical): product name to "X4 AI Assistant Toolkit"
   everywhere current (README title + "What is Claude Code?" framing, setup.sh, SETUP_PROMPT,
   installers, ci.yml, x4-paths.env.example, `build-release.sh:33` zip prefix
   `X4.Foundations.AI.Assistant.Toolkit-vX.zip` + `test_build_release.py`, generated sources via
   `agent/`); leave CHANGELOG history and dated docs alone; a test pins the new zip name.
2. **4.0 docs**: README overview for all agents, CHANGELOG `## v4.0.0` section consolidated
   from Unreleased, version bump.
3. Combined gate again; deploy; commit game root.

## Wave 3 -- release v4.0.0 (release-review + releasing skills)

1. **Full release review** of everything since v3.3.1 (user rule: every changed file read in
   full), split into parallel opus reviewers by area: (a) guards + adapters + rules;
   (b) generator + agent trees + instructions + skills; (c) installers + setup + x4lock +
   x4refguard + x4doctor + deploy; (d) x4validate/BaseX/xref tool fixes (Codex audit range);
   (e) docs/README/CHANGELOG claims vs code. One fix pass, each fix RED->GREEN.
2. Cold-clone verification; install red-team by a cold docs-only subagent (memory:
   redteam_release_install_flow); combined gate.
3. **User go-aheads, one at a time**: push master -> read CI per job; `gh repo rename` (me) +
   remote URL update; tag + GitHub release (releasing skill); Nexus pack built locally, upload
   = user.

## User steps (any time, independent of the waves)

1. `python scripts/x4refguard.py apply` from the toolkit (this is M12's measurement).
2. Codex `/hooks` trust check + `x4doctor --agent codex` (confirms M11 live).
3. Optional `scripts/codex-e2e.py --phase B`.

## Verification

- Per lane: focused tests RED->GREEN with twins; lane report lists tests, deviations, files.
- Per wave: ONE combined gate -- `test-hooks.sh` (count matches EXPECT), `test-protect-bash.sh`,
  `test_hook_facts.py`, `test_audit0924_hooks.py`, `fuzz-guard.py`, `verify-hook-tests.py`
  (0 uncaught, 0 gaps), `scan-identifiers.py`, `gen-agent-trees.py --check`,
  `gen-cli-reference.py --check`, full pytest (only deploy parity may fail before deploy);
  then deploy, parity, live probes in the game root (deny on a reference write via relative
  path; advise on an X4-folder delete; `x4doctor`).
- Release: release-review findings closed or ruled; cold clone green; red-team install report;
  CI green per job read individually.

## Rough timeline (parallel)

Wave 1: planners ~20 min -> your questions -> implementers ~2-3 h in parallel -> merges +
gate ~1.5 h. Wave 2: ~2 h. Wave 3: review ~1-2 h parallel + fixes + your go-aheads.
