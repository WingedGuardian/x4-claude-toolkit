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

Initial read-only verification used a separate detached worktree, temporary installer
destinations and disposable hook targets. That initial phase changed no game, profile,
reference or system-software files and no safety behavior. The later implementation and
deployment, including the scope correction, are recorded below. Hook edits belong in
`agent/guards/claude-hooks/`, followed by regeneration; never edit generated hooks directly.

## Status — 2026-10-02 (master)

- **F2, F3, F4 FIXED** on master, test-first (`tests/test_framework_hardening.py`), ported from
  the rolled-back `78841ba` with one change: F3's "VALIDATION PARTIAL" advisory on any skip was
  dropped, because MEASURED over 50 real edits in 23 dev mods, 50 of 50 carry a routine `--file`
  skip. F4 is fixed in CI only. The user decided (2026-10-02) that end-user setup does NOT refuse
  a stale lock: CI catches it before release, and setup keeps resolving.
- **Still open:** F1 (opaque interpreter writes), F8/F9 (installers and x4lock omit `AGENTS.md`
  and `agent/`), guard-health telemetry. These go to Plan 2.

## Reconciliation with master — 2026-10-02

The audit branch was rebased onto `74b38fe`. Master's wrapper, neutral guard sources,
generated guards, instruction entry point, generators and tests are retained unchanged.
The original pre-rebase branch is preserved as
`session/framework-audit-pre-rebase-20261002`. The game-root deployment at `a643472`
is owned by the parallel session; this rebase performs no deployment or new fixes.

Master incorporates F5/F6 and resolves relative native file paths from the caller's current
directory (F7). It supersedes this session's wrapper: timeouts are per guard, not a shared
budget for composed delete checks. The historical test counts below certify their named
baselines, not this rebase. New verification results are recorded separately below.

Master also clarifies that the current AGENTS.md is a toolkit-repository entry point, not
a game-root template. F8/F9 remain measured omissions, but their remedy belongs to the
portability deployment design; they do not prove installers violate a promised runtime
contract. Installed-source ownership and instruction discovery still need that decision.
F1–F4 and guard-health history remain deferred findings.

### Rebase verification

- Independent read-only review: no Critical or Important issues; zero net production-code,
  guard, wrapper, generator, test, installer/CI or AGENTS.md changes versus `74b38fe`.
- Focused wrapper, generator, CLI-reference and deployment-parity tests: **79 passed,
  zero skipped, exit 0**, 98.54 seconds.
- Regeneration: **0 written, all 40 already fresh**; subsequent generator `--check`: exit 0.
- After review, `bash scripts/test-hooks.sh`: **177 passed, zero failed, zero skipped**, exit 0.
- After review, full regression suite: **3,011 passed, three skipped, exit 0**, 1,556.56 seconds.
  The skips are the same Windows file-symlink privilege checks in `test_deploy_mod.py`;
  those three protections were not exercised. The command used the toolkit's existing
  Python 3.13 virtual environment, Git Bash first on PATH, and no pytest cache writes.
- The initial focused command named a nonexistent CLI-reference test file and collected
  no tests; its corrected run is the 79-pass result above. A subsequent user-interrupted
  invocation has no captured result and is not counted as verification.

This run was slower than the historical baseline. Installer integration and Git-history
identifier scanning were observed during long stretches; the cause of the timing difference
was not isolated, so no performance regression is claimed. These results certify script and
integration behavior, not enforcement inside a live agent session. No game deployment,
profile/reference changes, new safety behavior or host package installation was performed
by this reconciliation.

## Interpretation

The toolkit has substantial regression, mutation and installation verification, and its
neutral-source extraction preserves the existing Claude hook contract. It is a credible
foundation for other agents, but command inspection is not a filesystem security boundary.
Passing the existing suites does not establish that every mutation route is protected.

## Verified baseline findings (F5/F6 subsequently fixed)

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

### Follow-up: install artifacts and protection coverage

