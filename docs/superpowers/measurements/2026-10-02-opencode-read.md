# OpenCode: what was READ, and the little that was MEASURED (Plan 3 lane L)

**OpenCode support is best effort, CLI only, from docs and source, not measured against a
running OpenCode.** No OpenCode was installed or run for this work (user decision, Plan 3
DECISIONS #2). Every behaviour claim below is READ unless the tier column says otherwise.

Canonical repository: `anomalyco/opencode` (`sst/opencode` redirects there), MIT. Source read at
tag **v1.18.34** (2026-09-30) and at `dev` `108b988a` (2026-10-02); the cited parts were identical.
Re-queried on the implementation day (2026-10-02, `gh api repos/anomalyco/opencode/releases/latest`):
the latest release was still **v1.18.34**, so nothing newer had to be re-read.

Tier key: MEASURED = observed here, with the command; READ = from docs or source, file named;
INFERRED = from reading code, not run (hedged).

| # | Finding | Tier + source |
|---|---|---|
| R1 | Project instructions: `AGENTS.md`, else `CLAUDE.md`; `instructions: [...]` in config adds files (concatenated across configs, deduplicated). `OPENCODE_DISABLE_CLAUDE_CODE(_PROMPT/_SKILLS)` turn the Claude fallbacks off. No size limit found. | READ https://opencode.ai/docs/rules/ ; `packages/opencode/src/session/instruction.ts`; `config/config.ts` `mergeConfigConcatArrays` |
| R2 | Skills: `.opencode/skills/<n>/SKILL.md`, `.claude/skills/`, `.agents/skills/` (walking up) + globals. A duplicate name is a warning and the LAST scanned wins; `.opencode/skills` is scanned after the others. | READ https://opencode.ai/docs/skills/ ; `packages/opencode/src/skill/index.ts` |
| R3 | Config order: global (`<xdg config>/opencode/{config.json,opencode.json,opencode.jsonc}`) -> `OPENCODE_CONFIG` -> project `opencode.json(c)` -> `.opencode/opencode.json` then `.opencode/opencode.jsonc` -> managed. Merged with remeda `mergeDeep`: a string in an earlier file is REPLACED by an object in a later one. JSONC accepted. `OPENCODE_DISABLE_PROJECT_CONFIG` disables project config, `.opencode` dirs (plugins included) and project instructions. OpenCode writes `.opencode/.gitignore` and installs `@opencode-ai/plugin` into `.opencode/` itself. | READ https://opencode.ai/docs/config/ ; `config/config.ts` L272-274, L415-460; `packages/core/src/global.ts` (`xdgConfig`) |
| R4 | Permissions: allow/ask/deny; `edit` covers edit, write, apply_patch; the last matching rule wins; `--auto` approves asks but explicit denies still hold. The built-in defaults start `"*": "allow"`, so a deny-only object falls back to allow. | READ https://opencode.ai/docs/permissions/ ; `agent/agent.ts` L119-135; `permission/index.ts` `fromConfig`/`merge` |
| R5 | "An explicit deny is final" holds only with the defaults: `evaluate()` is `findLast` over `[config rules, session approvals]`, so an "always" approval appended after the config overrides a matching deny, as does a per-agent rule. | INFERRED from `permission/index.ts` `evaluate`/`ask`/`reply`, `agent/agent.ts` |
| R6 | Matched strings: edit/write/apply_patch match `path.relative(worktree, file)` (worktree = git top level, else `/`); apply_patch checks each change's SOURCE path only, not a `Move to:` destination; bash matches each parsed command node's text. | READ `tool/edit.ts`, `tool/write.ts`, `tool/apply_patch.ts`, `tool/shell.ts`, `project/project.ts` |
| R7 | Matcher: `\` folded to `/` in input and pattern; anchored; `*` -> `.*`, `?` -> `.`; case-insensitive on win32; a trailing ` *` is optional. | READ `packages/core/src/util/wildcard.ts` (vendored as `tools/x4validate/tests/fixtures/opencode/wildcard-v1.18.34.mts`) |
| R8 | Plugins: `.opencode/plugins/` + `~/.config/opencode/plugins/`, run by Bun; `tool.execute.before(input:{tool,sessionID,callID}, output:{args})`; throw to block. | READ https://opencode.ai/docs/plugins/ ; `packages/plugin/src/index.ts` |
| R9 | A plugin that fails to load is SKIPPED with a log line (fails open). Every export of a plugin module is called as a plugin. Hooks are awaited with no timeout. | READ `plugin/index.ts`; `session/tools.ts` (INFERRED that a thrown error aborts the call) |
| R10 | `tool.execute.after(input:{...,args}, output:{title,output,metadata})`: appending to `output.output` reaches the model. | INFERRED from `session/tools.ts` |
| R11 | The shell tool id is `bash` on every OS (`command`, optional `workdir`); the shell that RUNS it is `cfg.shell`, else `$SHELL`, else on Windows pwsh/powershell/Git Bash/cmd. `edit` (`filePath`, `oldString`, `newString`), `write` (`filePath`, `content`), `apply_patch` (`patchText`, the Codex envelope). | READ `tool/shell/id.ts`, `tool/shell.ts`, `packages/core/src/shell.ts`, `tool/write.ts`, `tool/apply_patch.ts` |
| R12 | Subagents inherit the parent's deny rules. Whether `tool.execute.before` fires in a subagent session is UNKNOWN: #5894 is closed with no linked fix. | READ `agent/subagent-permissions.ts`; https://github.com/anomalyco/opencode/issues/5894 |
| R13 | Desktop app: plugin hooks are never invoked; closed as not planned. | READ https://github.com/anomalyco/opencode/issues/38604 |
| R14 | `experimental.chat.system.transform` lets a plugin add system text (the `X4 GUARDS LIVE` line). Experimental. | READ `packages/plugin/src/index.ts` |
| R15 | Which tools WRITE (2026-10-04, v4.0.0 review R7-13). `tool/registry.ts` registers, as built-ins: shell (id `bash`, `tool/shell/id.ts`), read, glob, grep, edit, write, task, webfetch, todowrite, websearch, skill, apply_patch, question, lsp (nine read-only queries: definitions, references, hover, symbols, call hierarchy), plan_exit, and -- when enabled -- code-mode `execute`, which can call MCP tools only (`tool/code-mode.ts`). The ones that write a file or run a command are exactly bash, edit, write, apply_patch: the plugin's JUDGED set. NOT judged: MCP tools (also through `execute`, whose child calls fire `tool.execute.before` with the MCP tool's key), custom tools loaded from `{tool,tools}/*.{js,ts}` in a config dir, and tools a plugin defines. OpenCode's own truncation writes (`tool/truncate.ts`) go to its data dir and are not agent-directed. | READ `tool/registry.ts` L101-226, `tool/shell/id.ts`, `tool/lsp.ts` L11-21, `tool/plan.ts`, `tool/code-mode.ts` L134-185, `tool/truncate.ts` |
| M1 | `path.relative` on Windows (node v24.19.0): worktree `/` + `C:\Users\someone\Mods\X4\reference\a.xml` -> `Users\someone\Mods\X4\reference\a.xml` (drive-less); another drive -> `D:\X4\reference\a.xml`; from `C:\Program Files (x86)\Steam\steamapps\common\X4 Foundations` -> `..\..\..\..\..\Users\someone\...`; inside the worktree -> `reference\a.xml`. | MEASURED: `node -e` over `path.relative` (script below) |
| M2 | The rendered deny rules agree with OpenCode's OWN `match()` on every case of the table: `tests/test_opencode_config.py::test_the_python_matcher_agrees_with_opencodes_own` runs the vendored v1.18.34 file under node against the Python port. | MEASURED, every test run (node required on CI) |
| M3 | Git Bash's `pwd` names the Windows temp folder `/tmp/...`, a mount OpenCode never sees; `cygpath -m` silently drops a `*` (`C:\a\b*c` -> `C:/a/bc`). Both shaped `opencode_config.py`. | MEASURED 2026-10-02 (Git for Windows bash) |

M1 script:

```js
const p = require("path");
const B = String.fromCharCode(92);
const w = (s) => s.split("/").join(B);
for (const [a, b] of [["/", w("C:/Users/someone/Mods/X4/reference/a.xml")], ["/", w("D:/X4/reference/a.xml")],
     [w("C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations"), w("C:/Users/someone/Mods/X4/reference/a.xml")],
     [w("C:/tk"), w("C:/tk/reference/a.xml")], [w("C:/tk"), w("D:/ref/a.xml")]])
  console.log(JSON.stringify([a, b, p.relative(a, b)]));
```

## Not measured, and cannot be under the user's decision

That OpenCode loads the plugin or the config at all; that a thrown error blocks the call;
R5, R9, R10 and R12 at runtime; Bun running the `node:`-builtin plugin exactly as node does (the
transport is tested under node only); the Windows default shell in practice. Each is disclosed
in README's OpenCode section.
