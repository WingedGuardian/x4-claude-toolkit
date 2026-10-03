# Universal Agent Support — Plan 3, Lane L: OpenCode, best effort, CLI only

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Every task is test-first: write the test, run it, WATCH IT FAIL for the
> predicted reason, then implement. Branch `session/p3-l` in its own worktree.

**Goal:** `--agent opencode` installs a best-effort OpenCode target instead of refusing: a
**primary** layer of explicit `deny` rules in OpenCode's permission config (per machine, rendered
at install), and a **secondary** layer — a plugin whose `tool.execute.before` asks the toolkit's
guards through a Python adapter and throws on deny. The OpenCode **desktop app is unsupported**.
Every OpenCode-behaviour claim is READ from docs/source; nothing is measured against a running
OpenCode (user decision: no local install).

**Architecture (one mechanism per behaviour):**
- `agent/guards/adapters/opencode.py` -> `.opencode/hooks/opencode_adapter.py`: translate an
  OpenCode tool call into x4guard checks; reuses the Codex adapter's `judge`/`aggregate`/
  `run_backups`/`_abspath`/`_run_hook` (shipped beside it as `codex_adapter.py`). Decides nothing.
- `agent/targets/opencode/x4guard.js` -> `.opencode/plugins/x4guard.js`: transport only (find
  Python, spawn the adapter with a bound, parse ONE `X4OK {...}` line, throw). Exactly ONE export.
- `agent/guards/adapters/opencode_config.py` -> `.opencode/hooks/opencode_config.py`: renders the
  per-machine `.opencode/opencode.jsonc` (deny rules + the addendum instruction) from the roots
  the GUARDS resolve (it sources `_x4-env.sh`, the one bash loader).
- `gen-agent-trees.py` gains an `opencode` target: `.opencode/hooks/` (guards verbatim + 4 adapter
  files), `.opencode/plugins/x4guard.js`, `.opencode/skills/`, `.opencode/X4-OPENCODE.md`.
- `x4guard._deployed()` accepts `.opencode/hooks` (one tuple element).

**Tech stack:** Python >= 3.10 stdlib for everything shipped in `.opencode/hooks/`; plain ESM
JavaScript using only `node:` builtins for the plugin (Bun runs it in OpenCode; Node runs it in our
tests). Python 3.13 via uv for tests and the generator.

---

## Context — what was READ and MEASURED while planning (2026-10-02)