**F7 — relative file paths bypass the front door's reference check (95% confidence).**
The measured example and scope correction are recorded below. This was open at the audit
baseline; master `74b38fe` subsequently added caller-relative native path resolution and its
regression tests. The rebased branch retains that implementation; see reconciliation above.

**F8 — installers omit the new agent instructions and neutral sources (98% confidence).**
Both copy lists omit `AGENTS.md` and `agent/`. Two disposable, real installer runs (Bash and
PowerShell) each exited 0 and copied the `CLAUDE.md` control, but neither copied the
`AGENTS.md` control or `agent/README.md` control. Setup was replaced only in the temporary
fixture with a no-op, so these probes did not install dependencies or run real setup.
This is an integration gap in the current source migration, not a claim that the published
v3.3.1 release promised universal-agent support. Decide whether installed toolkits are
editable sources or runtime-only distributions; instruction loading and maintenance guidance
must match that decision. At minimum, deliver the appropriate agent's instructions.

**F9 — the default lock manifest omits AGENTS.md (98% confidence).**
In one disposable configured game root containing both instruction files, `manifest()`
included `CLAUDE.md` and excluded `AGENTS.md`. No attributes were changed. `_GAME_RELATIVE`
names the Claude instructions but not the new agent instructions. Users can explicitly add
paths through `X4_PROTECTED`; the default migration has not incorporated this file.
Review instruction and source ownership when defining the protected set; do not blanket-lock
all generated folders or normal runtime state.

**Guard-health history remains absent (99% confidence in this boundary).**
A missing-interpreter check returned an inert denial; immediately afterward the real canary
returned 0 and `canary: 1 repository checked, no tracked file lost.` The fixture's tracked file
was intact. This is correct behavior for the loss canary, not a false result from that tool.
It proves the canary cannot establish that guards successfully evaluated payloads. A separate
health monitor must distinguish evaluation failures, successful evaluations, and no calls;
it must record failures before dependency parsing can fail. Retain the existing loss check.

Supporting existing tests: installer agreement, generator and canary **67 passed**, zero
skipped; lock tests **41 passed**, zero skipped. The additional artifact probes found F8/F9
despite those green suites. The agreement test checks both lists agree and pins `mods/`,
but does not require these newly introduced artifacts. No production files or live protections
were changed in this follow-up; only this report and project memory were updated.

### Assessment and proposed roadmap — no implementation authorized

The strongest parts are reproducible release archives, independent installer refusal checks,
failure controls in the test suites, and documented limits of the read-only lock. Both CI
platforms currently have `experimental: false`; older comments describing Ubuntu as merely
informational are stale, not evidence of a currently unenforced job.

The safety policy deliberately spends some convenience to protect shared records: it denies
broad staging even in a private repository and writes even to a unique `/tmp` subdirectory.
Those verified restrictions may be excessive for isolated work, but safe exceptions need
evidence of isolation and explicit ownership. The lock's documented force-delete gaps are
also real and tested; replacing it with broad ACL denies would repeat a documented read-access
and recovery failure. No blanket interpreter ban or ACL change is recommended without a
separate design and scratch-tree proof.

| Area | Current evidence | Proposed next work |
| --- | --- | --- |
| Neutral sources and Claude generation | Implemented and checked; core still contains Claude-specific operating assumptions | Keep one source and add explicit target rendering/conformance |
| Front door | F5/F6 and native relative-path handling now come from master `74b38fe` | Verify remaining path/root contracts before adapters rely on verdicts |
| Installed instruction discovery | Repository AGENTS.md exists; installers omit it | Test each installed layout's actual instruction discovery and ownership |
| Dependency and validation resilience | jq has a Python fallback; F2/F3/F4 remain open | Review unique backups, explicit incomplete validation, lock freshness and test tripwires together |
| Health monitoring | File-loss canary works; no evaluation history | Add a separate persistent guard-health contract and outage/recovery probes |
| Host enforcement | Script verdicts measured; a passing front-door call installs no host enforcement | Replay native payloads and prove deny/crash/timeout behavior in each host |
| Independent protection | Read-only lock has measured Windows/POSIX and force-operation limits | Decide the boundary for opaque programs; test any stronger layer's recovery first |
| Portable onboarding | No ADAPTING.md, x4doctor or Codex target artifact found in this snapshot | Provide setup, capability limits, shell routing, confirmation handling, backups, validation and verification guidance for other hosts |

