# Toolkit framework verification — 2026-10-01

## Scope and baseline

Full-suite baseline: `aa57efc`, including the neutral-source migration through that commit.
Supplemental current-version review: `367cf2e`, which adds a stopgap AGENTS.md and changes
the generator and its tests. Hook files are unchanged between these two commits.
Final supplemental baseline: `7bd554f`, adding x4guard.py and its tests. The existing guard
scripts remain unchanged. The audit branch includes this commit.
The latest published release is v3.3.1 (`4a9ff51`); it is not the same baseline.
Scope: instructions, generation, hooks, recovery, installation, CI and agent portability.
Individual tool algorithms are outside this review. Their regression suite is run as an
integration safeguard, not claimed as an algorithm audit.

Verification used a separate detached worktree, temporary installer destinations, and
disposable hook targets. No game, profile, reference or system-software changes were made.
No safety behavior was changed. Follow-up hook edits belong in
`agent/guards/claude-hooks/`, followed by regeneration; never edit generated hooks directly.

## Interpretation

The toolkit has substantial regression, mutation and installation verification, and its
neutral-source extraction preserves the existing Claude hook contract. It is a credible
foundation for other agents, but command inspection is not a filesystem security boundary.
Passing the existing suites does not establish that every mutation route is protected.

## Verified remaining findings

### F1 — interpreter writes bypass the reference write guard

**Confidence: 95% in the reproduced gap.** Feeding three equivalent synthetic requests to
the actual hooks produced: direct Write to a disposable reference file = deny; Bash
redirection to that file = deny; `python -c "open('<reference>/data.xml','w').write('x')"`
= empty output and exit 0. The commands were inspected, not executed.

This is a pre-existing limitation, not a regression caused by relocation. Do not promise
universal mutation protection from shell parsing, and do not equate a neutral adapter with
an independent boundary. A general fix needs a design decision about filesystem enforcement
and opaque program execution; blanket interpreter bans would obstruct legitimate work.
Confidence in a general parser-only fix is below the 90% implementation threshold.

### F2 — backup names collide within a second

**Confidence: 95%.** Two real backup hook calls against one disposable file, with its contents
changed between calls, completed in the same timestamp second. One snapshot remained,
containing the intermediate text, and both audit entries named that same snapshot. The
original text was lost from the backup directory.

`backup-before-edit.sh:101-126` uses a seconds-resolution timestamp and ordinary `cp`.
The long-path filename correction does not address this collision. A follow-up should
allocate a unique destination atomically and test rapid and concurrent backup calls.

### F3 — validation not run is silently indistinguishable from no findings

**Confidence: 95%.** A valid disposable mod with a diff XML file was sent to the post-edit
hook with UV set to a nonexistent executable. It returned exit 0, empty stdout and empty
stderr. A control executable returning a validation finding produced the expected advisory.

`x4validate-on-edit.sh:67-68` suppresses stderr and exits on empty output. Malformed output
also deserves explicit handling: the Python renderer treats parse failure as zero findings.
Preserve the advisory contract, but report that validation could not run or could not be
interpreted. Do not turn infrastructure errors into an apparent clean result.

### F4 — frozen dependency installation does not check lock freshness

**Confidence: 95%.** In a temporary copy of pyproject.toml and uv.lock, changing only the
project version left the lock stale. `uv sync --frozen --offline --no-install-project`
returned 0; `uv lock --check --offline` returned 1 and named the stale lockfile. This
installed cached dependencies only into the disposable virtual environment.

The CI comment that `--frozen` rejects drift is incorrect. Add an explicit freshness
check alongside frozen installation. Setup currently uses `uv sync` without a lock check;
decide and document whether end-user setup must preserve the shipped resolution.

### F5 — the new delete-path API uses write policy

**Confidence: 95%; introduced in `7bd554f`.** On the same disposable existing mod file,
`x4guard.py check --kind delete --path <mods>/testmod/data.xml` returned allow, whereas
`check --kind shell --shell bash --command 'rm "<same-path>"'` returned ask. The decoy
still existed afterward: neither check executed the operation.

