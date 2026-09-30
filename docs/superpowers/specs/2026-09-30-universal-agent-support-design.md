# Universal agent support — design

**Date:** 2026-09-30 · **Status:** DRAFT, awaiting user review · **Target release:** v4.0.0

## 1. Goal

Make the toolkit as functional under OpenAI Codex CLI as under Claude Code, **in the public
release**, and as portable as possible to agents we do not know in advance — including by
letting an unsupported agent adapt the toolkit to itself.

### Decisions already made (user, 2026-09-30)

| # | Decision |
|---|---|
| D1 | Scope is the **public release** (installers, README, CI, Nexus), not only the author's machine. |
| D2 | **Blocking guards need strict, tested parity** on every named agent; if parity cannot be proven, that agent's support does not ship. **Advisory** features may be weaker, with every gap documented in the README. |
| D3 | The toolkit is **renamed in the same release** to **"X4 AI Assistant Toolkit"**, repo `x4-ai-assistant-toolkit`. "Assistant" avoids reading as a toolkit for X4's own `aiscripts`/ship AI; the name drops "modding" because the toolkit serves players (modlist triage, debug triage, saves, live queries, compatibility) as much as modders. Tagline: "for players and modders — with Claude Code, Codex, or any coding agent". |
| D4 | Architecture **A: one neutral source, generated per-agent trees** (not Claude-as-source, not hand-kept twins). |
| D5 | **Layered portability model** (§3). Named agents get all layers with tested parity; unknown agents get Layers 0–2 and a documented gap list. |
| D6 | **OpenCode:** the adapter interface is designed for it now; it ships once a live test passes (this release if in time, else the next). |
| D7 | **Self-adaptation:** ship `ADAPTING.md`, `x4guard conformance`, and one universal setup prompt, so a future agent can port the toolkit to itself. |
| D8 | **Escape hatches** (§5.4): a failing guard ASKS (never silently passes); only the user can switch guards off; every hatch is visible. |

### Non-goals

- An MCP server (previously deferred on measurements; it cannot stop an agent bypassing it through its
  own shell, so it is not a safety layer). Revisit separately.
- Rewriting the ~500 `CLAUDE.md #NN` rule citations in code comments — the generated `CLAUDE.md` keeps the
  numbered rules, so they still resolve.
- The author's own game-root `CLAUDE.md` (a personal workspace file, not the shipped one). What to do with
  it is a separate decision; it also settles prompt-audit findings 1–5 and 13 for that workspace.

## 2. Evidence this design rests on

Tier labels per the project's evidence rules. Everything marked READ-DOCS came from official docs as
summarised by a research subagent on 2026-09-30 — **strong leads, not measurements**. §9 lists the live
measurements that must confirm them before the dependent phase starts.