The portability design already proposes most of this work. Its proposals are not shipped
capabilities. The current stopgap asks Codex to read the oversized CLAUDE.md manually; a true
shared core still needs the planned instruction split and host-specific addenda. Preserve
the distinction between instructions an agent reads, checks it may call, and decisions its
host actually enforces.

The optional mutation harness also has a process concern: it runs the full parser suite for
every mutant/predicate variant, including live PowerShell tests, without a subprocess timeout.
The interrupted local run cannot be counted as passing. Improving targeted execution and a
bounded failure result is proposed work; retaining native PowerShell coverage is essential.

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
- The initial-baseline README told maintainers to run checks after changes to `.claude/hooks/`.
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

The user's clarification limits authorization to F5 and F6: composed deletion policies
and explicit check-only inert denials. The agent exceeded that scope by also implementing
F2–F4 and package-manager tripwires. Those additional implementations and their two deployed
hooks were rolled back; the audit findings remain open. History preserves the overbroad
commits and their verification, rather than silently erasing what happened.

Tests reproduced the original failures before the fixes. A reviewer re-reviewed the changes
with no remaining Critical or Important findings. Six generated hook updates were initially
deployed with rollback copies under `.claude/backups/known-good-2026-10-01-framework-hardening/`.
Only the four files supporting F5/F6 remain changed after scope correction. Hooks were edited
in the neutral source tree. Master has active parallel work and was not changed by this session.

Final corrected-scope verification: **3,010 passed, three skipped, exit 0, 401.20 seconds**.
The skips are the same Windows file-symlink privilege checks. All 177 end-to-end smoke checks
passed. Generator freshness passed, all 40 managed deployed files are at parity, and the two
restored deployed hooks match their saved pre-change rollback copies. A follow-up reviewer
confirmed that only F5/F6 production changes remain, with no Critical or Important findings.

Post-review parser/integration checks: 610 passed plus 111 subtests. End-to-end script smoke:
177 passed, zero failed or skipped. The first full run had 3,028 passes, three Windows
symlink-privilege skips, and one expected deployment-parity failure because it ran before
deployment. The overbroad post-deployment full run passed: **3,029 passed, three skipped,
exit 0, 420.83 seconds**. The three skips remain the Windows file-symlink privilege checks.
The final smoke rerun again passed all 177 checks. Lock freshness and generator freshness
checks returned 0. The shipped instructions stayed below the existing 39,999-character
baseline (39,975); the worktree itself had no local budget baseline, so its budget gate
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

Additional measured finding, not fixed here: from the toolkit root, the deployed front door
allowed `--kind write --path reference/__guard_verification_only__.xml`, while the absolute
path equivalent denied. No write occurred. At that point the parallel session's relative-path
resolution change was uncommitted and not certified by this audit. Master `74b38fe` subsequently
committed it with regression tests; this rebase retains those tests and implementation. The
attempted additional regression test was discarded after the user clarified scope.

1. **Completed:** resolve F5 and F6 in the front door before adapter integration. These are material contract
   findings: pause implementation for a design checkpoint, rather than claiming the
   passing targeted suite proves equivalent protection.
2. **Open, implementation rolled back:** make backup allocation, validation failure disclosure and lock freshness separate,
   narrowly tested hardening changes. State confidence and assumptions before implementation.
3. Define persistent hook-health telemetry and its distinction from the existing loss canary.
4. Resolve the opaque-program boundary before claiming equivalent protection across agents;
   preserve legitimate scripting while documenting and measuring the remaining limits.
5. Verify host adapters end to end with disposable deny controls, crashes, timeouts and
   dependency failures. Keep live-host enforcement and script-level smoke tests distinct.
