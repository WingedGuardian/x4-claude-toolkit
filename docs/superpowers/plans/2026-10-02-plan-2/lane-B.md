# Universal Agent Support — Plan 2, Lane B: the Codex adapter and cross-agent conformance

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to carry out this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking. Write each test first and watch it fail before writing the implementation.

**Goal:** Codex gets spec D13's layers from the neutral source:
- a **generated Codex target tree**: `.codex/hooks/` holding the guards, the adapter and fail-closed entry points; `.codex/rules/x4.rules`; `.agents/skills/`; and a frozen `hooks.json` template;
- a **Codex hook adapter** that only translates (D10). It routes "Bash"-labelled PowerShell to `--shell powershell`, splits `apply_patch` with one shared parser, and emits only the JSON shape Codex honours;
- **detection and disclosure** of Codex's silent hook de-trust;
- **one conformance suite** that feeds the same cases to the Claude hooks and to the Codex adapter and requires equal verdicts, with mutants that turn it red.

**Spec:** `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` §§4, 5.2–5.5, 5.8, 7.2–7.6, 7.8, 9 (M10, M11, M13). **Evidence:** `docs/superpowers/measurements/2026-09-30-codex-spike.md` and the measurements in **Context** below, which this planner took on 2026-10-02.

**Repo:** `$X4_TOOLKIT` (`$X4_TOOLKIT`), with `PKG = tools/x4validate`. Run focused tests with `cd tools/x4validate && uv run --frozen python -m pytest -q -rs <files>`.

---

## Context — what this planner measured or read (2026-10-02)

| # | Fact | Tier |
|---|---|---|
| C1 | `codex --version` → **`codex-cli 0.160.0`**. The spike ran 0.159.2. `codex doctor --json` reports `codexVersion 0.160.0`, which is current (`latest version = 0.160.0`). | MEASURED |
| C2 | **The trust hash is reproducible offline.** Codex 0.160.0 source (`codex-rs/hooks/src/engine/discovery.rs::hook_hash`, `config/src/fingerprint.rs::version_for_toml`) computes `"sha256:" + sha256(canonical-JSON({"event_name": <snake_case event>, "matcher"?: <matcher>, "hooks": [<normalized handler>]}))`. The handler is `{"type":"command","command":<resolved; on Windows commandWindows wins>,"timeout":<given or 600>,"async":<bool, default false>,"statusMessage"?:…,"additionalContextLimit"?:… (omitted when 2500 or unset)}`. Keys are sorted recursively, separators are compact, and `None` is omitted. A Python re-implementation reproduced **4 of 4** `trusted_hash` values stored in `~/.codex/config.toml.bak-20260930-spike` against the spike's own `hooks.json` files. (Script: `<scratchpad>/laneB/hashprobe3.py`. A brute-force search over 589,479 naive serialisations matched 0 of 4, which serves as the control that the match is not trivial.) | MEASURED (match) / READ (scheme) |
| C3 | Hook state lives in `[hooks.state.'<abs hooks.json path>:<event>:<group i>:<handler j>']`, with **both `trusted_hash` and `enabled`**. `enabled = false` silently switches a hook off. Status is one of `Trusted` / `Modified` (the hash differs) / `Untrusted` (no entry). The live `~/.codex/config.toml` now has an **empty `[hooks.state]`**: the spike approvals are gone. | READ (source) / MEASURED (file) |
| C4 | **The PreToolUse output schema is `additionalProperties:false`** at both levels. The allowed top-level keys are `continue, decision, hookSpecificOutput, reason, stopReason, suppressOutput, systemMessage`. Inside `hookSpecificOutput` they are `additionalContext, hookEventName (required, const), permissionDecision (allow\|deny\|ask), permissionDecisionReason, updatedInput`. JSON-looking output that fails to parse makes the hook **`Failed`, so the call runs**. Any extra key, such as x4guard's `inert`, would therefore fail open. | READ (schema text extracted from the 0.160.0 binary; source `output_parser`) |
| C5 | Hooks run as **`%COMSPEC%` (`cmd.exe`) `/C "<command>"`** with `current_dir(<turn cwd>)`, under `env_clear()` plus the session's environment snapshot. Windows uses `commandWindows` when it is present. The process tree is put in a JobObject and killed on timeout. The default timeout is **600 s**. | READ (`command_runner.rs`, `discovery.rs`) |
| C6 | **`bash` under `cmd.exe` can be the WSL stub.** `C:\Windows\System32\bash.exe` exists on this machine. The spike launched Codex from Git Bash, so its PATH put Git's bash first. A user who launches Codex from PowerShell gets a PATH order that is **UNMEASURED**. If the stub is picked, a `bash "…"` hook cannot run, and Codex then **runs the command**. | MEASURED (`where bash`) / INFERRED (risk) |
| C7 | Hooked tool names: shell and `exec_command` (unified exec) arrive as **`Bash`**, with `tool_input = {"command": …}` only, so **`workdir` is not passed**. Patches arrive as `apply_patch`, which a matcher can also reach through the aliases `Write`/`Edit`. Also hooked: **`write_stdin`**, `spawn_agent` (alias `Agent`), MCP tools as `mcp__…`, and every other tool by its flat name. | READ (`core/src/tools/hook_names.rs` and the handlers) |
| C8 | PreToolUse **`exit 2` with a stderr reason now BLOCKS** in the 0.160.0 source (`events/pre_tool_use.rs`, `exit_code_two_blocks_processing`). The spike measured it **running** on 0.159.2. This may have changed, so **re-measure it (Task 1)**. The design relies on the JSON deny alone, either way. | READ vs MEASURED (conflict) |
| C9 | `codex exec --dangerously-bypass-hook-trust` exists in 0.160.0 ("Run enabled hooks without requiring persisted hook trust for this invocation"). It lets the live E2E exercise hook **behaviour** without a TUI review. It cannot test trust **detection**. | MEASURED (`--help`) |
| C10 | `additionalContext` spills to disk past **2,500 tokens** by default (`additionalContextLimit`; `0` disables spilling). Setting it changes the trust hash. This answers M10 at the READ tier. | READ |
| C11 | Hook events available: PreToolUse, PermissionRequest, PostToolUse, Pre/PostCompact, SessionStart, SessionEnd, UserPromptSubmit, SubagentStart/Stop, Stop, Interrupt. PostToolUse input carries `tool_response`, and its output may carry `additionalContext`. | READ (schemas in the binary) |
| C12 | `codex execpolicy check --rules F <tokens…>` works on 0.160.0. Inline `match=`/`not_match=` examples are **validated when the policy is parsed**: a wrong example gives `rc=1` and "failed to parse policy". The CLI does **not** unwrap `pwsh -Command "git add -A"` (no match). The spike measured the *runtime* unwrapping it on 0.159.2. | MEASURED |
| C13 | Real Codex payloads for `Bash` and for `apply_patch` Add/Update/Delete were captured on 2026-10-01 in a maintainer session's private scratch folder (`<scratchpad>/capcodex/raw/*.json`; not in the repo). Their patch paths are **relative** (`notes/a.txt`), and `cwd` is the session root. No `*** Move to:` sample exists. | MEASURED (files read) |
| C14 | The Codex hook command is part of the trust hash, so an **absolute path in it makes the definition per-install**: moving the game folder means re-review. No project-dir variable is substituted for project hooks; the `${PLUGIN_ROOT}` substitution applies to plugin hooks only. | READ (`discovery.rs` env fold) |
| C15 | `x4guard.py::_deployed()` accepts only `.claude/hooks`. A copy under `.codex/hooks` without `X4_TOOLKIT` set returns an **inert deny for every call**. `_x4-env.sh` derives the toolkit root from `HOOK_DIR/../..`, so `.codex/hooks` works there. | READ |
| C16 | `X4_GUARD=off` (spec §5.7) is **not implemented** anywhere in `agent/guards/claude-hooks/` (grep: 0 hits apart from `X4_GUARD_CHECK`). | MEASURED |
| C17 | `protect-files.sh` whitelists `<game>/.claude/{hooks,skills,…}` and `AGENTS.md` by name. It does not whitelist `<game>/.codex/` or `<game>/.agents/`, so Codex-side files in the game root are **denied as game-install files**. | READ |
| C18 | Master's working tree is **dirty** with another session's uncommitted edits (`agent/guards/claude-hooks/*`, `CLAUDE.md`, `ci.yml`, an untracked `tests/test_framework_hardening.py`). | MEASURED (`git status`) |

**Spike claims that may have changed on 0.160.0** (Task 1 re-measures each one):
- exit-2 semantics (C8);
- the shell `tool_name` under `unified_exec` (READ says still `Bash`);
- whether `write_stdin` and subagent calls reach PreToolUse;
- whether hooks still run under Git Bash when Codex is launched from PowerShell (C6);
- the 32 KiB `AGENTS.md` cap;
- the runtime `pwsh -Command` unwrapping for rules;
- that the payload keys are unchanged (the schema adds the optional `agent_id`/`agent_type`).

## Global constraints

- **Work in your own worktree:** `git worktree add ../x4-toolkit-laneB -b session/laneB` (C18). Stage explicit paths only and commit per task. Never push.
- **Zero behaviour change for Claude Code.** `.claude/hooks/` stays byte-identical, except where a cross-lane change lands through `agent/guards/claude-hooks/` and is regenerated (Task 6). Every existing guard suite keeps its meaning.
- Everything under `agent/guards/` is stdlib-only and imports on **Python 3.10**. The `.ps1` entry runs on **PowerShell 5.1 and 7**.
- **The Codex output is exactly one of these four shapes (C4)**, and nothing else ever reaches stdout:
  - `deny`: `{"hookSpecificOutput":{"hookEventName":E,"permissionDecision":"deny","permissionDecisionReason":R}}`
  - `advise`: `{"hookSpecificOutput":{"hookEventName":E,"additionalContext":C}}`
  - `allow`: empty stdout
  - SessionStart context: `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":C}}`

  Never `exit 2`, never `"ask"`, never an extra key.
