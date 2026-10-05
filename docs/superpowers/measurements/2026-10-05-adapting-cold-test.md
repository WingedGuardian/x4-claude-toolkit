# 2026-10-05 -- the v4.0.0 cold ADAPTING exercise (release candidate, lane FX-AD)

**What was tested:** the once-per-release cold exercise of `docs/ADAPTING-COLD-TEST.md`: can an
agent the toolkit has never seen write, from `ADAPTING.md` alone, an adapter for the toy agent
(`tools/x4validate/tests/fixtures/toy_agent/`) that passes `x4guard conformance`?

The previous exercise (lane G) is `2026-10-03-adapting-cold-test.md`; its ten document fixes are
still in `ADAPTING.md` (checked one by one in lane FX-AD: runtime and flushed progress, the
print commands for the timeout constants and `X4_HOOK_MAX_CHARS`, the canary environment, the
Characters rule, the payload's working directory, `--kind write` for edits, `no_native_analogue`,
unknown tools, forward slashes).

## Run #1 -- FAIL on the dispatcher's re-run

| | |
|---|---|
| when | 2026-10-04 evening, local time (file timestamps in the cold run's scratch folder) |
| who | a fresh subagent, no conversation context, given `ADAPTING.md`, `TOY-AGENT.md`, `toy_agent.py` and `payloads/` |
| the subagent's own conformance run | exit **0**: `conformance: 151 replayed of 173 cases; buckets: no_native_analogue=22, replayed=151`, `4 replayed case(s) were INERT in the guards (checked nothing): they agree, and prove nothing`, `OK: all 151 replayed cases agree (147 checked by the guards)`, no GAP line |
| **the dispatcher's re-run, adapter UNEDITED** | exit **1**: `DISAGREE #9 a KNOWLEDGEBASE.md deeper in the game is a game file [edit]: guards say deny, adapter says inert -- X4 GUARD INERT: protect-files.sh timed out: this check's 10s budget (X4_GUARD_TIMEOUT_S) ran out.` -- `FAIL: 1 of 151 replayed cases disagree` |
| run time | each full conformance run finished in under 8 minutes (file timestamps: adapter file -> first log -> re-run log) |
| fail-mode table (subagent, MEASURED with `toy_agent.py`) | a blocked; b exit 2 ran; c crash ran; d 40 s sleep ran (30 s timeout); e garbage ran -- matches `TOY-AGENT.md` |
| live canary (subagent) | `reference/decoy.xml` blocked with the guard's reason; control `dev/ok.xml` written; `../reference/decoy.xml` from `dev/` blocked; with no `X4_*` set the decoy was overwritten |

**The pass criterion did NOT hold:** the subagent's adapter set `X4_GUARD_TIMEOUT_S=10` (own
deadline 24 s, under the toy's 30 s), and `ADAPTING.md` gave no guidance for choosing that
number. One check of `protect-files.sh` ran past 10 s on the re-run. The cause is the DOCUMENT
(no budget guidance), so per `docs/ADAPTING-COLD-TEST.md` the document was fixed, not the adapter,
and a second cold run is required.

### What a 10 s budget is up against (MEASURED 2026-10-05, lane FX-AD)

`x4guard.py check` wall clock on the same machine (Windows 11, 28 logical CPUs, Python 3.10.10,
Git Bash), environment pinned to a scratch toolkit, each run through the resource-budget tool
(10% CPU cap). Script: lane FX-AD scratchpad `ad-lat/latency.py`.

| load | n | max | medians |
|---|---|---|---|
| quiet, serial (two runs) | write-deny 30, write-allow 30, bash shell 30, delete 30, PowerShell shell 10 | 0.81 s | 0.25-0.70 s |
| 2 idle-priority burners | write 43, bash shell 43 | 0.79 s | 0.25-0.29 s |
| 4 at a time (conformance `--workers 4` shape) | 10 each of 4 kinds | 0.87 s | 0.39-0.72 s |

Every verdict in those runs was the expected real one (deny for `reference/`, allow for `dev/`;
none inert). So typical latency is under 1 s, and the >10 s check of the re-run is a load tail
we could not reproduce on purpose. The re-run's exact machine load is UNKNOWN (other lanes were
running that evening; not recorded). I think the cause is load from concurrent work at the time,
but that is INFERRED, not measured.

Also MEASURED 2026-10-05: x4guard honours `X4_GUARD_TIMEOUT_S` (0.05 -> inert deny naming "this
check's 0.05s budget"; `abc` -> inert deny "is not a positive number of seconds"; unset -> a real
deny in 0.23 s), and the one-line print command prints `25.0 5 3` unset and `12.0 5 3` with the
variable at 12.

## Gaps the subagent reported, and what was done (commit `9f33484`)

| # | gap | what changed in `ADAPTING.md` | tier |
|---|---|---|---|
| 1 | section 5(a) passes `-- python adapter.py`, yet the profile "still has to carry a `command`" | section 4 `command`: `--` replaces `command` entirely; `command` is required only without `--`; keep one with `{PYTHON}`/`{TOOLKIT}` for an upstreamed profile | READ: `x4conformance.py` `adapter_command`, `main` |
| 2 | which of `command` and `--` was used was not visible | same paragraph: the first output line `adapter: ...` is the argv really used | READ |
| 3 | does a text-format profile need its own rule for inert text? | section 4: no; `_finish` turns any decoded deny/ask whose text contains `X4 GUARD INERT` (or `inert_pattern`) into `inert`, PROVIDED the rule's `text` group captures the reason; `exit_codes` may map to `"inert"` | READ: `x4conformance.py` `_finish`, `decode` |
| 4 | the "N INERT cases ... prove nothing" line was unexplained | section 5(a): every summary line explained; INERT = the guards themselves checked nothing, expected, the adapter agreed only because it decoded `inert`, they do not count toward `--min-cases`; the exit-0 sentence now says CHECKED cases | READ: `summarise` |
| 5 | timeout arithmetic: where H comes from, who sets the variable, whether x4guard honours it | new "Choosing the time budget": defaults table (25/5/3), worst case 33 s, H (read + bracket) -> D = H - 3 -> B = D - 11, toy example D 26 / B 15, latency table, the >10 s tail, "the ADAPTER sets it" and a bash + PowerShell verification; new `HOOK TIMEOUT` capability row in sections 1 and 7; bracketing procedure in section 1 | READ (constants) + MEASURED (latency, honouring, print command) |
| 6 | no ask: does the "MEASURED" requirement apply? | section 2: a no-ask agent uses the `NEEDS YOUR APPROVAL:` deny; that needs no ask measurement (row a measured the deny); record `ask: none (READ: ...)` | READ: the doc's own rules |
| 7 | ASCII replacement is lossy; UTF-8 untested | Characters rule rewritten: the 5 non-ASCII characters in the guard scripts; Python on a Windows pipe writes cp1252 and raises on an arrow (a crash = fail-open); write bytes yourself; UTF-8 only after a canary with an em dash and an arrow; ASCII fallback with transliteration first | MEASURED 2026-10-05 |
| 8 | no delete tool: is a shell `rm` covered? | section 2 `--kind delete`: a shell-tool delete is sent whole as `--kind shell`; the corpus has `rm`/`Remove-Item` cases | READ: `scripts/test-hooks.sh` |
| 9 | does the canary's scratch tree need `.claude/`? | section 5(b): no; only `dev/` and `reference/`; the real `x4guard.py` keeps running; env beats `x4-paths.env`; also pin `X4_PROFILE` and an empty `X4_CONFIG` | READ: `_x4-env.sh`; MEASURED (cold run + FX-AD probe) |
| 10 | 5(c) when x4doctor has no probe | section 5(c): the expected state of every new adapter; how to record it; the exact "partially supported" sentence | READ |
| 11 | self-assessment rows whose answer is "none" | section 1: fill them with "none", the tier and the source; never blank; measure a safety-relevant "none" when cheap | -- (doc rule) |
| 12 | Windows hook-launch quoting | section 1 "How your agent launches the hook command": `shell=True` -> cmd.exe, only double quotes group a path | MEASURED 2026-10-05: double quotes ran, single quotes and unquoted failed, for a path with a space |
| 13 | the workdir / relative-path note was what made the adapter work | kept unchanged (confirmed correct) | -- |

Re-checked from the earlier run's gap 1 (run time, buffered output): the "about 40 minutes" figure
is now one data point beside run #1's under-8-minute runs ("budget up to an hour"), and section
5(a) says the progress lines are flushed (READ: `say(..., flush=True)`) and that the replay itself
is silent until the summary.

`tools/x4validate/tests/test_adapting_doc.py` now pins every number of the time-budget section
(the three defaults, the 33 s sum, the `D >= 33 + 3` threshold, `B = D - 11`, and the D 26 / B 15
example against the committed toy adapter's constants) to x4guard's module, with four doc-mutation
twins and one constant-mutation twin.

Not verified by lane FX-AD: that the new text is followed correctly by a cold reader -- that is
run #2; a UTF-8 canary through the toy agent; and the cause of the >10 s check on the re-run.

## Run #2

2026-10-05. Toolkit: worktree branch `session/p3-ad` at `5fd1fd2` (master `77f0c02` plus the
FX-AD fixes). Model: `sonnet`, fresh, dispatched with the exact prompt of
`docs/ADAPTING-COLD-TEST.md` plus a dispatcher's machine-rules note (no printing of env
values, scratch-only writes, run long commands through the user's resource-budget launcher,
give bash by full path). The scratch folder held only `ADAPTING.md`, `TOY-AGENT.md`,
`toy_agent.py` and `payloads/`.

**Subagent's run (its report):** conformance exit 0 on the FIRST run, no iteration;
`conformance: 151 replayed of 173 cases; buckets: no_native_analogue=22, replayed=151`;
`4 replayed case(s) were INERT in the guards (checked nothing): they agree, and prove nothing`;
`OK: all 151 replayed cases agree (147 checked by the guards)`; 159.8 s under the launcher.
Budget it chose: H=30 (Toy Agent's documented timeout, bracketed by a 27 s sleep that was still
blocked), D=26, B=15 -- the section 2 formula. It verified that x4guard honours the variable (a
0.05 s budget gave the inert deny naming it). Fail-mode table: blocks only on a clean
`TOY-BLOCK`; exit 2, a crash, a 40 s sleep and garbage output all RAN (fails open). Canary
(all five variables pinned to scratch): `reference/decoy.txt` blocked, the decoy still
`ORIGINAL`; control `dev/control.txt` written. x4doctor: no target for Toy Agent (expected gap).

**Dispatcher's unedited re-run (MEASURED):** sha256 of `adapter.py` and `profile.json` recorded
before the re-run and re-checked after it (both OK). `x4guard.py conformance --profile
<scratch>/profile.json` (no `--`; the profile's own `command`) from the toolkit worktree, through
the budget launcher: exit 0, the same buckets and summary lines as above, `grep -c -E
'GAP|DISAGREE'` = 0, 136.5 s. **The pass criterion held unedited.** Run #1's single timed-out case
(a 10 s budget) did not recur at the documented 15 s budget.

**Gaps it reported (10) and what was done:**

| # | gap | action |
|---|---|---|
| 1 | `X4_GUARD_PY` is never said to be an adapter convention | FIXED: section 2 "Finding x4guard.py" says the toolkit does not read it; it is between a profile and its adapter; inert deny if unresolved |
| 2 | no command to check `bash`/`jq` | FIXED: section 0 gives `command -v bash jq` / `Get-Command bash, jq` (both MEASURED here) and the WSL-launcher trap |
| 3 | are placeholders expanded with no `--`? | no change: section 4 already lists them for `command`; the run confirmed `{PYTHON}` expands |
| 4 | how to wait for a backgrounded run | FIXED: section 5(a) says wait for the summary line and exit code, not the tool's background status |
| 5 | payload paths relative to the profile | no change: section 4 says so |
| 6 | edit judged as write or delete? | no change: section 2 says an edit is a write; the profile's case kind agrees |
| 7 | forward slashes in Windows paths | no change: section 4 already says forward slashes work on Windows |
| 8 | what "ran" looks like in the fail-mode table | no change: reading the decoy's content is the intended measurement |
| 9 | `X4_PROFILE`/`X4_CONFIG` easy to skip | FIXED: 5(b) lists all five variables in the main sentence |
| 10 | nothing on `.test-sandbox` when not killed | no change: only a killed run leaves one, as documented |

Not re-tested by a third cold reader: the four fixes above are clarifications of behaviour
the run itself confirmed, and the pass criterion already held, so `docs/ADAPTING-COLD-TEST.md`
does not call for another run.