Canonical repo: **`anomalyco/opencode`** (READ: GitHub API `repos/anomalyco/opencode` -> full_name
`anomalyco/opencode`, default branch `dev`, MIT; `sst/opencode` redirects there — READ, issue
https://github.com/anomalyco/opencode/issues/705 and search results). Latest release **v1.18.34**
(2026-09-30). Source READ at tag `v1.18.34` and at `dev` `108b988a` (2026-10-02); every source file
below was diffed tag-vs-dev and is identical in the parts cited unless noted. Raw copies are in the
session scratchpad `plan3/oc/` (not the repo).

| # | Finding | Tier + source |
|---|---|---|
| R1 | Project instructions: `AGENTS.md`, else `CLAUDE.md` (first project-level match wins, walking up from the start dir to the worktree); global `~/.config/opencode/AGENTS.md`, else `~/.claude/CLAUDE.md`. `instructions: [...]` in config adds files (relative ones are glob-searched upward from the start dir). `OPENCODE_DISABLE_CLAUDE_CODE(_PROMPT/_SKILLS)` turn the Claude fallbacks off. No size limit documented or found in code. | READ https://opencode.ai/docs/rules/ ; `packages/opencode/src/session/instruction.ts` |
| R2 | Skills: `.opencode/skills/<n>/SKILL.md`, `.claude/skills/`, `.agents/skills/` (project, walking up) + the global equivalents. Duplicate names: a **warning, and the LAST scanned wins**; `.opencode/skills` is scanned after `.claude`/`.agents`. Name regex `^[a-z0-9]+(-[a-z0-9]+)*$`, must equal the folder; description 1-1024 chars. | READ https://opencode.ai/docs/skills/ ; `packages/opencode/src/skill/index.ts` L125-137, L180-205 |
| R3 | Config files: global -> `OPENCODE_CONFIG` -> project `opencode.json(c)` (walking up to the worktree) -> **`.opencode/opencode.json` and `.opencode/opencode.jsonc`** -> `OPENCODE_CONFIG_CONTENT` -> managed. Merged with remeda `mergeDeep`: keys present only in the later file are APPENDED after the earlier file's keys; **a string in the earlier file is REPLACED by an object in the later one** (so a user's `"edit": "ask"` would be replaced by our deny-only object). JSONC accepted. `OPENCODE_DISABLE_PROJECT_CONFIG` disables project config, `.opencode` dirs (plugins included) and project instructions. | READ https://opencode.ai/docs/config/ ; `packages/opencode/src/config/config.ts` L415-450, `config/paths.ts`; remeda `mergeDeep.ts` (main) |
| R4 | Permissions: actions allow/ask/deny; `edit` covers edit, write, apply_patch; **"the last matching rule winning"**; `*` and `?` wildcards; `--auto` approves asks but "Explicit `deny` rules are still enforced". Agent permissions merge after global and take precedence. | READ https://opencode.ai/docs/permissions/ (source `packages/web/src/content/docs/permissions.mdx`) |
| R5 | **"An explicit deny is final" is only conditionally true.** `evaluate()` = `rulesets.flat().findLast(match)` over `[config ruleset, session-approved]`: an "always" approval is appended AFTER the config, so it overrides a config deny that matches the same input. The edit tools ask with `always: ["*"]`; so if edit ever ASKS (user config `edit: ask`) and the user picks "always", every edit deny is overridden for the rest of that session. Same for bash (`always` = command prefix + ` *`). A user's `agent.<name>.permission` rules are appended after the global ones and can override too. With OpenCode's defaults (edit/bash `allow`, nothing asks) the deny is final. | READ `packages/opencode/src/permission/index.ts` `evaluate`/`ask`/`reply`; `agent/agent.ts` L119-311 (INFERRED from code, not run) |
| R6 | Pattern INPUT strings: edit/write/apply_patch match `path.relative(instance.worktree, filePath)`; worktree = git top-level, or `/` when not a git repo. apply_patch checks only each change's SOURCE path (`c.filePath`), **not a move destination** (`movePath`). bash matches each parsed command node's text. `external_directory` asks for paths outside the worktree. | READ `tool/edit.ts` L95-147, `tool/write.ts` L54-56, `tool/apply_patch.ts` L205-208, `tool/shell.ts` L263-290 + L378-412, `tool/external-directory.ts`, `project/project.ts` L217 |
| R7 | Matcher: backslashes folded to `/` in input AND pattern; regex anchored `^...$`; case-INSENSITIVE on win32; a trailing ` *` is optional. | READ `packages/core/src/util/wildcard.ts@v1.18.34` |
| M1 | `path.relative` on Windows: worktree `/` + `C:\Users\..\reference\a.xml` -> `Users\..\reference\a.xml` (DRIVE-LESS); other drive -> `D:\...` (absolute); `C:\Program Files (x86)\...\X4 Foundations` -> `..\..\..\..\..\Users\...`; inside -> `reference\a.xml`. | MEASURED node v24.19.0 (`plan3/oc/rel.js`) |
| M2 | Real OpenCode `match` (the v1.18.34 file run under node 24 type stripping) against the planned pattern forms: `*Users/<user>/Desktop/Modding/X4/reference/*` matches the drive-less, `..`-chain and upper-cased forms, NOT `reference-backup/` and NOT another drive; `reference/*` matches `reference\a.xml` and NOT `dev\myreference\a.xml`; `*<game>/*.cat` matches `01.cat` and `ext_01.CAT`; `rm *<ref>/*` matches `rm -rf C:/.../reference/x`, not `rm -rf dev/x`, not `cp <ref>/x dev/`; `Remove-Item *<ref>/*` matches `remove-item -Recurse C:\...\reference\x`. 13/13 as predicted. | MEASURED (`plan3/oc/wc_probe.mts`) |
| R8 | Plugins: `.opencode/plugins/` (project) and `~/.config/opencode/plugins/`, JS/TS run by **Bun**; `async ({project, client, $, directory, worktree}) => hooks`; `"tool.execute.before": async (input:{tool,sessionID,callID}, output:{args})`; **throw an Error to block** (docs example). | READ https://opencode.ai/docs/plugins/ ; `packages/plugin/src/index.ts` L261-281 |
| R9 | **A plugin that fails to load is SKIPPED with only a log line** (fail OPEN). A legacy plugin module's EVERY export must be a function and EVERY export is called as a plugin ("Plugin export is not a function" otherwise) — so the plugin file exports exactly one function and nothing else. Hooks are awaited with **no timeout** (the plugin must bound itself). A thrown error propagates out of `tool.execute.before` before `item.execute` runs (Effect.promise -> defect). | READ `packages/opencode/src/plugin/index.ts` L99-127, L219-240, L284-297; `session/tools.ts` L102-125 (INFERRED that a defect aborts the call; the docs state it blocks) |
| R10 | `tool.execute.after` gets `(input:{tool,sessionID,callID,args}, output:{title,output,metadata})`; the same `output` object is returned to the model after the hook, so appending to `output.output` reaches it. | READ `session/tools.ts` L107-125 (INFERRED from code) |
| R11 | Tool ids / args: shell tool id is **`bash` on every OS** (`args.command`, optional `args.workdir`, resolved against the instance directory); the shell that RUNS it is `cfg.shell`, else `$SHELL`, else on Windows the first of pwsh, powershell, Git Bash, cmd. `edit` (`filePath`, `oldString`, `newString`), `write` (`filePath`, `content`), `apply_patch` (`patchText`; Codex patch envelope `*** Begin Patch`/`Add|Update|Delete File:`/`Move to:`, paths resolved against the instance directory). | READ `tool/shell/id.ts`, `tool/shell.ts` L595-630, `packages/core/src/shell.ts` L35-120 + L205-220, `tool/write.ts` L20-43, `tool/apply_patch.ts` L19 + L73 + L142, `tool/apply_patch.txt` |
| R12 | Subagent sessions (task tool) inherit the parent's `deny` and `external_directory` rules. Whether `tool.execute.before` fires inside a subagent session is **UNKNOWN**: issue #5894 "Plugin hooks (tool.execute.before) don't intercept subagent tool calls" (opened 2025-12-21) is CLOSED with no linked PR; a third party's later probe reported it does fire, and a re-run is pending. | READ `agent/subagent-permissions.ts`; https://github.com/anomalyco/opencode/issues/5894 ; https://github.com/nightgauge/nightgauge/issues/1805 |
| R13 | **Desktop app: issue #38604 VERIFIED** — anomalyco/opencode, "Desktop app: local plugins load and register but their hooks (tool.execute.before, event) are never invoked", by SamBWagner, 2026-07-24, **closed as not planned**; Desktop v1.18.4 macOS arm64; the same plugin works under the CLI (v1.17.11, `opencode run`). | READ https://github.com/anomalyco/opencode/issues/38604 |
| R14 | `experimental.chat.system.transform` (input `{sessionID?, model}`, output `{system: string[]}`) lets a plugin add system text — usable as a "guards live" banner whose ABSENCE says the plugin did not load. Experimental. | READ `packages/plugin/src/index.ts` L291-296 |
| M3 | `node` is installed here: **v24.19.0** (`/c/Program Files/nodejs/node`). | MEASURED |
| M4 | **Pre-existing, in-arc, not this lane's:** the generated Codex/generic skills carry `$X4_TOOLKIT`, not the `{{TOOLKIT}}` token (0 of 22 files under `.agents/` hold `{{TOOLKIT}}`, 7 hold `$X4_TOOLKIT`), while Plan 2 DECISIONS #2 says generated skills KEEP the token and the installers render it per OS (`install.sh` `render_toolkit_token`, `X4_TOOLKIT_TOKEN='{{TOOLKIT}}'`). The installer render is therefore a no-op on a real source, and Codex-on-Windows skills say `$X4_TOOLKIT`, which PowerShell expands to EMPTY (lane A MEASURED). The installer test passes because it builds a synthetic source containing `{{TOOLKIT}}` (`test_install_over_existing.py:1521`). | MEASURED (grep counts) / READ — **report to the orchestrator; owner J or H** |

**Not measured, and cannot be under the user's decision (each is disclosed in README):** that
OpenCode loads our plugin/config at all; that the thrown error blocks; R5/R9/R10/R12 behaviour at
runtime; Bun running our `node:`-builtin plugin identically to Node; the Windows default shell
choice in practice.

## Global constraints

- **Never edit generated files** (`.claude/`, `.codex/`, `.agents/`, `.opencode/` outputs, `AGENTS.md`,
  `CLAUDE.md`): edit `agent/`, run `cd tools/x4validate && uv run --frozen python scripts/gen-agent-trees.py`.
- `CLAUDE.md`/`agent/instructions/core.md`: **add nothing** (no headroom; 40,000 ceiling).
  `AGENTS.md`: unchanged (the OpenCode addendum is a separate file loaded via `instructions`).
- Everything in `.opencode/hooks/` is stdlib-only, Python >= 3.10 (no `match`, no 3.11 APIs).
  The plugin uses only `node:child_process`, `node:path`, `node:url`, `node:fs`; ESM; one export.
