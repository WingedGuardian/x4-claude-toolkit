# 2026-10-03 -- the first cold ADAPTING exercise (lane G, Plan 3)

**What was tested:** whether `ADAPTING.md` alone lets an agent the toolkit has never seen write an
adapter that passes `x4guard conformance`. **Subject:** the toy agent
(`tools/x4validate/tests/fixtures/toy_agent/`: `TOY-AGENT.md`, `toy_agent.py`, `payloads/`) --
a fictional agent that fails OPEN on a non-zero exit, a crash and a 30 s timeout, has no ask
verdict, and starts its hook outside the call's working directory.

**Who:** one fresh subagent, model `sonnet`, no conversation context. Given a scratch folder
holding only `ADAPTING.md` (as of lane G commit `4f48d40`), `TOY-AGENT.md`, `toy_agent.py` and
`payloads/`; told to run the toolkit's tools as `ADAPTING.md` says and to read no other toolkit
file. The dispatch text was the prompt in `docs/ADAPTING-COLD-TEST.md`, plus environment notes
(Windows, Git Bash, run one conformance at a time, write only inside the scratch folder) and the
two output file names.

## Result -- PASS, unedited

| | |
|---|---|
| conformance exit | **0** (`conformance: 133 replayed of 148 cases; buckets: no_native_analogue=15, replayed=133`, `OK: all 133 replayed cases agree`, `extras: 6 neutral case(s)`, no GAP line) |
| runs | 2: the first was killed by the subagent's own 15-minute background limit and printed nothing; the second passed. No adapter change between a failing and a passing conformance run |
| adapter edits by the dispatcher | **none**. The committed `toy_adapter.py` is byte-identical to the cold one; the committed `profile.json` differs only in the adapter path (scratch-absolute -> `{TOOLKIT}/...`) |
| the subagent's own fix before its first full run | its first adapter printed a reason containing an em dash; the toy decoded it as UTF-8 and crashed printing it to a cp1252 console. It switched to ASCII-only output |
| fail-mode table (MEASURED by the subagent with `toy_agent.py`) | a TOY-BLOCK control: blocked. b exit 2: ran. c crash: ran. d 45 s sleep: ran (30 s timeout). e garbage (JSON): ran. Matches `TOY-AGENT.md` |
| live canary | `write_file reference/decoy.xml` blocked with the guard's reason; control `write_file dev/decoy.xml` written |

The pass was re-measured by the dispatcher, not taken from the subagent's word:
`tests/test_toy_agent_conformance.py` replays the full corpus through the committed adapter and
kills five adapter mutants.

## Gaps the subagent reported, and what was done

| # | gap (quoted or paraphrased) | action |
|---|---|---|
| 1 | "a few minutes": a full run took about 40 minutes; output appeared only at the end, so slow and hung looked the same | `ADAPTING.md` 5(a) now says to budget tens of minutes and run it in the background; the engine now prints flushed progress lines (dump, extras, replay count) |
| 2 | the timeout default "is stated in the docstring of x4guard itself", but it was told not to read toolkit files | `ADAPTING.md` 2 now gives a one-line command printing `TIMEOUT_S`, `KILL_WAIT_S`, `DRAIN_GRACE_S` (no number restated: lane J may move the default) |
| 3 | `X4_HOOK_MAX_CHARS` "is in `.claude/hooks/_x4-env.sh`" -- how to read it was a guess | a one-line command to print it |
| 4 | the canary is silent on the environment: with no `X4_*` set both writes were allowed; with `X4_GAME` at the canary root, `dev/` was refused too | 5(b) now names `X4_TOOLKIT`, `X4_REFERENCE` and a SEPARATE `X4_GAME` |
| 5 | encoding is not mentioned; one em dash crashed the agent | new "Characters" rule in section 2 |
| 6 | "run it in your agent's working directory" -- the toy distinguishes its own directory from `workdir` | reworded: the directory the PAYLOAD names, not where the hook process started |
| 7 | which `--kind` an edit is | "`--kind write` for any tool that creates a file OR changes an existing one" |
| 8 | "worst verdict wins" never exercised (one path per toy call) | none needed; the Codex example exercises it |
| 9 | `no_native_analogue=15` unexplained | 5(a) explains it, and the engine prints which tools those cases were |
| 10 | bare `python` was 3.10, not the 3.13 the dispatch said | dispatch-note error, not a doc gap; 3.10 meets the stated minimum |
| 11 | what to do with an unknown tool or interpreter | section 2: inert deny, unless the capability report MEASURED the tool cannot write or run anything |
| 12 | forward slashes in the profile `command` on Windows | noted as fine |
| 13 | the adapter's own fallback for finding `x4guard.py` was a guess that never mattered | none: `{HOOKS}` via the profile `env` is the documented way |

Not done by the subagent, by its own report: 5(c) (`x4doctor` has no toy target -- a gap by the
document's own wording), backups after an allow, and a test that x4guard honours its lowered
`X4_GUARD_TIMEOUT_S`.

A second cold run was NOT made: the plan requires one only when the dispatcher had to
hand-correct the adapter, and it did not. The document changes above are clarifications the
next per-release run (`docs/ADAPTING-COLD-TEST.md`) will test.