`guard_payload` maps every non-shell kind to a Write payload; `verdict_for` runs
protect-files for both write and delete. This does not preserve the existing deletion
confirmation policy. The reference-only delete test passes because that path is blocked
for both operations, concealing the semantic mismatch. Define and test deletion semantics
across mod, toolkit, profile and reference paths before adapters use this endpoint.

### F6 — underlying guard failure is reported as a non-inert question

**Confidence: 95%; introduced in `7bd554f`.** With X4_BASH explicitly naming working Git Bash
and X4_PYTHON pointing to a missing executable, a shell echo check returned decision ask
and inert false. Its reason explicitly said GUARD INERT, no Python, and nothing checked.

The wrapper detects its own launch/parse errors, but a successfully launched guard that
reports its internal inability to evaluate is forwarded as an ordinary verdict. This
violates the documented inert-deny contract. Normalize guard evaluation failures through
a reliable contract rather than treating exit 0 plus parseable JSON as successful analysis.
Persistent failure telemetry and host enforcement remain separate requirements.

## Safety and process observations

- Missing jq is handled better than in the reported Skyrim incident: the actual file
  guard still denied the disposable reference write with JQ pointing to a missing binary.
- Missing Python produced an explicit `ask` verdict naming GUARD INERT. That is disclosure,
  not evidence that every agent host will enforce it. The host-specific verdict contract
  must be measured before an adapter claims protection.
- Runtime inert events have no persistent heartbeat/failure-event mechanism in the reviewed
  guards. `session-canary.sh` checks irreplaceable-file loss through x4canary, not successful
  evaluation of recent hook payloads. It must not be presented as guard-health monitoring.
- Bash, PowerShell, Edit, Write and NotebookEdit are registered with protection hooks.
  The previous missing-PowerShell registration finding is addressed.
- Setup prints winget installation advice; it does not execute winget. The reported Skyrim
  system-install incident was not reproduced here. Installer tests sandbox filesystem
  destinations, but inherited PATH still lacks a package-manager invocation tripwire.
  Add such isolation before future setup code introduces system installation behavior.
- A synthetic `git add -A` in a freshly created private repository was denied with the
  shared-workspace reason. A write to a unique subdirectory under `/tmp` was also denied.
  These are verified conservative policy choices; narrowing them requires a reliable
  definition of isolated work, not merely trusting a caller's claim.
- README currently tells maintainers to run checks after changes to `.claude/hooks/`.
  Update maintainer guidance to name `agent/guards/claude-hooks/` as the editing location.
  The migration README and changelog already document the new source layout.
- **SUPERSEDED at `367cf2e`:** there was no toolkit AGENTS.md at the full-suite baseline.
  The subsequent commit generates a stopgap AGENTS.md, naming the source layout and directing
  agents to read CLAUDE.md manually. This addresses missing startup instructions; it does not
  install a Codex enforcement adapter. The x4guard front door remained planned at `367cf2e`;
  **SUPERSEDED at `7bd554f`:** it is implemented, with F5 and F6 measured above.

## Verification evidence

- Generator `--check`: exit 0 in the clean worktree.
- Git diff of `.claude/hooks/` between `0a31923` and `aa57efc`: empty, including mode summary.
- Source-versus-deployed game-root hooks: 13 of 13 match after CRLF normalization.
  This compares files; it does not prove host registration or execution in a live session.
- Framework tests: 243 passed, zero skipped; covers generators, installer upgrades,
  deployment, locks, canary and hermetic gate fixtures.
- Hook tests: 610 passed, 111 subtests passed.
- `bash scripts/test-hooks.sh` in the clean worktree: 177 passed, zero failed, zero skipped.
- Full repository regression suite at `aa57efc`: 2,985 passed, three skipped, exit 0,
  410.08 seconds. The skips are file-symlink deployment checks requiring Windows privileges;
  those three protections were not exercised. This is not a claim of live-host hook
  enforcement or an in-game test.
- Supplemental `367cf2e` generator and CLI-reference tests: 38 passed, zero skipped,
  exit 0; generator `--check` also returned 0. The full suite was not repeated for this
  five-file delta; its generator code, instructions and tests were reviewed separately.