- Hooks deny/advise the agent; they never prompt the user except X4 profile edits/saves/broken
  guard (repo rule). A guard `ask` becomes a THROW whose message tells the model to ask the user
  (Codex precedent `ASK_PREFIX`/`ASK_SUFFIX`), never an allow.
- Fail CLOSED everywhere we control: no Python, adapter crash, timeout, unreadable output, missing
  adapter, an unknown shell -> throw `X4 GUARD INERT: ...`. Load failure of the plugin itself is
  fail OPEN in OpenCode (R9) and is disclosed, not fixable.
- New helpers are local to their file or prefixed `oc_` / `_oc_` (Plan 2 helper-collision lesson).
- No new `pytest.skip` on CI legs: node-dependent tests `pytest.fail` when `CI` is set and node is
  absent; they skip only off-CI (counted). Never a bare `return` in a test.
- Every hand mutation: apply to `agent/`, regenerate, run the named test RED for the predicted
  reason, revert, delete `__pycache__` under `agent/guards/*` and `.opencode/hooks/`, regenerate,
  GREEN. Table in the commit body.
- Content with backslashes: Write/Edit tools (build `\` as `chr(92)` in Python, `String.fromCharCode(92)` in JS).
- Stage explicit paths; one commit per task on `session/p3-l`; never push. Trailer:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Focused command form: `cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/<file>` — one test process at a time.

## Interfaces

**Produces**
- `x4guard._deployed()` true for `<root>/.opencode/hooks` (and still `.claude`, `.codex`).
- Adapter CLI: `python .opencode/hooks/opencode_adapter.py <pre|post>` with stdin JSON
  `{"v":1,"tool":str,"args":object,"directory":str,"shell":"bash"|"powershell"}`; stdout exactly one line
  `X4OK {"v":1,"decision":"allow"|"advise"|"deny","inert":bool,"reason":str|null,"context":str|null}`,
  exit 0. `ask` is rendered as `deny` with reason `NEEDS YOUR APPROVAL: ... Ask the user; do not retry until they agree.`
- Config renderer CLI: `python .opencode/hooks/opencode_config.py {render|write|check} --root R`
  -> render prints the JSONC; write writes `R/.opencode/opencode.jsonc` (refuses to overwrite a file
  lacking our first-line banner); check rc 0 fresh / 1 stale-or-missing / 2 cannot render.
- Generator: `TARGETS["opencode"]` (skills dir `.opencode/skills/`, token as Codex's), `OPENCODE_ADAPTERS`,
  `render_opencode_tree(src)`, OWNED += `.opencode/hooks/`, `.opencode/plugins/x4guard.js`,
  `.opencode/skills/`, `.opencode/X4-OPENCODE.md`.
- Installers: `--agent opencode` / `-Agent opencode` (NOT part of `all`, see Q1); item set
  `AGENTS.md .opencode`; `.opencode/opencode.jsonc` in KEEP_LOCAL; rendered after copy.
- x4doctor: target `opencode`; rows `opencode.plugin`, `opencode.config`, `opencode.cli` (INFO).
- x4lock: `.opencode/hooks/*.py|*.sh|*.ps1`, `.opencode/plugins/x4guard.js`, `.opencode/opencode.jsonc`,
  `.opencode/skills/*/SKILL.md` (+ `reference/*.md`).

**Consumes**
- Codex adapter (`agent/guards/adapters/codex.py`): `judge(calls, deadline)`, `aggregate(verdicts)`,
  `inert(reason,label)`, `_abspath(p, base)`, `run_backups(ops, base, deadline)`, `_run_hook(...)`,
  `bounded`, `budget_s()`, `ASK_PREFIX`, `ASK_SUFFIX`. **If lane G moves these into a shared adapter
  module, re-point the import at merge (same names).**
- `patch_paths.parse_patch` (shared parser, spec 5.2). `x4guard.resolve_bash`, `x4guard.verdict_for`.
- `_x4-env.sh` (roots as the guards see them). Lane I will change WHERE it reads config; the
  renderer inherits that by sourcing it, by design.

---

## Task 1 — `x4guard` runs from `.opencode/hooks`

**Files:** `agent/guards/claude-hooks/x4guard.py` (L179-182 `_deployed`, L195-196 inert text),
`tools/x4validate/tests/test_x4guard_codex_dir.py`; regenerated `.claude/hooks/x4guard.py`,
`.codex/hooks/x4guard.py`.

Failing test first (append to `test_x4guard_codex_dir.py`):

```python
def test_runs_when_deployed_under_opencode_hooks(tmp_path, env_without_toolkit):
    oc_hooks = tmp_path / "root" / ".opencode" / "hooks"
    shutil.copytree(GUARDS, oc_hooks)
    v = check(env_without_toolkit, oc_hooks / "x4guard.py")
    assert not v["inert"] and v["decision"] == "allow", v["reason"]
```
and extend the twin parametrize with `(".opencode", "guards")` and `(".opencodex", "hooks")` (must
stay inert). Run: `... tests/test_x4guard_codex_dir.py` — Expected: the new test FAILS with
`inert: True` "...not under .claude/hooks or .codex/hooks..."; twins pass.

Implement: `HERE.parent.name in (".claude", ".codex", ".opencode")`; docstring and the inert
message name `.opencode/hooks` too (check `grep -rn "not under .claude/hooks" tools/x4validate/tests`
first — MEASURED 0 hits today, so no test pins the text). Regenerate. Expected: `wrote 2 of N`.

Mutation: revert the tuple element -> the new test RED; restore -> GREEN.

Commit: `x4guard: a copy under .opencode/hooks finds its roots like .claude and .codex (lane L)`

**Confidence 95%.**

## Task 2 — generator: the `opencode` target (hooks copy, skills, addendum)

**Files:** `tools/x4validate/scripts/gen-agent-trees.py`, `agent/instructions/opencode.md` (new),
`tools/x4validate/tests/test_gen_opencode_tree.py` (new); generated `.opencode/hooks/**`,
`.opencode/skills/**`, `.opencode/X4-OPENCODE.md`.

Failing tests first (`test_gen_opencode_tree.py`, modelled on `test_gen_codex_tree.py`: `load()`
by `spec_from_file_location`, autouse skip only when `agent/` is absent):

```python
def test_opencode_hooks_carry_every_guard_byte_for_byte():
    g = load(); out = g.generate(REPO)
    guards = {k[len(".claude/hooks/"):]: v for k, v in out.items() if k.startswith(".claude/hooks/")}
    oc = {k[len(".opencode/hooks/"):]: v for k, v in out.items() if k.startswith(".opencode/hooks/")}
    for rel, text in guards.items():
        assert oc.get(rel) == text, rel
    assert {"patch_paths.py", "codex_adapter.py"} <= set(oc)

def test_opencode_skills_render_the_same_toolkit_token_as_codex():
    g = load(); out = g.generate(REPO)
    for k, v in out.items():
        if k.startswith(".opencode/skills/"):
            assert v == out[".agents/skills/" + k[len(".opencode/skills/"):]], k

def test_opencode_addendum_is_generated_with_a_banner_and_no_claude_mechanism():
    g = load(); text = g.generate(REPO)[".opencode/X4-OPENCODE.md"]
    assert g.BANNER_MD in text and "desktop app" in text.lower() and ".opencode/hooks/x4guard.py" in text
    g.check_neutral(text)          # the neutrality list applies to this file too

def test_opencode_paths_are_owned_so_a_stray_file_is_a_GHOST(tmp_path): ...
    # copy the repo's generated .opencode/hooks into a tmp git repo + one extra file -> problems() names GHOST
def test_a_user_plugin_beside_ours_is_NOT_owned(): 
    g = load(); assert ".opencode/plugins/" not in g.OWNED and ".opencode/plugins/x4guard.js" in g.OWNED
```
Expected RED: `KeyError`/assertion — no `.opencode/` keys in `generate()`.

Implement:
- `TARGETS["opencode"] = {"entry": None, "addendum": "opencode.md", "skills": ".opencode/skills/",
  "tokens": dict(TARGETS["codex"]["tokens"])}` (same skill token as Codex — M4 governs both; when
  the M4 fix lands it fixes both). `render_entry` is never called for opencode.
- `OPENCODE_ADAPTERS = {"patch_paths.py": "patch_paths.py", "codex.py": "codex_adapter.py"}` (Task 3/4
  add `opencode.py` and `opencode_config.py`); `render_opencode_tree(src)`: guards from
  `render_hooks(src)` re-prefixed to `.opencode/hooks/` + adapters (same clash refusal as Codex) +
  `render_skills(src, "opencode")` + `.opencode/X4-OPENCODE.md` = `agent/instructions/opencode.md`
  with `BANNER_MD` after line 1, after `check_neutral()`.
- `OWNED += (".opencode/hooks/", ".opencode/plugins/x4guard.js", ".opencode/skills/", ".opencode/X4-OPENCODE.md")`.
  NOT `.opencode/` (OpenCode itself writes `.opencode/.gitignore`, R3 `ensureGitignore`) and NOT
  `.opencode/plugins/` (a user's own plugin is not ours).
- `generate()`: `out.update(render_opencode_tree(src))`.
- `agent/instructions/opencode.md` (~1.5 KB, line 1 an H1): BEST EFFORT, CLI only, from docs not
  measured; desktop app UNSUPPORTED (#38604); guards ask: `python .opencode/hooks/x4guard.py check ...`
  (`--shell powershell` on Windows unless OpenCode was configured for bash); `deny`/`ask`/`inert`
  are stops; the plugin may not run inside subagents (R12) — check before a write from a subagent;
  `$X4_TOOLKIT` vs `$env:X4_TOOLKIT`; skills under `.opencode/skills/`.

Commands: `uv run --frozen python scripts/gen-agent-trees.py` (Expected: `wrote K of N`, K = new
files), `uv run --frozen python scripts/gen-agent-trees.py --check` (Expected: rc 0), then the two
test files `test_gen_opencode_tree.py test_gen_agent_trees.py` (Expected: all pass).

Commit: `gen-agent-trees: an opencode target -- guard copy, skills and addendum (lane L)`

**Confidence 90%.**

## Task 3 — the OpenCode adapter (Python)

**Files:** `agent/guards/adapters/opencode.py` (new), gen `OPENCODE_ADAPTERS["opencode.py"] =
"opencode_adapter.py"`, `tools/x4validate/tests/test_opencode_adapter.py` (new); generated
`.opencode/hooks/opencode_adapter.py`.

Tests run the GENERATED `.opencode/hooks` copied into a tmp root that has a `.claude/x4-paths.env`
pointing `X4_REFERENCE`/`X4_GAME` at tmp dirs (reuse `codex_testlib` root builders; read it first).
Failing tests first — one per routing clause, each with a twin:

```python
def run(root, event, payload, **env):
    r = subprocess.run([sys.executable, str(root/".opencode/hooks/opencode_adapter.py"), event],
                       input=json.dumps(payload).encode(), capture_output=True, timeout=120,
                       env=dict(os.environ, **env))
    assert r.returncode == 0 and r.stdout.startswith(b"X4OK "), r
    return json.loads(r.stdout[5:])

@pytest.mark.parametrize("tool,args", [
    ("edit",  {"filePath": "{ref}/libraries/wares.xml", "oldString": "a", "newString": "b"}),
    ("write", {"filePath": "{ref}/x.xml", "content": ""}),
    ("apply_patch", {"patchText": "*** Begin Patch\n*** Add File: {ref}/n.xml\n+x\n*** End Patch\n"}),
    ("apply_patch", {"patchText": "*** Begin Patch\n*** Update File: dev/m/a.xml\n*** Move to: {ref}/a.xml\n@@\n-a\n+b\n*** End Patch\n"}),  # move DEST: the permission layer misses it (R6)
    ("bash", {"command": "rm -rf {ref}/libraries"}),
])
def test_a_write_into_reference_is_DENIED(oc_root, tool, args): ...   # decision == "deny", not inert

def test_TWIN_a_write_in_dev_is_allowed(oc_root): ...                 # edit dev/m/a.xml -> allow/advise
def test_a_relative_filePath_resolves_against_the_payload_directory(oc_root): ...   # "../ref/x" from directory=dev
def test_bash_workdir_is_the_cwd_for_a_relative_operand(oc_root): ...  # command "rm -rf x", workdir=<ref> -> deny; TWIN workdir=dev -> allow
def test_an_ask_is_a_deny_that_says_ask_the_user(oc_root): ...        # write into X4_PROFILE -> deny, reason startswith "NEEDS YOUR APPROVAL"
def test_unreadable_payload_and_unparseable_patch_are_INERT_denies(oc_root): ...
def test_an_unknown_shell_is_an_INERT_deny(oc_root): ...              # "shell": "cmd"
def test_tools_that_write_nothing_are_allowed_without_a_guard_run(oc_root): ...  # read/glob/grep/webfetch -> allow
def test_post_on_an_edit_returns_the_validator_advisory_or_nothing(oc_root): ...
def test_X4_GUARD_off_turns_a_deny_into_an_advise_naming_it(oc_root): ...
```
Expected RED: file not found (adapter absent).

Implement `opencode.py` (~180 lines, stdlib): import path set like `codex.py` L46-48 plus
`import codex_adapter as core` (fallback `import codex as core` in the source tree); `handle(event,
raw)`: parse, validate `v`, `os.chdir(directory)`; shell from payload (`bash`/`powershell`, else
inert); routing: `bash` -> `("shell", shell, command)` with cwd = `core._abspath(workdir, directory)`
(chdir there before judging: x4guard reads `os.getcwd()`, lane F); `edit`/`write` ->
`("write", core._abspath(filePath, directory))`; `apply_patch` -> `patch_paths.parse_patch(patchText)`
mapped with the Codex `OP_KIND` (add/update/move_to write, delete/move_from delete); anything else
-> allow. Verdict = `core.aggregate(core.judge(calls, deadline))`; on allow/advise, backups via
`core.run_backups` for existing edit/write targets and patch update/delete ops (Claude parity:
backup-before-edit runs on Edit/Write). `post`: `x4validate-on-edit.sh` per written path via
`core._run_hook` (as `core.post_tool_use` does for patches) -> advise. Render `ask` as deny with
`core.ASK_PREFIX + reason + core.ASK_SUFFIX`. Print `X4OK <json>` ASCII, one line; a top-level
`BaseException` handler prints an inert deny (Codex `main()` pattern).

Mutation twins (each RED on its named test): drop the `move_to` mapping; resolve `filePath`
against `os.getcwd()` instead of `directory`; ignore `workdir`; render `ask` as allow; drop the
inert-on-unknown-shell branch.

Commit: `opencode adapter: OpenCode tool calls judged by the same guards as Codex (lane L)`

**Confidence 85%.** Below 90 because the payload shapes are READ from source (R11), never captured
from a running OpenCode. Raising measurement (allowed under the user's decision, no install): the
tests above use the exact arg names READ in R11; plus a source re-read of `tool/edit.ts`,
`write.ts`, `apply_patch.ts`, `shell.ts` at the newest tag on the day of implementation, diffed
against v1.18.34 (`plan3/oc/tag/`), recorded in the measurements doc (Task 8).

## Task 4 — the permission config renderer (primary layer)

**Files:** `agent/guards/adapters/opencode_config.py` (new), gen `OPENCODE_ADAPTERS[...] =
"opencode_config.py"`, `tools/x4validate/tests/test_opencode_config.py` (new),
`tools/x4validate/tests/fixtures/opencode/wildcard-v1.18.34.mts` (vendored, MIT, attribution header),
`.gitignore` (+ `.opencode/opencode.jsonc`).

**What it emits** (READ R4-R7, MEASURED M1-M2). For each root P the guards resolve (sourcing
`<root>/.opencode/hooks/_x4-env.sh` under `x4guard.resolve_bash()` with `HOOK_DIR` set and the
caller's environment, printing `X4_REFERENCE X4_GAME X4_EXTENSIONS X4_MODS X4_TOOLKIT`
NUL-separated): `D(P)` = P with `/` separators, drive letter and leading `/` removed; `W` = `git -C
root rev-parse --show-toplevel` (none -> `/`).
- `permission.edit`: reference `"*" + D(ref) + "/*"`, plus `relpath(ref, W) + "/*"` when ref is under W;
  `.cat`/`.dat` under each of GAME/EXTENSIONS/MODS/TOOLKIT (protect-files.sh L116-121 scope): `"*" +
  D(P) + "/*.cat"` / `"*.dat"`, plus the W-relative forms. All `"deny"`. **No `"*"` key and no allow
  rule** (an allow would loosen the user's own stricter config).
- `permission.bash` (Q2): for each deletion verb `rm rmdir unlink shred del erase rd Remove-Item ri
  mv move Move-Item mi ren Rename-Item`: `"<verb> *" + D(ref) + "/*"` and `"<verb> *" + D(ref)`,
  `"deny"`. Never a read verb (cp/copy/cat/grep read reference legitimately — M2 `cp` row).
- `"instructions": [".opencode/X4-OPENCODE.md"]`, `"$schema"`, and a first-line comment banner
  `// GENERATED by .opencode/hooks/opencode_config.py for <root> -- per machine; never commit.
  OpenCode support is best effort, from docs, not measured.`
- **Game-install hard block: NOT in this layer** (Q3): protect-files.sh allows a whitelist inside
  the game folder (toolkit dirs, `extensions/` asks, the in-game install where toolkit == game);
  that is only expressible with allow rules, which would loosen user config. The plugin carries it.
- Refuse (rc 2, nothing written) when a root contains `*` or `?`, when a root is unresolved/empty
  for reference, or when bash/`_x4-env.sh` cannot run.

Failing tests first. `oc_match(input, pattern, win)` = a Python port of R7 (folding, escaping, `.*`,
`.`, optional trailing ` *`, `re.S | (re.I if win)`), plus a cross-check test that runs the
vendored REAL `match` under node over the same table and asserts identical results (`CI` + no node
-> fail; no node off-CI -> skip):

```python
TABLE = [  # (input as OpenCode builds it, should_deny)  -- M1 shapes
    ("Users/<user>/Desktop/Modding/X4/reference/a.xml", True),            # worktree "/"
    ("../../../../../Users/<user>/Desktop/Modding/X4/reference/l/w.xml", True),
    ("C:/USERS/someone/Desktop/Modding/X4/reference/a.xml", True),        # win32 case
    ("Users/<user>/Desktop/Modding/X4/reference-backup/a.xml", False),
    ("D:/X4/reference/a.xml", False),
    ("dev/m/libraries/wares.xml", False),
]
def test_rendered_edit_rules_deny_exactly_the_reference_forms(tmp_path): ...
def test_cat_dat_denied_only_under_the_four_roots(tmp_path): ...       # Documents/x.dat -> not denied
def test_reference_inside_the_worktree_gets_the_relative_form_too(tmp_path): ...  # git init root; "reference/a.xml" denied
def test_bash_deletion_verbs_deny_and_read_verbs_do_not(tmp_path): ... # rm/Remove-Item yes; cp/cat/grep no
def test_no_allow_rule_and_no_catch_all_is_ever_emitted(tmp_path): ...
def test_roots_come_from_the_guards_loader_not_a_second_parser(tmp_path): ...  # X4_REFERENCE exported wins, as in _x4-env.sh
def test_a_wildcard_in_a_root_REFUSES(tmp_path): ...                   # rc 2, no file
def test_write_never_overwrites_a_file_without_our_banner(tmp_path): ...
def test_check_reports_stale_after_the_reference_moves(tmp_path): ...  # rc 1
def test_the_python_matcher_agrees_with_opencodes_own(tmp_path): ...  # node cross-check
```
Expected RED: module missing.

Mutation twins: drop the W-relative form (the in-worktree test RED); emit `"*reference/*"` instead
of the full drive-less path (the `reference-backup`/`dev/myreference` twins RED); add `cp` to the
verbs (the read-verb twin RED); emit a `"*": "allow"` (the no-allow test RED).

Commit: `opencode: render the permission deny rules from the roots the guards resolve (lane L)`

**Confidence 75%.** The pattern semantics are MEASURED against OpenCode's own matcher (M2) and
the input forms against Node's `path.relative` (M1), but which string OpenCode feeds the matcher
and the merge/precedence behaviour (R3, R5) are READ, not run. Raising measurement (no install):
the node cross-check test above; re-read `permission/index.ts`, `config.ts` merge and the four
tool files at the newest tag on the implementation day (diff vs `plan3/oc/tag/`).

## Task 5 — the plugin (secondary layer)

**Files:** `agent/targets/opencode/x4guard.js` (new), generator (plugin rendered with a
`// GENERATED ... Do not edit: regenerate.` line 1), `tools/x4validate/tests/test_opencode_plugin_node.py`
(new), `tools/x4validate/tests/fixtures/opencode/drive-plugin.mjs` (new test driver); generated
`.opencode/plugins/x4guard.js`.

Plugin contract (one export, `export const X4Guard = async ({ directory, worktree }) => ({...})`):
- `"tool.execute.before"`: skip tools other than `bash`, `edit`, `write`, `apply_patch` (allow,
  no spawn). Else payload `{v:1, tool:input.tool, args:output.args, directory, shell}`; shell =
  `X4_OPENCODE_SHELL` || (win32 ? (basename of `$SHELL` is bash -> "bash", else "powershell") : "bash")
  (mirrors R11's order for the common cases; `cfg.shell` is NOT read — disclosed; a mismatch fails
  CLOSED because a bash command judged as PowerShell is "could not be translated" -> inert).
  Python = `X4_PYTHON`, then `py -3` (win32), `python3`, `python` (Codex entry order). Adapter =
  `fileURLToPath(new URL("../hooks/opencode_adapter.py", import.meta.url))`. Spawn async with stdin,
  timer = `X4_OPENCODE_TIMEOUT_S` (default 60 > the adapter's 45 s budget), on expiry kill the TREE
  (`taskkill /F /T /PID` on win32, process group on POSIX — x4guard `_kill_tree` reasoning) then
  throw inert. Output must be exactly one line starting `X4OK ` with a JSON object carrying
  `decision` in allow/advise/deny — anything else throws `X4 GUARD INERT: ...`. `deny` -> `throw
  new Error(reason)`. `advise` -> remember `context` by `input.callID`.
- `"tool.execute.after"`: append the remembered advisory (and, for edit/write/apply_patch, the
  adapter's `post` advisory) to `output.output` as `\n\n[X4 guards] ...`; never throws.
- `"experimental.chat.system.transform"`: push `X4 GUARDS LIVE (opencode plugin v1) -- every bash,
  edit, write and apply_patch is checked. If you do not see this line, the plugin did not load.`
- Any exception inside before -> rethrown as inert; nothing ever resolves to allow on error.

Failing tests first (`test_opencode_plugin_node.py`; copies the generated `.opencode/` into a tmp
root with config; `drive-plugin.mjs <plugin> <case.json>` imports the plugin, asserts it has
exactly one export, calls it with `{directory, worktree}`, invokes the hook, prints
`{"threw":bool,"message":...,"output":...}`):

```python
NODE = shutil.which("node")
@pytest.fixture(autouse=True)
def _node():
    if not NODE:
        if os.environ.get("CI"): pytest.fail("node is required on CI for the OpenCode plugin tests")
        pytest.skip("node not installed -- OpenCode plugin transport NOT checked here")

def test_the_plugin_module_has_exactly_one_export(oc_root): ...      # R9
def test_a_reference_edit_THROWS_with_the_guard_reason(oc_root): ...  # real adapter + guards
def test_TWIN_a_dev_edit_does_not_throw(oc_root): ...
def test_a_read_tool_never_spawns_python(oc_root): ...               # X4_PYTHON=<nonexistent> still no throw for "read"
def test_no_python_THROWS_inert(oc_root): ...                        # X4_PYTHON=nonexistent, X4_NO_PYTHON_FALLBACK=1, edit -> throws "INERT"
@pytest.mark.parametrize("stub", ["garbage", "two_lines", "crash", "sleep", "unknown_decision", "empty"])
def test_any_adapter_failure_THROWS_inert(oc_root, stub): ...        # stub opencode_adapter.py; sleep with X4_OPENCODE_TIMEOUT_S=2
def test_an_advise_reaches_the_tool_output_after(oc_root): ...
def test_the_banner_is_added_to_the_system_prompt(oc_root): ...
```
Expected RED: plugin file missing.

Mutation twins: catch-and-ignore errors in before (the failure-stub tests RED); treat a missing
`X4OK ` prefix as allow; export a helper function too (the one-export test RED); drop the tree kill
(the sleep stub test RED on wall-clock bound > timeout + 10 s).

Commit: `opencode: a plugin that throws when the guards deny (lane L)`

**Confidence 80%.** The transport is fully testable under Node here (M3); what stays unmeasured is
Bun-vs-Node behaviour and OpenCode honouring the throw (R8/R9 READ). Raising measurement: the
Node suite; CI must log `node --version` on both legs (read it on the early `ci/` push).

## Task 6 — installers: `--agent opencode` installs best effort

**Files:** `install.sh` (L515-549 agent sets + resolve; KEEP_LOCAL L188; one call site after the
Codex hooks.json writes ~L1414-1455; summary), `install.ps1` (L175 KeepLocal, L318-353 sets +
resolve, matching call site), `tools/x4validate/tests/test_installers_agree.py`,
`tools/x4validate/tests/test_install_over_existing.py`.

Tests changed first — **these pin today's refusal and are REPLACED, not deleted silently**:
`test_both_installers_refuse_opencode_naming_M8` (test_installers_agree.py:369) -> 
`test_both_installers_offer_opencode_as_best_effort` (both texts contain `opencode` and
`best effort`, neither contains `M8`); `test_an_unknown_or_unsupported_agent_REFUSES_before_writing`
(test_install_over_existing.py:1595) loses the `("opencode","M8")` case (keeps `nonsense`). New:

```python
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_agent_opencode_installs_the_opencode_tree_and_renders_its_config(installer, tmp_path):
    src = _agent_source(tmp_path)          # extend the fixture source with a minimal .opencode/
    dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", "opencode", source=src)
    assert r.returncode == 0, _ok(r)
    for rel in ("AGENTS.md", ".opencode/plugins/x4guard.js", ".opencode/hooks/opencode_adapter.py"):
        assert (dest / rel).exists(), rel
    assert not (dest / "CLAUDE.md").exists() and not (dest / ".codex").exists()
    assert "best effort" in r.stdout and "desktop app" in r.stdout.lower()
    assert (dest / ".opencode/opencode.jsonc").is_file() or ".opencode/opencode.jsonc" in r.stdout  # INCOMPLETE named, never silent
def test_all_does_NOT_include_opencode(...)                            # Q1
def test_opencode_jsonc_is_KEEP_LOCAL_in_both(...)                     # never copied from source
def test_an_existing_user_opencode_jsonc_is_never_overwritten(...)     # no banner -> INCOMPLETE named
```
plus extend `test_installers_agree` set-equality checks (they compare the two installers' item
sets and KEEP_LOCAL lists — read them; the new entries must be added to both).

Implement (keep it small; H and I edit these files too): `X4_AGENT_ITEMS_opencode="AGENTS.md .opencode"`;
`X4_AGENT_NAMES` stays `claude codex generic` and the resolve `case` gains
`opencode) X4_AGENTS="opencode" ;;` (ps1 mirror), so `all` is unchanged; `X4_TOKEN_DIRS=".agents .opencode"`
(both — inert until M4 is fixed, then correct for both); KEEP_LOCAL += `.opencode/opencode.jsonc`;
`write_opencode_config DEST`: when `.opencode` is selected, run the first Python found (same order
as Task 5) on `DEST/.opencode/hooks/opencode_config.py write --root DEST`; rc != 0 or no Python ->
`add_failed ".opencode/opencode.jsonc (the permission deny layer was NOT installed: <why>; run ... write --root DEST)"`.
Dry-run: list it, write nothing (`refuse_if_dry_run`). Print once when opencode is selected:
`OpenCode: BEST EFFORT, CLI only, from docs, not measured. The OpenCode desktop app is NOT supported (its plugin hooks never fire, anomalyco/opencode#38604).`
`--method global` refuses `--agent opencode` as it does codex/generic (L1469).

Commands: the four named tests, both installers (`-k opencode`), Expected: pass on Windows.

Commit: `installers: --agent opencode installs a best-effort OpenCode target (lane L)`

**Confidence 80%.** Installer suites are slow and both shells must agree; lane H edits the same
blocks. Raising measurement: run `-k "opencode or agent"` of both test files before and after;
`test_installers_agree.py` in full (it is fast).

## Task 7 — x4doctor and x4lock know the opencode target

**Files:** `scripts/x4doctor.py` (L53 TARGETS, L107-117 `detect_targets`, `guard_dirs` L221-228,
`check_guards` L530-535, a new `check_opencode`), `scripts/x4lock.py` (`_TARGET_DEMANDS` L114-117,
`_GAME_GLOBS`), `tools/x4validate/tests/test_x4doctor.py`, `tools/x4validate/tests/test_x4lock.py`.

Tests changed first — **pinned today**: `test_x4doctor.py:110` (`detect_targets(tmp) == {claude,
codex, generic: False}`) gains `"opencode": False`; `test_an_unknown_agent_filter_is_a_usage_error`
(L119) uses `"nonsense"` instead of `"opencode"`. New: detect on `.opencode/plugins/x4guard.js`;
`opencode.plugin` FAIL when the plugin or `opencode_adapter.py` is missing; `opencode.config`
FAIL when `.opencode/opencode.jsonc` is missing or `opencode_config.py check` rc 1, UNKNOWN on rc 2;
`opencode.config` WARN when the project `opencode.json(c)` or the global config sets
`permission`, `permission.edit` or `permission.bash` to a STRING (R3: our object replaces it);
`opencode.cli` INFO with `opencode --version` if on PATH, always naming "desktop app unsupported";
`guards.selftest.opencode` through the existing guard self-test machinery. x4lock: lock-if-present
globs for `.opencode/hooks/*.py|*.sh|*.ps1`, `.opencode/plugins/x4guard.js`,
`.opencode/opencode.jsonc`, `.opencode/skills/*/SKILL.md`, `.opencode/skills/*/reference/*.md`,
`.opencode/X4-OPENCODE.md`; `_TARGET_DEMANDS[".opencode/hooks"] = ("AGENTS.md", ".opencode/plugins/x4guard.js")`.

Commit: `x4doctor/x4lock: the opencode target (lane L)`

**Confidence 85%** (straight extension of the Codex rows; lane I rewrites config lookup in
x4doctor — merge order L before I keeps this small).

## Task 8 — README, CHANGELOG, measurements record

**Files:** `README.md` (new `### OpenCode: best effort, CLI only, from docs, not measured` after
"Platform support", ~40 lines), `CHANGELOG.md` (Unreleased), `agent/README.md` (targets table row),
`docs/superpowers/measurements/2026-10-02-opencode-read.md` (new: the R/M table above with URLs,
tag/commit, the M1/M2 scripts inline).

README section content (every behaviour claim carries READ + URL): what installs; the two
layers; **desktop app unsupported** (#38604, closed not planned); deny is final only with
OpenCode's defaults — an "always" approval or a per-agent rule can override it (R5), the plugin
still applies; the plugin may not run inside subagents (#5894, R12) while the deny rules do
(R12); a plugin that fails to load is silently skipped (R9) — look for the `X4 GUARDS LIVE` line;
start OpenCode in the toolkit folder (config and plugins are found walking up from the start
dir, R3); `OPENCODE_DISABLE_PROJECT_CONFIG` turns BOTH layers off; Windows shell
(`X4_OPENCODE_SHELL` if you set `shell` in OpenCode's config); a `permission.edit`/`bash` STRING
in your own config is replaced (R3) — write it as `{"*": "ask"}`; re-run
`python .opencode/hooks/opencode_config.py write --root .` after moving reference/game; verify
with `python scripts/x4doctor.py --agent opencode`; MCP tools are not judged.

Test: extend `test_codex_disclosure.py`-style check (new `test_opencode_disclosure.py`, 3 asserts:
README has the heading, names #38604, says "not measured"). Commit:
`docs: OpenCode -- best effort, CLI only, from docs, not measured (lane L)`

**Confidence 90%.**

---

## Files touched (union)

New: `agent/guards/adapters/opencode.py`, `agent/guards/adapters/opencode_config.py`,
`agent/targets/opencode/x4guard.js`, `agent/instructions/opencode.md`,
`tools/x4validate/tests/test_gen_opencode_tree.py`, `tools/x4validate/tests/test_opencode_adapter.py`,
`tools/x4validate/tests/test_opencode_config.py`, `tools/x4validate/tests/test_opencode_plugin_node.py`,
`tools/x4validate/tests/test_opencode_disclosure.py`,
`tools/x4validate/tests/fixtures/opencode/wildcard-v1.18.34.mts`,
`tools/x4validate/tests/fixtures/opencode/drive-plugin.mjs`,
`docs/superpowers/measurements/2026-10-02-opencode-read.md`;
generated `.opencode/hooks/**` (guards + `patch_paths.py`, `codex_adapter.py`, `opencode_adapter.py`,
`opencode_config.py`), `.opencode/plugins/x4guard.js`, `.opencode/skills/**`, `.opencode/X4-OPENCODE.md`.

Modified: `agent/guards/claude-hooks/x4guard.py` (+ generated `.claude/hooks/x4guard.py`,
`.codex/hooks/x4guard.py`, `.opencode/hooks/x4guard.py`), `tools/x4validate/scripts/gen-agent-trees.py`,
`tools/x4validate/tests/test_x4guard_codex_dir.py`, `install.sh`, `install.ps1`,
`tools/x4validate/tests/test_installers_agree.py`, `tools/x4validate/tests/test_install_over_existing.py`,
`scripts/x4doctor.py`, `tools/x4validate/tests/test_x4doctor.py`, `scripts/x4lock.py`,
`tools/x4validate/tests/test_x4lock.py`, `.gitignore`, `README.md`, `CHANGELOG.md`, `agent/README.md`.

Not touched: `CLAUDE.md`, `AGENTS.md`, `agent/instructions/core.md`, `agent/instructions/codex.md`,
`agent/guards/adapters/codex.py`, the frozen `hooks.json.tmpl`, `deploy-claude-dir.py` (the game
root gets no `.opencode/`: nobody runs OpenCode there).

## Verify-hook-tests anchors touched

**None.** `scripts/verify-hook-tests.py` mutates `hook_facts.py`/`test_hook_facts.py` only
(FILES, L45); this lane edits neither. `x4guard._deployed()` has no anchor (MEASURED: grep of
verify-hook-tests.py for `_deployed`/`.codex"` -> 0 hits). Mutation-gate code under
`test_codex_adapter_mutants.py` targets `codex.py`, which this lane does not edit.

## Cross-lane dependencies

- **G (adapters/conformance):** L imports Codex-adapter internals by name (Interfaces/Consumes). If G
  extracts them into a shared module, re-point L's import at merge; if G's `x4guard conformance`
  can drive any adapter, the OpenCode adapter is a natural second subject (stdin JSON in,
  `X4OK` line out) — offer, not required. G and J both edit `x4guard.py`; L's change is one tuple
  element + docstring/message (L179-196).
- **J:** README residuals and CHANGELOG — textual merge only. M4 (skill token) is likely J's or H's.
- **H (installers):** same blocks (agent sets, resolve `case`, summary). H's `--agent auto` should
  detect `opencode` on PATH / an existing `.opencode/` — recommend auto selects opencode only when
  explicitly named (consistent with Q1). H's `X4_TOOLKIT` env-setting is what lets OpenCode's
  shell expand `$X4_TOOLKIT` in skills.
- **I (config move):** `opencode_config.py` sources `_x4-env.sh`, so I's move flows through with no
  L change; I edits x4doctor/x4lock/installers after L — L's additions there are small and named.
- **K (rename):** the addendum and README section use the new product name if K lands first; else K's
  sweep covers them.

## Questions for the user (genuine decisions)

1. **Does `--agent all` include OpenCode?** Recommendation: **No.** `all` stays the measured set
   (claude, codex, generic); OpenCode is installed only when asked for by name, so nobody gets an
   unmeasured guard layer by default.
2. **Bash deny rules in the primary layer?** They can only match the command TEXT, so they catch
   deletion verbs (`rm`, `Remove-Item`, `mv`, ...) aimed at the reference folder by absolute path,
   and nothing else (not redirects, not `python -c`, not relative paths). Recommendation: **include
   them, deletion verbs only** — they keep a little protection where the plugin may not run
   (subagents, a plugin that failed to load) and cannot block a read.
3. **Game-install hard block is plugin-only.** The guard allows a whitelist inside the game folder
   (the in-game install has the toolkit IN the game folder), which a deny-only permission list
   cannot express without allow rules that would loosen your own OpenCode config. Recommendation:
   **plugin-only for the game-install block, disclosed in README**; reference and .cat/.dat get
   both layers.
4. **Vendor OpenCode's 14-line wildcard matcher (MIT, attributed) as a test fixture?** It lets CI
   check our rules against OpenCode's own matcher instead of only our Python port. Recommendation:
   **yes**.

## Confidence per task

| Task | % | Measurement that raises it (if < 90) |
|---|---|---|
| 1 x4guard `.opencode` | 95 | — |
| 2 generator target | 90 | — |
| 3 adapter | 85 | Re-read the four tool sources at the newest tag on the day; diff vs v1.18.34 copies; tests pin the READ arg names |
| 4 config renderer | 75 | Node cross-check against OpenCode's real matcher (vendored); re-read permission/config merge source at the newest tag |
| 5 plugin | 80 | Node transport suite incl. failure stubs and timeout; read `node --version` on both CI legs from the early `ci/` push |
| 6 installers | 80 | `-k "opencode or agent"` on both installer test files before/after; `test_installers_agree.py` in full |
| 7 x4doctor/x4lock | 85 | Full `test_x4doctor.py` + `test_x4lock.py` (focused, fast) |
| 8 docs | 90 | — |

Lowest: **Task 4 (75%)** — the primary layer's correctness rests on READ source for which string
OpenCode matches and how configs merge; only the matcher itself is MEASURED.

## Gate plan (focused only; the orchestrator runs the one full gate per wave)

One test process at a time, from `tools/x4validate`:
1. `uv run --frozen python scripts/gen-agent-trees.py --check` — Expected: rc 0.
2. `uv run --frozen python -m pytest -q -rs tests/test_x4guard_codex_dir.py tests/test_gen_opencode_tree.py tests/test_gen_agent_trees.py tests/test_gen_codex_tree.py` — Expected: pass.
3. `... tests/test_opencode_adapter.py` then `tests/test_opencode_config.py` then `tests/test_opencode_plugin_node.py` — Expected: pass, 0 skips (node present).
4. `... tests/test_installers_agree.py` then `tests/test_install_over_existing.py -k "opencode or agent"` — Expected: pass.
5. `... tests/test_x4doctor.py tests/test_x4lock.py tests/test_opencode_disclosure.py` — Expected: pass.
6. `python scripts/x4doctor.py --root <tmp opencode install> --agent opencode` on a scratch install — Expected: plugin/config rows PASS, cli row INFO.
Report: tests run, skip counts (CI skip ceilings: L adds 0 CI skips by design), deviations, files.
