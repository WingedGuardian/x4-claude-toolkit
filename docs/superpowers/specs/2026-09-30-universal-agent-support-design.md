# Universal agent support — design (v2)

**Date:** 2026-09-30 · **Status:** v2 DRAFT, awaiting user review · **Target release:** v4.0.0
**Evidence:** `docs/superpowers/measurements/2026-09-30-codex-spike.md` (Codex CLI 0.159.2, Windows 11).
v1 and its two addenda are summarised in §13; v2 supersedes them.

## 1. Goal

Make the toolkit work under OpenAI Codex CLI as well as Codex itself allows, **in the public release**.
Make it portable to agents we do not know in advance, including by letting an unsupported agent adapt
the toolkit to itself. "As well as Codex allows" is deliberate: the spike measured that Codex hooks
fail open (§2), so parity is defined per agent (D2, D13).

### Decisions (user, 2026-09-30)

| # | Decision |
|---|---|
| D1 | Scope is the **public release**: installers, README, CI, Nexus. |
| D2 | **Claude Code:** blocking guards keep strict, tested parity, exactly as today. |
| D13 | **Codex:** D2 cannot hold, because Codex runs the command whenever a hook cannot run. Codex support ships with **three enforcement layers plus disclosure**: (1) our hook code never fails silently, and any internal error emits an explicit `deny`; (2) generated `.rules` block the prefix-expressible worst cases, fail-closed and independent of hooks; (3) `reference\` carries the OS deny-delete (D14); and `x4doctor` detects unreviewed or changed hooks from outside. The README states plainly what Codex itself lets through. |
| D3 | Renamed in the same release to **"X4 AI Assistant Toolkit"**, repo `x4-ai-assistant-toolkit`. Tagline: "for players and modders — with Claude Code, Codex, or any coding agent". |
| D4 | **One neutral source, generated per-agent trees.** |
| D5 | **Layered portability model** (§3). |
| D6 | **OpenCode:** the adapter interface allows for it; it ships after its own live measurement (M8). |
| D7 | **Self-adaptation:** `ADAPTING.md`, `x4guard conformance`, one universal setup prompt. |
| D8 | **Escape hatches:** only the user can switch guards off, and every hatch is visible. A failing guard ASKS on agents that can ask (Claude) and DENIES on agents that cannot (Codex). |
| D10 | **Wrap, don't rewrite.** The existing, hardened guards stay the engine. Per-agent adapters only translate. |
| D11 | **Codex "ask":** a generated `.rules` `prompt` where the case is prefix-expressible. Everything else that asks under Claude becomes **deny with instructions** on Codex. |
| D14 | **OS deny-delete on `reference\` only.** Not on the game install, which is Steam-managed, and not on git-tracked trees. |

### Non-goals

- An MCP server. It cannot stop an agent bypassing it through its own shell, so it is not a safety layer.
- Porting the guards to a new engine (D10).
- Rewriting the ~500 `CLAUDE.md #NN` citations in code comments; the generated `CLAUDE.md` keeps the
  numbered rules.
- The author's personal game-root `CLAUDE.md`.

## 2. Evidence

**MEASURED** = on this machine, with controls; see the measurements doc.