| Fact | Tier | Source |
|---|---|---|
| Codex has `PreToolUse`/`PostToolUse`/`SessionStart`/`UserPromptSubmit` hooks, stable since v0.124; stdin carries `tool_name`/`tool_input`; deny via `permissionDecision:"deny"` or exit 2; context via `additionalContext` | READ-DOCS | learn.chatgpt.com/docs/hooks |
| Codex edits arrive as `apply_patch` (paths inside the patch text); no Grep/Glob tools | READ-DOCS | same |
| Codex project hooks, rules and config load **only in a trusted project** | READ-DOCS | learn.chatgpt.com/docs/config-file/config-basic |
| Codex `AGENTS.md` cap `project_doc_max_bytes` = 32 KiB default; behaviour past the cap unknown | READ-DOCS / UNMEASURED | agents-md, config-reference |
| Codex skills: `SKILL.md` standard, discovered in `.agents/skills/` (not `.claude/skills/`); `allowed-tools` not honoured | READ-DOCS | build-skills |
| Codex subagents: TOML in `.codex/agents/`, `model` field, no per-agent tool allowlist | READ-DOCS | subagents |
| Codex `.rules` (`prefix_rule` allow/prompt/forbidden) in `.codex/rules/` | READ-DOCS | rules |
| OpenCode reads `AGENTS.md` (CLAUDE.md fallback), skills in `.agents/skills` **and** `.claude/skills`; native `permission` config with allow/ask/deny by path glob; plugins (`tool.execute.before`, throw to block) | READ-DOCS | opencode.ai/docs |
| OpenCode risks: plugin hooks on subagent calls unconfirmed; `tool.execute.after` had a never-fired report; reason visibility to the model unconfirmed; WSL recommended on Windows | READ-DOCS (issues, titles only) | anomalyco/opencode issues |
| Toolkit CLIs are agent-neutral; Claude coupling is comments, messages, and the `.claude/x4-paths.env` location | READ (repo inventory) | tools/x4validate |
| Guard logic: `hook_facts.py` (4,087 lines) + `ps_translate.ps1` are generic; verdict policy and protocol I/O live in `protect-bash.sh`, `protect-files.sh`, `search-scope.sh`, `backup-before-edit.sh` | READ | .claude/hooks |
| Today a guard that cannot analyse (no input, no Python, unparseable PowerShell, unresolvable target) returns **ask**, not deny | READ | protect-bash.sh:43,155,198,225,340 |
| Shipped `CLAUDE.md` = **40,887 bytes (39.9 KiB)**; the maintainer-only sections total ~11.9 KB | MEASURED 2026-09-30 | §6 |

## 3. The layered portability model

Each guarantee lives at the lowest layer that can hold it.

| Layer | Reaches | What lives there |
|---|---|---|
| **0 — CLIs** | any agent that runs shell commands | the 11 existing CLIs, plus **`x4guard`** (the guard engine as a command) and **`x4doctor`** (which layers are live) |
| **1 — Plain-text knowledge** | any agent that reads files | generated `AGENTS.md` / `CLAUDE.md`, skills (`SKILL.md` open standard) in `.agents/skills/` and `.claude/skills/`, `ADAPTING.md` |
| **2 — Enforcement below the agent** | every agent, known or not | OS-level protection of `reference\`, `.cat`/`.dat`, the game install (read-only attribute or deny-delete ACL — chosen by measurement, §9); `deploy.py` as the only deploy path; git + `x4canary` as recovery |
| **3 — In-loop hooks** | named agents only | per-agent adapters around `x4guard`: pre-tool block/ask, post-edit validator feedback, session-start checks |

What an **unknown** agent lacks (documented in the README): ask-before-editing profile files, blocking
destructive commands on paths the OS does not protect, and automatic post-edit validator feedback.

## 4. Source layout and generation

```
agent/
  instructions/core.md        both agents; hard cap (§6)
  instructions/claude.md      Claude addendum
  instructions/codex.md       Codex addendum
  skills/<name>/SKILL.md      the skills (moved from .claude/skills; format unchanged)
  agents/<name>.yaml          name, description, instructions, tier: fast|balanced|deep, read_only
  guards/                     x4guard engine + adapters/<agent>/
