# Plan 3 -- Lane G: ADAPTING.md, `x4guard conformance`, toy agent, universal setup prompt

Planner: opus, 2026-10-02, read-only against toolkit master `0cb667f`.
Implementer branch: `session/p3-g` in its own worktree. Merge order J -> **G** -> L -> H.

## Context

Spec D7 / §11 / §7.10 asks for: `ADAPTING.md` (self-assessment including a measured fail-open /
fail-closed check, the guard contract, worked Claude + Codex examples, where adapters go, required
proof, rules, an upstream template), an `x4guard conformance` that drives ANY adapter, a toy agent
whose adapter is written only from `ADAPTING.md`, and one universal setup prompt.

What exists today (READ unless marked):

| Fact | Tier | Where |
|---|---|---|
| `x4guard check` takes ARGUMENTS, not stdin: `--kind shell --shell bash\|powershell --command C` or `--kind write\|delete --path P`; prints ONE JSON line `{"v":1,"decision","reason","context","inert","guards"}`; exit 0 for every verdict, exit 2 only for a usage error (argparse) | READ | `agent/guards/claude-hooks/x4guard.py:1-24, 281-297` |
| Spec §5.6 shows `x4guard check --agent <name> ...`; the implementation has **no `--agent`** | READ | spec line 172 vs x4guard.py:284-289. ADAPTING.md documents the real CLI; the spec drift is reported, not fixed here. |
| A shell check's payload `cwd` = `os.getcwd()`; a write/delete path is `abspath`ed from the caller's cwd -> an adapter must run x4guard IN the agent's reported cwd | READ | x4guard.py:131-138, 265 |
| A copy not under `.claude/hooks` or `.codex/hooks` refuses (inert) unless `X4_TOOLKIT` is set | READ | x4guard.py:179-196 |
| The Codex adapter imports x4guard in-process, renders deny / `NEEDS YOUR APPROVAL:` deny / additionalContext / empty, prints `X4OK <json>` to a fail-closed wrapper | READ | `agent/guards/adapters/codex.py` (all 428 lines) |
| Conformance machinery is test-local: `dumped` fixture (runs `scripts/test-hooks.sh` with `X4_DECIDE_DUMP`), `classify`, `claude_hook` (reference verdict, re-run under `X4_GUARD_CHECK=1` to detect "inert"), `native_for`, `codex_chain`, `parse_output` | READ | `tools/x4validate/tests/test_codex_conformance.py:126-252`, `codex_testlib.py:51-74` |
| `scripts/test-hooks.sh` has 121 `decide` call lines and **0 occurrences of "PowerShell"** -> the dump replays NO PowerShell case; PowerShell routing is covered only by the Codex-only `conformance_extra.yaml` | MEASURED (grep) | a generic conformance built on the dump alone could never catch a shell-routing bug |
| test-hooks.sh REFUSES a sandbox under `/tmp/*` (rc 2); the Codex test passes it a `tmp_path_factory` base, which on Linux is `/tmp/pytest-of-...` | READ (test-hooks.sh:53-56, test_codex_conformance.py:132) | INFERRED: the Codex conformance test fails on ubuntu CI (informational leg). Measured in T0. |
| Installed toolkits copy `tools bin scripts mods ... SETUP_PROMPT.txt` but **never `agent/`**; `--agent` defaults to `all` (ships `.claude/hooks` + `.codex/hooks`); `--agent generic` ships NO guard tree | READ | install.sh:44, 513-523; install.ps1:319-321 |
| `verify-hook-tests.py` anchors only `hook_facts.py` / `test_hook_facts.py` / `ps_translate.ps1` | READ | scripts/verify-hook-tests.py:47 |
| `gen-agent-trees.py` copies `agent/guards/claude-hooks/**` verbatim into `.claude/hooks/` and `.codex/hooks/`; adapters only by the explicit `CODEX_ADAPTERS` map | READ | gen-agent-trees.py:321-360 |
| `SETUP_PROMPT.txt` is Claude-specific ("Claude Code Modding Toolkit", "bash setup.sh"); no test pins its text | READ (grep of tests/, gates/, scripts/: 0 hits) | |
| AGENTS.md 28,512 B (cap 32,768); core.md has no pointer for an unsupported agent | MEASURED (wc -c) | |

## Global constraints

- Test-first, watch each test fail for the RIGHT reason before implementing; one falsification twin
  per clause (exit-code clauses especially).
- Never edit generated trees: edit `agent/guards/claude-hooks/x4guard.py` and `agent/instructions/core.md`,
  then `uv run python scripts/gen-agent-trees.py` (from `tools/x4validate`).
