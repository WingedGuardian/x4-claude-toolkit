# Plan 3 -- Lane J: the hardening backlog

Planner: opus, 2026-10-02, read-only against toolkit master `0cb667f`
(`$X4_TOOLKIT`). All evidence below is labelled.
`$TK` = the toolkit worktree the implementer works in (`session/p3-J`); `$SCRATCH` = the
implementer's session scratchpad (never `/tmp`, never the repo).

## Context

Nine items from PLAN.md row J plus one placeholder. They are independent of each other except
J3 -> J5 (README text quotes J3's final numbers) and J4 -> J5 (both describe the Codex banner).
Four findings came out of planning that the backlog did not name; each is folded into the task
it belongs to and flagged **[NEW]**:

- **[NEW] J1** -- the unguarded decode is in `problems()`, which `main()` calls OUTSIDE its
  `try`, in BOTH modes: a non-UTF-8 committed file makes `--check` AND the regenerate mode die
  with a traceback (READ `gen-cli-reference.py:192-193, 220-229`). So a corrupted file also
  blocks its own repair.
- **[NEW] J3** -- `x4guard`'s 25 s default does NOT govern the Codex hook path: the adapter
  passes its own deadline (`X4_CODEX_BUDGET_S`, default 45) into every check
  (READ `agent/guards/adapters/codex.py:159-188`, `x4guard.py:199-201`). It governs only
  direct `x4guard check` calls (AGENTS.md's instructions, x4doctor, generic agents, lane G's
  conformance). But the timeout reason ALWAYS names `X4_GUARD_TIMEOUT_S`
  (READ `x4guard.py:203-215`), so a Codex user is told to tune the wrong knob.
- **[NEW] J4** -- AGENTS.md tells Codex to run `python .claude/hooks/x4guard.py ...`
  (READ `AGENTS.md:118-120`), but `install.sh --agent codex` copies `AGENTS.md .codex .agents`
  and NOT `.claude` (READ `install.sh:520-521`). On a Codex-only install the instructed command
  points at a file that is not there (INFERRED; J4 Step 1 measures it). The game root has only
  `.claude/hooks/x4guard.py` (MEASURED `ls`), so neither path alone is right everywhere.
- **[NEW] J5** -- README `:299-300` says x4guard "applies a separate timeout to each guard",
  STALE since Plan-2 lane E made it one budget per check (READ `CHANGELOG.md:101`). And the
  bare `git clean -fdx` residual is worse than "a disclosure nit": MEASURED this session, with
  cwd = the game root, `x4guard check --kind shell --shell bash --command "git clean -fdx"` ->
  **allow**, while `cd "<game root>" && git clean -fdx` -> ask. The game-root repo's
  `.gitignore` is a whitelist (`*`), so `-x` would delete every untracked file -- the whole
  install (INFERRED from READ `.gitignore`; never run). It is deliberate (lane F commit
  `5506cfb`: the user ruled out new prompts) but a DENY is not a prompt -> Question Q1.

## Global constraints

- Test-first: every behaviour change starts with a failing test that is run and seen RED.
  One falsification twin per clause.
- Never edit generated files: `agent/` is the source; regenerate with
  `cd $TK/tools/x4validate && uv run python scripts/gen-agent-trees.py` (renders `.claude/`,
  `.codex/`, `AGENTS.md`, `CLAUDE.md`). `x4guard.py` exists in 3 copies; edit only
  `agent/guards/claude-hooks/x4guard.py`.
- The Codex hooks.json template is FROZEN (`test_codex_hooks_template_is_frozen`,
  `test_template_change_is_announced`). J3 changes it ONLY if its decision rule says so.
- File content with backslashes: Write/Edit tools only, never heredocs.
- Focused tests only, one test process at a time. No full pytest, no verify-hook-tests run.
- Load generators are self-terminating (fixed duration) so nothing is orphaned.
- Commit small, explicit paths, on `session/p3-J`. Never push.
- CHANGELOG: append-only entries under `## Unreleased`, headed by date + slug.

## Interfaces

**Produces**
- `gen-cli-reference.py`: rc 2 + `REFUSING: <rel> is not UTF-8 ...` for an undecodable
  committed file (both modes). `problems()` raises `GenerationError` for it.
- `test-hooks.sh`: a failing `decide()` line now carries `[hook rc=N; stderr: <first 300 chars>]`.
  Counts, `EXPECT=187`, and the `X4_DECIDE_DUMP` record format are UNCHANGED.
- `x4guard.py`: the timeout/spent-budget reason names the budget that actually ran out
  (`X4_GUARD_TIMEOUT_S` when x4guard set the deadline, "the caller's deadline" otherwise).
  Default value of `X4_GUARD_TIMEOUT_S` = 25 unless J3's measurement says otherwise.
- `agent/instructions/codex.md`: the banner paragraph; a guard path valid on every install.
- README: Codex residual disclosures; corrected x4guard budget sentence.
- Measurements doc: J3 latency-under-load table, the flake hunt result, M10 result.

**Consumes**
- Lane G (conformance) calls `x4guard check` directly, so it inherits J3's default and
  message. Lane G should not assert on the exact timeout-reason text (tell G).
- The orchestrator fills J9 from the `ci/plan2` run.

---

## Task J1 -- `gen-cli-reference.py`: an undecodable committed file refuses with rc 2

**Files:** `tools/x4validate/scripts/gen-cli-reference.py`, `tools/x4validate/tests/test_cli_reference.py`

**Step 1 -- failing tests** (append to `test_cli_reference.py`; `fresh_copy`, `gen` exist):

```python
def test_TWIN_a_non_utf8_committed_file_REFUSES_in_check_mode(monkeypatch, fresh_copy, capsys):
    """An undecodable file is not 'stale' or 'fresh' -- the check could not read it. It must
    say so (rc 2), never die with a traceback (rc 1, which reads as 'stale')."""
    (fresh_copy / "reference" / "x4save.md").write_bytes(b"\xff\xfe not utf-8\n")
    monkeypatch.setattr(gen, "SKILL_DIR", fresh_copy)
    assert gen.main(["--check"]) == 2
    err = capsys.readouterr().err
    assert "REFUSING" in err and "reference/x4save.md" in err and "UTF-8" in err, err


def test_TWIN_a_non_utf8_committed_file_REFUSES_in_write_mode_and_writes_nothing(monkeypatch, fresh_copy):
    bad = fresh_copy / "reference" / "x4save.md"
    bad.write_bytes(b"\xff\xfe not utf-8\n")
    before = {p: p.read_bytes() for p in fresh_copy.rglob("*") if p.is_file()}
    monkeypatch.setattr(gen, "SKILL_DIR", fresh_copy)
    assert gen.main([]) == 2
    assert {p: p.read_bytes() for p in fresh_copy.rglob("*") if p.is_file()} == before


def test_problems_raises_GenerationError_on_an_undecodable_file(fresh_copy, expected):
    (fresh_copy / "SKILL.md").write_bytes(b"\x80")
    with pytest.raises(gen.GenerationError, match=r"SKILL\.md.*not UTF-8"):
        gen.problems(expected, fresh_copy)


def test_TWIN_a_non_utf8_GHOST_is_still_just_a_ghost(fresh_copy, expected):
    """Only EXPECTED files are decoded; a stray binary file is a GHOST, not a refusal."""
    (fresh_copy / "reference" / "x4junk.bin").write_bytes(b"\xff\xfe")
    assert gen.problems(expected, fresh_copy) == ["GHOST    reference/x4junk.bin"]
```

Controls already in the file that must STAY green (they pin the other clauses):
`test_TWIN_CRLF_line_endings_alone_are_NOT_stale` (valid UTF-8 differing only in bytes is not
a refusal), `test_the_check_mode_exits_1_on_a_stale_tree` (stale is still rc 1).

Run: `cd $TK/tools/x4validate && uv run pytest tests/test_cli_reference.py -k "non_utf8 or undecodable" -q`
Expected: 3 failed (the first two ERROR/FAIL with `UnicodeDecodeError`, the third fails with
DID NOT RAISE / UnicodeDecodeError), 1 passed (the ghost twin -- it is a control, green before
and after; it proves ghosts are never decoded).

**Step 2 -- implementation.** In `problems()`, around the `_norm(p.read_bytes())` comparison:

```python
        else:
            try:
                text_on_disk = _norm(p.read_bytes())
            except UnicodeDecodeError as exc:
                raise GenerationError(
                    f"{rel} is not UTF-8 ({exc.reason} at byte {exc.start}) -- it cannot be "
                    f"checked or safely overwritten; delete it and re-run to regenerate") from exc
            if text_on_disk != text:
                out.append(f"STALE    {rel}")
```

In `main()`, move `found = problems(expected)` inside the existing `try` (its `except` already
catches `GenerationError` and returns 2). Update the module docstring's exit line:
`2 could not generate, or could not read a committed file (nothing is written)`.

**Step 3 -- green.** Run: `cd $TK/tools/x4validate && uv run pytest tests/test_cli_reference.py -q`
Expected: all pass (previous count + 4). Then
`uv run python scripts/gen-cli-reference.py --check` -> Expected: `x4-cli-reference fresh: N file(s)`, rc 0.

**Commit:** `gen-cli-reference: an undecodable committed file refuses with rc 2 instead of a traceback (both modes)`

---

## Task J2 -- the test-hooks.sh 1/187 flake: NAME the probe first, then fix

Facts: MEASURED this session, 1 idle run: `RESULT: 187 passed, 0 failed`, **126 s**, 28 logical
CPUs (`nproc`). Previous failures: 1/187 twice, only under heavy load, probe never recorded
(memory `x4_universal_agent_support.md`; no log survives). READ: `decide()` discards the
hook's stderr and exit code (`2>/dev/null`, `test-hooks.sh:73`) and maps EMPTY stdout to
`allow` (`:74`), so a hook that crashed under load reads exactly like a hook that allowed.
That is the leading hypothesis (INFERRED), and it has two very different meanings:
(a) the HARNESS failed (its own `jq`/subshell fork) -> instrument defect;
(b) the HOOK failed (non-zero exit, no JSON) -> a product finding: in Claude Code a hook that
exits non-zero other than 2 is a non-blocking error, i.e. the call PROCEEDS (fail open).
The plan therefore refuses to "fix" anything before the probe and its rc/stderr are on file.

**Step 1 -- instrument (diagnostic only; no verdict, count or dump change).** In `decide()`:
capture the hook's exit code and the first 300 chars of its stderr, and append them to the
FAIL message only:

```bash
  local rc errf="$SBX_TMP/decide.stderr"
  out=$(printf '%s' "$json" | bash "$HOOKS/$hook" 2>"$errf"); rc=$?
  ...
  [ "$got" = "$exp" ] && ok "$label ($got)" \
    || no "$label — expected $exp, got $got [hook rc=$rc; stderr: $(head -c 300 "$errf" 2>/dev/null | tr '\n' ' ')]"
```

(`rc=$?` right after a command substitution is the pipeline's last command = the hook, which
is the one we want. `$SBX_TMP` is outside `/tmp` by the file's own guard.) Do not change the
`X4_DECIDE_DUMP` record -- `test_codex_conformance.py` parses it.

Falsification of the instrument (it must be able to show a non-zero rc): in the worktree,
temporarily change ONE probe's expectation (e.g. the first `decide deny` -> `decide allow`),
run, confirm the FAIL line ends `[hook rc=0; stderr: ]`; then temporarily point that probe at
a hook name that does not exist (`protect-bashX.sh`), run, confirm `rc=127` and a
`No such file` stderr. Revert both with `git checkout -- scripts/test-hooks.sh` and re-apply
Step 1 (or do the two probes on a scratch copy of the edited file inside the worktree and
delete it). Expected after revert: `RESULT: 187 passed, 0 failed, 0 skipped`.

Run: `X4_TEST_SANDBOX="$SCRATCH/j2/sbx" bash $TK/scripts/test-hooks.sh > "$SCRATCH/j2/idle.log" 2>&1; echo rc=$?`
Expected: `rc=0`, last line `RESULT: 187 passed, 0 failed, 0 skipped`.

Commit (instrument only): `test-hooks: a failing probe reports the hook's exit code and stderr (flake hunt, lane J)`

**Step 2 -- reproduce under synthetic load (background, ~60-90 min).** Two scratch files
(Write tool), neither committed:

`$SCRATCH/j2/burn.py` -- N CPU burners that EXIT after `--seconds` (self-terminating):
```python
import multiprocessing as mp, sys, time
def burn(until):
    while time.time() < until:
        pass
if __name__ == "__main__":
    n, secs = int(sys.argv[1]), float(sys.argv[2])
    until = time.time() + secs
    ps = [mp.Process(target=burn, args=(until,)) for _ in range(n)]
    [p.start() for p in ps]; [p.join() for p in ps]
```

`$SCRATCH/j2/loop.sh` -- 4 concurrent suite lanes x 5 runs = 20 samples, logs kept per run:
```bash
#!/bin/bash
S="$1"; TK="$2"
lane(){ for i in 1 2 3 4 5; do
  t0=$(date +%s)
  X4_TEST_SANDBOX="$S/sbx-$1-$i" bash "$TK/scripts/test-hooks.sh" > "$S/run-$1-$i.log" 2>&1
  echo "lane=$1 run=$i rc=$? secs=$(( $(date +%s) - t0 ))" >> "$S/summary.txt"
done; }
for L in a b c d; do lane "$L" & done; wait
grep -H "^  FAIL" "$S"/run-*.log > "$S/fails.txt"; echo "FAIL lines: $(wc -l < "$S/fails.txt")" >> "$S/summary.txt"
```

Launch both with `run_in_background` (timeout 7200000):
`python "$SCRATCH/j2/burn.py" 24 5400` and `bash "$SCRATCH/j2/loop.sh" "$SCRATCH/j2" "$TK"`.
Each suite run copies nothing outside its own sandbox; memory per lane is one bash + jq/python
children (small). Do NOT run this while any other heavy job (a full gate, mutation probe) runs.

**Prediction, written before measuring:** 20 runs at ~250-450 s each (2-3.5x idle). If the
flake is spawn failure under load, >= 1 FAIL line whose bracket shows `rc` != 0 or a
`fork`/`Resource temporarily unavailable`/`child_info_fork` stderr, on a probe expecting a
non-allow verdict (got `allow`).

Expected record (into `docs/superpowers/measurements/2026-10-02-codex-0160.md`, new section
`### 2026-10-02 test-hooks-flake-hunt`): `summary.txt` verbatim (20 rows rc/secs), every FAIL
line verbatim, the load (24 burners / 28 CPUs), and the classification below.

**Step 3 -- decision tree (NO fix before the probe is named in the record):**

| Observed | Classification | Action |
|---|---|---|
| FAIL on a `decide()` probe, `rc` != 0, stderr = fork/resource error inside the HOOK | (b) product: a guard fails OPEN under load in Claude Code | STOP. Report to the orchestrator with the label + stderr; this is a guard-robustness finding (BLIND-SPOTS row via `next-blind-spot-id.py`), NOT a test fix. Remedy is a user decision. |
| FAIL whose stderr is empty, rc 0, `got allow` for an expected deny/ask | harness: the hook answered but the harness lost it (jq / `$( )` failure) | Fix the INSTRUMENT: harness-side `jq` failure becomes a distinct `ERROR` line (counted in `fail`, named as harness), never a silent `allow`. Test: run with `JQ` pointed at a stub that exits 1 once -> the line says HARNESS, not the hook's verdict. |
| FAIL on a non-`decide()` probe (static or cap section) | that probe's own assumption | Read the probe; fix the probe's assumption; twin = the same probe red against a planted defect. |
| 0 FAIL in 20 runs | NOT REPRODUCED, 0/20 under 24 burners | No fix. Record the denominator; keep the Step 1 instrument (the next occurrence names itself); recommend the orchestrator tee every gate's test-hooks output to the scratchpad. BLIND-SPOTS row "test-hooks 1/187 flake: 0/20 under synthetic load, open". |

**Commit** (only for a row-2/row-3 fix): `test-hooks: <probe label> -- <named cause> (RED under load before, 0/20 after)`;
the after-measurement re-runs the same 20-sample harness.

---

## Task J3 -- x4guard default timeout vs the Codex hook timeout, measured under load

The budgets as READ today (PreToolUse; SessionStart in parentheses):

| Layer | Value | Where |
|---|---|---|
| Codex kills the hook (then FAILS OPEN) | **60 s** (30) | FROZEN `agent/targets/codex/hooks.json.tmpl` |
| wrapper limit | 50 s (25) | `codex-entry.sh:55`, `codex-entry.ps1:88-89` |
| adapter budget, shared by every guard in the call | 45 s | `codex.py:75-79` `X4_CODEX_BUDGET_S` |
| x4guard per-check default (direct `x4guard check` only) | 25 s (+ KILL_WAIT 5 + DRAIN 3) | `x4guard.py:42-57` |

Prior evidence: "a real delete check took 22-24 s of the default 25 under load (MEASURED
2026-10-02)" (READ `test_x4guard_check.py:36-39`) -- that is why the verdict tests run with
`X4_GUARD_TIMEOUT_S=120`. M13 measured chain p95 <= 7.4 s under a concurrent pytest run
(READ codex-0160.md) -- the chain has never been measured under synthetic CPU saturation, nor
with a hung guard under load.

**Step 1 -- measure (scratch harness `$SCRATCH/j3/measure.py`, not committed).** Under
`burn.py 24 <secs>` (from J2; never concurrently with J2's loop), against `$TK`'s generated
`.codex/hooks/` copy and a decoy tree like `scripts/codex-e2e.py` builds (`X4_CONFIG=/nonexistent`,
all `X4_*` roots in `$SCRATCH/j3/tree`), record wall clock per call:

| case | n | how | env |
|---|---|---|---|
| A direct delete check | 30 | `python .codex/hooks/x4guard.py check --kind delete --path <tree>/dev/x.xml` | `X4_GUARD_TIMEOUT_S=120` (uncensored) |
| B direct PowerShell shell check | 30 | `... --kind shell --shell powershell --command "Remove-Item -Force reference/libraries/x.xml"` | same |
| C full chain, 3-file apply_patch (1 delete) | 30 | `pwsh -NoProfile -File .codex/hooks/codex-entry.ps1 pre_tool_use` fed a fixture payload | defaults (45/50) |
| D full chain, HUNG guard | 5 | as C, with the tree's `protect-bash.sh` replaced by the 40 s busy loop from `test_codex_adapter_mutants.p_hung_guard` | defaults |
| E pwsh cold start | 30 | `pwsh -NoProfile -Command exit` | -- |

Report p50 / p95 / max per case, plus for C/D the verdict and whether it was inert.

**Prediction:** A max 15-30 s; B max 10-25 s; C max < 30 s; D answers an inert deny at
~45-53 s, every time, before 60; E max 2-6 s.

**Step 2 -- decision rule (pre-registered):**
1. x4guard default `D = max(25, 5 * ceil(1.5 * maxA / 5))`. If `maxA <= 16.7` -> keep 25.
   Changing D changes no Codex behaviour (the adapter passes its own deadline).
2. Codex chain stays as is **iff** `maxD + 5 <= 60` (the wrapper always answers with >= 5 s to
   spare before Codex kills and fails open) **and** `maxC * 1.25 <= 45`.
3. If (2) fails on `maxC` only: lower nothing; raise the adapter budget within the wrapper's
   room (`budget <= 50 - 5`) -- no template change possible, so if `maxC * 1.25 > 45`, report.
4. If (2) fails on `maxD` (the wrapper cannot answer before 60 under load): first lower the
   wrapper limit/adapter budget (NOT the template) so `maxD + 5 <= 60`; only if that would push
   the adapter budget below `maxC * 1.25` is a template change required -> that is a
   **user decision** (every Codex user re-reviews hooks; CHANGELOG "Codex users must re-review
   hooks" + `codex-hooks-template: <new sha>`; update `TEMPLATE_SHA256` in
   `test_gen_codex_tree.py` and the `timeout == 60` assertion at `:52`). Do not make it here.

My expectation (INFERRED): rule 1 may move D to 35-40; rule 2 holds; **no template change.**

**Step 3 -- the misleading reason (always, independent of the numbers).** Failing test first,
append to `tools/x4validate/tests/test_x4guard_check.py` (reuses `sandbox`, `_load`,
`_fake_runner` exactly as `test_E2_a_spent_budget_runs_no_further_guard_and_is_inert` does):

```python
def test_J3_a_CALLERS_spent_deadline_does_not_blame_X4_GUARD_TIMEOUT_S(sandbox, monkeypatch):
    """The Codex adapter passes its own deadline (X4_CODEX_BUDGET_S). A reason naming
    X4_GUARD_TIMEOUT_S sends the user to a knob that played no part."""
    _, tk, env = sandbox
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    g = _load(X4GUARD)
    v = g.verdict_for("write", None, None, str(tk / "x.txt"), deadline=g._clock() - 1)
    assert v["decision"] == "deny" and v["inert"], v
    assert "X4_GUARD_TIMEOUT_S" not in v["reason"] and "caller" in v["reason"], v["reason"]


def test_J3_TWIN_a_caller_deadline_that_RUNS_OUT_mid_guard_blames_the_caller(sandbox, monkeypatch):
    _, tk, env = sandbox
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    g = _load(X4GUARD)
    _fake_runner(g, monkeypatch, {"protect-files.sh": 99.0})
    v = g.verdict_for("write", None, None, str(tk / "x.txt"), deadline=g._clock() + 2.0)
    assert v["inert"] and "X4_GUARD_TIMEOUT_S" not in v["reason"] and "caller" in v["reason"], v
```

Control that must stay green: `test_E2_a_spent_budget_runs_no_further_guard_and_is_inert`
(x4guard's OWN deadline still names `X4_GUARD_TIMEOUT_S`). ⚠ The implementer must read
`_fake_runner` first and adapt the twin to its contract (whether it returns a timeout as
`rc None`); if it cannot simulate "ran out mid-guard", use a real hung guard as
`test_E2_a_delete_with_both_guards_hung_spends_one_budget` does.

Run: `cd $TK/tools/x4validate && uv run pytest tests/test_x4guard_check.py -k J3 -q`
Expected RED: 2 failed (reason contains `X4_GUARD_TIMEOUT_S`).

Implementation: `_verdict` knows whether it created the deadline; pass a `budget_label` into
`run_guard` (`"this check's {TIMEOUT_S:g}s budget (X4_GUARD_TIMEOUT_S)"` when own, else
`"the caller's deadline (the Codex adapter's X4_CODEX_BUDGET_S)"`), used in both messages
(`:204-205`, `:214-215`). If rule 1 moved D, change `_timeout_setting`'s `25.0`, the
docstring (`:20`), and add a test pinning the new default:
`assert _load(X4GUARD).TIMEOUT_S == <D>` with `X4_GUARD_TIMEOUT_S` unset.

Green: `uv run pytest tests/test_x4guard_check.py tests/test_codex_adapter.py tests/test_codex_adapter_mutants.py -q`
Expected: all pass. Then regenerate (`uv run python scripts/gen-agent-trees.py`) and
`uv run python scripts/gen-agent-trees.py --check` -> Expected: rc 0.

Record the J3 table + decision in the measurements doc (`### 2026-10-02 guard-latency-under-load`).
CHANGELOG `## Unreleased`: one entry for the message; one for the default if it moved.

**Commits:** `x4guard: a timeout names the budget that actually ran out (Codex passes its own)`;
(if moved) `x4guard: X4_GUARD_TIMEOUT_S default 25 -> <D> (max delete check <maxA> s under load, measured)`;
`docs: guard latency under synthetic load (J3)`.

---

## Task J4 -- codex.md: the banner paragraph (flip the strict xfail) + a guard path that exists

**What the xfail pins (READ `test_codex_disclosure.py:31-37`):** the substring before ` —` of
`codex.py`'s `BANNER` -- i.e. exactly `X4 GUARDS LIVE (codex hooks v1)` -- must appear in
`agent/instructions/codex.md`. It is `xfail(strict=True)`, so today it passes BECAUSE it fails;
adding the paragraph without removing the marker turns the suite red (XPASS strict). Both
changes go in one commit.

**Step 1 -- measure the [NEW] path defect.** In `$SCRATCH/j4`, run
`bash $TK/install.sh --agent codex --dry-run <dest>` (or a real install into `$SCRATCH/j4/dest`)
and list whether `.claude/hooks/x4guard.py` and `.codex/hooks/x4guard.py` exist / would be copied.
Prediction: `.codex/hooks/x4guard.py` yes, `.claude/hooks/x4guard.py` no.

**Step 2 -- RED.** Remove the `@pytest.mark.xfail(...)` decorator. Add to
`test_gen_agent_trees.py`:

```python
def test_J4_every_x4guard_path_agents_md_names_ships_with_the_codex_target():
    """--agent codex installs AGENTS.md .codex .agents -- not .claude. A guard path AGENTS.md
    tells Codex to run must be in that set (MEASURED by lane J: .claude/hooks/x4guard.py is not)."""
    import re
    text = load().generate(REPO)["AGENTS.md"]
    cmds = [l.strip() for l in text.splitlines() if l.strip().startswith("python ") and "x4guard.py" in l]
    assert cmds, "AGENTS.md names no x4guard command"
    for l in cmds:
        path = l.split()[1]
        assert path.startswith(".codex/hooks/"), l
```

Run: `cd $TK/tools/x4validate && uv run pytest tests/test_codex_disclosure.py tests/test_gen_agent_trees.py -k "banner or J4" -q`
Expected: 2 failed.

**Step 3 -- implementation** (`agent/instructions/codex.md`):
- the three command lines become `python .codex/hooks/x4guard.py check ...`, followed by one
  prose line: "If this folder has no `.codex/hooks/` (a Claude-only setup), the same guard is
  `.claude/hooks/x4guard.py`." (prose, not starting with `python `, so
  `test_every_x4guard_line_in_agents_md_parses_and_answers` still runs only the `.codex` lines,
  which exist in the toolkit repo -- READ `git ls-files`).
- the banner paragraph, after the fail-OPEN paragraph:

  > **Check for the banner.** When the X4 hooks are live, your session context starts with
  > `X4 GUARDS LIVE (codex hooks v1)`. If you do not see that line, the hooks are not running
  > here (never reviewed, changed since review, or disabled) and nothing is enforced for you:
  > tell the user before any write or delete, and suggest they run
  > `python scripts/x4doctor.py --agent codex` from the toolkit folder.

Size: AGENTS.md is 28,512 / 32,768 bytes (MEASURED `wc -c`); this adds ~550 bytes.

**Step 4 -- green + regenerate:** `uv run python scripts/gen-agent-trees.py`, then
`uv run pytest tests/test_codex_disclosure.py tests/test_gen_agent_trees.py -q`
Expected: all pass, no xfail/xpass in the summary for `test_banner_text_is_in_the_codex_addendum`.
`uv run python scripts/gen-agent-trees.py --check` -> rc 0; the AGENTS.md advisory line shows
<= 29,100 bytes.

**Commit:** `codex.md: tell Codex to look for the hooks banner (strict xfail flipped) and name a guard path a Codex install has`

---

## Task J5 -- README residual disclosures (+ the stale budget sentence)

**Files:** `README.md` only (all text; no code).

Insert after the "What each class of agent gets" table (before the `global installs no guards`
note, READ `README.md:466-474`), a short subsection **"What the Codex hooks cannot see"**:

1. **A shell `workdir`.** Codex can run a command in another directory, and the hook is not
   told which (MEASURED P1: `tool_input` is `{command}` only). A relative path is judged
   against the session folder. Use absolute paths for anything under `reference\` or the game.
2. **Typing into a running shell (`write_stdin`).** An interactive shell or REPL started with a
   harmless command can be fed any command afterwards, and those lines reach no guard
   (MEASURED 0 hook events for 2 `write_stdin` calls; a direct call is unmeasured). Disclosed,
   not blocked (plan-2 DECISIONS #20).
3. **Bare `git clean` / `git reset --hard` (both agents).** They name no path, so they are
   judged only when the command itself names the folder (`cd <folder> && ...`, `git -C`).
   Run bare from the game folder, `git clean -fdx` is NOT stopped, and because that repo
   ignores everything but its own files, it would delete the game installation's untracked
   files. (Wording depends on Q1; if Q1 = deny, item 3 shrinks to "denied with a reason".)

Fix README `:299-300`: replace "It applies a separate timeout to each guard; a delete check can
run two guards." with "One time budget covers the whole check (`X4_GUARD_TIMEOUT_S`, default
<D from J3> s), shared by a delete's two guards; a check that runs out is an inert deny. The
Codex hook path uses its own budget instead (`X4_CODEX_BUDGET_S`, 45 s)."

**Scope expansion flagged (Q3):** the measurements doc lists 9 README residuals
(codex-0160.md "Residuals the README must disclose"); README covers items 1, 2, 9 in the table.
Items 5 (unknown/MCP/subagent-control tools allowed, logged to `.codex/x4-unknown-tools.log`),
6 (`.codex/rules` prefix-only; untrusted-project loading unmeasured), 7 (moving the folder
re-requires review), 8 (no post-edit validator for a patch applied through the shell) are
absent (grep for their keywords: 0 hits). If Q3 = yes, add them as items 4-7, one line each.

Verify (no test pins this text): `grep -n "write_stdin\|workdir\|git clean" $TK/README.md`
Expected: the new lines; and `grep -n "separate timeout to each guard" $TK/README.md` -> no
output. Then focused README-reading tests:
`uv run pytest tests/test_skills_are_documented.py tests/test_write_verb_promises_are_consistent.py tests/test_audit0924_gates.py -q`
Expected: all pass. `python $TK/scripts/scan-identifiers.py` (README must carry no personal
path) -> Expected: rc 0.

**Commit:** `README: disclose what the Codex hooks cannot see (workdir, write_stdin, bare git clean); fix the per-guard timeout sentence`

---

## Task J6 -- the stale CI comment

READ `.github/workflows/ci.yml:47-50`:
> Ubuntu is INFORMATIONAL, not a gate. ... POSIX behaviour has never been measured, so gating
> on it would be asserting something unverified. ... promote it to a gate once it is green on
> its own merits.

**What is stale:** the ubuntu leg WAS promoted -- `experimental: false` for both matrix rows,
with the in-file note "PROMOTED 2026-09-09 ... tests (ubuntu-latest) = success, per JOB"
(READ `:77-78, :93`). So `continue-on-error: ${{ matrix.experimental }}` is false for every
leg; the comment above it describes the opposite. ("Never been measured" is also false: CI
ubuntu has run every push since.) Line 1's product name is lane K's, not touched here.

Replace lines 47-50 with:
```yaml
    # Both legs GATE: ubuntu was promoted on 2026-09-09 (the matrix note below records the run
    # and why). `continue-on-error` stays keyed on `experimental` so demoting a leg is one
    # visible edit. Ubuntu is the only POSIX evidence: Linux/macOS support is still "best
    # effort, not device-tested" (README), so a green ubuntu leg is not a device test.
```

Verify: `cd $TK/tools/x4validate && uv run python -c "import yaml,sys; yaml.safe_load(open(r'$TK/.github/workflows/ci.yml',encoding='utf-8')); print('ok')"`
Expected: `ok`. `grep -n "INFORMATIONAL" $TK/.github/workflows/ci.yml` -> no output.
`uv run pytest tests/test_framework_hardening.py tests/test_lua_suite_is_not_silently_absent.py tests/test_no_stale_bytecode.py -q`
(the tests that read ci.yml) -> Expected: all pass.

**Commit:** `ci.yml: the ubuntu leg gates since 2026-09-09; the comment above continue-on-error said the opposite`

---

## Task J7 -- M10: Codex's `additionalContext` cap (USER-GATED run)

What exists: the 10,000-char bound is kept "until measured (M10)" (READ spec `:145`, `:292`).
One run measures five sizes at once, so the plan is **1 `codex exec` run**, at most 2 more only
if the answer falls between two sizes AND the orchestrator wants finer resolution.

**Step 1 -- build the scratch harness (no quota).** In `$SCRATCH/m10/` (Write tool):
- `emit.py` -- a PreToolUse hook. Keeps a counter in `$SCRATCH/m10/state/n`; the k-th call
  emits `additionalContext` of size `SIZES[k] = [8000, 16000, 32000, 64000, 128000]` chars:
  `M10-HEAD-<size>-<nonce>` + filler + `M10-TAIL-<size>-<nonce>`, nonce = 8 random hex per
  call written to `$SCRATCH/m10/state/keys.txt` (outside the Codex root). No
  `permissionDecision` (allow). Also records the payload's `transcript_path`.
  SessionStart: the same script with arg `session` prints 40,000 chars of plain stdout with its
  own HEAD/TAIL nonces.
- `root/.codex/hooks.json` -- both events; `"command"` and `"commandWindows"` =
  `python "<abs>/emit.py" pre` / `... session` (must NOT start with `"` -- MEASURED: such a hook
  never runs). Timeouts 30.
- `run.py` -- mirrors `scripts/codex-e2e.py:codex_exec` (stdin DEVNULL, timeout 600, log to
  `$SCRATCH/m10/run-1.log`).

**Step 2 -- THE USER-GATED RUN (spends Codex quota; needs the user's go-ahead).** Exact command:

```
codex exec --dangerously-bypass-hook-trust -s workspace-write --skip-git-repo-check -C "<SCRATCH>/m10/root" "Run these five shell commands one at a time, waiting for each: echo m10-1, echo m10-2, echo m10-3, echo m10-4, echo m10-5. Then list, verbatim, every token beginning M10-HEAD or M10-TAIL that you can see anywhere in your context, one per line, and nothing else." </dev/null
```
(run from Git Bash; or `python <SCRATCH>/m10/run.py`, which passes stdin=DEVNULL). One run.

**Step 3 -- readout (no quota).** Primary: grep the rollout JSONL at the recorded
`transcript_path` for each HEAD/TAIL nonce and for any spill/truncation marker (`truncated`,
a file path replacing the text). Secondary (model-reported, labelled as such): the model's
final list vs `keys.txt` -- a TAIL nonce it quotes correctly was in its context; nonces are
random so it cannot guess them. ⚠ ASSUMED: the rollout records what the MODEL received rather
than the raw hook output; if the two readouts disagree, the model's quoted nonces win for
"in context" and the disagreement is itself recorded.

**Prediction:** 8k and 16k intact; a cap or spill somewhere at 32k-128k (INFERRED from
the spec's "spills to disk past some size").

Record in `docs/superpowers/measurements/2026-10-02-codex-0160.md`, new section
`### 2026-10-0x M10-additionalContext-cap`: Codex version, sizes, per-size intact/truncated/
spilled from each readout, the exact command, and the implication: whether the 10,000-char
bound is (a) needed and (b) sufficient on Codex. No code change in this lane -- changing the
bound is a follow-up decision.

**Commit:** `docs: M10 -- Codex additionalContext cap measured (<result>)`

---

## Task J8 -- branch `pr2`: what it is (REPORT ONLY, done at planning time)

MEASURED (read-only git, this session):
- `pr2` -> `a18ab2e` "feat: cross-platform support + guided installer (Linux/macOS/Windows)",
  author **the original author**, 2026-06-27; history `a18ab2e <- b3554d0 <- 9dc393c` (v1.0).
- Its reflog: `fetch origin pull/2/head:pr2` -- a local copy of **GitHub PR #2** (an external
  contribution), not a session branch. No upstream configured.
- `git log master..pr2` = **0 commits**; `merge-base pr2 master` = `a18ab2e` itself; the commit
  is contained in tags `v2.0`, `v2.01`, `v2.02`. **It is fully merged into master** -- deleting
  it loses nothing (not done; no action in this lane).
- Not on the remote (`ls-remote --heads origin`: master, ci/plan2, session/2026-09-02-round3).
  Side observation: `origin/session/2026-09-02-round3` (`c8bb927`) is a stale remote branch;
  not investigated.

Nothing to implement. The implementer re-runs the four commands above only if asked.

---

## Task J9 -- CI failures from `ci/plan2` (PLACEHOLDER -- the orchestrator fills this)

Rows to be added from the per-JOB, per-TEST read of the `ci/plan2` run, each classified
real vs CI-environment, each with its own failing-test-first task. Also: correct the counted
skip ceilings from the real run (PLAN.md Step 0.2).

---

## Files touched (union)

- `tools/x4validate/scripts/gen-cli-reference.py` (J1)
- `tools/x4validate/tests/test_cli_reference.py` (J1)
- `scripts/test-hooks.sh` (J2)
- `agent/guards/claude-hooks/x4guard.py` (J3) + generated `.claude/hooks/x4guard.py`, `.codex/hooks/x4guard.py`
- `tools/x4validate/tests/test_x4guard_check.py` (J3)
- CONDITIONAL on J3 rules 3-4 only: `agent/guards/adapters/codex.py` (+ `.codex/hooks/codex_adapter.py`),
  `agent/guards/adapters/codex-entry.sh/.ps1` (+ `.codex/hooks/` copies); template change ONLY with user approval:
  `agent/targets/codex/hooks.json.tmpl`, `tools/x4validate/tests/test_gen_codex_tree.py`
- `agent/instructions/codex.md` (J4) + generated `AGENTS.md`
- `tools/x4validate/tests/test_codex_disclosure.py`, `tools/x4validate/tests/test_gen_agent_trees.py` (J4)
- `README.md` (J5)
- `.github/workflows/ci.yml` (J6)
- `docs/superpowers/measurements/2026-10-02-codex-0160.md` (J2, J3, J7)
- `CHANGELOG.md` (J1, J3, J4, J5 -- append-only)
- CONDITIONAL: `docs/BLIND-SPOTS.md` (J2 row; id from `next-blind-spot-id.py`)

## Verify-hook-tests anchors touched

**None.** `scripts/verify-hook-tests.py` names no line in x4guard.py, codex.py, test-hooks.sh,
codex.md or gen-cli-reference.py (MEASURED: grep for `x4guard|TIMEOUT_S|codex.py|budget_s` -> 0
hits). `test_codex_adapter_mutants.py` anchors on `codex_adapter.py` strings (`SHELL = ...`,
`os.chdir(cwd)`, ...); J3 touches codex.py ONLY under rules 3-4, and then only `budget_s`'s
default, which no mutant anchors (READ `:86-100`). If that changes, re-grep the MUTANTS table.

## Cross-lane dependencies

- **G** edits `x4guard.py` (conformance subcommand). J's edit is confined to `_verdict` /
  `run_guard` messages (+ maybe `_timeout_setting`'s default). Merge order J -> G; G must not
  assert on the timeout-reason wording, and G's conformance inherits J3's default.
- **G** may also touch `agent/instructions/` (ADAPTING / setup prompt): J4 edits `codex.md` only.
- **L, H, K** edit `README.md`: J5 inserts one subsection after the agent table and edits
  `:299-300`; low conflict risk but same file. CHANGELOG is shared append-only.
- **I** (config move) touches `test-hooks.sh`'s sandbox/env? -- J2's edit is inside `decide()`
  only.
- **K** (rename) owns `ci.yml:1`; J6 edits `:47-50` only.
- J5's budget sentence depends on J3's outcome; J5's item 3 depends on Q1.
- J7 needs the user's go-ahead for one `codex exec` run.

## Questions for the user

1. **Q1 -- bare `git clean -fdx` from the game folder is ALLOWED today** (MEASURED this session
   via the deployed `x4guard check`, cwd = game root). In the game-root repo (whitelist
   `.gitignore`) it would delete every untracked game file. Lane F left it unseeded because the
   rule ASKS and you ruled out new prompts. **Recommendation:** make the *seed-only* case (bare
   `git clean` with `-x` or `-d`, or `reset --hard`, whose session folder is the game root or
   reference) a **DENY with a reason** -- "name the folder explicitly with `git -C`" -- which
   never reaches you, and keep the explicit-folder case as it is. That is a guard change
   (protect-bash/hook_facts, verify-hook-tests anchors) and would be its own task here or in a
   follow-up lane; until decided, J5 discloses it.
2. **Q2 -- the Codex banner over-claims.** It reads "every shell command and apply_patch is
   checked" (READ `codex.py:53`), but `write_stdin` input and a hidden `workdir` are not.
   **Recommendation:** keep the pinned prefix `X4 GUARDS LIVE (codex hooks v1)` and change the
   tail to "shell commands and apply_patch are checked (input typed into a running shell is
   not)". The banner lives in the adapter, not the frozen template, so no re-review is needed
   (INFERRED from the spike's "changed hook DEFINITIONS are inert" -- the adapter script is
   not a definition; confirm with `codex_trust.py report` after deploy).
3. **Q3 -- README residuals beyond the three named.** Items 5-8 of the measurements doc's
   README list are not in README. **Recommendation:** yes, add them in J5 (four one-line items,
   text only).
4. **Q4 -- J7's quota.** One `codex exec` run (five sizes in one session). **Recommendation:**
   approve one run; a second only if the cap falls between two sizes and you want it narrower.

## Confidence

| Task | Conf. | What raises it (if < 90%) |
|---|---|---|
| J1 decode refusal | 95% | -- |
| J2 instrument | 92% | -- |
| J2 name the probe | 55% | It is a reproduction attempt: 0/20 is a likely outcome. Raised only by the 20-sample run; the instrument makes any future occurrence self-identifying, which is the durable win. |
| J2 fix | n/a | Not plannable until the probe is named (by design). |
| J3 measurement + rules | 80% | Step 1's numbers. Weakest link: whether `pwsh` cold start under 24 burners stays < 10 s (case E) -- measured first. |
| J3 reason-message fix | 90% | Read `_fake_runner` before writing the twin. |
| J4 banner + path | 88% | Step 1 install listing (confirms the Codex-only install lacks `.claude/hooks/x4guard.py`). |
| J5 README | 92% | Q1/Q3 answers fix the wording. |
| J6 CI comment | 97% | -- |
| J7 M10 harness | 75% | The readout assumption (rollout = what the model saw) is ASSUMED; the random-nonce model echo is the cross-check. Also ASSUMED: Codex accepts `python "<abs>"` as a hook command on Windows (the spike measured `bash "..."`; a dry `codex exec` is NOT free) -- mitigate by testing `emit.py` offline with a fixture payload and copying the spike's proven command shape (`bash "<abs>/emit.sh"` wrapper calling python) if in doubt. |
| J8 pr2 report | 99% | -- |

## Gate plan (focused only; the orchestrator runs the one full gate per wave)

1. `uv run pytest tests/test_cli_reference.py -q` (J1)
2. `X4_TEST_SANDBOX=$SCRATCH/j2/sbx bash scripts/test-hooks.sh` -> `187 passed, 0 failed` (J2)
3. `uv run pytest tests/test_x4guard_check.py tests/test_codex_adapter.py tests/test_codex_adapter_mutants.py -q` (J3)
4. `uv run pytest tests/test_codex_disclosure.py tests/test_gen_agent_trees.py tests/test_gen_codex_tree.py -q` (J4; and J3 if the template ever moved)
5. `uv run python scripts/gen-agent-trees.py --check` and `uv run python scripts/gen-cli-reference.py --check` -> rc 0
6. `uv run pytest tests/test_skills_are_documented.py tests/test_write_verb_promises_are_consistent.py tests/test_audit0924_gates.py tests/test_framework_hardening.py -q` (J5, J6)
7. `python scripts/scan-identifiers.py` -> rc 0
One at a time; never alongside J2's load loop.