- **Hook definitions are frozen once Task 7 lands** (spec §5.4). A test pins the template bytes. Behaviour goes in scripts.
- Write UTF-8 LF: encode first, then `write_bytes`. Write no personal paths in committed files (`scripts/scan-identifiers.py` clean). Fixtures are sanitised (Task 1).
- `X4_HOOK_MAX_CHARS` (10,000) bounds every reason and context the adapter renders, with the directive first (CLAUDE.md #38). That bound sits under C10's 2,500-token spill threshold (INFERRED: about 4 chars per token). `additionalContextLimit` stays unset.

## Interfaces

**Produced by this lane:**
- `agent/guards/adapters/patch_paths.py` provides `parse_patch(text) -> list[PatchOp]`, where `PatchOp = (op, path)` and `op ∈ {"add","update","delete","move_from","move_to"}`. It raises `PatchParseError` on any unrecognised `*** ` header, a missing `*** Begin Patch` or `*** End Patch`, or an empty path. This is **the one shared helper** for every adapter (spec §5.2).
- `agent/guards/adapters/codex.py` (rendered to `.codex/hooks/codex_adapter.py`):
  - CLI: `python codex_adapter.py <session_start|pre_tool_use|post_tool_use>`, with the payload on stdin. It prints **exactly one line**, `X4OK <codex-json-or-empty>`, and exits 0.
  - Python API: `translate(payload: dict, event: str, *, shell: str) -> list[GuardCall]`, `aggregate(verdicts) -> dict`, `render(event, verdict) -> str`.
- `agent/guards/adapters/codex-entry.ps1` and `codex-entry.sh` (rendered to `.codex/hooks/`) are the fail-closed wrappers. On **every** failure path they print a deny (PreToolUse) or an advisory (other events).
- `agent/guards/adapters/codex_trust.py` (rendered to `.codex/hooks/codex_trust.py`):
  - `hook_hash(event_key, group, handler) -> str`
  - `expected_entries(hooks_json: Path) -> dict[key, hash]`
  - `trust_report(hooks_json: Path, codex_config: Path, project_root: Path) -> dict` with per-hook `status ∈ {trusted, untrusted, modified, disabled, unknown}`, plus `project_trusted: bool|None`
  - CLI: `python codex_trust.py report --hooks-json P [--codex-config P] [--project-root P]` prints JSON; exit 0 when all trusted, 1 otherwise, 2 when it cannot tell.

  **Lane C's `x4doctor` consumes this.**
- `agent/targets/codex/hooks.json.tmpl` is the frozen definition template with a `{{ROOT}}` token. `gen-agent-trees.py` gains `render_codex_hooks_json(root: Path) -> str`, which deploy and installers (lane C) call to write `<root>/.codex/hooks.json`.
- `agent/rules/codex-rules.yaml` holds the rule classification. Its generated output is `.codex/rules/x4.rules`.
- Generated and committed: `.codex/hooks/**`, `.codex/rules/x4.rules`, `.agents/skills/**`. `.codex/hooks.json` is **not committed**, because it holds an absolute path (C14); it is git-ignored.
- `scripts/test-hooks.sh` gains an opt-in dump mode, `X4_DECIDE_DUMP=<file>`, that appends one JSONL record per `decide`. With the variable unset, nothing changes.

**Consumed from other lanes:**
- **A:** the `agent/instructions/codex.md` addendum carries the paragraph from Task 11.
- **C:** deploy and installers write the rendered `hooks.json`, plus x4doctor.
- **E:** `X4_GUARD=off`, x4guard hardening, and the Codex self-config protection rule.

---

## Task 1: Re-measure Codex 0.160.0 and capture native fixtures (M-B1)

**Files:**
- Create: `scripts/capture-codex-fixtures.py`
- Create: `PKG/tests/fixtures/codex/0.160.0/*.json` (sanitised payloads) and `PKG/tests/fixtures/codex/0.160.0/README.md` (provenance)
- Create: `PKG/tests/fixtures/codex/0.160.0/schemas/{pre-tool-use,post-tool-use,session-start}.command.{input,output}.json` (extracted from the binary, as C4 did)
- Create: `PKG/tests/test_codex_fixtures.py`
- Create: `docs/superpowers/measurements/2026-10-02-codex-0160.md`

The live probes run **only in a scratch tree** under the session scratchpad, against a decoy `reference/`, using `codex exec --dangerously-bypass-hook-trust` with a capture hook copied from `spike/capture_hook.py`. Outcomes are read from disk, never from the model.

| Probe | Prediction | Decides |
|---|---|---|
| P1 | Shell command arrives as `tool_name:"Bash"` with `tool_input` keys == `{"command"}` | routing (C7) |
| P2 | `apply_patch` covering Add, Update, Delete, and Update+`*** Move to:` | parser grammar |
| P3 | Model asked to run `apply_patch` *through the shell* (heredoc): either reaches the hook as `apply_patch`, or as `Bash` with `apply_patch` as the first token | Task 4's shell-patch route |
| P4 | An interactive `exec_command` then `write_stdin`: a `write_stdin` PreToolUse is fired, with `tool_input` keys | Task 4's `write_stdin` route (Q3) |
| P5 | A spawned subagent's shell call fires PreToolUse with `agent_id` | coverage disclosure |
| P6 | **Exit 2 + stderr reason** (C8): blocks on 0.160.0 | records only; the design is unchanged |
| P7 | Launched from **PowerShell**, not Git Bash: does `bash "…"` in a hook resolve to Git Bash or to the WSL stub? | Q1 / Task 5 |
| P8 | Session started in a **subdirectory** of the project: hook `cwd`, and whether the project `.codex/hooks.json` is still discovered | hooks.json command form |
| P9 | A `.rules` `forbidden` rule still blocks a `pwsh -Command`-wrapped command on 0.160.0, and is it ignored when the project is **untrusted**? | Task 8 disclosure |
| P10 | `AGENTS.md` 46,737 bytes: tail sentinel still dropped | lane A budget |
| P11 | `PostToolUse` after `apply_patch`: payload has `tool_response`; `additionalContext` reaches the model | Task 4 post route |

- [ ] **Step 1: Write the failing fixture test**

```python
# PKG/tests/test_codex_fixtures.py
"""The Codex fixtures are REAL captured payloads (spec §7.2), sanitised, and shaped as the
0.160.0 schema says. A hand-written fixture would encode our assumptions, not Codex's."""
import json
import re
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
PERSONAL = re.compile(r"[A-Za-z]:[\\/]|/home/|/Users/|\b\d{8}\b")


def payloads():
    return sorted(p for p in FIX.glob("*.json"))


def test_fixtures_exist_for_every_required_shape():
    names = {p.stem for p in payloads()}
    for need in ("bash_powershell", "apply_patch_add", "apply_patch_update", "apply_patch_delete",
                 "apply_patch_move", "apply_patch_multi", "session_start", "post_tool_use_apply_patch"):
        assert need in names, f"missing captured fixture {need}"


def test_fixtures_are_sanitised():
    for p in payloads():
        text = p.read_text(encoding="utf-8")
        assert not PERSONAL.search(text), f"{p.name} carries a personal path"
        assert "<CWD>" in text or "SessionStart" in text, f"{p.name}: cwd placeholder missing"


def test_fixtures_carry_exactly_the_schema_required_keys():
    schema = json.loads((FIX / "schemas" / "pre-tool-use.command.input.json").read_text(encoding="utf-8"))
    allowed, required = set(schema["properties"]), set(schema["required"])
    for p in payloads():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("hook_event_name") != "PreToolUse":
            continue
        assert required <= set(d) <= allowed, (p.name, set(d) ^ required)
```

- [ ] **Step 2: Run it.** Expected: FAIL (no fixtures).
- [ ] **Step 3: Implement `scripts/capture-codex-fixtures.py`.** It builds the scratch project, runs each probe with `codex exec --dangerously-bypass-hook-trust -C <scratch>`, and copies each raw payload. It **sanitises only** `cwd` → `<CWD>`, `transcript_path` → `<TRANSCRIPT>`, the `session_id`/`turn_id`/`tool_use_id` values, and absolute prefixes inside `tool_input` → `<CWD>/…`. It writes a provenance README that names the Codex version and date for each file. Sanitisation must leave the patch text byte-identical apart from the prefix substitution. Assert that by re-applying the reverse substitution and comparing against the raw file, and keep the raw files in the scratchpad.
- [ ] **Step 4: Run the probes, write the measurements doc** (one row per probe, with prediction / result / tier), and run the test.

```
cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/test_codex_fixtures.py
Expected: 3 passed
```

- [ ] **Step 5: Stop for a decision if any probe contradicts the plan.** For example: P1 shows `tool_input` carrying `workdir`, P7 shows the WSL stub, or P3 shows a shell-routed patch. Any of these materially changes Tasks 4 and 5.
- [ ] **Step 6: Commit.** `codex 0.160.0: re-measure the spike, capture native hook fixtures (sanitised) and schemas`

**Confidence: 85%.** P4, P5 and P7 depend on model cooperation in `codex exec` and on PATH state. The fallback is the user running one TUI session; the probe list is unchanged.

---

## Task 2: The one shared `apply_patch` path parser

**Files:** Create `agent/guards/adapters/patch_paths.py` and `PKG/tests/test_patch_paths.py`.

- [ ] **Step 1: Write the failing tests** (they load the rendered copy once Task 7 exists; until then, they load the source by path).

```python
# PKG/tests/test_patch_paths.py
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "agent" / "guards" / "adapters" / "patch_paths.py"
FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
spec = importlib.util.spec_from_file_location("patch_paths", SRC)
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)


def test_add_update_delete_move_multi():
    text = ("*** Begin Patch\n*** Add File: a/new.xml\n+<x/>\n*** Update File: b/old.xml\n@@\n-a\n+b\n"
            "*** Update File: c/from.xml\n*** Move to: d/to.xml\n@@\n-a\n+b\n*** Delete File: e/gone.xml\n*** End Patch")
    assert pp.parse_patch(text) == [("add", "a/new.xml"), ("update", "b/old.xml"),
                                    ("move_from", "c/from.xml"), ("move_to", "d/to.xml"),
                                    ("delete", "e/gone.xml")]


def test_header_text_inside_added_content_is_content():
    text = "*** Begin Patch\n*** Add File: a.txt\n+*** Delete File: reference/x.xml\n*** End Patch"
    assert pp.parse_patch(text) == [("add", "a.txt")]


def test_paths_with_spaces_and_drive_letters_kept_verbatim():
    text = "*** Begin Patch\n*** Update File: C:\\X4 Foundations\\libraries\\wares.xml\n@@\n-a\n+b\n*** End Patch"
    assert pp.parse_patch(text) == [("update", "C:\\X4 Foundations\\libraries\\wares.xml")]


@pytest.mark.parametrize("bad", [
    "*** Add File: a.txt\n+x\n*** End Patch",                          # no Begin
    "*** Begin Patch\n*** Add File: a.txt\n+x",                        # no End
    "*** Begin Patch\n*** Rename File: a -> b\n*** End Patch",         # unknown header
    "*** Begin Patch\n*** Add File:   \n*** End Patch",                # empty path
    "*** Begin Patch\n*** Move to: x\n*** End Patch",                  # Move without Update
    "*** Begin Patch\n*** End Patch",                                  # touches nothing
])
def test_malformed_patch_refuses(bad):
    with pytest.raises(pp.PatchParseError):
        pp.parse_patch(bad)


def test_every_captured_fixture_parses():
    n = 0
    for p in sorted(FIX.glob("apply_patch_*.json")):
        ops = pp.parse_patch(json.loads(p.read_text(encoding="utf-8"))["tool_input"]["command"])
        assert ops, p.name; n += 1
    assert n >= 5, f"only {n} apply_patch fixtures were exercised"
```

- [ ] **Step 2: Run.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Parse line by line, tolerating CRLF.
  - Header lines are recognised **only** when the line starts with `*** `. Inside an Add body, every content line starts with `+`, so a `+*** …` line is content.
  - Recognised headers are `Begin Patch`, `End Patch`, `Add File: `, `Update File: `, `Delete File: `, `Move to: ` (valid only directly after an Update header) and `End of File`. Anything else raises.
  - Strip the path of surrounding whitespace only.
- [ ] **Step 4: Run.** Expected: `10 passed` (6 parametrised cases).
- [ ] **Step 5: Commit.** `agent/guards/adapters: one shared apply_patch path parser (refuses unknown grammar)`

**Confidence: 92%.** The grammar is READ from Codex's apply_patch format plus fixtures. Task 1's P2 confirms `Move to`.

---

## Task 3: Codex hook-trust library (M11)

**Files:** Create `agent/guards/adapters/codex_trust.py` and `PKG/tests/test_codex_trust.py`. Create `PKG/tests/fixtures/codex/0.160.0/trust_vectors.json`, holding hashes **produced by Codex itself** for neutral, non-personal definitions (Step 3).

- [ ] **Step 1: Write the failing tests.**

```python
# PKG/tests/test_codex_trust.py
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "agent" / "guards" / "adapters" / "codex_trust.py"
FIX = Path(__file__).parent / "fixtures" / "codex" / "0.160.0"
spec = importlib.util.spec_from_file_location("codex_trust", SRC)
ct = importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)


def test_hash_matches_codex_oracle_vectors():
    """The oracle is Codex (hooks/list current_hash), never our own reimplementation (#14)."""
    vectors = json.loads((FIX / "trust_vectors.json").read_text(encoding="utf-8"))
    assert len(vectors) >= 4
    for v in vectors:
        assert ct.hook_hash(v["event_key"], v["group"], v["handler"]) == v["codex_hash"], v["label"]


def test_TWIN_every_hashed_field_moves_the_hash():
    base = {"type": "command", "command": "bash x.sh", "timeout": 30}
    h0 = ct.hook_hash("pre_tool_use", {"matcher": ".*"}, base)
    for k, v in (("command", "bash y.sh"), ("timeout", 31), ("async", True), ("statusMessage", "s")):
        assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, **{k: v})) != h0, k
    assert ct.hook_hash("pre_tool_use", {"matcher": "Bash"}, base) != h0
    assert ct.hook_hash("post_tool_use", {"matcher": ".*"}, base) != h0
    assert ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=None)) == \
        ct.hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=600))   # default normalised


def test_report_statuses(tmp_path):
    hj = tmp_path / ".codex" / "hooks.json"; hj.parent.mkdir()
    hj.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "a", "timeout": 60}]}],
        "PostToolUse": [{"matcher": "apply_patch", "hooks": [{"type": "command", "command": "b", "timeout": 60}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "c", "timeout": 30}]}]}}), encoding="utf-8")
    exp = ct.expected_entries(hj)
    keys = sorted(exp)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"[projects.'{str(tmp_path).lower()}']\ntrust_level = \"trusted\"\n\n"
        f"[hooks.state.'{keys[0]}']\ntrusted_hash = \"{exp[keys[0]]}\"\n\n"
        f"[hooks.state.'{keys[1]}']\ntrusted_hash = \"sha256:{'0' * 64}\"\n\n", encoding="utf-8")
    r = ct.trust_report(hj, cfg, tmp_path)
    st = {e["key"]: e["status"] for e in r["hooks"]}
    assert st[keys[0]] == "trusted" and st[keys[1]] == "modified" and st[keys[2]] == "untrusted"
    assert r["project_trusted"] is True
    cfg.write_text(cfg.read_text(encoding="utf-8") + f"[hooks.state.'{keys[2]}']\nenabled = false\n",
                   encoding="utf-8")
    assert {e["status"] for e in ct.trust_report(hj, cfg, tmp_path)["hooks"]} >= {"disabled"}


def test_unreadable_config_is_unknown_never_trusted(tmp_path):
    hj = tmp_path / "hooks.json"; hj.write_text('{"hooks":{}}', encoding="utf-8")
    r = ct.trust_report(hj, tmp_path / "missing.toml", tmp_path)
    assert r["overall"] == "unknown"
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Produce the oracle vectors (MEASURE).** In a scratch project, write `.codex/hooks.json` using **neutral** commands (`bash "/x4/hooks/codex-entry.sh" pre_tool_use` and so on, four or more definitions that vary timeout, matcher, event and `commandWindows`). Obtain Codex's own `current_hash` by one of two routes:
  - **(a)** the `codex app-server` JSON-RPC `hooks/list` for that cwd (READ: `app-server-protocol` `HooksList => "hooks/list"`, returning `current_hash` and `trust_status`);
  - **(b)** fallback: the user reviews the scratch hooks once in the TUI, and the plan reads `trusted_hash` back from `~/.codex/config.toml`.

  Record the vectors with their label. Also re-run C2's offline check against the four stored spike hashes. That result goes in the measurements doc only, because those paths are personal.
- [ ] **Step 4: Implement.**
  - **TOML parsing:** `tomllib` exists only on 3.11+, so on 3.10 use a minimal reader limited to `[projects.'…']`/`trust_level` and `[hooks.state.'…']`/`trusted_hash`/`enabled`. An unparseable section makes the result `unknown`.
  - **Key path:** use the absolute `hooks.json` path as Codex forms it. Compare both the exact and the case-folded form, and record which matched.
  - **Event keys** are snake_case.
  - **Windows:** resolve `commandWindows` over `command`.
  - **Overall result:** `trusted` only if every expected entry is trusted and none is disabled.
- [ ] **Step 5: Run.** Expected: `4 passed`.
- [ ] **Step 6: Commit.** `codex_trust: reproduce Codex's hook trust hash; report trusted/untrusted/modified/disabled per hook`

**Confidence: 90%.** The scheme is READ and its match MEASURED (4 of 4). The residual risk is a future Codex change to the scheme, so the report says `unknown`, not `modified`, when **no** entry matches and the vectors test is stale. Running route (a) live at each release (Task 13) is the guard against that.

---

## Task 4: The Codex adapter (translate → x4guard → render)

**Files:** Create `agent/guards/adapters/codex.py` and `PKG/tests/test_codex_adapter.py`.

**Behaviour:**

1. **Read stdin.** Bad JSON, or a missing `hook_event_name`/`tool_name` → deny with the reason `X4 GUARD INERT: unreadable Codex payload`. If argv's event disagrees with the payload's event → deny.
2. **`os.chdir(payload["cwd"])`.** A missing directory → inert deny. (Relative paths in patches and shell commands are the turn cwd's; C13.)
3. **Shell is `--shell powershell` on `win32` and `bash` elsewhere.** `X4_CODEX_SHELL` overrides it, for tests and for M9.
4. **Route `PreToolUse` by `tool_name`:**
   - `Bash` → `x4guard.verdict_for("shell", SHELL, command, None)`. If the first token is `apply_patch`/`applypatch` (P3), also parse the heredoc body as a patch.
   - `apply_patch` → `parse_patch`:
     - `add`/`update`/`move_to` → `verdict_for("write", …, abspath(p))`;
     - `delete`/`move_from` → `verdict_for("delete", …)`;
     - `PatchParseError` → inert deny.
   - `write_stdin` → if the `chars` contain a newline, judge each submitted line as a shell command with `SHELL`; otherwise allow (Q3).
   - Any other name → allow, and record the name (Q3).
5. **Aggregate:** `inert deny > deny > ask > advise > allow`. Join reasons per path with the path named, and bound the result to `X4_HOOK_MAX_CHARS` with the directive first.
6. **Render (D11):**
   - `deny` → deny;
   - `ask` → deny whose reason starts `NEEDS YOUR APPROVAL: ` and ends `Ask the user; do not retry until they agree.`;
   - `advise` → `additionalContext`;
   - `allow` → empty.
7. **Backups:** when the final decision is not deny, run `backup-before-edit.sh` (Claude-shaped `Edit` payload) for every `update`/`delete`/`move_from` path that exists.
8. **`post_tool_use`** (matcher `apply_patch`): run `x4validate-on-edit.sh` with a `PostToolUse` Claude payload per `add`/`update`/`move_to` path, and render `additionalContext`. On failure, render the advisory `X4 VALIDATION DID NOT RUN: <cause>`.
9. **`session_start`:** run `check-reference-version.sh` and `session-canary.sh`, then prepend the banner `X4 GUARDS LIVE (codex hooks v1) — every shell command and apply_patch is checked.` The model is told to look for it (Task 11).
10. **Deadline:** keep an overall budget of 45 s. Before each guard call, set `x4guard.TIMEOUT_S = max(1, int(remaining))`; once it is exhausted, the remaining calls are inert denies.
11. **Output:** always print exactly one line, `X4OK ` + rendered text (empty for allow).

- [ ] **Step 1: Write the failing tests.** Reuse the Plan-1 sandbox fixture shape (`test_x4guard_check.py::sandbox`) and drive the **rendered** `.codex/hooks/codex_adapter.py` through subprocess. Until Task 7 exists, set `ADAPTER` to the source path and run with `X4_TOOLKIT` set.

```python
# PKG/tests/test_codex_adapter.py  (excerpt -- the full file has one test per routing branch)
import json, os, shutil, subprocess, sys
from pathlib import Path
import pytest

PKG = Path(__file__).resolve().parents[1]; REPO = PKG.parents[1]
ADAPTER = REPO / ".codex" / "hooks" / "codex_adapter.py"
FIX = PKG / "tests" / "fixtures" / "codex" / "0.160.0"
HAS_PWSH = bool(shutil.which("pwsh") or shutil.which("powershell"))
ALLOWED_TOP = {"continue", "decision", "hookSpecificOutput", "reason", "stopReason", "suppressOutput", "systemMessage"}
ALLOWED_HSO = {"additionalContext", "hookEventName", "permissionDecision", "permissionDecisionReason", "updatedInput"}


def native(name, cwd, **tool_input):
    """A captured fixture with <CWD> filled in and tool_input overridden -- never a hand-built envelope."""
    d = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8").replace("<CWD>", str(cwd).replace("\\", "\\\\")))
    d["cwd"] = str(cwd)
    d["tool_input"].update(tool_input)
    return d


def run(env, payload, event="pre_tool_use", shell="powershell"):
    r = subprocess.run([sys.executable, str(ADAPTER), event], input=json.dumps(payload).encode(),
                       capture_output=True, env=dict(env, X4_CODEX_SHELL=shell), timeout=180)
    lines = r.stdout.decode("utf-8").splitlines()
    assert r.returncode == 0 and len(lines) == 1 and lines[0].startswith("X4OK"), (r.returncode, r.stdout, r.stderr)
    body = lines[0][len("X4OK"):].strip()
    if not body:
        return "allow", None
    out = json.loads(body)
    assert set(out) <= ALLOWED_TOP and set(out["hookSpecificOutput"]) <= ALLOWED_HSO   # C4: extra key = fail-open
    hso = out["hookSpecificOutput"]
    if hso.get("permissionDecision") == "deny":
        r_ = hso["permissionDecisionReason"]
        return ("ask" if r_.startswith("NEEDS YOUR APPROVAL:") else "deny"), r_
    assert "permissionDecision" not in hso, "Codex fails open on 'ask' and 'allow'-with-reason; never emit them"
    return "advise", hso["additionalContext"]


@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell -- routing NOT checked here")
def test_bash_labelled_powershell_is_routed(sandbox):
    tmp, tk, env = sandbox
    cmd = f"Set-Content -Path '{tk / 'reference' / 'libraries' / 'wares.xml'}' -Value 'x'"
    assert run(env, native("bash_powershell", tmp, command=cmd), shell="powershell")[0] == "deny"
    assert run(env, native("bash_powershell", tmp, command=cmd), shell="bash")[0] != "deny"  # twin: routing decides


def test_relative_patch_path_resolves_against_payload_cwd(sandbox):
    tmp, tk, env = sandbox
    patch = "*** Begin Patch\n*** Update File: reference/libraries/wares.xml\n@@\n-ref\n+x\n*** End Patch"
    assert run(env, native("apply_patch_update", tk, command=patch))[0] == "deny"
    assert run(env, native("apply_patch_update", tk / "dev", command=patch))[0] == "allow"  # same text, other cwd


def test_multi_file_patch_worst_verdict_wins_and_names_path(sandbox):
    tmp, tk, env = sandbox
    patch = ("*** Begin Patch\n*** Add File: dev/mymod/a.xml\n+<a/>\n"
             "*** Delete File: reference/libraries/wares.xml\n*** End Patch")
    d, reason = run(env, native("apply_patch_multi", tk, command=patch))
    assert d == "deny" and "wares.xml" in reason


def test_move_to_checks_both_ends(sandbox):
    tmp, tk, env = sandbox
    patch = ("*** Begin Patch\n*** Update File: reference/libraries/wares.xml\n*** Move to: dev/mymod/w.xml\n"
             "@@\n-ref\n+x\n*** End Patch")
    assert run(env, native("apply_patch_move", tk, command=patch))[0] == "deny"


def test_profile_ask_becomes_deny_with_approval_text(sandbox):
    tmp, tk, env = sandbox
    patch = f"*** Begin Patch\n*** Update File: {tmp / 'profile' / 'content.xml'}\n@@\n-a\n+b\n*** End Patch"
    d, reason = run(env, native("apply_patch_update", tk, command=patch))
    assert d == "ask" and reason.startswith("NEEDS YOUR APPROVAL:")


def test_unparseable_patch_is_inert_deny(sandbox):
    tmp, tk, env = sandbox
    d, reason = run(env, native("apply_patch_update", tk, command="*** Begin Patch\n*** Frobnicate: x\n*** End Patch"))
    assert d == "deny" and "INERT" in reason


def test_unreadable_payload_is_inert_deny(sandbox):
    _, _, env = sandbox
    r = subprocess.run([sys.executable, str(ADAPTER), "pre_tool_use"], input=b"{not json", capture_output=True, env=env)
    assert b"permissionDecision\":\"deny" in r.stdout.replace(b" ", b"") and b"INERT" in r.stdout


def test_reason_is_bounded_directive_first(sandbox):
    tmp, tk, env = sandbox
    many = "".join(f"*** Delete File: reference/libraries/f{i:04d}.xml\n" for i in range(400))
    d, reason = run(env, native("apply_patch_delete", tk, command="*** Begin Patch\n" + many + "*** End Patch"))
    assert d == "deny" and len(reason) <= 10_000 and reason.lstrip().startswith(("BLOCKED", "X4"))


def test_session_start_banner(sandbox):
    tmp, _, env = sandbox
    d = json.loads((FIX / "session_start.json").read_text(encoding="utf-8").replace("<CWD>", "x")); d["cwd"] = str(tmp)
    assert "X4 GUARDS LIVE" in run(env, d, event="session_start")[1]
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `agent/guards/adapters/codex.py`. Import the sibling `x4guard` and `patch_paths`, and keep it stdlib-only. Wrap all of `main()` in `try/except BaseException`, and make the handler print an inert deny (or, for post/session events, an advisory) before returning 0.
- [ ] **Step 4: Run.** Expected: all pass, with the PowerShell routing test SKIPPED only where `pwsh` is absent (counted).
- [ ] **Step 5: Commit.** `agent/guards/adapters/codex.py: translate Codex payloads to the guards; render only Codex-honoured JSON`

**Confidence: 85%.** The `write_stdin` and shell-`apply_patch` branches rest on Task 1's P3/P4. The deadline handling mutates a module global (named in Task 10's mutants).

---

## Task 5: Fail-closed entry wrappers (spec §5.3, adjusted by C5/C6)

**Files:** Create `agent/guards/adapters/codex-entry.ps1`, `agent/guards/adapters/codex-entry.sh` and `PKG/tests/test_codex_wrapper.py`.

**Design.** Codex launches every hook through `cmd.exe /C` (C5), and `bash` from `cmd`'s PATH can be the WSL stub (C6). So the **Windows** definition (`commandWindows`) starts a PowerShell wrapper: `pwsh … -File codex-entry.ps1 <event> || powershell … -File codex-entry.ps1 <event>`. The fallback to `powershell` covers a missing pwsh, because `cmd` returns 9009. The POSIX `command` uses `codex-entry.sh`. Both wrappers:
- find Python in this order: `X4_PYTHON`, then `py -3`, then `python3`, then `python`;
- run `codex_adapter.py <event>` with the payload on stdin and a **50 s** kill, safely below the 60 s hook timeout, killing the process tree;
- accept only a single line starting `X4OK`, and print whatever follows it;
- on **every** other outcome (no Python, a missing adapter, a non-zero exit, timeout, empty output, no `X4OK` prefix, more than one line, or the payload failing to parse as a JSON object with one top-level key `hookSpecificOutput`) print the event's fail-closed JSON (PreToolUse → a deny naming the cause; other events → an advisory) and exit 0.

The `.sh` wrapper uses `trap … ERR EXIT` per spec. The `.ps1` uses `try/catch/finally`, with an `$emitted` flag checked in `finally`.

- [ ] **Step 1: Write the failing tests.** They run each wrapper against a copy of `.codex/hooks/` in `tmp_path`, with the adapter replaced by a fault double:

```python
# PKG/tests/test_codex_wrapper.py
import json, os, shutil, subprocess, sys
from pathlib import Path
import pytest

PKG = Path(__file__).resolve().parents[1]; REPO = PKG.parents[1]
HOOKS = REPO / ".codex" / "hooks"
PWSH = shutil.which("pwsh") or shutil.which("powershell")
BASH = os.environ.get("X4_BASH") or shutil.which("bash")
FAULTS = {
    "crash":   "import sys; sys.exit(3)",
    "garbage": "print('hello')",
    "empty":   "pass",
    "twolines": "print('X4OK '); print('X4OK ')",
    "extrakey": "print('X4OK {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"allow\"},\"inert\":true}')",
    "hang":    "import time; time.sleep(600)",
    "raise_after_partial": "import sys; sys.stdout.write('X4O'); raise SystemExit(0)",
}


def wrappers():
    out = []
    if PWSH:
        out.append(("ps1", [PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]))
    if BASH and "system32" not in BASH.lower():
        out.append(("sh", [BASH]))
    return out


@pytest.fixture
def tree(tmp_path):
    t = tmp_path / ".codex" / "hooks"; shutil.copytree(HOOKS, t); return t


@pytest.mark.parametrize("kind,launcher", wrappers() or [pytest.param("none", None, marks=pytest.mark.skip("no shell"))])
@pytest.mark.parametrize("fault", sorted(FAULTS) + ["missing_adapter", "missing_python"])
def test_every_fault_yields_json_deny(tree, kind, launcher, fault):
    env = dict(os.environ, X4_WRAPPER_TIMEOUT_S="5")
    if fault == "missing_adapter":
        (tree / "codex_adapter.py").unlink()
    elif fault == "missing_python":
        env["X4_PYTHON"] = str(tree / "no-such-python.exe"); env["X4_NO_PYTHON_FALLBACK"] = "1"
    else:
        (tree / "codex_adapter.py").write_text(FAULTS[fault], encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = subprocess.run(launcher + [str(script), "pre_tool_use"], input=b'{"hook_event_name":"PreToolUse"}',
                       capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out) == {"hookSpecificOutput"}
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "X4 GUARD INERT" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("kind,launcher", wrappers())
def test_control_allow_passes_through_empty(tree, kind, launcher):
    (tree / "codex_adapter.py").write_text("print('X4OK ')", encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = subprocess.run(launcher + [str(script), "pre_tool_use"], input=b"{}", capture_output=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == b""          # the control: a real allow is NOT a deny
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement both wrappers.**
  - `X4_WRAPPER_TIMEOUT_S` is a test-only override with a default of 50.
  - `X4_NO_PYTHON_FALLBACK=1` is test-only, so the missing-Python case is real and not masked by `py -3`.
  - Encode the deny JSON as a **literal constant** in each wrapper (no `jq`, no Python), and escape the cause string with a character allowlist.
- [ ] **Step 4: Run.** Expected:

```
cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/test_codex_wrapper.py
Expected: 20 passed (9 faults x 2 wrappers + 2 controls) on Windows with Git Bash; SKIPs named, never silent
```

- [ ] **Step 5: Measure M13** (no Codex needed). Time the full chain, wrapper → adapter → guards, over the fixtures, 30 runs each, for p50 and p95: a PowerShell `Get-Date`, `Set-Content` into the decoy `reference/`, and a 3-file `apply_patch`. Record the numbers in the measurements doc. **If p95 is over 5 s, stop and ask.** The options are a narrower PreToolUse matcher (it cannot be changed after the freeze), or caching the `ps_translate` pwsh process (lane E).
- [ ] **Step 6: Commit.** `codex entry wrappers: every failure path emits the JSON deny (pwsh on Windows, bash elsewhere)`

**Confidence: 88%.** The open link is whether `cmd /C "pwsh … || powershell …"` behaves as INFERRED under Codex's runner. Task 13 measures it live, with P7 as the control.

---

## Task 6: `x4guard` runs from `.codex/hooks` (coordinate with lane E)

**Files:** Modify `agent/guards/claude-hooks/x4guard.py` and `PKG/tests/test_x4guard_check.py`, then regenerate `.claude/hooks/x4guard.py`. **Skip this task if lane E has already landed an equivalent; verify with the test below.**

- [ ] **Step 1: Write the failing test** in `test_x4guard_check.py`:

```python
def test_runs_when_deployed_under_codex_hooks(sandbox, tmp_path):
    _, tk, env = sandbox
    codex_hooks = tmp_path / "root" / ".codex" / "hooks"
    shutil.copytree(X4GUARD.parent, codex_hooks)
    env = {k: v for k, v in env.items() if k != "X4_TOOLKIT"}
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi", script=codex_hooks / "x4guard.py")
    assert rc == 0 and not v["inert"], v["reason"]


def test_TWIN_other_dir_without_toolkit_still_inert(sandbox, tmp_path):
    _, _, env = sandbox
    lone = tmp_path / "x" / "hooks"; shutil.copytree(X4GUARD.parent, lone)
    env = {k: v for k, v in env.items() if k != "X4_TOOLKIT"}
    _, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi", script=lone / "x4guard.py")
    assert v["inert"]
```

- [ ] **Step 2: Run.** Expected: FAIL (first test).
- [ ] **Step 3: Implement.** `_deployed()` returns `HERE.name == "hooks" and HERE.parent.name in (".claude", ".codex")`, and the docstring names both.
- [ ] **Step 4: Regenerate and run.** Expected: `gen-agent-trees.py --check` exits 0, and `test_x4guard_check.py` passes in full.
- [ ] **Step 5: Commit.** `x4guard: a copy under .codex/hooks finds its roots like .claude/hooks (twin: any other dir stays inert)`

**Confidence: 95%.**

---

## Task 7: Generator — the Codex target tree and the frozen `hooks.json` template

**Files:**
- Modify: `PKG/scripts/gen-agent-trees.py` and `PKG/tests/test_gen_agent_trees.py`
- Create: `agent/targets/codex/hooks.json.tmpl`
- Modify: `.gitignore` (`/.codex/hooks.json`)
- Modify: `agent/README.md`
- Generated: `.codex/hooks/**` and `.agents/skills/**`

**Template (frozen v1).** `{{ROOT}}` is the absolute project root, rendered at deploy. Its forward-slash form goes in `command`, its backslash form in `commandWindows`.

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "timeout": 30,
      "command": "bash \"{{ROOT}}/.codex/hooks/codex-entry.sh\" session_start",
      "commandWindows": "pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" session_start || powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" session_start"}]}],
    "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "timeout": 60,
      "command": "bash \"{{ROOT}}/.codex/hooks/codex-entry.sh\" pre_tool_use",
      "commandWindows": "pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" pre_tool_use || powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" pre_tool_use"}]}],
    "PostToolUse": [{"matcher": "apply_patch", "hooks": [{"type": "command", "timeout": 60,
      "command": "bash \"{{ROOT}}/.codex/hooks/codex-entry.sh\" post_tool_use",
      "commandWindows": "pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" post_tool_use || powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{{ROOT_WIN}}\\.codex\\hooks\\codex-entry.ps1\" post_tool_use"}]}]
  }
}
```

**Rendering:**
- `.codex/hooks/` = every file of `agent/guards/claude-hooks/` **byte-identical**, plus `adapters/codex.py` → `codex_adapter.py`, `adapters/patch_paths.py`, `adapters/codex_trust.py`, `adapters/codex-entry.ps1` and `adapters/codex-entry.sh`.
- `.agents/skills/` = `agent/skills/**`, with `{{TOOLKIT}}` → `$env:X4_TOOLKIT` (Q4; the mapping lives in one table, `TOOLKIT_BY_TARGET`). All 8 current uses are `cd {{TOOLKIT}}/…` command lines (READ).
- `OWNED` gains `.codex/hooks/`, `.codex/rules/` and `.agents/skills/`.
- `render_codex_hooks_json(root)` refuses a root containing `"` or a newline. It fills `{{ROOT}}` (posix) and `{{ROOT_WIN}}` (backslashes), JSON-escaped.

- [ ] **Step 1: Write the failing tests** (added to `test_gen_agent_trees.py`):

```python
import hashlib

TEMPLATE_SHA256 = "<filled in once, in the commit that freezes v1>"


def test_codex_hooks_template_is_frozen():
    """Changing a Codex hook DEFINITION silently switches every user's guards off (spike R5).
    Changing this pin needs a CHANGELOG line headed 'Codex users must re-review hooks'."""
    b = (REPO / "agent" / "targets" / "codex" / "hooks.json.tmpl").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(b).hexdigest() == TEMPLATE_SHA256


def test_rendered_hooks_json_is_valid_and_uses_wrappers(tmp_path):
    root = tmp_path / "X4 Foundations"
    d = json.loads(gen.render_codex_hooks_json(root))
    pre = d["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == ".*" and pre["hooks"][0]["timeout"] == 60
    assert str(root).replace("/", "\\") in pre["hooks"][0]["commandWindows"]
    assert "codex-entry.ps1" in pre["hooks"][0]["commandWindows"]


@pytest.mark.parametrize("bad", ['C:/a"b', "C:/a\nb"])
def test_render_refuses_unsafe_root(bad):
    with pytest.raises(gen.GenerationError):
        gen.render_codex_hooks_json(Path(bad))


def test_codex_hooks_carry_the_guards_byte_identical():
    exp = gen.generate(REPO)
    for rel, text in exp.items():
        if rel.startswith(".claude/hooks/"):
            assert exp[".codex/hooks/" + rel[len(".claude/hooks/"):]] == text, rel


def test_codex_skills_render_powershell_env_var():
    exp = gen.generate(REPO)
    skills = {k: v for k, v in exp.items() if k.startswith(".agents/skills/")}
    assert skills and not any("{{TOOLKIT}}" in v or "$CLAUDE_PROJECT_DIR" in v for v in skills.values())
    assert any("$env:X4_TOOLKIT" in v for v in skills.values())


def test_TWIN_ghost_in_codex_hooks_is_reported(tmp_path):
    # mirrors the existing .claude/hooks ghost twin: a stray file under .codex/hooks/ -> GHOST
    ...
```

  (The ghost twin copies the existing `test_TWIN_*` body with the prefix changed.)
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement**, then regenerate and fill in `TEMPLATE_SHA256`.
- [ ] **Step 4: Run:**

```
cd tools/x4validate && uv run python scripts/gen-agent-trees.py && uv run python scripts/gen-agent-trees.py --check
Expected: exit 0; then
uv run --frozen python -m pytest -q -rs tests/test_gen_agent_trees.py tests/test_codex_adapter.py tests/test_codex_wrapper.py tests/test_patch_paths.py tests/test_codex_trust.py
Expected: all pass; tests now import from the RENDERED .codex/hooks/ (switch ADAPTER/SRC paths in the same commit)
uv run python ../../scripts/scan-identifiers.py
Expected: clean
```

- [ ] **Step 5: Commit** (the template freeze is called out in the message). `gen-agent-trees: Codex target tree (.codex/hooks, .agents/skills) + FROZEN hooks.json template v1`

**Confidence: 88%.** Two links are open. The first is that `.codex/hooks/` duplicates about 12.5k lines of guards (Q2). The second is whether `deploy-parity` and `deploy-claude-dir.py` must learn about `.codex/`; that is lane C's work, and this lane only exposes the function.

---

## Task 8: Codex `.rules` — classify every guard rule, generate, prove

**Files:**
- Create: `agent/rules/codex-rules.yaml` (the classification)
- Modify: `PKG/scripts/gen-agent-trees.py`, which renders `.codex/rules/x4.rules`
- Create: `PKG/tests/test_codex_rules.py`
- Modify: `.github/workflows/ci.yml` (install `@openai/codex@0.160.0` pinned for `execpolicy check`)

**Classification rule.** A guard rule becomes a `prefix_rule` **only if every command that matches the prefix gets at least that verdict from the hook**: the rule may never be stricter than the guard. Prefix-expressible denies become `forbidden`, prefix-expressible asks become `prompt`, and everything else is listed as `hook_only` with a reason. Expected candidates (INFERRED until classified):
- `git add -A`/`--all`/`.` (deny → forbidden);
- an XRCatTool re-unpack — that rule is sentinel-gated, so its prefix is **not** sufficient; it is hook_only.

Path-scoped rules (reference writes, profile edits, `git clean` in X4 dirs) are hook_only.

The YAML has one row per rule: `id`, `source` (`protect-bash.sh:<line>` or a `hook_facts` predicate name), `verdict`, `bucket ∈ {forbidden, prompt, hook_only}`, `reason`, `patterns`, `match`, `not_match`.

- [ ] **Step 1: Write the failing tests.**

```python
# PKG/tests/test_codex_rules.py
import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest
from ruamel.yaml import YAML

PKG = Path(__file__).resolve().parents[1]; REPO = PKG.parents[1]
ROWS = YAML(typ="safe").load((REPO / "agent" / "rules" / "codex-rules.yaml").read_text(encoding="utf-8"))
RULES = REPO / ".codex" / "rules" / "x4.rules"
CODEX = shutil.which("codex")
SITE = re.compile(r"(?:^|&&\s*|^\s*on \w+ && )(deny|ask|advise) \"", re.M)


def guard_rule_sites():
    """The INVENTORY is derived from the guard source, never retyped: every literal verdict site
    in protect-bash.sh. A new rule there with no row here turns this red."""
    src = (REPO / "agent" / "guards" / "claude-hooks" / "protect-bash.sh").read_text(encoding="utf-8")
    return [i + 1 for i, line in enumerate(src.splitlines()) if SITE.search(line)]


def test_buckets_sum_to_the_rule_inventory():
    sites = guard_rule_sites()
    rows = {int(r["source"].split(":")[1]) for r in ROWS if r["source"].startswith("protect-bash.sh:")}
    assert rows == set(sites), {"unclassified": sorted(set(sites) - rows), "stale": sorted(rows - set(sites))}
    assert sum(1 for r in ROWS if r["bucket"] in ("forbidden", "prompt", "hook_only")) == len(ROWS)


@pytest.mark.skipif(not CODEX, reason="codex CLI absent -- rule parsing NOT checked here (CI installs it)")
def test_generated_rules_parse_and_examples_hold():
    r = subprocess.run([CODEX, "execpolicy", "check", "--rules", str(RULES), "echo", "x"], capture_output=True)
    assert r.returncode == 0, r.stderr     # C12: a wrong match/not_match example is a PARSE error


@pytest.mark.skipif(not CODEX, reason="codex CLI absent")
@pytest.mark.parametrize("row", [r for r in ROWS if r["bucket"] != "hook_only"], ids=lambda r: r["id"])
def test_each_rule_matches_and_misses(row):
    for ex in row["match"]:
        out = json.loads(subprocess.run([CODEX, "execpolicy", "check", "--rules", str(RULES), *ex],
                                        capture_output=True).stdout)
        assert out.get("decision") == row["bucket"], ex
    for ex in row["not_match"]:
        out = json.loads(subprocess.run([CODEX, "execpolicy", "check", "--rules", str(RULES), *ex],
                                        capture_output=True).stdout)
        assert not out.get("matchedRules"), ex


@pytest.mark.parametrize("row", [r for r in ROWS if r["bucket"] != "hook_only"], ids=lambda r: r["id"])
def test_rule_is_never_stricter_than_the_guard(row, sandbox):
    """forbidden needs the guard to DENY every match example; prompt needs at least ASK, under both shells."""
    _, _, env = sandbox
    floor = {"forbidden": 3, "prompt": 2}[row["bucket"]]
    rank = {"allow": 0, "advise": 1, "ask": 2, "deny": 3}
    for ex in row["match"]:
        for shell in ("bash", "powershell"):
            v = json.loads(subprocess.run([sys.executable, str(REPO / ".codex" / "hooks" / "x4guard.py"), "check",
                                           "--kind", "shell", "--shell", shell, "--command", " ".join(ex)],
                                          capture_output=True, env=env).stdout)
            assert rank[v["decision"]] >= floor, (ex, shell, v)
```

  (`sandbox` moves to `PKG/tests/conftest_codex.py`, shared with Tasks 4 and 9.)
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Classify every site** by reading each rule's fact predicate in `hook_facts.py`. Add **`hook_facts`-only rules** too: the predicates that `on <fact>` references; derive their list from `protect-bash.sh` `on <name>` occurrences, never by hand. Render with `match`/`not_match` inline, so `codex execpolicy` itself refuses a wrong example (C12). Every `justification` names the source rule and ends with `(X4 toolkit rule <id>)`.
- [ ] **Step 4: Run.** Expected: all pass locally, where codex is present. `test_buckets_sum_to_the_rule_inventory` prints the bucket counts; put them in the commit message.
- [ ] **Step 5: CI.** Add a Windows and an Ubuntu step `npm i -g @openai/codex@0.160.0`, run before pytest. Do not raise `X4_MAX_SKIPS`: with codex installed, the new skips are zero.
- [ ] **Step 6: Commit.** `codex rules: every protect-bash rule classified (forbidden/prompt/hook_only, buckets sum), generated x4.rules proven by execpolicy`

**Confidence: 80%.** The inventory regex must reproduce the spec's 17/6/3 counts. If it does not, the **checker** is the first suspect (CLAUDE.md #22): reconcile it per site before classifying. The live claim that runtime unwraps `pwsh -Command` on 0.160.0 is Task 1's P9.

---

## Task 9: Cross-agent conformance suite (spec §7.2)

**Files:**
- Modify: `scripts/test-hooks.sh`, adding a dump mode with **no behaviour change when unset**:

  ```sh
  decide(){
    local exp="$1" hook="$2" json="$3" label="$4" out got
    [ -n "${X4_DECIDE_DUMP:-}" ] && jq -cn --arg e "$exp" --arg h "$hook" --argjson j "$json" --arg l "$label" \
      '{exp:$e,hook:$h,payload:$j,label:$l,env:{X4_TOOLKIT:env.X4_TOOLKIT,X4_GAME:env.X4_GAME,X4_REFERENCE:env.X4_REFERENCE,X4_PROFILE:env.X4_PROFILE,X4_MODS:env.X4_MODS,X4_EXTENSIONS:env.X4_EXTENSIONS,X4_SAVES:env.X4_SAVES,X4_DOCUMENTS:env.X4_DOCUMENTS}}' \
      >> "$X4_DECIDE_DUMP" 2>/dev/null
  ```

  The rest of `decide()` is unchanged.
- Create: `PKG/tests/test_codex_conformance.py`
- Create: `PKG/tests/fixtures/codex/conformance_extra.yaml`, the Codex-specific required cases (spec §7.2): PowerShell-as-Bash, multi-file `apply_patch`, `*** Delete File:`, `*** Move to:`, paths with spaces, drive dialects (`C:\`, `C:/`, `/c/`), and relative paths against `cwd`.

**Equivalence.** For each dumped case, the **Claude verdict** comes from running the hook script itself on the Claude-shaped payload. That path is independent of x4guard. The **Codex verdict** comes from encoding the same case in **native shape** and running it through the rendered `codex-entry` wrapper (the full chain). Native encoding works like this:
- a `PowerShell` case becomes a captured `bash_powershell` fixture with the command, and `X4_CODEX_SHELL=powershell`;
- a `Bash` case becomes the same fixture with `X4_CODEX_SHELL=bash`, standing in for Codex on POSIX (M9);
- an `Edit` case becomes an `apply_patch_update` fixture;
- a `Write` case becomes an `apply_patch_add` fixture;
- `Grep`/`Glob`/`NotebookEdit` cases have **no Codex analogue** and are counted in the `no_native_analogue` bucket.

Normalise both verdicts as follows:
- Claude `ask` whose reason matches `x4guard.NOT_CHECKED` → `inert`;
- Codex deny containing `X4 GUARD INERT` → `inert`;
- Codex deny whose reason starts `NEEDS YOUR APPROVAL:` → `ask`.

They must be **equal**. Delete cases from the extras compare against `max(Claude Write hook, Claude Bash rm -f hook)`, the composition spec §5.2 defines.

- [ ] **Step 1: Write the failing test.**

```python
# PKG/tests/test_codex_conformance.py
import json, os, subprocess, sys
from pathlib import Path
import pytest

PKG = Path(__file__).resolve().parents[1]; REPO = PKG.parents[1]
BUCKETS = ("replayed", "no_native_analogue")


@pytest.fixture(scope="session")
def dumped(tmp_path_factory):
    dump = tmp_path_factory.mktemp("conf") / "cases.jsonl"
    r = subprocess.run(["bash", str(REPO / "scripts" / "test-hooks.sh")], cwd=REPO,
                       env=dict(os.environ, X4_DECIDE_DUMP=str(dump)), capture_output=True, timeout=1500)
    assert r.returncode == 0, r.stdout[-2000:]
    rows = [json.loads(l) for l in dump.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 100, f"only {len(rows)} cases dumped -- the harness or the dump hook changed"
    return rows


def classify(row):
    return "no_native_analogue" if row["payload"]["tool_name"] in ("Grep", "Glob", "NotebookEdit") else "replayed"


def test_buckets_sum(dumped):
    counts = {b: sum(1 for r in dumped if classify(r) == b) for b in BUCKETS}
    assert sum(counts.values()) == len(dumped), counts
    print("conformance buckets:", counts)


def test_every_replayable_case_agrees(dumped, codex_verdict, claude_verdict):
    diffs = []
    for row in (r for r in dumped if classify(r) == "replayed"):
        c, x = claude_verdict(row), codex_verdict(row)
        if c != x:
            diffs.append((row["label"], row["payload"]["tool_name"], c, x))
    assert not diffs, "\n".join(map(str, diffs))   # PER ITEM, never a total (CLAUDE.md aggregate rule)


def test_codex_specific_extras(extra_cases, codex_verdict, claude_verdict):
    for case in extra_cases:
        assert codex_verdict(case) == claude_verdict(case) == case["expect"], case["label"]
```

  (The `codex_verdict`/`claude_verdict`/`extra_cases` fixtures live in the same file. `claude_verdict` pipes the payload to `bash .claude/hooks/<hook>` with the row's env; `codex_verdict` builds the native payload from the fixture and runs the wrapper.)
- [ ] **Step 2: Run.** Expected: FAIL (the dump mode is absent, so 0 cases are dumped and the length assertion fires).
- [ ] **Step 3: Implement the dump hook and the fixtures.**
- [ ] **Step 4: Run.**

```
cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/test_codex_conformance.py
Expected: 3 passed; printed buckets sum to the dumped total
bash ../../scripts/test-hooks.sh
Expected: 177 passed, 0 failed, 0 skipped (dump mode off: unchanged)
```

- [ ] **Step 5: Diagnose any disagreement per item** before touching code. A disagreement is either a translation defect (fix it in the adapter) or a genuine semantic difference that the user must decide on, such as Edit versus Update-File on a non-existent path. **Never edit the corpus or the guards to pass** (spec §11.6).
- [ ] **Step 6: Commit.** `conformance: replay every test-hooks case through the Claude hooks and the Codex adapter in native shape; equal verdicts required`

**Confidence: 82%.** The suite runs about 120 cases through the full chain, so it is slow (M13 decides how slow). It may surface real Edit-versus-patch differences that need a decision.

---

## Task 10: Adapter mutants — each must turn conformance red (spec §7.3)

**Files:** Create `PKG/tests/test_codex_adapter_mutants.py`.

Each mutant is a **text substitution applied to a tmp copy of `.codex/hooks/`**, and the test asserts the substitution matched exactly once, so a no-op mutant fails loudly. The test then runs a **fast conformance subset**: about 15 cases drawn from the extras, one per routing branch, plus the wrapper fault set. It asserts that at least one case flips.

| Mutant | Substitution (target) |
|---|---|
| shell routing dropped | `SHELL = "powershell" if` → `SHELL = "bash" if` (codex_adapter.py) |
| apply_patch paths dropped | `for op, p in ops:` → `for op, p in ops[:0]:` |
| Move-to dropped | `"move_to": "write"` → `"move_to": None` |
| payload cwd ignored | `os.chdir(cwd)` → `pass` |
| deny rendered as exit 2 | the deny render → `sys.stderr.write(reason); sys.exit(2)` |
| ask rendered as `ask` | `"NEEDS YOUR APPROVAL: " + r` with `"deny"` → `"ask"` |
| extra key in output | the render dict gains `"inert": True` |
| wrapper error swallowed to allow | in `codex-entry.ps1`, the fail-closed emitter body → `exit 0` |
| deadline ignored | `x4guard.TIMEOUT_S = ` line → `pass` (with a fault double that hangs one guard) |
| write_stdin unguarded | the `write_stdin` branch → `return []` |

- [ ] **Step 1: Write the test** (parametrised over the table; each row is `(file, old, new, probe_case_id)`).
- [ ] **Step 2: Run it against the unmutated tree** as the control: every probe case agrees. Then run the mutants. Expected: **10 of 10 red**. A mutant that stays green means a missing conformance case: add the case, never weaken the mutant.
- [ ] **Step 3: Commit.** `codex adapter mutants: 10 of 10 turn conformance red`

**Confidence: 85%.**

---

## Task 11: Trust disclosure — in-session banner, outside check, CHANGELOG convention

**Files:**
- Create: `PKG/tests/test_codex_disclosure.py`
- Hand-off text for **lane A** to place in `agent/instructions/codex.md` (below)
- Modify: `CHANGELOG.md` (Unreleased)
- Modify: `agent/README.md`

**Three detectors**, because an unreviewed hook cannot report itself (spec §5.8):
1. **In-session (prose).** Task 4 adds the SessionStart banner. The addendum text for lane A reads:

   > *"At session start you should see the line `X4 GUARDS LIVE (codex hooks v1)`. If you do not, the toolkit's Codex hooks are NOT running: they are unreviewed, were changed by an update, or are disabled. Say so to the user in your first reply, and ask them to run `x4doctor` and to review the hooks in Codex (`/hooks` in the TUI). Until then, Codex's `.rules` and the OS protection on `reference\` are the only guards."*

   This is MEASURED-possible: SessionStart output reaches the model (spike). The model's compliance is ASSUMED, and Task 13 checks it.
2. **Outside (code).** `codex_trust.py report` (Task 3), which lane C's x4doctor calls. It reports per-hook `trusted / untrusted / modified / disabled / unknown`, plus project trust.
3. **Release convention.** Any change to `TEMPLATE_SHA256` requires a CHANGELOG line headed `Codex users must re-review hooks`.

- [ ] **Step 1: Write the failing test.**

```python
# PKG/tests/test_codex_disclosure.py
import hashlib, re
from pathlib import Path
from test_gen_agent_trees import TEMPLATE_SHA256   # the pin from Task 7

REPO = Path(__file__).resolve().parents[3]


def test_template_change_is_announced():
    log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    pinned = re.findall(r"codex-hooks-template: ([0-9a-f]{64})", log)
    assert pinned and pinned[0] == TEMPLATE_SHA256, (
        "the frozen Codex hook template changed: add a CHANGELOG entry headed "
        "'Codex users must re-review hooks' carrying 'codex-hooks-template: <new sha>'")


def test_banner_text_is_one_constant():
    adapter = (REPO / "agent" / "guards" / "adapters" / "codex.py").read_text(encoding="utf-8")
    addendum = (REPO / "agent" / "instructions" / "codex.md").read_text(encoding="utf-8")
    banner = re.search(r'BANNER = "([^"]+)"', adapter).group(1)
    assert banner.split(" —")[0] in addendum      # the model is told to look for EXACTLY what is printed
```

- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement** the CHANGELOG entry and the `BANNER` constant. **Step 4: Run.** Expected: `2 passed`, once lane A has merged the addendum text. Until then, mark the second test `xfail(strict=True)` with the reason `lane A addendum pending`.
- [ ] **Step 5: Commit.** `codex: hook-trust disclosure -- session banner, CHANGELOG re-review convention`

**Confidence: 85%.** The model's compliance with the banner instruction is ASSUMED until Task 13 measures it.

---

## Task 12: Measurement doc and README residuals (no code)

**Files:** Modify `docs/superpowers/measurements/2026-10-02-codex-0160.md` (created in Task 1) and `agent/README.md`.

Record C1–C18, Task 1's probes, M13, and the **residuals the README must state** (D13 disclosure, for lane C's README work):
1. If neither `pwsh` nor `powershell` (Windows) or `bash` (POSIX) can start, **Codex runs the command**.
2. Unreviewed, changed or disabled hooks are **silent** until `x4doctor` or the banner check.
3. **A shell `workdir` is not visible to hooks (C7).** A relative path in a command is judged against the session cwd, which may differ from where the command runs. Layer 2 covers deletes in `reference\`.
4. Tools Codex adds later are allowed until the adapter learns them (Q3).
5. `.rules` are prefix-only, and are INFERRED to load only in a trusted project (P9).
6. Moving the project folder changes the hook definitions (C14), so they need re-review.

- [ ] Commit: `docs: Codex 0.160.0 measurements and the residuals the README must disclose`

**Confidence: 95%.**

---

## Task 13: Live E2E release gate (spec §7.8, local only)

**Files:** Create `scripts/codex-e2e.py`. Its output goes to the session scratchpad, never `/tmp`.

It builds a decoy root: a decoy `reference\` holding a sentinel, a decoy profile and a `dev\` mod. It deploys with `render_codex_hooks_json` plus a copy of the generated tree, and points `X4_*` at the decoy with `X4_CONFIG=/nonexistent`. Then it runs `codex exec` prompts.

**Phase A** uses `--dangerously-bypass-hook-trust` (behaviour). Every outcome is read from disk:
- a shell `Set-Content` into the decoy `reference` → file unchanged, and the transcript names the reason;
- `apply_patch` into it → unchanged;
- `Remove-Item` → unchanged (the hook; Layer 2 when lane D has landed);
- a forbidden-rule command (`git add -A` in a decoy git repo) → index unchanged, with rule text in the transcript;
- a diff-XML patch under `dev\` → the `PostToolUse` validator context appears in the transcript;
- the banner appears.

**Controls:**
- the same prompts with **hooks removed** → the decoy *does* change, which proves the probe can go red;
- **wrapper fault:** rename `codex_adapter.py` → still blocked, with an inert deny.

**Phase B** is trust detection and **needs the user once**. With the hooks unreviewed, `codex_trust.py report` says `untrusted` and the Phase A writes **succeed**, which is the measured reason for disclosure. The user reviews the hooks in the TUI. Then the report says `trusted`, and the Phase A blocks hold without the bypass flag. Finally, edit one template byte in the decoy: the report says `modified`.

- [ ] Expected: every row matches its prediction. Write the per-row table into the measurements doc. A row that fails stops the lane for a decision.
- [ ] Commit: `scripts/codex-e2e.py: live Codex E2E (behaviour with bypass flag, trust detection with one user review)`

**Confidence: 75%.** It depends on model cooperation and on one user TUI review. It cannot run in CI.

---

## Files touched (union)

```
.agents/skills/**                                   (generated)
.codex/hooks/**                                     (generated: guards copy + codex_adapter.py, patch_paths.py, codex_trust.py, codex-entry.ps1, codex-entry.sh)
.codex/rules/x4.rules                               (generated)
.claude/hooks/x4guard.py                            (regenerated, Task 6 only)
.github/workflows/ci.yml
.gitignore
CHANGELOG.md
agent/README.md
agent/guards/adapters/codex.py
agent/guards/adapters/codex-entry.ps1
agent/guards/adapters/codex-entry.sh
agent/guards/adapters/codex_trust.py
agent/guards/adapters/patch_paths.py
agent/guards/claude-hooks/x4guard.py                (Task 6; CONFLICT RISK with lane E)
agent/rules/codex-rules.yaml
agent/targets/codex/hooks.json.tmpl
docs/superpowers/measurements/2026-10-02-codex-0160.md
scripts/capture-codex-fixtures.py
scripts/codex-e2e.py
scripts/test-hooks.sh                               (dump mode only)
tools/x4validate/scripts/gen-agent-trees.py         (CONFLICT RISK with lane A: AGENTS.md render)
tools/x4validate/tests/conftest_codex.py
tools/x4validate/tests/fixtures/codex/0.160.0/**
tools/x4validate/tests/fixtures/codex/conformance_extra.yaml
tools/x4validate/tests/test_codex_adapter.py
tools/x4validate/tests/test_codex_adapter_mutants.py
tools/x4validate/tests/test_codex_conformance.py
tools/x4validate/tests/test_codex_disclosure.py
tools/x4validate/tests/test_codex_fixtures.py
tools/x4validate/tests/test_codex_rules.py
tools/x4validate/tests/test_codex_trust.py
tools/x4validate/tests/test_codex_wrapper.py
tools/x4validate/tests/test_gen_agent_trees.py      (CONFLICT RISK with lane A)
tools/x4validate/tests/test_patch_paths.py
tools/x4validate/tests/test_x4guard_check.py        (Task 6; CONFLICT RISK with lane E)
```

## Cross-lane dependencies

**This lane needs:**
- **A (instruction split):** `agent/instructions/codex.md` carries the Task 11 banner paragraph, and the AGENTS.md render must stay under 32,768 bytes once it is added. A also owns `render_agents_md` in `gen-agent-trees.py`, so the two lanes **edit the same file**: land A's generator change first, or merge by function. Q4 (the skill token) affects A's addendum wording.
- **C (installers / x4doctor):**
  - deploy and installers call `render_codex_hooks_json(root)` and copy `.codex/hooks`, `.codex/rules` and `.agents/skills`;
  - `deploy-parity` / `deploy-claude-dir.py` learn the `.codex/` tree;
  - x4doctor calls `codex_trust.py report`;
  - the README states Task 12's residuals.

  The installer must **never** approve hooks or trust the project (spec §8).
- **D (Layer 2):** the E2E delete row is fully "blocked even with hooks unreviewed" only once D's deny-delete exists. Until then that row is hook-only.
- **E (x4guard hardening):**
  - (1) `_deployed()` accepts `.codex/hooks` (Task 6; whichever lane lands first, the other rebases);
  - (2) implement `X4_GUARD=off` (C16) **in the guards or in x4guard**, never in the adapter. The adapter inherits it, and conformance checks parity;
  - (3) **a guard rule denying agent writes to `.codex/hooks.json`, `.codex/hooks/**`, `.codex/rules/**` and `~/.codex/config.toml`.** Any of these writes is a silent self-disable vector (C3 `enabled=false`; spike R5);
  - (4) optionally, a `timeout` parameter on `run_guard`, replacing Task 4's module-global deadline;
  - (5) the guard-health telemetry hook point: the adapter will call it if E provides one.

**Other lanes need from this lane:** `codex_trust.report` (C), `render_codex_hooks_json` (C), the generated `.codex/` + `.agents/skills` trees (C), the banner constant (A), the fixtures and conformance harness (E, to prove hardening keeps Codex parity), and `patch_paths.parse_patch` (any future adapter, ADAPTING.md).

## Questions for the user

1. **Windows hook entry via PowerShell, not bash (deviates from spec §5.3's bash wrapper).** Codex runs hooks through `cmd.exe /C` (C5), and `bash` there can resolve to the WSL stub (C6). That makes the hook fail, and Codex then runs the command. *Recommend:* a `commandWindows` `pwsh … || powershell …` launcher, which leaves a smaller residual (no PowerShell at all), with `bash` kept for POSIX.
2. **Where the guards live for Codex.** `.codex/hooks/` would be a full generated copy (about 12.5k lines, byte-identical). The alternative is pointing Codex at `.claude/hooks/`. *Recommend:* the copy, so a Codex-only install needs no `.claude/`, and `protect-files` already denies agent edits under the game root's `.codex/` (C17).
3. **Tools the adapter does not know** (MCP tools, future Codex tools), and `write_stdin`. *Recommend:* allow unknown tools, as Claude parity does (Claude does not hook them either), and record their names. Treat `write_stdin` text that contains a newline as a shell command for the guards; Task 1's P4 confirms it is hooked first.
4. **`{{TOOLKIT}}` in Codex skills.** Codex runs PowerShell on Windows, where `$X4_TOOLKIT` is an empty variable. *Recommend:* render `$env:X4_TOOLKIT` for v4.0 (Windows-first), with the mapping in one table that M9 can change for POSIX Codex.
5. **Deny agent edits to Codex's own hook and config files** (lane E implements this). *Recommend:* yes. One `enabled = false` line silently switches the guards off.
6. **Live E2E method.** *Recommend:* use `--dangerously-bypass-hook-trust` for behaviour rows, plus **one** TUI review by you per release for the trust-detection rows. Behaviour cannot prove detection.
7. **Codex subagents** (`.codex/agents/*.toml` in spec §4). The 0.160.0 config shows `[agents.<name>] description/config_file` (READ, strings only), which does not match the spec's assumed file layout. *Recommend:* defer them out of v4.0 until they are measured. The two subagents are optional helpers.

## Confidence summary

| Task | Confidence | What would raise it |
|---|---|---|
| 1 Re-measure + fixtures | 85% | user TUI fallback for P4/P5/P7 |
| 2 Patch parser | 92% | P2 `Move to` capture |
| 3 Trust library | 90% | Codex-produced vectors (Step 3a/3b) |
| 4 Adapter | 85% | P3/P4 results; Q3 decision |
| 5 Wrappers | 88% | live `cmd /C "pwsh … \|\| powershell …"` under Codex (Task 13); M13 numbers |
| 6 x4guard `.codex` | 95% | — |
| 7 Generator + freeze | 88% | Q2 decision; lane C's deploy integration |
| 8 Rules | 80% | inventory reconciled to 17/6/3 per site; P9 |
| 9 Conformance | 82% | first full run's per-item diff list |
| 10 Mutants | 85% | — |
| 11 Disclosure | 85% | Task 13 shows the model reacting to a missing banner |
| 12 Docs | 95% | — |
| 13 Live E2E | 75% | a user review session scheduled |

## Gate plan

- **Per task**, only that task's focused tests, as listed in each task's `Expected:` lines. Plus `gen-agent-trees.py --check` after Tasks 6, 7, 8 and 11, and `scan-identifiers.py` after Tasks 1 and 7.
- **Once, at lane end, in the lane worktree:**
  - `bash scripts/test-hooks.sh` (177 expected, unchanged; this proves the dump mode is inert);
  - `bash .claude/hooks/test-protect-bash.sh`;
  - the full `pytest` (backgrounded, about 30 min);
  - `verify-hook-tests.py`;
  - the mutation gate (backgrounded, about 29 min; never port or commit while it runs, per CLAUDE.md #27);
  - `gates/deploy_parity.py` (after lane C's deploy change);
  - `gates/claude_md_budget.py` (CLAUDE.md is untouched by this lane, so it is expected unchanged);
  - then Task 13's live E2E.
- Compare the full-suite result **per test** against the lane-start baseline, which you record before Task 1, and name every new SKIP.


## Amendments -- 2026-10-02 (user decisions; binding, supersede the text above)

Read DECISIONS.md in this folder first. Changes to THIS lane:
- **#2 changed:** Codex skills/agents keep the token form; the installer renders it per OS (coordinate the token with lanes A and C). Your Q4 answer (`$env:X4_TOOLKIT` everywhere) is superseded.
- **#3:** PowerShell entry on Windows AND a bash entry (codex-entry.sh) on Linux/macOS -- both generated, both tested (the bash one on CI ubuntu, results READ per test).
- **#15:** Linux/macOS best-effort: the adapter's shell routing must pick `--shell bash` off Windows (spec: Codex labels shell calls Bash there, INFERRED, M9); disclose that it is not device-tested.