| Fact | Tier |
|---|---|
| Codex PreToolUse: only a JSON `permissionDecision:"deny"` blocks. `exit 2` (contradicting the docs), `exit 1`, malformed JSON, `ask`, a timeout and a missing hook script all mark the hook `Failed`, and **the command runs**. | MEASURED (0.154 and 0.159.2) |
| Codex hooks run only after the user reviews them. Approval is stored per hook in `~/.codex/config.toml` as `[hooks.state.'<abs hooks.json>:<event>:<i>:<j>'] trusted_hash`. The hash covers the hook **definition**, not the script it calls. Unreviewed or changed definitions are **silently inert**, with no warning. | MEASURED |
| Codex `.rules`: `forbidden` blocks even with unreviewed hooks. `prompt` asks the user interactively and is rejected non-interactively (approval `never`). Rules match the command inside Codex's `pwsh -Command` wrapper. Prefix-only. | MEASURED |
| Codex on Windows sends shell calls as `tool_name:"Bash"` but runs them in PowerShell 7. The payload does not name the shell. | MEASURED |
| Codex file edits: `tool_name:"apply_patch"`, the patch text in `tool_input.command` (`*** Add/Update/Delete File:` lines). | MEASURED |
| Codex: PreToolUse `additionalContext` and SessionStart stdout reach the model. Bash-invoked hooks run under Git Bash. | MEASURED |
| The existing `protect-bash.sh`, unmodified as a Codex hook, **allowed** a PowerShell overwrite of a decoy `reference\` file. Routed as `tool_name:"PowerShell"`, it **blocked** it. | MEASURED (live, decoy) |
| A launch-time `X4_GUARD=off` is what hooks see, under both Codex and Claude Code, even after the agent sets it to `on` in-session. | MEASURED |
| Codex silently truncates `AGENTS.md` at 32 KiB. `project_doc_max_bytes` in a project `.codex/config.toml` raises the cap. | MEASURED |
| Codex reads skills from `.agents/skills/` and ignores unknown frontmatter keys. | MEASURED (Skyrim session, 0.154) |
| Read-only attribute: blocks 11 of 14 write primitives on Windows, but not `rm -f`, `Remove-Item -Force` or `Copy-Item -Force`. A deny ACL `(W,D,WDAC,WO)` was withdrawn earlier because it blocked reads and could not be removed. | MEASURED earlier (`scripts/x4lock.py`) |
| An inherited `icacls <root> /deny <user>:(OI)(CI)(DE,DC)` blocked **8 of 8** delete primitives; reads, in-place writes and new files still worked; it carries no Synchronize right and is removable unelevated. DE on the file alone does not hold. | MEASURED (scratch tree, user-owned) |
| The game root, `01.cat`, `reference\` and `dev\` are owned by the user, not Administrators. | MEASURED (`Get-Acl`) |
| Codex's built-in policy rejects `Remove-Item -Force` under approval `never` ("blocked by policy"). | MEASURED (incidental; not relied on) |
| OpenCode: reads `AGENTS.md`; skills in `.agents/skills`; `permission` config; plugins that can block. | READ-DOCS only (M8) |
| Shipped `CLAUDE.md` is 40,887 bytes; the maintainer-only sections total about 11.9 KB. | MEASURED |

## 3. The layered portability model

| Layer | Reaches | What lives there |
|---|---|---|
| **0 — CLIs** | any agent that can run a shell | the 11 CLIs, plus `x4guard check` (one front door to the guards) and `x4doctor` (which layers are live) |
| **1 — Plain-text knowledge** | any agent that reads files | generated `AGENTS.md` / `CLAUDE.md`, skills in `.agents/skills/` and `.claude/skills/`, `ADAPTING.md` |
| **2 — Below the agent** | every agent | `reference\`: ~~read-only attribute **plus** inherited deny-delete (D14)~~ *(SUPERSEDED 2026-10-02: the read-only attribute is not applied to `reference\`, MEASURED 0 of 3,429 sampled files)* inherited delete+write deny `(OI)(CI)(DE,DC,WD,AD)`, mask 65606 (D14, decision #14; `scripts/x4refguard.py`), plus the `.unpacked-and-locked` sentinel; Linux/macOS best effort (`chattr +i` / `chflags uchg` / `chmod a-w`). The irreplaceable files: x4lock's read-only attribute (blocks accidental overwrites, 11 of 14). `deploy.py` as the only deploy path; git and `x4canary` for recovery. |
| **3a — Agent-native policy** | agents that have one | Codex `.rules` (`forbidden` / `prompt`), generated. Fail-closed; does not depend on hooks. |
| **3b — In-loop hooks** | named agents | the existing guards behind per-agent adapters |

**What each class of agent gets** (this table goes in the README):

| | Claude Code | Codex | Unknown agent |
|---|---|---|---|
| Deletes in `reference\` | blocked (hook + OS) | blocked (OS; and hook when live) | blocked (OS) |
| Overwrites in `reference\` | blocked (hook + read-only) | blocked when the hook is live; read-only stops accidental ones | read-only stops accidental ones |
| Destructive shell commands elsewhere | blocked or asked (hook) | blocked when the hook is live; the worst prefix cases by rules regardless | not blocked |
| Ask before editing profile files | yes | **deny with instructions** (path-based; rules cannot express it) | no |
| A guard that crashes | asks | **denies** (our wrapper), unless the interpreter cannot start: then **Codex runs the command** | — |
| Hooks not reviewed or changed | n/a | **guards off, silently**: `x4doctor` and the session instructions flag it | — |
| Post-edit validator feedback | yes | yes (when the hook is live) | no |

## 4. Source layout and generation

```
agent/
  instructions/core.md        both agents; ≤ 32 KiB budget (§6)
  instructions/claude.md      Claude addendum
  instructions/codex.md       Codex addendum
  skills/<name>/SKILL.md      the skills (moved from .claude/skills; format unchanged)
  agents/<name>.yaml          name, description, instructions, tier: fast|balanced|deep, read_only
  guards/                     the EXISTING hook scripts, moved as-is, plus:
    entry.sh                  the one stable hook entry point per agent+event (§5.4)
    adapters/claude.py        identity translation (payload already in the guard's shape)
    adapters/codex.py         shell routing + apply_patch split + verdict rendering
    x4guard                   Layer 0 front door (§5.6)
  rules/codex.rules.tmpl      the prefix rules (§5.5)
tools/x4validate/scripts/gen-agent-trees.py   writes every per-agent file
```

| | Claude Code | Codex | Generic |
|---|---|---|---|
| instructions | `CLAUDE.md` = core + claude addendum | `AGENTS.md` = core + codex addendum | `AGENTS.md` |
| skills | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| subagents | `.claude/agents/*.md` (tier → haiku/sonnet/opus) | `.codex/agents/*.toml` (tier → one editable model table) | — |
| guards | `.claude/settings.json` → `.claude/hooks/` | `.codex/hooks.json` + `.codex/rules/x4.rules` → the same guard scripts | Layer 2 only |

- **Generated files are committed**, each with a `GENERATED` banner. A CI gate regenerates them and
  fails on any difference.
- **Skills use `$X4_TOOLKIT`**. The installers' `$CLAUDE_PROJECT_DIR` rewrite is removed when the
  installers change (phase 7). Until then the Claude rendering keeps today's bytes.
- **One deploy script for every agent tree**, keeping refuse-on-drift and never-delete.

## 5. Guards: the existing engine, thin adapters

### 5.1 The engine is unchanged

The engine is `protect-bash.sh` + `hook_facts.py` + `ps_translate.ps1`, `protect-files.sh`,
`backup-before-edit.sh`, `search-scope.sh`, `x4validate-on-edit.sh` and the two session scripts. All
of them, with their tests, mutants, fuzzer and the 23,490-command replay gate, keep their behaviour.
Their input is the **Claude-shaped payload** they already read
(`{tool_name, tool_input:{command|file_path|path, timeout, run_in_background}}`). That shape is the
internal contract every adapter translates to.

### 5.2 Adapter duties, and nothing else

- **Translate the native payload into the guard's shape:**
  - **Claude:** identity.
  - **Codex shell call:** `tool_name` becomes `PowerShell` on Windows (MEASURED). On Linux/macOS it
    stays `Bash` (INFERRED; measured before Codex ships there, M9).
  - **Codex `apply_patch`:** split into one `Write`-shaped payload per `*** Add/Update File:` path, and
    a delete check for every `*** Delete File:` path. Delete checks retain the `Write`-shaped
    protection and also inspect a quoted synthetic removal through `protect-bash.sh`; the
    stricter verdict wins. The removal is never executed. This supersedes the write-only
    deletion mapping after the verified 2026-10-01 front-door audit.
    One shared helper parses patch paths for every adapter.
- **Run the guards it would run under Claude:** shell → `protect-bash.sh`; each file path →
  `protect-files.sh` + `backup-before-edit.sh`. Aggregate: deny beats ask beats advise.
- **Render the verdict for the agent:**
  - **Claude:** unchanged.
  - **Codex:** deny → the JSON deny; ask → JSON deny whose reason starts "NEEDS YOUR APPROVAL:" and tells
    the model to ask the user (D11); advise → `additionalContext`. **Never `exit 2`** (MEASURED fail-open).
- **Fit each agent's context cap.** Claude: 10,000 characters (`X4_HOOK_MAX_CHARS`). Codex: unmeasured,
  so the 10,000-character bound is kept until measured (M10).

### 5.3 Codex fail-closed wrapper

The Codex hook entry is a bash script whose every failure path prints the JSON deny before exiting 0:
a trap on ERR and EXIT, a missing or non-zero adapter, empty or unparseable output, and a timeout
enforced by the wrapper itself **below** the hook timeout Codex is configured with. Residual, disclosed
in the README: if Codex cannot start `bash` at all, it runs the command.

### 5.4 Stable hook definitions (from R4/R5)

Each agent+event has exactly ONE hook definition, pointing at `agent/guards/entry.sh <agent> <event>`
with a fixed timeout. **Definitions are frozen across releases.** A test pins the generated
`.codex/hooks.json` byte for byte. Changing it is a deliberate act: a CHANGELOG line headed "Codex users
must re-review hooks", and `x4doctor` detects the stale approval. Behaviour changes go in scripts,
which keep their approval.

### 5.5 Codex rules (D11, D13 layer 2)

Every rule in `protect-bash.sh` (17 deny, 6 ask, 3 advise, plus the non-fact rules) is classified
**prefix-expressible or not**. The buckets must sum to the total. Prefix-expressible denies become
`forbidden`, prefix-expressible asks become `prompt`, and the rest stay hook-only. The template lists
each rule's source. `codex execpolicy check` tests every generated rule in CI, and each rule has a
must-match and a must-not-match command.

### 5.6 Layer 0 front door

`x4guard check --agent <name> --kind shell|write|delete --shell bash|powershell (--command C | --path P)`
builds the guard-shaped payload, runs the same guards, and prints a neutral verdict JSON:
`{"v":1,"decision":"allow|advise|ask|deny","reason":…,"context":…}`. Unknown agents call it, and so do
`ADAPTING.md` adapters and the conformance suite.

Implemented follow-up (2026-10-01): delete checks compose file hard-block policy with shell
deletion approval policy, using a synthetic quoted command that is inspected, never executed.
The wrapper sets `X4_GUARD_CHECK=1` in child environments; guards signal evaluation failures
with exit 2 in that mode, producing `decision: deny, inert: true`. Native Claude approval
JSON stays unchanged. Plan 2 lane E (2026-10-02): one budget per check, shared by both delete
guards; the guard's process tree is killed on timeout (Windows MEASURED, POSIX via process
group: see CI); worst-case wall clock = `X4_GUARD_TIMEOUT_S` + 8 s. Agent-host enforcement
still requires separate verification.

### 5.7 Escape hatches (D8)

- A launch-time `X4_GUARD=off` (MEASURED, effective under both agents) turns the hook verdicts into
  advisories for that session. While it is active the session-start output carries a GUARDS OFF banner,
  every overridden call is logged, and `x4doctor` reports it. Codex `.rules` and the OS deny-delete do not
  read the variable. They are switched off by the user explicitly (approving a `prompt`, or lifting the
  deny), never by the agent.
- Each agent's own hook switch is the last resort and is documented.
- A false positive becomes a corpus case, and the existing false-positive gate stops it recurring.

### 5.8 `x4doctor`

Per agent, it reports **live / not live / unknown**, and never blank:
- **Claude:** hooks wired in `settings.json`.
- **Codex:** the project is trusted; a `[hooks.state]` entry exists for every current definition; its
  `trusted_hash` matches (the hash scheme is reverse-engineered, or compared live, M11); the rules file is
  present and parses.
- **Layer 2:** the deny entry is present on `reference\`; x4lock status.
- **`X4_GUARD`** state.

The Codex addendum tells the model to run `x4doctor` at session start. That is prose, because an
unreviewed hook cannot report itself.

## 6. Instruction split

- Measured: the shipped `CLAUDE.md` is 40,887 bytes against Codex's 32,768-byte default cap. The core
  sheds about 11.9 KB of maintainer guidance into a new `x4-toolkit-dev` skill (Derived Artifact, Concurrent
  Sessions, Narrowing Data, Bug Funnel, Trustworthy-before-Lock); text is relocated, never deleted. The
  core lands at about 29 KB.
- The core keeps what players and modders need every session, including the routing table.
- The core is agent-neutral; agent specifics live only in the addenda.
- Instruction files are generated and never hand-edited. User content goes in a user-owned
  **`X4-NOTES.md`** that every agent is told to read. Installers never overwrite it.
- **Gates:** generated `AGENTS.md` ≤ 32,768 **bytes** (MEASURED silent truncation past it). `CLAUDE.md`
  keeps its budget gate. A neutrality gate fails if the core names a Claude-only tool or variable.

## 7. Testing and CI

1. **Every existing guard suite stays green and unchanged in meaning:** `test-protect-bash.sh`,
   `test_hook_facts.py`, `test_audit0924_hooks.py`, `scripts/test-hooks.sh`, the fuzzer, the mutants and
   the replay gate.
2. **Adapter conformance:**
   - Every case in the guard corpus is replayed **through each adapter in that agent's native shape**,
     and the adapter's verdict must equal the guard's verdict on the Claude-shaped case.
   - Codex fixtures are the payload shapes captured in the spike, never hand-written from docs.
   - Required cases: PowerShell-as-Bash, multi-file `apply_patch`, `*** Delete File:`, paths with
     spaces and drive dialects.
3. **Adapter mutants, each of which must turn conformance red:**
   - shell routing dropped;
   - `apply_patch` paths dropped;
   - deny rendered as `exit 2`;
   - ask rendered as `ask`;
   - a wrapper error swallowed to allow.
4. **Fail-closed wrapper tests:** a missing adapter, a missing guard script, an adapter that crashes,
   hangs or prints garbage. Each must yield the JSON deny.
5. **Rules tests:** `codex execpolicy check` must-match and must-not-match per rule; bucket counts sum to
   the rule total.
6. **Hook-definition pin:** the generated `.codex/hooks.json` bytes are pinned (§5.4).
7. **Layer 2 tests (scratch tree, Windows CI):**
   - the deny-delete blocks all 8 primitives and leaves read and write working;
   - it is removable;
   - the unpack path lifts it and restores it.
   - Control: the same primitives succeed without the deny.
8. **Live E2E, a release gate run locally:**
   - **Claude:** `claude -p`.
   - **Codex:** `codex exec` against a decoy tree, with the hooks reviewed once (definitions frozen).
   - **Expected outcomes:**
     - a shell write into a decoy `reference\` is blocked, and the model sees the reason;
     - an `apply_patch` into it is blocked;
     - a delete is blocked by the OS even with the hook unreviewed;
     - a forbidden-rule command is blocked;
     - a diff-XML edit returns validator context;
     - `x4doctor` reports every layer correctly, including "hooks not reviewed" when they are not.
9. **CI additions:**
   - the generator drift gate;
   - conformance, mutants and wrapper tests;
   - the `AGENTS.md` byte budget;
   - core neutrality;
   - both installers per `--agent`;
   - cold install, and upgrade from 3.3.1.
10. **`ADAPTING.md` tests itself:** a toy agent whose adapter is written only from `ADAPTING.md` must pass
    conformance. Before release, a cold docs-only subagent follows the Codex install.
11. **Release:** the `release-review` skill over the full range. Full E2E functionality test before and
    after code review.

## 8. Installers, rename, migration

- `--agent claude|codex|opencode|generic|auto` alongside `--method`. `install.sh` and `install.ps1`
  must agree per agent.
- `X4_TOOLKIT` is set at OS user level.
- **Codex:** the installer never trusts a project and never approves hooks; it prints the exact steps.
  `x4doctor` reports until they are done. It writes `project_doc_max_bytes` only if the user opts in.
- The deny-delete on `reference\` is applied by the existing unpack/lock flow (x4lock), and lifted
  before any re-unpack.
- Global installs stay hook-free.
- `x4-paths.env` moves to the toolkit root; the old location is read with a deprecation notice.
- Rename (D3): repo, zips (`X4.Foundations.AI.Assistant.Toolkit-vX.zip`), Nexus page 2186 text. The
  upload stays the user's manual step.
- **v4.0.0.** An upgrade from 3.x preserves a personalised `CLAUDE.md` as `X4-NOTES.pre-4.0.md`, found
  by matching against the hashes of every shipped version.

## 9. Open measurements (each blocks the phase named)

| # | Question | Blocks |
|---|---|---|
| M9 | Codex on Linux/macOS: which shell runs `tool_name:"Bash"` calls? | Codex support on Linux/macOS (Windows ships first if needed) |
| M10 | Codex context cap for `additionalContext` (it spills to disk past some size) | phase 4 output bounding |
| M11 | The `trusted_hash` scheme, or a reliable live check for `x4doctor` | phase 5 doctor |
| M12 | Deny-delete on the REAL `reference\` (user-owned): applies, blocks, lifts, and survives the unpack flow | phase 5 |
| M13 | Hook latency of the wrapped guards under Codex (the Skyrim session measured a bash+jq guard at 300–670 ms p95) | phase 4 (perf budget) |
| M8 | OpenCode live: block, subagent block, reason visible, after-hook fires | OpenCode |

M1–M7 are done (§2).

## 10. Phases

1. **Neutral source + generator, Claude only, zero change.**
2. **Guards move into `agent/guards/` as-is**, plus `entry.sh` and the Claude identity adapter, plus
   `x4guard check`. Gate: every existing suite and the replay gate unchanged.
3. **Instruction split**, the `x4-toolkit-dev` skill, `X4-NOTES.md`.
4. **Codex:**
   - the adapter, wrapper and rules;
   - generated `.codex/` + `.agents/skills` + `AGENTS.md`;
   - conformance, mutants and wrapper tests;
   - live E2E (needs M10, M13).
5. **Layer 2** deny-delete on `reference\` with x4lock integration, and `x4doctor` (needs M11, M12).
6. **`ADAPTING.md`**, the toy-agent test, the universal setup prompt.
7. **Installers**, migration, rename, README/CHANGELOG, v4.0.0 via `release-review` + `releasing`.
8. *(Follow-up)* OpenCode after M8. Codex on Linux/macOS after M9.

Each phase lands as small commits on master, with its gates green and a functionality check before
the next one starts. **Any finding that materially changes the design stops the work for a
decision.**

## 11. `ADAPTING.md` (D7)

Written to the agent: *"you are an agent this toolkit does not support yet."*
1. **Self-assessment** in a fixed capability-report format. It now includes: **does your hook system
   fail open or closed?** (measure it the way the spike did: a deny control, then exit 2, a crash and a
   timeout).
2. **The contract:** translate to the guard's Claude-shaped payload, call `x4guard check` or the
   guards, and render the verdict natively. Never rely on an exit code your agent has not been
   measured to honour.
3. **Worked examples:** the Claude and Codex adapters.
4. **Where the adapter goes**, and how to register a generator target.
5. **Required proof before any claim:** conformance passes; a live canary on a decoy path is blocked;
   `x4doctor` shows the layer live. Until then: "partially supported, with these gaps".
6. **Rules:** never edit the corpus or the guards to pass; adapters only translate; report every gap.
7. **Upstream submission template.**

**Universal setup prompt:** if an adapter exists for you, install it; otherwise follow `ADAPTING.md`.

## 12. Risks

- **Codex fail-open is permanent until OpenAI changes it.** Mitigated by D13's layers and disclosure,
  not eliminated.
- **Silent hook de-approval** on any definition change: definitions are frozen (§5.4), with detection in
  `x4doctor`.
- **Codex release cadence:** the captured fixtures and the live E2E are re-run each release, and a
  protocol change turns conformance red.
- **Shell routing on non-Windows Codex** is unmeasured (M9).
- **Latency:** wrapped bash guards may be slow under Codex (M13).
- **A self-ported adapter can be wrong about its own agent:** it cannot claim protection without proof,
  and Layer 2 holds regardless.

## 13. Revision history

- **v1 (2026-09-30)** proposed a Python rewrite of the guards (`x4guard` engine), Layer 2 as
  OS-locked game install + archives + `reference\` for every agent, and strict parity for every named
  agent. All three were withdrawn on evidence:
  - the repo had already measured that the read-only attribute misses deletes, and had withdrawn a deny
    ACL (x4lock);
  - the spike measured Codex fail-open, and that the existing guard works under Codex once the shell
    is routed (so wrap, D10).
- **Addendum §13 (late 2026-09-30)** put the spec on hold and decided D9 (spike first) and D10–D12
  (pending).
- **Addendum §14** decided D13 and D14 after the spike.
- **v2** folds all of the above into the body.