scripts/gen-agent-trees.py    writes every per-agent file
```

| | Claude Code | Codex | Generic |
|---|---|---|---|
| instructions | `CLAUDE.md` = core + claude addendum | `AGENTS.md` = core + codex addendum | `AGENTS.md` |
| skills | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| subagents | `.claude/agents/*.md` (tier → haiku/sonnet/opus) | `.codex/agents/*.toml` (tier → one editable model table) | — |
| guards | `.claude/settings.json` | `.codex/hooks.json` + `.codex/rules/*.rules` | Layer 2 only |

- **Generated files are committed**, each with a `GENERATED — edit agent/...` header. A CI gate regenerates
  and fails on any difference, so a hand edit cannot survive.
- **Skills use `$X4_TOOLKIT`** everywhere; the `$CLAUDE_PROJECT_DIR` → `$X4_TOOLKIT` `sed` rewrite in both
  installers and the deploy script is removed.
- **`deploy-claude-dir.py` becomes one deploy script for all agent trees**, keeping refuse-on-drift and
  never-delete.
- OpenCode (when it ships) is a third generator target: `opencode.json` permissions + a `.opencode/plugins/`
  shim; it reads the generated `AGENTS.md` and skills as-is.

## 5. Guard engine and adapter contract

### 5.1 One engine

All verdict policy and side effects move into `x4guard` (Python): the rules in the four bash hooks, the
pre-edit backup, post-edit validation, session-start checks (reference version, `x4canary`). Adapters only
translate.

### 5.2 Contract (versioned; JSON on stdin, JSON on stdout)

```
request: {v:1, agent, event: pre_tool|post_tool|session_start,
          kind: shell|write|read|search, shell: bash|powershell|null,
          command, paths[], cwd}
verdict: {v:1, decision: allow|ask|deny, reason, context}
```

### 5.3 Adapter duties, and nothing else

- native payload → request. Path extraction: Claude `tool_input.file_path`; Codex/OpenCode `apply_patch`
  patch text (`*** Add/Update/Delete File:` lines) via **one shared core helper**, not per-adapter code.
- verdict → native reply (Claude `permissionDecision`; Codex deny JSON / exit 2; OpenCode throw).
- declare the agent's context cap; the core orders output directive-first (#38) and fits it
  (Claude 10,000 chars via `X4_HOOK_MAX_CHARS`; Codex ~2,500 tokens per docs — confirm, §9).

### 5.4 Failure handling and escape hatches

- **Guard failure** (no input, no Python, malformed engine output, unanalysable command): verdict **ask**
  with the failure named — today's behaviour, preserved. On an agent that cannot ask, **deny** with the
  failure named. Never a silent allow.
- **User switch-off:** launch the agent with `X4_GUARD=off` → guards downgrade to advisories for that
  session. Launch-time env, not a workspace file, because an agent can create a file but (INFERRED, verify
  per agent, §9) cannot change the environment its hooks inherit. While active: a GUARDS OFF banner at
  session start, every overridden call logged, `x4doctor` reports it.
- **Last resort:** each agent's own hook switch (`/hooks` in Claude Code, `[features] hooks = false` in
  Codex), documented.
- **False positive:** the user runs the command themselves (e.g. `!` in Claude); the case joins the corpus
  so the false-positive gate prevents recurrence.
- **Rules:** the agent can never unlock anything alone; no hatch is silent.

### 5.5 Order of work inside the guards

A **Claude-only, zero-behaviour-change refactor comes first** (§8 phase 2), gated by per-item verdict
equivalence (§7.2). Codex adapter work starts only after it passes.

## 6. Instruction split

- Measured: shipped `CLAUDE.md` 40,887 bytes; Codex default cap 32,768 bytes; the Codex addendum is
  estimated at ~1.5 KB, so the core must shed ~9.5 KB.
- **Core keeps** what a player or modder needs every session: key paths, silent no-op traps, validation,
  dry-run, safety, confidence, copy-don't-compose, assume-live, Nexus research, prove-it-ran, evidence
  scope, Three Values + IS/OOS, knowledgebase, workflow, and the routing table (7,070 bytes; stays because
  it is needed before any skill triggers).
- **Moves to a new `x4-toolkit-dev` skill** (maintainer guidance, relocated not deleted): Derived Artifact
  Must Declare WHEN (3,659), Concurrent Sessions (3,693), A Step That Narrows Data (2,465), Bug Funnel
  (1,227), Tools Trustworthy Before Lock (850) — ~11.9 KB, leaving the core ≈ 29 KB.
- **Core is agent-neutral:** "the guards", `$X4_TOOLKIT`; agent specifics only in addenda.
- **Instruction files are never hand-edited.** Paths come from `x4-paths.env`. User content goes in a
  user-owned **`X4-NOTES.md`**, which the core tells every agent to read if present (no reliance on
  `@import`, which Codex does not expand). Installers never overwrite it.
- **Gates:** generated `AGENTS.md` ≤ 32,768 **bytes**; `CLAUDE.md` keeps its existing budget; a
  neutrality gate fails if the core names a Claude-only tool or variable.

## 7. Testing and CI

1. **Shared guard corpus**: agent-neutral requests + expected verdicts, seeded from
   `test-protect-bash.sh`, `test_hook_facts.py`, `test_audit0924_hooks.py`, the fuzzer, and the
   false-positive gate. Every future false positive or miss becomes a case.
2. **Refactor equivalence gate (one-time)**: old bash hooks vs `x4guard` + Claude adapter over the corpus
   and real recorded payloads, diffed **per item**; every row where the old hook was stricter is read by
   hand (#36). Zero unexplained differences.
3. **Conformance per adapter** in each agent's native payload shape. **Native fixtures are captured from
   real sessions** by a logging hook, never hand-written from docs (shapes #14/#16).
4. **Adapter mutants** (drop paths, invert deny→allow, swallow engine error) must each turn conformance
   red (#26).
5. **Live E2E per agent (release gate, run locally, not CI)** via `claude -p` / `codex exec` (later
   `opencode run`), under Git Bash and PowerShell: a write to a **decoy** protected path and a forbidden
   command are blocked with the reason visible to the model; a diff-XML edit returns validator context;
   session-start checks appear; `x4doctor` reports all layers live.
6. **Layer 2 measured**: `rm -rf` (Git Bash), `Remove-Item -Force`, `del` against a locked decoy; one-off
   Steam "verify files" measurement. Read-only attribute vs deny-delete ACL chosen from the result.
7. **CI additions** (existing three platforms): generator drift gate, conformance for all adapters,
   `AGENTS.md` byte budget, core neutrality, both installers per `--agent`, cold install and
   upgrade-from-3.3.1.
8. **`ADAPTING.md` tests itself**: a toy agent with an invented hook format, whose adapter is written only
   from `ADAPTING.md`, must pass conformance in CI. Before release, a cold docs-only subagent follows the
   Codex install and the adaptation path (red-team of the install flow).
9. **Release**: the `release-review` skill over the full range; a clean review is necessary, not sufficient.

## 8. Installers, rename, migration

- **`--agent claude|codex|opencode|generic|auto`** alongside `--method in-game|separate|global`; `auto`
  installs for every agent found on PATH. `install.sh` and `install.ps1` must agree per agent.
- **`X4_TOOLKIT` is set at OS user level** (Windows user environment / shell-profile snippet). The Claude
  `settings.json` env merge stays for existing installs but is no longer the source.
- **The installer never marks a project trusted** in `~/.codex/config.toml`; it prints the step, and
  `x4doctor` reports "Codex hooks not loaded (project untrusted)" until done.
- **Global installs stay hook-free** (skills, agents, env only) for every agent.
- **`x4-paths.env` moves to the toolkit root**; the old `.claude/` location is still read with a
  deprecation notice; the config-precedence test gains the case.
- **Rename** (D3): GitHub repo `x4-claude-toolkit` → `x4-ai-assistant-toolkit` (redirects keep old links);
  zips `X4.Foundations.AI.Assistant.Toolkit-vX.zip`;
  Nexus title/description updated on page 2186 (upload remains the user's manual step). Local clone folder
  need not change.
- **v4.0.0** (generated instruction files, `X4-NOTES.md`, moved config).
- **Upgrade from 3.x:** an installed `CLAUDE.md` that matches no shipped version's hash is copied to
  `X4-NOTES.pre-4.0.md` before regeneration, with instructions to move personal content into
  `X4-NOTES.md`; never deleted, never guessed. Requires a hash list of every shipped `CLAUDE.md`.
  `settings.local.json`, backups and the `reference\` lock are untouched.

## 9. Measurements before the dependent phase (each can change the design)

| # | Question | Blocks phase | If it fails |
|---|---|---|---|
| M1 | Capture real Codex hook payloads (Bash, `apply_patch` add/update/delete, SessionStart) on this machine | 5 | adapter built from captures, not docs |
| M2 | Can a Codex `PreToolUse` hook return **ask**? | 5 | profile-edit ask via `PermissionRequest` or a `prompt` rule — chosen by test |
| M3 | Codex hooks under Windows: Git Bash vs PowerShell (`commandWindows`) | 5 | per-shell command lines |
| M4 | Untrusted project: are hooks silently absent, and can `x4doctor` detect it? | 5 | a SessionStart canary + doctor probe |
| M5 | Codex behaviour past 32 KiB `AGENTS.md` | 4 | budget gate stays hard regardless |
| M6 | Do hooks inherit launch env, and can an in-session `export` reach them? (per agent) | 3 | switch-off mechanism redesigned |
| M7 | Layer 2: do Git Bash `rm`, `Remove-Item -Force`, `del` fail on a locked decoy? Does Steam verify strip locks? | 6 | ACL-based locking |
| M8 | OpenCode: block a shell call, block a subagent's call, reason visible, `tool.execute.after` fires | OpenCode | OpenCode deferred to next release |

## 10. Phases

1. **Measurements M1–M7** (M8 when OpenCode starts).
2. **Neutral source + generator, Claude target only** — generated `.claude/` byte-identical to today's
   (modulo headers and the `$X4_TOOLKIT` change).
3. **`x4guard` refactor + Claude adapter**, equivalence gate (§7.2).
4. **Instruction split** + `x4-toolkit-dev` skill + `X4-NOTES.md`.
5. **Codex adapter + generated Codex tree**, conformance, mutants, live E2E.
6. **Layer 2 locks + `x4doctor`.**
7. **`ADAPTING.md`, toy-agent test, universal setup prompt** (replaces `SETUP_PROMPT.txt`).
8. **Installers `--agent`, migration, rename, README/CHANGELOG, v4.0.0** via `release-review` + `releasing`.
9. *(Follow-up)* **OpenCode** once M8 passes.

Each phase lands as small commits on master with its gates green before the next starts.

## 11. `ADAPTING.md` contents (D7)

Written to the agent: *"you are an agent this toolkit does not support yet."*
1. Self-assessment checklist → a capability report in a fixed format (instruction file + cap, skills +
   paths, subagents, pre-tool hook + can it block/ask, post-tool, session start, permission/sandbox config).
2. The §5.2 contract.
3. The Claude, Codex (and later OpenCode) adapters as commented worked examples — copy, don't compose.
4. Where the adapter goes (`agent/adapters/<name>/`) and how to register a generator target.
5. **Required proof before any claim:** `x4guard conformance --adapter <cmd>` passes; a live canary (a
   harmless forbidden action on a decoy path) is blocked; `x4doctor` shows the layer live. Until both pass,
   the status is "partially supported, with these gaps".
6. Porting rules: never edit the corpus or the engine to pass; adapters only translate; report every gap.
7. Upstream submission template.

The **universal setup prompt** (paste into any agent): if a native adapter exists for you, install it;
otherwise follow `ADAPTING.md`.

## 12. Risks

- **The guard refactor is the riskiest step**: mitigated by doing it alone, Claude-only, behind a per-item
  equivalence gate.
- **Codex and OpenCode move fast** (weekly releases): conformance fixtures are captured, so a protocol
  change turns CI red; the live E2E is re-run each release.
- **A self-ported adapter can be wrong about its own agent**: it cannot claim protection without
  conformance + canary, and Layer 2 protects the critical paths regardless.
- **Windows sandbox bugs in Codex** (issues #23552, #18558, titles only): Layer 2 does not depend on them.