- Supplemental `7bd554f` front-door and generator tests: 34 passed, zero skipped, exit 0.
  Independent live subprocess checks reproduced F5 and F6 despite this green suite.
- Published v3.3.1 CI: Windows, Ubuntu and identifier-scan jobs all succeeded in
  [run 36619127983](https://github.com/WingedGuardian/x4-claude-toolkit/actions/runs/36619127983).
  That run does not certify the subsequent local generator commits.

The first hook-test attempt selected the Windows WSL bash stub and failed to launch Bash.
It was rerun with Git Bash explicitly first on PATH. An initial smoke run in the existing
audit worktree failed because the identifier scanner included another audit's untracked
output. The clean worktree run passed. Neither failure is reported as a guard regression.

## Recommended next decisions

### Implementation status (2026-10-01)

The user authorized the narrow remediation after confidence was stated at 93–95%.
F2–F6 now have regression coverage and fixes: unique atomic backup allocation, explicit
failed/degraded/partial validator advisories that retain findings and skipped-check reasons,
lock freshness checks before frozen synchronization, composed deletion policies, and an
explicit check-only inert-deny protocol. Tests intercept PATH package-manager calls in both
shells and fail on recorded invocation. This is a tripwire, not an OS sandbox.

Tests reproduced the original failures before the fixes. A reviewer found degraded validator
results can exit 1 rather than 3; the correction reads the JSON coverage status and was
re-reviewed with no remaining Critical or Important findings. Six generated hook updates
were deployed with rollback copies under `.claude/backups/known-good-2026-10-01-framework-hardening/`;
all 40 managed deployed files then matched. Hooks were edited in the neutral source tree.

Post-review parser/integration checks: 610 passed plus 111 subtests. End-to-end script smoke:
177 passed, zero failed or skipped. The first full run had 3,028 passes, three Windows
symlink-privilege skips, and one expected deployment-parity failure because it ran before
deployment. The fresh post-deployment full run passed: **3,029 passed, three skipped,
exit 0, 420.83 seconds**. The three skips remain the Windows file-symlink privilege checks.
The final smoke rerun again passed all 177 checks. Lock freshness and generator freshness
checks returned 0. The shipped instructions stay below the existing 39,999-character
baseline (39,975); the worktree itself has no local budget baseline, so its budget gate
refuses rather than claiming to check historical growth.

Deployed front-door controls returned deny for a reference write, ask for a development-tree
deletion, and inert deny with a missing interpreter. These are actual script subprocesses,
not evidence that a live agent host enforces the results. No probe performed those writes.
The differential fuzzer passed 3,959 mutants over 24 of 26 policy rules; the remaining two
are structurally outside this fuzzer and are unit-tested. Its broken-scanner control
rediscovered 182 bypasses. The optional full mutation/predicate harness was stopped before
completion: it repeats the full live PowerShell parser suite per mutant, with observed
child runs taking minutes. Its result is **NOT VERIFIED** here. Optimize that harness
separately without removing native PowerShell coverage. The parser itself is unchanged.

F1 remains: arbitrary program writes are outside the parser's reliable enforcement boundary.
Persistent guard-evaluation telemetry, process-tree termination on wrapper timeout, and
live agent-host enforcement also remain separate work. This patch does not certify them.

1. **Completed:** resolve F5 and F6 in the front door before adapter integration. These are material contract
   findings: pause implementation for a design checkpoint, rather than claiming the
   passing targeted suite proves equivalent protection.
2. **Completed:** make backup allocation, validation failure disclosure and lock freshness separate,
   narrowly tested hardening changes. State confidence and assumptions before implementation.
3. Define persistent hook-health telemetry and its distinction from the existing loss canary.
4. Resolve the opaque-program boundary before claiming equivalent protection across agents;
   preserve legitimate scripting while documenting and measuring the remaining limits.
5. Verify host adapters end to end with disposable deny controls, crashes, timeouts and
   dependency failures. Keep live-host enforcement and script-level smoke tests distinct.