- The engine is **stdlib only, Python >= 3.10** (x4guard's own constraint: it runs from a bare interpreter).
- Write file content with the Write/Edit tools (backslashes); no heredocs.
- Memory: at most ONE heavy process (a dump, a replay, a focused pytest of the conformance files) at a time.
  Use `--workers 4` (not the Codex test's 6) everywhere new.
- Do not change x4guard's `check` behaviour or the `_timeout_setting` region (lane J owns the timeout default).
- No new numbers hard-coded in docs that another lane can move (timeout default, rule counts): docs say
  where to read them, and a test derives them.
- Product name in every NEW doc: **"X4 AI Assistant Toolkit"** (lane K renames the rest later).

## Interfaces

### Produces

1. **`scripts/x4conformance.py`** -- the engine (installed with `scripts/`, so it works in an installed
   toolkit, not only a source checkout). Public API:
   ```python
   KINDS = ("shell-bash", "shell-powershell", "edit", "write")
   RC_OK, RC_DISAGREE, RC_ERROR, RC_NOTHING = 0, 1, 2, 3
   class ProfileError(ValueError): ...
   def load_profile(spec: str, root: Path) -> dict          # NAME -> scripts/conformance-profiles/NAME.json, else a path
   def classify(row: dict) -> str                            # a KIND or "no_native_analogue"
   def fill(template, values: dict)                          # {{COMMAND}} {{PATH}} {{CONTENT}} {{CONTENT|lines:+}} {{CWD}}
   def decode(output: dict, stdout: bytes, rc: int) -> tuple[str, str | None]
                                                             # allow|advise|ask|deny|inert|unreadable, text
   def dump_cases(root: Path, base: Path | None = None) -> tuple[list[dict], Path]
   def extra_rows(root: Path, rows: list[dict]) -> list[dict]   # neutral PowerShell/space/drive cases
   def reference_verdict(row: dict, root: Path) -> str
   def adapter_verdict(row, profile, argv, root, run_dir) -> tuple[str, str | None]
   def replay(rows, profile, argv, root, workers=4) -> list[dict]
   def summarise(results, n_total, buckets, gaps, min_cases) -> tuple[int, str]
   def main(argv: list[str]) -> int                          # prog "x4guard conformance"
   ```
   Exit codes: **0** every replayed case agrees and replayed >= `--min-cases` (default 80) ·
   **1** at least one disagreement or unreadable adapter output (listed PER ITEM) ·
   **2** cannot evaluate: bad/incomplete profile, no adapter command, toolkit or `.claude/hooks`
   or bash/jq missing, the dump harness failed, a reference verdict unreadable, a reference control
   (an extra case's `expect`) failed · **3** nothing (or too little) examined: replayed == 0 or
   replayed < `--min-cases`. Never 0 on an empty population.
2. **`scripts/conformance-profiles/{claude,codex}.json`** -- profile format v1 (below).
3. **`scripts/conformance-extra-cases.json`** -- neutral Claude-shaped cases the dump cannot express
   (PowerShell write/delete/allow, a path with spaces, a Git-Bash drive path), each with a reference
   `expect` control.
4. **`x4guard conformance ...`** -- a dispatch in `x4guard.py` main() into the engine.
5. **`ADAPTING.md`** (toolkit root), **`docs/ADAPTING-COLD-TEST.md`** (release exercise),
   rewritten **`SETUP_PROMPT.txt`**.
6. **Toy agent** under `tools/x4validate/tests/fixtures/toy_agent/`: `TOY-AGENT.md` (the toy's own
   docs), `toy_agent.py` (a runnable harness that FAILS OPEN by design), `payloads/*.json`,
   `toy_adapter.py` + `profile.json` (written by a cold subagent from ADAPTING.md + TOY-AGENT.md only).
7. `conftest.py` session fixture **`conformance_dump`** (one dump per pytest session, shared by the
   Codex and toy tests).

### Profile format v1 (the contract between an adapter author and the engine)

```json
{
  "v": 1,
  "agent": "toy",
  "command": ["{PYTHON}", "{TOOLKIT}/tools/x4validate/tests/fixtures/toy_agent/toy_adapter.py"],
  "requires": ["bash", "jq"],
  "run_cwd": "neutral",
  "timeout_s": 120,
  "env": {"X4_GUARD_PY": "{HOOKS}/x4guard.py"},
  "cases": {
    "shell-bash":       {"payload": "payloads/run_shell.json",
                         "set": {"/args/cmdline": "{{COMMAND}}", "/args/interpreter": "bash", "/workdir": "{{CWD}}"}},
    "shell-powershell": {"payload": "payloads/run_shell.json",
                         "set": {"/args/cmdline": "{{COMMAND}}", "/args/interpreter": "powershell", "/workdir": "{{CWD}}"}},
    "edit":  {"payload": "payloads/edit_file.json",  "set": {"/args/target": "{{PATH}}", "/workdir": "{{CWD}}"}},
    "write": {"payload": "payloads/write_file.json", "set": {"/args/target": "{{PATH}}", "/args/text": "{{CONTENT}}", "/workdir": "{{CWD}}"}}
  },
  "unsupported": {},
  "output": {
    "format": "text",
    "exit_codes": {"0": "decode"},
    "empty": "allow",
    "rules": [
      {"regex": "^TOY-BLOCK (?P<text>NEEDS YOUR APPROVAL:.*)$", "decision": "ask"},
      {"regex": "^TOY-BLOCK (?P<text>.*)$", "decision": "deny"},
      {"regex": "^TOY-NOTE (?P<text>.*)$",  "decision": "advise"}
    ]
  }
}
```

- Command placeholders: `{TOOLKIT}` (the engine's own toolkit root, NOT the row's sandbox
  `X4_TOOLKIT`), `{HOOKS}` (`{TOOLKIT}/.claude/hooks`), `{PYTHON}`, `{BASH}`, `{PWSH}`, `{HOOK}`
  (the row's hook script name; used by the Claude identity profile). `--` + argv on the command line
  overrides `command`.
- `payload` paths are relative to the PROFILE file; the special value `"row"` sends the dumped
  Claude-shaped payload itself (Claude identity profile).
- `set` keys are JSON pointers; values are filled AFTER JSON parsing (no escaping hazards), one regex
  pass over the TEMPLATE (a `{{` inside a case's command is never re-expanded). A template token the
  engine does not know -> `ProfileError` (rc 2).
- `cases` + `unsupported` must cover ALL FOUR kinds; a kind in neither -> rc 2. An `unsupported` kind
  is reported as a GAP on every run (its rows go to `no_native_analogue`), so a lazy profile cannot
  pass silently by dropping PowerShell.
- `run_cwd`: `"neutral"` (default) runs the adapter in an empty scratch dir, so an adapter that ignores
  its payload's cwd fails the relative-path cases; `"case"` runs it in the row's cwd (Claude identity).
- `output.format`: `"json"` rules match `{"when": {pointer: value | {"present": true}}, "absent": [pointer],
  "text": pointer, "decision": D, "prefix_decisions": {"NEEDS YOUR APPROVAL:": "ask"}}`; `"text"` rules
  match a regex with a `text` group. Optional `strip_prefix`, `single_line`, `allowed_keys`
  (`{"": [...], "/hookSpecificOutput": [...]}` -- an extra key is `unreadable`, because Codex fails open on it).
  `exit_codes` maps an exit status to `"decode"` or a decision (`{"0": "decode", "2": "inert"}`); an
  unlisted status is `unreadable`. After a rule matches: a deny/ask whose text contains
  `X4 GUARD INERT` is `inert`. No rule matches -> `unreadable` (a disagreement, never an allow).

## Tasks

### T0 -- measurements that gate the build (read-only; ~30 min wall, one heavy job at a time)

1. **M-G1, ubuntu Codex conformance.** `gh run view <id> --log` for the `ci/plan2` run (in progress at
   planning time, id 37091872873) -> grep `test_codex_conformance`. Prediction (INFERRED): it errors on
   ubuntu with test-hooks' "sandbox landed under /tmp" refusal. Either answer is recorded in the lane report;
   if it passes, the `.test-sandbox` base in T2 is still kept (it is the harness's own default) but the
   "fixes ubuntu" claim is dropped from the CHANGELOG.
2. **M-G2, per-item baseline.** On the untouched branch, in the background:
   `cd tools/x4validate && uv run python -m pytest -q -rs tests/test_codex_conformance.py tests/test_codex_adapter.py tests/test_codex_adapter_mutants.py tests/test_codex_wrapper.py -p no:cacheprovider --junitxml=<scratch>/g-baseline.xml`
   Expected: all pass (or the same set as master's last gate). The junit file is the per-test-id baseline for T4.
3. **M-G3, dump cost and shape.** `X4_DECIDE_DUMP=<scratch>/dump.jsonl X4_TEST_SANDBOX=<toolkit>/.test-sandbox/g bash scripts/test-hooks.sh`
   timed; then a python one-off counting rows, `classify` buckets, tool names, and rows per reference
   decision. Expected: >= 100 rows, `PowerShell` rows = 0 (prediction from grep), ask rows >= 3, deny >= 20.
   Remove the kept sandbox it names in `dump.jsonl.sandbox` afterwards (exact path, `rm -r` of that one dir).
4. **M-G4, the toy's premise.** For 10 dumped rows (mixed decisions, incl. one relative-path row), run
   `python .claude/hooks/x4guard.py check ...` with the row's env, cwd = row cwd, and compare to the row's
   `got`. Expected: 10/10 equal modulo inert normalisation. If not, STOP: the Layer-0 contract the toy
   and ADAPTING.md rely on disagrees with the hooks, which is a finding for the orchestrator, not something to paper over.

Commit: none (measurements go in the lane report).

### T1 -- engine core: profile, fill, decode, classify, summarise (pure, fast tests)

Files: `scripts/x4conformance.py` (new), `scripts/conformance-profiles/claude.json`,
`scripts/conformance-profiles/codex.json` (new), `tools/x4validate/tests/test_x4conformance_engine.py` (new).

Failing tests first:

```python
"""x4conformance engine, pure parts: no bash, no dump. Every exit-code clause has a twin."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("x4conformance", REPO / "scripts" / "x4conformance.py")
xc = importlib.util.module_from_spec(spec); spec.loader.exec_module(xc)

CODEX = xc.load_profile("codex", REPO)
CLAUDE = xc.load_profile("claude", REPO)


def _old_codex_patch(op, path, content=""):          # verbatim from test_codex_conformance._patch
    if op == "add":
        body = "".join("+" + ln + "\n" for ln in (content.split("\n") if content else [""]))
        return f"*** Begin Patch\n*** Add File: {path}\n{body}*** End Patch"
    return f"*** Begin Patch\n*** Update File: {path}\n@@\n-x\n+y\n*** End Patch"


@pytest.mark.parametrize("content", ["", "a", "a\nb", "a\n", "{{COMMAND}}"])
def test_codex_write_template_reproduces_the_old_patch_builder(content):
    t = CODEX["cases"]["write"]["set"]["/tool_input/command"]
    assert xc.fill(t, {"PATH": "p q.xml", "CONTENT": content}) == _old_codex_patch("add", "p q.xml", content)


def test_fill_never_re_expands_a_token_inside_a_value():
    assert xc.fill("{{COMMAND}}", {"COMMAND": "echo {{PATH}}", "PATH": "X"}) == "echo {{PATH}}"


def test_an_unknown_template_token_is_a_profile_error():
    with pytest.raises(xc.ProfileError):
        xc.fill("{{NOPE}}", {})


def _profile(**over):
    p = json.loads(json.dumps(CODEX)); p.update(over); return p


def test_a_kind_neither_mapped_nor_unsupported_is_refused(tmp_path):
    p = _profile(); del p["cases"]["shell-powershell"]
    f = tmp_path / "p.json"; f.write_text(json.dumps(p), encoding="utf-8")
    with pytest.raises(xc.ProfileError, match="shell-powershell"):
        xc.load_profile(str(f), REPO)


def test_TWIN_a_kind_declared_unsupported_loads_and_is_a_gap(tmp_path):
    p = _profile(); del p["cases"]["shell-powershell"]; p["unsupported"] = {"shell-powershell": "no PS"}
    f = tmp_path / "p.json"; f.write_text(json.dumps(p), encoding="utf-8")
    assert xc.load_profile(str(f), REPO)["unsupported"] == {"shell-powershell": "no PS"}


# --- decode: Codex shapes (the C4 contract), Claude shapes, text rules --------------------- #

def _hso(**k):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **k}}).encode()


@pytest.mark.parametrize("out,expect", [
    (b"", "allow"),
    (_hso(permissionDecision="deny", permissionDecisionReason="BLOCKED x"), "deny"),
    (_hso(permissionDecision="deny", permissionDecisionReason="NEEDS YOUR APPROVAL: x"), "ask"),
    (_hso(permissionDecision="deny", permissionDecisionReason="X4 GUARD INERT: y"), "inert"),
    (_hso(additionalContext="note"), "advise"),
    (_hso(permissionDecision="ask", permissionDecisionReason="x"), "unreadable"),    # Codex fails open on ask
    (_hso(permissionDecision="allow", permissionDecisionReason="x"), "unreadable"),
    (json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "r",
                                        "extra": 1}}).encode(), "unreadable"),        # extra key = fail-open
    (b"not json", "unreadable"),
])
def test_codex_decode(out, expect):
    assert xc.decode(CODEX["output"], out, 0)[0] == expect


def test_codex_a_nonzero_exit_is_unreadable_never_a_verdict():
    assert xc.decode(CODEX["output"], _hso(permissionDecision="deny", permissionDecisionReason="r"), 2)[0] == "unreadable"


@pytest.mark.parametrize("out,rc,expect", [
    (_hso(permissionDecision="ask", permissionDecisionReason="x"), 0, "ask"),          # Claude honours ask
    (_hso(permissionDecision="ask", permissionDecisionReason="NO rule was evaluated"), 2, "inert"),
    (b"", 0, "allow"),
])
def test_claude_decode(out, rc, expect):
    assert xc.decode(CLAUDE["output"], out, rc)[0] == expect


# --- classify + summarise ------------------------------------------------------------------ #

@pytest.mark.parametrize("payload,kind", [
    ({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "shell-bash"),
    ({"tool_name": "PowerShell", "tool_input": {"command": "dir"}}, "shell-powershell"),
    ({"tool_name": "Edit", "tool_input": {"file_path": "a"}}, "edit"),
    ({"tool_name": "Write", "tool_input": {"file_path": "a", "content": ""}}, "write"),
    ({"tool_name": "Bash", "tool_input": {"command": ""}}, "no_native_analogue"),
    ({"tool_name": "Grep", "tool_input": {"pattern": "x"}}, "no_native_analogue"),
    ({"tool_name": "Bash", "tool_input": "notadict"}, "no_native_analogue"),
])
def test_classify(payload, kind):
    assert xc.classify({"payload": payload}) == kind


def _res(n_agree, n_disagree=0):
    r = [{"label": f"a{i}", "kind": "shell-bash", "reference": "deny", "adapter": "deny"} for i in range(n_agree)]
    r += [{"label": f"d{i}", "kind": "write", "reference": "deny", "adapter": "allow"} for i in range(n_disagree)]
    return r


def test_zero_replayed_refuses_with_3():
    rc, text = xc.summarise([], n_total=12, buckets={"no_native_analogue": 12}, gaps={}, min_cases=1)
    assert rc == xc.RC_NOTHING and "0 replayed" in text


def test_TWIN_one_agreeing_case_with_a_floor_of_one_passes():
    assert xc.summarise(_res(1), n_total=1, buckets={"replayed": 1}, gaps={}, min_cases=1)[0] == xc.RC_OK


def test_below_the_floor_refuses_with_3():
    assert xc.summarise(_res(5), n_total=5, buckets={"replayed": 5}, gaps={}, min_cases=80)[0] == xc.RC_NOTHING


def test_one_disagreement_is_1_and_names_the_item():
    rc, text = xc.summarise(_res(90, 1), n_total=91, buckets={"replayed": 91}, gaps={}, min_cases=80)
    assert rc == xc.RC_DISAGREE and "d0" in text


def test_buckets_that_do_not_sum_to_the_total_are_an_engine_error():
    with pytest.raises(AssertionError):
        xc.summarise(_res(3), n_total=5, buckets={"replayed": 3}, gaps={}, min_cases=1)


def test_a_gap_is_printed_on_a_passing_run():
    rc, text = xc.summarise(_res(90), n_total=90, buckets={"replayed": 90}, gaps={"shell-powershell": "no PS"},
                            min_cases=80)
    assert rc == xc.RC_OK and "GAP" in text and "shell-powershell" in text
```

Run (RED: module missing): `cd tools/x4validate && uv run python -m pytest -q tests/test_x4conformance_engine.py`
Expected RED: collection error `FileNotFoundError ... scripts/x4conformance.py`.

Implementation: `scripts/x4conformance.py` with the API above (stdlib only; module docstring states the
exit codes and the profile format; `summarise` asserts `sum(buckets.values()) == n_total` and that
`buckets.get("replayed", 0) == len(results)`). Codex profile = the Codex test's choices, verbatim:
`command` = `["{PWSH}", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
"{TOOLKIT}/.codex/hooks/codex-entry.ps1", "pre_tool_use"]`, `env` `{"X4_PYTHON": "{PYTHON}"}` plus
per-case `env` `X4_CODEX_SHELL` (bash for shell-bash/edit/write, powershell for shell-powershell),
payloads from `../../tools/x4validate/tests/fixtures/codex/0.160.0/` (bash_powershell, apply_patch_update,
apply_patch_add) with `"/cwd": "{{CWD}}"`, `requires: ["pwsh","bash","jq"]`, `allowed_keys` = codex_testlib's
ALLOWED_TOP/ALLOWED_HSO, `exit_codes {"0":"decode"}`. Claude profile: `payload: "row"`,
`command ["{BASH}", "{HOOKS}/{HOOK}"]`, `env {"X4_GUARD_CHECK": "1"}`, `run_cwd: "case"`,
`exit_codes {"0":"decode","2":"inert"}`, json rules for deny/ask/advise.

GREEN: same command. Expected: all pass.
Commit: `x4conformance: engine core -- profiles, fill, decode, classify, exit codes (lane G)`

### T2 -- engine harness: dump, reference, adapter run, neutral extras, identity control

Files: `scripts/x4conformance.py`, `scripts/conformance-extra-cases.json` (new),
`tools/x4validate/tests/conftest.py` (append one session fixture), `tools/x4validate/tests/test_x4conformance_harness.py` (new).

Failing tests first:

```python
"""x4conformance harness: the dump, the reference verdict, the neutral extras, and the identity
control that proves the engine itself agrees with the guards (#22: check the checker first)."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("x4conformance", REPO / "scripts" / "x4conformance.py")
xc = importlib.util.module_from_spec(spec); spec.loader.exec_module(xc)

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")),
                                reason="needs Git Bash and jq -- conformance harness NOT checked here")


def test_the_dump_is_big_enough_and_every_row_is_classified(conformance_dump):
    rows, _ = conformance_dump
    assert len(rows) >= 100
    kinds = [xc.classify(r) for r in rows]
    assert set(kinds) <= set(xc.KINDS) | {"no_native_analogue"}
    assert sum(k != "no_native_analogue" for k in kinds) >= 80


def test_the_dump_sandbox_is_under_the_toolkit_never_tmp(conformance_dump):
    _, sbx = conformance_dump
    assert (REPO / ".test-sandbox") in sbx.parents


def test_neutral_extras_add_powershell_cases_and_their_reference_controls_hold(conformance_dump):
    rows, _ = conformance_dump
    extras = xc.extra_rows(REPO, rows)
    assert sum(xc.classify(r) == "shell-powershell" for r in extras) >= 3
    for r in extras:                       # the reference control: the guard still says what the case expects
        assert xc.reference_verdict(r, REPO) == r["expect"], r["id"]


def test_identity_control_claude_profile_agrees_on_every_row(conformance_dump):
    rows, _ = conformance_dump
    rows = rows + xc.extra_rows(REPO, rows)
    prof = xc.load_profile("claude", REPO)
    res = xc.replay(rows, prof, None, REPO, workers=4)
    bad = [r for r in res if r["reference"] != r["adapter"]]
    assert not bad, bad[:10]               # PER ITEM


def test_cleanup_removes_only_the_recorded_sandbox(tmp_path):
    base = tmp_path / "base"; keep = tmp_path / "keep"
    (base / "hooks.abc").mkdir(parents=True); keep.mkdir()
    xc.remove_sandbox(base / "hooks.abc", base)
    assert not (base / "hooks.abc").exists() and keep.exists()
    with pytest.raises(ValueError):
        xc.remove_sandbox(keep, base)      # TWIN: outside the base it refuses, deletes nothing
    assert keep.exists()
```

conftest.py addition (session-scoped, lazy -- only tests that request it pay for the dump):

```python
@pytest.fixture(scope="session")
def conformance_dump():
    """ONE test-hooks.sh dump per session, shared by the Codex and toy conformance tests. The base is
    <repo>/.test-sandbox (the harness's own default, gitignored), never tmp_path: test-hooks.sh refuses
    a sandbox under /tmp, which is where pytest puts tmp_path on Linux."""
    import importlib.util
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("x4conformance", repo / "scripts" / "x4conformance.py")
    xc = importlib.util.module_from_spec(spec); spec.loader.exec_module(xc)
    rows, sbx = xc.dump_cases(repo)
    yield rows, sbx
    xc.remove_sandbox(sbx, repo / ".test-sandbox")
```

RED: `uv run python -m pytest -q tests/test_x4conformance_harness.py` -> `AttributeError: dump_cases` etc.

Implementation: move `dumped`, `claude_hook`, `_hook_decision`, `_env` logic out of test_codex_conformance.py
into the engine (reference_verdict = the hook on the Claude payload, re-run with `X4_GUARD_CHECK=1` to
detect inert -- exactly the existing logic). `dump_cases` runs test-hooks.sh with `X4_DECIDE_DUMP`
and `X4_TEST_SANDBOX=<base>/conf-<pid>` (forward slashes, as the existing test does), refuses (rc 2 /
RuntimeError) on a non-zero harness exit or < 100 rows, reads the kept sandbox from `<dump>.sandbox`.
`remove_sandbox(path, base)` refuses unless `base` is a parent, then `shutil.rmtree(path)` and
`rmdir` of the empty `conf-<pid>` dir. Extra cases JSON: tokens `{TK}` `{TKP}` `{TKMSYS}` (same
meanings as conformance_extra.yaml), `hook`, Claude-shaped `payload`, `cwd`, `files`, `expect`;
`extra_rows` fills them from the first dump row's `env["X4_TOOLKIT"]` and env. Seed cases (the
`expect` values are verified by T0-style one-off runs BEFORE they are written in, never assumed):
PowerShell `Set-Content` into reference (deny), `Remove-Item -Recurse` in reference (deny),
`Get-ChildItem dev` (allow), a PowerShell relative `Set-Content libraries/w.xml` with cwd `{TK}/reference` (deny),
an Edit of `{TK}/reference/my file.xml` (deny, a space), a Bash `rm -f {TKMSYS}/reference/libraries/wares.xml` (deny, drive dialect).

GREEN: same command. Expected: 5 passed. Wall clock recorded in the lane report.
Commit: `x4conformance: dump, reference verdict, neutral PowerShell/space/drive extras, identity control (lane G)`

### T3 -- `x4guard conformance` subcommand

Files: `agent/guards/claude-hooks/x4guard.py` (regions: module docstring lines 4-9 -- add one usage
line and the exit-code note; `main()` lines 281-297 -- add the subparser entry for `--help` and an
early dispatch; new functions `_g_engine_path()` and `_g_conformance(argv)` placed directly above `main`),
regenerated `.claude/hooks/x4guard.py` and `.codex/hooks/x4guard.py`,
`tools/x4validate/tests/test_x4guard_conformance_cli.py` (new).

Failing tests first:

```python
"""`x4guard conformance` -- the CLI wrapper's exit codes; every refusal has a passing twin."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"
TOY = REPO / "tools" / "x4validate" / "tests" / "fixtures" / "toy_agent"


def run(*args, env=None, cwd=None):
    return subprocess.run([sys.executable, str(X4GUARD), *args], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=1800)


def test_help_lists_conformance():
    r = run("--help")
    assert r.returncode == 0 and "conformance" in r.stdout


def test_conformance_help_is_the_engines():
    r = run("conformance", "--help")
    assert r.returncode == 0 and "--profile" in r.stdout and "--min-cases" in r.stdout


def test_an_empty_case_file_refuses_with_3(tmp_path):
    (tmp_path / "c.jsonl").write_text("", encoding="utf-8")
    r = run("conformance", "--profile", "claude", "--cases", str(tmp_path / "c.jsonl"), "--min-cases", "1")
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "0 replayed" in r.stdout


def test_a_missing_profile_is_2(tmp_path):
    r = run("conformance", "--profile", str(tmp_path / "nope.json"))
    assert r.returncode == 2


def test_no_adapter_command_anywhere_is_2(tmp_path):
    p = json.loads((REPO / "scripts" / "conformance-profiles" / "claude.json").read_text(encoding="utf-8"))
    del p["command"]
    f = tmp_path / "p.json"; f.write_text(json.dumps(p), encoding="utf-8")
    r = run("conformance", "--profile", str(f))
    assert r.returncode == 2 and "command" in (r.stdout + r.stderr)


def test_a_copy_that_cannot_find_its_toolkit_is_2(tmp_path):
    lone = tmp_path / "x4guard.py"; shutil.copy(X4GUARD, lone)
    env = {k: v for k, v in __import__("os").environ.items() if k != "X4_TOOLKIT"}
    r = subprocess.run([sys.executable, str(lone), "conformance", "--profile", "claude"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "x4conformance.py" in r.stderr


def test_TWIN_the_same_copy_with_X4_TOOLKIT_finds_the_engine(tmp_path):
    lone = tmp_path / "x4guard.py"; shutil.copy(X4GUARD, lone)
    env = dict(__import__("os").environ, X4_TOOLKIT=str(REPO))
    r = subprocess.run([sys.executable, str(lone), "conformance", "--help"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "--profile" in r.stdout


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs Git Bash and jq")
def test_below_the_floor_is_3_and_the_twin_with_the_floor_lowered_is_0(conformance_dump, tmp_path):
    rows, _ = conformance_dump
    few = [r for r in rows if r["payload"].get("tool_name") == "Bash"][:3]
    f = tmp_path / "few.jsonl"; f.write_text("".join(json.dumps(r) + "\n" for r in few), encoding="utf-8")
    assert run("conformance", "--profile", "claude", "--cases", str(f), "--no-extras").returncode == 3
    assert run("conformance", "--profile", "claude", "--cases", str(f), "--no-extras",
               "--min-cases", "3").returncode == 0


def test_the_double_dash_adapter_argv_overrides_the_profile_and_is_stripped(tmp_path):
    (tmp_path / "c.jsonl").write_text("", encoding="utf-8")
    r = run("check", "--kind", "write", "--path", "x")  # sanity: check still works unchanged
    assert r.returncode == 0 and json.loads(r.stdout)["v"] == 1
    r = run("conformance", "--profile", "claude", "--cases", str(tmp_path / "c.jsonl"),
            "--min-cases", "1", "--", sys.executable, "-c", "pass")
    assert r.returncode == 3 and "adapter: " in r.stdout and " -- " not in r.stdout.split("adapter: ")[1].splitlines()[0]
```

RED: `uv run python -m pytest -q tests/test_x4guard_conformance_cli.py` -> `invalid choice: 'conformance'` (rc 2) in each.

Implementation (x4guard.py; nothing in `check`'s path changes):
```python
def _g_engine_path() -> Path | None:
    """scripts/x4conformance.py of THIS copy's toolkit (repo .claude/hooks or the agent/ source),
    else of $X4_TOOLKIT (a deployed copy)."""
    cands = [HERE.parents[1] / "scripts", HERE.parents[2] / "scripts"] if len(HERE.parents) > 2 else []
    if os.environ.get("X4_TOOLKIT"):
        cands.append(Path(os.environ["X4_TOOLKIT"]) / "scripts")
    return next((d / "x4conformance.py" for d in cands if (d / "x4conformance.py").is_file()), None)


def _g_conformance(argv: list) -> int:
    path = _g_engine_path()
    if path is None:
        sys.stderr.write("x4guard conformance: scripts/x4conformance.py not found next to this copy "
                         "or under $X4_TOOLKIT; run the toolkit's own .claude/hooks/x4guard.py\n")
        return 2
    import importlib.util
    spec = importlib.util.spec_from_file_location("x4conformance", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main(argv)
```
In `main`: `argv = sys.argv[1:] if argv is None else argv`; `if argv[:1] == ["conformance"]: return _g_conformance(argv[1:])`
BEFORE `ap.parse_args` (argparse REMAINDER does not capture leading options); register
`sub.add_parser("conformance", help="replay the guard corpus through an adapter (see ADAPTING.md)")`
so `--help` lists it. Engine `main` strips one leading `--` from the adapter argv. Then
`cd tools/x4validate && uv run python scripts/gen-agent-trees.py`.

GREEN: `uv run python -m pytest -q tests/test_x4guard_conformance_cli.py tests/test_x4guard_check.py tests/test_gen_agent_trees.py`
Expected: all pass (the existing check suite unchanged = `check` untouched; trees fresh).
Commit: `x4guard: conformance subcommand dispatching to scripts/x4conformance.py (lane G)`

### T4 -- the Codex conformance test and codex_testlib use the engine (one mechanism)

Files: `tools/x4validate/tests/test_codex_conformance.py`, `tools/x4validate/tests/codex_testlib.py`.

No new failing test: this is a refactor whose oracle is M-G2's per-item baseline. Changes:
- `test_codex_conformance.py`: delete `dumped`, `classify`, `_hook_decision`, `claude_hook`, `codex_chain`,
  `_env`, `_patch`, `native_for`, `judge_row`; the three dump tests use `conformance_dump` and
  `xc.replay(rows, xc.load_profile("codex", REPO), None, REPO, workers=6)` (6 = unchanged from today);
  `test_buckets_sum` asserts the engine's buckets. `test_codex_specific_extras` keeps its YAML and its
  `native()` payloads but calls `xc.reference_verdict` (Claude side) and `xc.adapter_verdict` (Codex side).
- `codex_testlib.parse_output`: `d, text = xc.decode(CODEX_PROFILE["output"], stdout, 0)`;
  `assert d != "unreadable", text`; return `(d, text)`. Its callers keep their names and assertions.

Verify: rerun M-G2's exact command with `--junitxml=<scratch>/g-after.xml`; a 20-line python diff of the two
junit files PER TEST ID. Expected: identical outcome for every id present in both; ids only in one run
listed by name (the deleted helpers are not tests, so predicted: none). In particular every mutant in
`test_codex_adapter_mutants.py` is still killed (a mutant that renders `ask` must still fail via
`parse_output` -> the decode is `unreadable` -> AssertionError).
Commit: `tests: Codex conformance and codex_testlib.parse_output run on the x4conformance engine (lane G)`

### T5 -- `ADAPTING.md` + its doc tests + installer copy lists + the core.md pointer

Files: `ADAPTING.md` (new), `tools/x4validate/tests/test_adapting_doc.py` (new), `install.sh`
(X4_COPY_ITEMS line 513: add `ADAPTING.md`), `install.ps1` ($X4CopyItems line 319-321: add `'ADAPTING.md'`),
`agent/instructions/core.md` (one line), regenerated `CLAUDE.md` + `AGENTS.md`.

Failing tests first:

```python
"""ADAPTING.md is executable documentation: every x4guard command it shows parses, every repo path
it cites exists, no number it states can drift from the code, and installers ship it."""
from __future__ import annotations

import importlib.util
import os
import re
import shlex
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "ADAPTING.md"
TEXT = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
spec = importlib.util.spec_from_file_location("x4guard_src", REPO / "agent/guards/claude-hooks/x4guard.py")


def test_it_exists_and_names_the_product():
    assert "X4 AI Assistant Toolkit" in TEXT


@pytest.mark.parametrize("heading", [
    "Self-assessment", "fail open or closed", "The guard contract", "Worked example: Claude Code",
    "Worked example: Codex", "Where your adapter goes", "Required proof", "Rules", "Upstream submission"])
def test_every_spec_11_section_is_present(heading):
    assert heading.lower() in TEXT.lower()


def _x4guard_lines():
    return [ln.strip().split("x4guard.py", 1)[1] for ln in TEXT.splitlines()
            if "x4guard.py check" in ln and not ln.strip().startswith(("#", ">"))]


def test_every_check_command_it_shows_parses_with_the_real_cli(monkeypatch):
    lines = _x4guard_lines()
    assert len(lines) >= 3                                   # shell, write, delete at least
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    monkeypatch.setattr(x4g, "verdict_for", lambda *a, **k: {"v": 1})
    for ln in lines:
        argv = [t for t in shlex.split(ln.replace("\\", "/")) if t]
        argv = [("x" if "<" in t else t) for t in argv]      # placeholders like <cmd>
        assert x4g.main(argv) == 0, ln


def test_TWIN_a_wrong_flag_would_have_failed(monkeypatch):
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    with pytest.raises(SystemExit) as e:
        x4g.main(["check", "--agent", "toy", "--kind", "write", "--path", "x"])   # the spec's --agent: not real
    assert e.value.code == 2


def test_every_repo_path_it_cites_exists():
    cited = set(re.findall(r"`((?:agent|scripts|tools|docs)/[^`\s*]+)`", TEXT))
    assert cited
    missing = [p for p in sorted(cited) if not (REPO / p.rstrip("/")).exists() and "<" not in p]
    assert not missing, missing


def test_the_timeout_default_is_never_restated_wrongly(monkeypatch):
    monkeypatch.delenv("X4_GUARD_TIMEOUT_S", raising=False)
    x4g = importlib.util.module_from_spec(spec); spec.loader.exec_module(x4g)
    default = x4g._timeout_setting()[0]
    for m in re.finditer(r"X4_GUARD_TIMEOUT_S[^.\n]{0,60}?default\D{0,10}(\d+(?:\.\d+)?)", TEXT):
        assert float(m.group(1)) == default, m.group(0)


def test_capability_report_fields_match_the_upstream_template():
    def fields(section):
        body = TEXT.split(section, 1)[1].split("\n## ", 1)[0]
        return re.findall(r"^\s*([A-Z][A-Z /-]{2,}):", body, re.M)
    assert fields("## 1.") and fields("## 1.") == fields("## 7.")


@pytest.mark.parametrize("installer,pattern", [("install.sh", r"X4_COPY_ITEMS=\"[^\"]*\bADAPTING\.md\b"),
                                               ("install.ps1", r"\$X4CopyItems\s*=\s*@\([^)]*'ADAPTING\.md'")])
def test_installers_ship_it(installer, pattern):
    assert re.search(pattern, (REPO / installer).read_text(encoding="utf-8"), re.S)


def test_the_instruction_core_points_an_unsupported_agent_at_it():
    assert "ADAPTING.md" in (REPO / "AGENTS.md").read_text(encoding="utf-8")
```

RED: `uv run python -m pytest -q tests/test_adapting_doc.py` -> every test fails (no file / no line).

Implementation -- `ADAPTING.md` outline (written TO the agent: "you are an agent this toolkit does not
support yet"), every factual claim tiered:
0. **Before you start** -- you need a guard tree: `.claude/hooks/` or `.codex/hooks/` of an install made
   with `--agent all` (the default) or the release zip / a clone; an `--agent generic` install ships none
   (READ install.sh). `x4guard conformance` additionally needs the toolkit's `scripts/`, bash and jq.
1. **Self-assessment** -- the fixed capability report (UPPER-CASE fields, also used by §7): AGENT, VERSION,
   OS, HOOK EVENTS, PAYLOAD CAPTURE (fixtures captured from a live run, never hand-written), TOOLS THAT
   WRITE (and which are hooked), SHELL ROUTING (which shell executes the shell tool -- Codex's "Bash" is
   PowerShell on Windows), VERDICT SHAPES HONOURED (deny / ask / context, each MEASURED), FAIL MODE (the
   table below), HOOK APPROVAL (can a changed definition silently switch hooks off?), CONTEXT CAP,
   NATIVE POLICY LAYER, INSTRUCTION FILE + BYTE CAP, EVIDENCE (tier per row).
   **"Does your hook system fail open or closed?"** -- the spike's procedure, written as steps against a
   decoy file in a scratch dir: (a) deny control: a hook that emits your documented deny -> the write
   must NOT happen (if it happens, nothing else in this doc can protect you); (b) exit 2 + stderr;
   (c) a crash (uncaught exception / non-zero exit); (d) a timeout (sleep past the hook timeout);
   (e) garbage on stdout. Record blocked/ran per row. Any "ran" = your agent fails open on that path ->
   you need a fail-closed wrapper (§3 Codex: `codex-entry.sh/.ps1`).
2. **The guard contract** -- the real CLI (no `--agent`), stdout JSON fields, exit 0 per verdict / 2 usage,
   run it in the agent's cwd, `--shell` = the shell that will execute, delete = stricter of write and
   `rm -rf`, `inert: true` -> deny (or a question if your agent can ask; never an allow),
   `X4_GUARD_TIMEOUT_S` budget (default: read `x4guard.py`'s docstring -- not restated) with worst case
   budget + `KILL_WAIT_S` + `DRAIN_GRACE_S`; your own timeout above that and below the agent's hook timeout;
   treat non-zero / empty / unparseable / `v != 1` as an inert deny; `X4_GUARD=off`; `check` runs no
   backups (an adapter that wants them runs `backup-before-edit.sh` as the Codex adapter does);
   bound injected context to `X4_HOOK_MAX_CHARS` with the directive first.
   Rendering table: decision -> native shape, with the "only if MEASURED honoured" rule for ask.
3. **Worked examples** -- Claude Code (identity: the guards ARE Claude hooks; `agent/targets/claude/settings.json`;
   `scripts/conformance-profiles/claude.json` is the engine's identity control) and Codex
   (`agent/guards/adapters/codex.py`: the routing table, apply_patch split, `X4OK` wrapper protocol, frozen
   `agent/targets/codex/hooks.json.tmpl`; `scripts/conformance-profiles/codex.json`).
4. **Where your adapter goes** -- local first (anywhere, run conformance with `--profile`); upstream:
   `agent/guards/adapters/<agent>.py`, a generator target in `tools/x4validate/scripts/gen-agent-trees.py`
   (model: `CODEX_ADAPTERS` + `render_codex_hooks`), `agent/targets/<agent>/`, an installer item set
   `X4_AGENT_ITEMS_<agent>` in BOTH installers, `scripts/conformance-profiles/<agent>.json`, captured
   fixtures under `tools/x4validate/tests/fixtures/<agent>/<version>/`.
   **Writing a profile** -- the format v1 above, with the toy's profile as the minimal example.
5. **Required proof** -- (a) `python .claude/hooks/x4guard.py conformance --profile <yours> -- <adapter argv>`
   exits 0 (what 1/2/3 mean); (b) a live canary in the real agent against a decoy `reference/` (blocked,
   the model saw the reason) plus its control (the same write elsewhere succeeds); (c) `x4doctor` shows the
   layer live -- for an agent x4doctor does not know it reports no target: say so, it is a gap until a
   doctor probe is upstreamed; (d) the fail-mode table filled with MEASURED rows. Until all four:
   "partially supported, with these gaps: ...".
6. **Rules** -- never edit the corpus (`scripts/test-hooks.sh`, `scripts/conformance-extra-cases.json`), the
   guards or another profile to pass; adapters translate and decide nothing; never emit a shape your agent
   was not measured to honour; never claim protection without the §5 proof; report every gap (an
   `unsupported` kind is a gap, not a pass).
7. **Upstream submission** -- a copy-paste issue/PR body: the §1 capability report (same fields), the
   conformance summary line + buckets + gaps, the canary transcript, the fail-mode table, versions, files added.

`agent/instructions/core.md`: one line in the agent-neutral orientation: *"An agent this toolkit has no
adapter for: read `ADAPTING.md` before relying on any guard."* Then regenerate; check sizes printed
(AGENTS.md must stay <= 32,768 B; CLAUDE.md <= 40,000 chars; predicted +~110 B).

GREEN: `uv run python -m pytest -q tests/test_adapting_doc.py tests/test_gen_agent_trees.py tests/test_installers_agree.py`
Expected: all pass.
Commit: `ADAPTING.md: how an unsupported agent adapts, proves and upstreams an adapter (lane G)`

### T6 -- the toy agent: harness, cold-written adapter, CI conformance, mutants, canary

Files (all new) under `tools/x4validate/tests/fixtures/toy_agent/`: `TOY-AGENT.md`, `toy_agent.py`,
`payloads/{run_shell,edit_file,write_file}.json`, then (cold subagent) `toy_adapter.py`, `profile.json`;
`tools/x4validate/tests/test_toy_agent_conformance.py`; `docs/superpowers/measurements/2026-10-0X-adapting-cold-test.md`.

Steps:
1. Implementer writes `TOY-AGENT.md` -- the fictional agent's OWN docs, nothing about X4: payload shape
   `{"event":"before_tool","tool":"run_shell|edit_file|write_file","args":{...},"workdir":"..."}` on the
   hook's stdin; hook output `TOY-BLOCK <reason>` blocks and shows the reason, `TOY-NOTE <text>` adds
   context, anything else / empty allows; it has NO ask; a non-zero exit, a crash or a 10 s timeout
   **runs the call** (fails open -- deliberately like Codex). And `toy_agent.py`: runs a JSONL script of
   tool calls through a `--hook` command; `write_file` really writes (inside a given `--root` only),
   `run_shell`/`edit_file` only log. ~100 lines, stdlib.
2. **Cold subagent (sonnet; a fresh agent given ONLY `ADAPTING.md` + `TOY-AGENT.md` + the payload
   examples, no repo browsing beyond what ADAPTING.md tells it to run)** writes `toy_adapter.py` and
   `profile.json`, runs `x4guard conformance` until rc 0, and reports every place ADAPTING.md was unclear.
   Each gap -> fix ADAPTING.md (T5 tests stay green) -> one more fresh cold run if the adapter had to be
   hand-corrected. The committed adapter is the cold one, unedited. Record runs, gaps and fixes in the
   measurements doc.
3. Tests (written by the implementer after step 2; they test the committed artefacts):

```python
"""The toy agent (spec 7.10): an adapter written only from ADAPTING.md passes `x4guard conformance`,
and the conformance it passes can fail: each mutant of the adapter turns it red on a non-empty case
set whose unmutated control is green."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"
TOY = REPO / "tools" / "x4validate" / "tests" / "fixtures" / "toy_agent"

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")),
                                reason="needs Git Bash and jq -- toy conformance NOT checked here")


def conformance(cases: Path, adapter: Path, *extra):
    return subprocess.run([sys.executable, str(X4GUARD), "conformance", "--profile", str(TOY / "profile.json"),
                           "--cases", str(cases), "--workers", "4", *extra, "--", sys.executable, str(adapter)],
                          capture_output=True, text=True, timeout=1800)


def _write(rows, path):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_the_toy_adapter_passes_full_conformance(conformance_dump, tmp_path):
    rows, _ = conformance_dump
    r = conformance(_write(rows, tmp_path / "all.jsonl"), TOY / "toy_adapter.py")
    assert r.returncode == 0, r.stdout[-4000:]
    assert "GAP" not in r.stdout                       # the toy maps all four kinds


MUTANTS = {   # name -> (exact source text, replacement, row selector). Filled in after step 2 from
              # the COLD adapter's real source; each `old` must occur exactly once.
    "always_allow": ("<the line that prints TOY-BLOCK>", "<print nothing>", lambda r: r["got"] == "deny"),
    "ask_as_plain_deny": ("NEEDS YOUR APPROVAL: ", "", lambda r: r["got"] == "ask"),
    "powershell_as_bash": ("<the interpreter routing>", "<always bash>", lambda r: r.get("kind") == "shell-powershell"),
    "ignores_workdir": ("<the chdir/cwd use>", "<no-op>", lambda r: r.get("relative")),
    "crash_exits_nonzero": ("<the catch-all>", "<re-raise>", lambda r: True),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_adapter_mutant_turns_conformance_red(name, conformance_dump, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("x4conformance", REPO / "scripts" / "x4conformance.py")
    xc = importlib.util.module_from_spec(spec); spec.loader.exec_module(xc)
    old, new, pick = MUTANTS[name]
    rows, _ = conformance_dump
    pool = rows + xc.extra_rows(REPO, rows)
    chosen = [r for r in pool if pick(r)][:12]
    assert chosen, f"{name}: no case can express this defect -- add one, never drop the mutant"
    cases = _write(chosen, tmp_path / "c.jsonl")
    src = (TOY / "toy_adapter.py").read_text(encoding="utf-8")
    assert src.count(old) == 1, f"{name}: anchor matches {src.count(old)} times"
    mutant = tmp_path / "toy_adapter.py"; mutant.write_text(src.replace(old, new), encoding="utf-8")
    floor = ("--min-cases", str(len(chosen)))
    control = conformance(cases, TOY / "toy_adapter.py", *floor)
    assert control.returncode == 0, control.stdout[-3000:]          # control first
    red = conformance(cases, mutant, *floor)
    assert red.returncode == 1, (name, red.returncode, red.stdout[-3000:])


def test_live_canary_through_the_toy_agent_blocks_and_its_control_writes(conformance_dump, tmp_path):
    """ADAPTING.md 5(b): the agent itself, not the adapter alone, refuses the decoy write."""
    rows, _ = conformance_dump
    env_row = next(r for r in rows if r["env"].get("X4_TOOLKIT"))
    tk = Path(env_row["env"]["X4_TOOLKIT"])
    script = tmp_path / "calls.jsonl"
    decoy, ctrl = tk / "reference" / "canary-decoy.xml", tk / "dev" / "mymod" / "canary-ok.xml"
    _write([{"tool": "write_file", "args": {"target": str(decoy), "text": "x"}, "workdir": str(tk)},
            {"tool": "write_file", "args": {"target": str(ctrl), "text": "x"}, "workdir": str(tk)}], script)
    env = dict(__import__("os").environ, **env_row["env"])
    r = subprocess.run([sys.executable, str(TOY / "toy_agent.py"), "--root", str(tk), "--script", str(script),
                        "--hook", f'"{sys.executable}" "{TOY / "toy_adapter.py"}"'],
                       capture_output=True, text=True, env=env, timeout=600)
    try:
        assert not decoy.exists() and "TOY-BLOCK" in r.stdout
        assert ctrl.exists()                                         # the control: writes do happen
    finally:
        ctrl.unlink(missing_ok=True)


def test_the_fail_mode_measurement_reproduces_the_toys_fail_open(tmp_path):
    """ADAPTING.md 1: the procedure finds what TOY-AGENT.md says -- exit 2 does NOT block the toy."""
    hook = tmp_path / "exit2.py"; hook.write_text("import sys; sys.exit(2)\n", encoding="utf-8")
    deny = tmp_path / "deny.py"; deny.write_text("print('TOY-BLOCK control')\n", encoding="utf-8")
    target = tmp_path / "decoy.txt"
    script = _write([{"tool": "write_file", "args": {"target": str(target), "text": "x"}, "workdir": str(tmp_path)}],
                    tmp_path / "s.jsonl")
    def go(h):
        target.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(TOY / "toy_agent.py"), "--root", str(tmp_path), "--script", str(script),
                        "--hook", f'"{sys.executable}" "{h}"'], capture_output=True, timeout=60)
        return target.exists()
    assert go(deny) is False          # deny control blocks
    assert go(hook) is True           # exit 2 runs the call: fails open, as documented
```

The `MUTANTS` anchors are placeholders until the cold adapter exists; the implementer fills each with the
adapter's real text (exactly-once rule enforced by the test). Row selectors `kind`/`relative` are fields
`extra_rows`/the engine add to rows (`kind` = classify; `relative` = the extra or dump row whose path/command
is relative); if T0/M-G3 shows no relative-cwd row exists in the dump, add one neutral extra case (T2's
PowerShell relative case already qualifies).

RED: before the adapter exists the module fails (missing `toy_adapter.py`); before each mutant anchor is
filled, the anchor assertion fails. GREEN:
`uv run python -m pytest -q tests/test_toy_agent_conformance.py` -> Expected: all pass; record wall clock
(predicted: one dump shared + one full toy replay ~2-4 min on Windows + 5 x 2 subset replays).
Commits: `tests: toy agent harness and docs (lane G)`; `tests: toy adapter written cold from ADAPTING.md + CI conformance and mutants (lane G)`.

### T7 -- the once-per-release cold-subagent exercise

Files: `docs/ADAPTING-COLD-TEST.md` (new), `tools/x4validate/tests/test_adapting_doc.py` (two tests appended),
`docs/REVIEW-SCOPE.md` (one bullet linking it under Track 1, "release exercises").

Tests first:
```python
COLD = REPO / "docs" / "ADAPTING-COLD-TEST.md"

def test_the_cold_exercise_gives_the_subagent_only_adapting_and_the_toy_docs():
    t = COLD.read_text(encoding="utf-8")
    prompt = t.split("<!-- PROMPT -->", 2)[1]
    assert "ADAPTING.md" in prompt and "TOY-AGENT.md" in prompt
    for leak in ("codex.py", "x4conformance.py", "toy_adapter.py", "profile.json\"", "MUTANTS"):
        assert leak not in prompt, leak

def test_the_cold_exercise_has_a_pass_criterion_and_a_record_location():
    t = COLD.read_text(encoding="utf-8")
    assert "exits 0" in t and "docs/superpowers/measurements/" in t
```
Content: when (once per release, before the release review closes), who (a fresh subagent, sonnet,
no conversation context), the exact prompt between `<!-- PROMPT -->` markers, what it is given (a
scratch copy containing ADAPTING.md, TOY-AGENT.md, toy_agent.py, payloads -- NOT the committed adapter),
the pass criterion (its adapter's `x4guard conformance` exits 0 with no GAP, unedited by the dispatcher),
what a failure means (ADAPTING.md is wrong or stale -- fix the doc, not the adapter), the record
(`docs/superpowers/measurements/<date>-adapting-cold-test.md`: gaps found, rc, buckets).
GREEN: `uv run python -m pytest -q tests/test_adapting_doc.py`. Commit: `docs: once-per-release cold ADAPTING exercise (lane G)`

### T8 -- the universal setup prompt

Files: `SETUP_PROMPT.txt` (rewritten, same filename so no installer list changes),
`README.md` (the "paste the setup prompt" paragraph around lines 361-364: agent-neutral wording + one
sentence linking ADAPTING.md), `tools/x4validate/tests/test_adapting_doc.py` (tests appended), `CHANGELOG.md` (Unreleased).

Tests first:
```python
PROMPT = (REPO / "SETUP_PROMPT.txt").read_text(encoding="utf-8")

def test_setup_prompt_is_agent_neutral_and_routes_unknown_agents():
    assert "X4 AI Assistant Toolkit" in PROMPT and "ADAPTING.md" in PROMPT
    assert "x4doctor" in PROMPT and "--help" in PROMPT          # supported agents come from the installer, not a list here
    assert "Claude runs" not in PROMPT and "Claude Code Modding Toolkit" not in PROMPT

def test_setup_prompt_never_tells_the_agent_to_trust_or_approve_hooks_itself():
    low = PROMPT.lower()
    assert "never approve" in low or "do not approve" in low
```
Prompt text (one paragraph, plain English, any agent): identify which agent you are; run
`bash install.sh --help` (or `install.ps1 -Help`) to see whether this toolkit has an adapter for you; if
so, install for your agent and follow the steps it prints (for Codex: the user trusts the project and
reviews hooks -- never do it yourself); if not, read ADAPTING.md, tell me your agent is not supported yet,
and that only the OS-level protection of `reference/` applies until an adapter passes conformance; then
`bash setup.sh`, install missing prerequisites (jq, uv/Python 3.13; Java optional), run
`python scripts/x4doctor.py` and report each layer's state honestly, the reference unpack with XRCatTool,
the optional Nexus key; explain in plain English and ask questions.
GREEN: `uv run python -m pytest -q tests/test_adapting_doc.py`.
Commit: `SETUP_PROMPT.txt: one setup prompt for any agent; README and CHANGELOG (lane G)`

## Files touched (union)

- NEW: `ADAPTING.md`, `docs/ADAPTING-COLD-TEST.md`, `scripts/x4conformance.py`,
  `scripts/conformance-profiles/claude.json`, `scripts/conformance-profiles/codex.json`,
  `scripts/conformance-extra-cases.json`, `tools/x4validate/tests/test_x4conformance_engine.py`,
  `tools/x4validate/tests/test_x4conformance_harness.py`, `tools/x4validate/tests/test_x4guard_conformance_cli.py`,
  `tools/x4validate/tests/test_adapting_doc.py`, `tools/x4validate/tests/test_toy_agent_conformance.py`,
  `tools/x4validate/tests/fixtures/toy_agent/{TOY-AGENT.md,toy_agent.py,toy_adapter.py,profile.json,payloads/*.json}`,
  `docs/superpowers/measurements/2026-10-0X-adapting-cold-test.md`
- MODIFIED: `agent/guards/claude-hooks/x4guard.py` (docstring lines 4-9; new `_g_engine_path`/`_g_conformance`
  above `main`; `main` lines 281-297), `.claude/hooks/x4guard.py` + `.codex/hooks/x4guard.py` (generated),
  `agent/instructions/core.md` (one line) + `CLAUDE.md` + `AGENTS.md` (generated),
  `tools/x4validate/tests/conftest.py` (append fixture), `tools/x4validate/tests/test_codex_conformance.py`,
  `tools/x4validate/tests/codex_testlib.py` (`parse_output` only), `install.sh` (line 513 only),
  `install.ps1` (lines 319-321 only), `SETUP_PROMPT.txt`, `README.md` (setup-prompt paragraph ~361-364),
  `CHANGELOG.md` (Unreleased), `docs/REVIEW-SCOPE.md` (one bullet)

## Verify-hook-tests anchors touched

**None.** `scripts/verify-hook-tests.py` anchors only `hook_facts.py`, `test_hook_facts.py`,
`ps_translate.ps1` (READ, line 47); lane G edits none of them.

## Cross-lane dependencies

- **J** edits `x4guard.py`'s `_timeout_setting` (line 47) and its docstring line 20. G's hunks are lines
  4-9 and 281-297 plus new functions above `main` -- non-overlapping; the generated `.claude/hooks/x4guard.py`
  / `.codex/hooks/x4guard.py` must be REGENERATED after the merge, not hand-merged. ADAPTING.md never
  restates the timeout (a test derives it), so J's new default needs no doc change.
- **J** also edits `README.md` (residual disclosures) and `codex.py`. G touches a different README paragraph
  and not `codex.py`. If J changes the Codex adapter's rendered shapes, `scripts/conformance-profiles/codex.json`
  must follow -- T4's per-item comparison catches it at the combined gate.
- **L** (OpenCode) and **H** edit `install.sh`/`install.ps1`; G changes only the common copy-item lines
  (one token each). L adds a generator target -- ADAPTING.md §4 describes the CODEX pattern; L may add a
  second example line after merge (not required).
- **L** may want an `scripts/conformance-profiles/opencode.json`: the engine is ready for it; without a
  live OpenCode it can only be a profile over hand-derived payloads, which ADAPTING.md's rules forbid
  claiming as proof -- L labels it "not measured" or skips it.
- **I** moves `x4-paths.env`; the engine passes the dump rows' env through untouched, so no change expected.
  I's replay harness is unrelated (lane F's).
- **K** renames the product; G already writes "X4 AI Assistant Toolkit" in new docs and SETUP_PROMPT.txt.
  K must not regress `test_setup_prompt_is_agent_neutral...`.
- `CHANGELOG.md` Unreleased: every lane appends -- expect a trivial merge.

## Questions for the user

1. **Where does the once-per-release cold exercise get REMEMBERED?** The repo has no release checklist file;
   the procedure lives in your user-level `releasing` / `release-review` skills. Recommendation: the
   in-repo doc `docs/ADAPTING-COLD-TEST.md` + a bullet in `docs/REVIEW-SCOPE.md` (this plan), AND you
   approve one line added to your user-level `releasing` skill pointing at it -- otherwise the step exists
   only where a release session might not look.
2. **Should `x4guard conformance` replay the 6 neutral extra cases by default for EVERY adapter** (PowerShell,
   spaces, drive dialect), with each case's reference `expect` acting as a control that fails the run (rc 2)
   if the guards' policy changes? Recommendation: yes -- without them the dump has 0 PowerShell rows
   (MEASURED, grep) and a shell-routing bug is invisible; the cost is that a deliberate guard-policy change
   must update `scripts/conformance-extra-cases.json` in the same commit (a test failure says exactly that).

## Confidence

| Task | Conf. | What raises it (for < 90%) |
|---|---|---|
| T0 | 95% | -- |
| T1 | 90% | -- |
| T2 | 80% | M-G3 (dump wall clock, row shape, sandbox file) and M-G1 (the /tmp premise). The `expect` values of the extras are measured one by one before they are written. |
| T3 | 90% | -- (dispatch before argparse avoids the REMAINDER quirk; the copy-location twin pins the lookup) |
| T4 | 75% | M-G2 baseline vs after, per test id. Main risk: `parse_output`'s exact edge semantics (inert-before-ask order, empty-body handling) -- the engine decode tests in T1 encode both before T4 starts. |
| T5 | 85% | The `fields("## 1.") == fields("## 7.")` and command-parse tests are only as good as the doc's structure; the cold run in T6 is the real measurement of ADAPTING.md's sufficiency. |
| T6 | 70% | M-G4 (x4guard from the real tree agrees with the hooks under a dump row's env). The cold subagent may need >1 round; each mutant needs a case that can express it -- T2's extras guarantee PowerShell and relative-cwd ones. CI wall clock is unmeasured until the first run. |
| T7 | 95% | -- |
| T8 | 90% | -- |

## Gate plan (focused only; the orchestrator runs ONE full gate per wave)

One process at a time, from `tools/x4validate`:
1. `uv run python -m pytest -q tests/test_x4conformance_engine.py` (seconds)
2. `uv run python -m pytest -q tests/test_x4conformance_harness.py tests/test_x4guard_conformance_cli.py` (one dump)
3. `uv run python -m pytest -q tests/test_x4guard_check.py tests/test_gen_agent_trees.py tests/test_installers_agree.py tests/test_adapting_doc.py`
4. `uv run python -m pytest -q tests/test_toy_agent_conformance.py` (one dump + replays)
5. M-G2 rerun for T4 (Codex conformance + adapter + mutants + wrapper), junit per-id diff -- in the background.
6. `uv run python scripts/gen-agent-trees.py --check` -> Expected: rc 0.

For the orchestrator's combined gate: the full pytest gains ~5 new files; predicted 0 new skips on the
Windows leg (bash, jq present). On ubuntu, if M-G1 confirms the /tmp failure, the move to a
`.test-sandbox` base changes that leg's Codex conformance from error to run -- re-read its result rather
than assuming green. CI skip ceilings (`X4_MAX_SKIPS`) need no change unless the per-job `-rs` output shows new skips.
