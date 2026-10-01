# Codex / Layer-2 measurement spike — 2026-09-30

For: spec `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` §13 (D9–D12).
Machine: Windows 11, Git Bash 5.2.37 (msys), PowerShell 7. **Codex CLI 0.159.2**, model `gpt-6-luna`
(reasoning low). Every probe ran in a scratch folder under the session scratchpad (written `<scratch>`
below), never against the game root, `reference\`, `dev\` or the profile. Every Codex outcome is
read from **disk** (did a flag file appear / survive), never from the model's own report.

Prior evidence used: a Skyrim-session probe on Codex **0.154.0** earlier the same day (raw hook log and
five run transcripts, read directly; never written up there). Every 0.154 finding below was re-run on
0.159.2.

## Results

### Hook gates and failure semantics (Codex)

| # | Probe | Prediction | Result (0.159.2) | Tier |
|---|---|---|---|---|
| R1 | hooks present, **not reviewed**, no bypass flag | silently inert | **Silently inert**: no hook ran, no `hook:` line, no warning; even the `deny` case created its file | MEASURED |
| R2 | after user review in the TUI: control `deny` | blocked | **blocked** (`Command blocked by PreToolUse hook: probe deny`) | MEASURED |
| R2 | control: allow (exit 0, no output) | runs | runs | MEASURED |
| R2 | `exit 2` + reason on stderr | runs (fail-open), though the doc says it blocks | **runs** — `PreToolUse Failed`, command proceeds. **Contradicts learn.chatgpt.com/docs/hooks** | MEASURED |
| R2 | `exit 1` | runs | **runs** (`Failed`) | MEASURED |
| R2 | malformed JSON on stdout | runs | **runs** (`Failed`) | MEASURED |
| R2 | `permissionDecision:"ask"` | runs (doc: unsupported) | **runs** (`Failed`) | MEASURED |
| R2 | hook sleeps 20 s, timeout 5 s | runs | **runs** (`Failed`) | MEASURED |
| R3 | hook script missing (definition unchanged) | runs | **runs** (`Failed`) | MEASURED |
| R4 | script CONTENT edited after review | still active | **still active** (new deny text came through) | MEASURED |
| R5 | hook DEFINITION edited (timeout 5→6) after review | inert | **silently inert**: no hook ran, no warning | MEASURED |
| R6 | control: definition restored byte-for-byte | active again | **active again** (blocked) | MEASURED |

**Conclusion — Codex PreToolUse hooks fail OPEN.** Only an explicit JSON `deny` blocks. A crash,
timeout, bad output, `ask`, `exit 2` or a missing script all let the tool call run. **Review state**
lives in the user's global `~/.codex/config.toml` as
`[hooks.state.'<abs path to hooks.json>:<event>:<i>:<j>'] trusted_hash = "sha256:…"`, and the hash
covers the hook DEFINITION, not the script it runs. Any toolkit update that changes a hook definition
silently switches the guards off until the user re-reviews.

### Rules (Codex execpolicy)

| # | Probe | Result | Tier |
|---|---|---|---|
| RULE | `.codex/rules/*.rules` `prefix_rule(... decision="forbidden")` | **blocked** (`rejected: probe: forbidden by rule`), **even while the hooks were unreviewed (R1)**. Matches the command INSIDE Codex's `pwsh -Command '…'` wrapper | MEASURED |
| S3a | `decision="prompt"`, non-interactive `codex exec` (approval `never`) | **rejected** (`approval required by policy, but AskForApproval is set to Never`) — fails closed | MEASURED |
| S3b | `decision="prompt"`, interactive TUI, user present | **the USER got an approval prompt** (not the auto-review model); the command ran only after approval | MEASURED (user-observed) |

Rules are a **fail-closed** layer that does not depend on hooks or hook review. Their limit: prefix
matching on the command's tokens, so they cannot express "a delete whose TARGET is under reference\".

### Payload shape and shell (Codex on Windows)

- PreToolUse stdin: `session_id, turn_id, transcript_path, cwd, hook_event_name, model,
  permission_mode, tool_name, tool_input, tool_use_id`. SessionStart: `session_id, transcript_path,
  cwd, hook_event_name, model, permission_mode, source`. Compact JSON (no spaces).
- **Shell commands arrive as `tool_name:"Bash"` but are PowerShell**, executed as
  `"C:\Program Files\PowerShell\7\pwsh.exe" -Command '…'`. Nothing in the payload names the shell.
- File edits: `tool_name:"apply_patch"`, the patch text in `tool_input.command`
  (`*** Begin Patch` / `*** Add File:` / `*** Update File:` lines).
- `additionalContext` from PreToolUse and plain stdout from SessionStart both reach the model
  (Skyrim-session markers `SPIKE-CONTEXT-TOKEN-9191`, `SPIKE-SESSIONSTART-MARKER-4242`).
- Bash-invoked hooks (`"command": "bash \"…\""`) run under Git Bash on Windows.

### Reusing the existing guard (D10) — live, decoy tree

`protect-bash.sh` wired unmodified as a Codex hook, `X4_*` roots pointed at a decoy tree,
`X4_CONFIG=/nonexistent`:

| Wiring | `Set-Content -Path '<decoy>\reference\libraries\wares.xml' -Value 'OVERWRITTEN'` |
|---|---|
| as-is (payload says "Bash") | **ALLOWED — the decoy was overwritten** |
| Codex shell calls routed as `tool_name:"PowerShell"` | **BLOCKED**: `reference/ is the read-only unpacked base game data — never write into it` |

Offline, with the real deployed hook and the real environment: `Remove-Item -Force '<real reference
path>'` → **deny** as `tool_name:"PowerShell"`, **allow** as `tool_name:"Bash"`. A first live attempt
with `Remove-Item -Force` was VOID: Codex's own built-in policy rejected it (`blocked by policy`)
before our hook mattered. User rules were checked and are all `allow`, so this was Codex itself.

**Conclusion:** the hardened guard works under Codex when the adapter tells it the real shell. Reused
raw, it has a live hole.

### Environment inheritance (switch-off, spec §5.4)

| Agent | Launched with `X4_GUARD=off`; agent then sets it to `on` in-session | Tier |
|---|---|---|
| Codex | every hook call saw `off` | MEASURED |
| Claude Code (`claude -p`, Haiku) | both hook calls saw `off` | MEASURED |

A launch-time switch cannot be flipped by the agent from inside the session.

### AGENTS.md size cap (Codex)

46,737-byte `AGENTS.md`, sentinel A first line, sentinel B last line: **A seen, B UNKNOWN, no warning**
in the output. Control (1,547 bytes): both seen. Codex 0.154 (Skyrim session) showed the same, and that
raising `project_doc_max_bytes` in the project `.codex/config.toml` restores the tail. **Silent
truncation at 32 KiB, MEASURED on both versions.**

### Delete protection (D12) — scratch tree only

`scripts/x4lock.py` already measured the read-only attribute: 11/14 write primitives blocked, NOT
`rm -f` / `Remove-Item -Force` / `Copy-Item -Force`; a deny ACL `(W,D,WDAC,WO)` was withdrawn (W
includes SYNCHRONIZE so reads failed; WDAC made it unremovable on Administrators-owned files).

New probe: `icacls <root> /deny <user>:(OI)(CI)(DE,DC)` on a user-owned scratch tree.

| Check | Result |
|---|---|
| ACE recorded | `Delete, DeleteSubdirectoriesAndFiles`, inherited by children — **no Synchronize** |
| DELETE denied on a file alone (no DC on parent) | **does NOT hold** (parent's delete-child right allows it) |
| Gate 1: remove at root, unelevated, before any attack | **0 deny entries left anywhere** |
| 8 delete primitives (`rm -f`, `Remove-Item -Force`, `del /f /q`, `os.remove`, move/rename, `.cat` `-Force`, `rm -rf` tree, `Remove-Item -Recurse -Force` tree) | **8/8 survived** (control without the deny: all deleted) |
| read / in-place write / create new file | **all still work** (so overwrite protection still needs the read-only bit) |
| Gate 2: final removal | **0 deny entries left** |

**Ownership (MEASURED, `Get-Acl`):** the game root, `01.cat`, `reference\` and `dev\` on this machine
are owned by the user, not Administrators — the condition under which the old ACL became
unremovable does not hold here. **Not measured:** the same deny on the real paths; Steam updates or
"verify files" against a denied game install (Steam replaces files, which needs DELETE, so INFERRED:
it would break updates unless removed first); git operations on a denied tracked file (git replaces
files by unlink, so INFERRED: checkout/stash would fail on a denied tree).

## What this changes (for the spec revision; decisions are the user's)

1. **D2 as written ("strict, tested parity on blocking guards") is not achievable for Codex.** Our code
   can be made never to fail (always an explicit `deny` on any internal error), but Codex lets a call
   through whenever the hook cannot run at all, and silently skips unreviewed or changed hooks.
2. **Codex needs three layers, not one:** hooks (via the existing guard plus a shell-routing adapter),
   **rules** `forbidden` for the prefix-expressible worst cases (fail-closed, independent of hook
   review), and **OS-level deny-delete** on `reference\` (independent of any agent).
3. **D11: a real "ask" exists on Codex:** rules `prompt`. It asks the user interactively and refuses
   non-interactively. It is prefix-only; path-based asks fall back to deny-with-instructions.
4. **D10: wrap, don't rewrite.** The live decoy test shows the existing guard blocks correctly once
   the adapter supplies the real shell. The adapter must also split `apply_patch` into file paths for
   `protect-files.sh`.
5. **x4doctor must check hook review from outside:** compare each `[hooks.state.'…']` `trusted_hash`
   entry against the current `hooks.json` definitions (the hash input still needs reverse-engineering
   or a live comparison), because an unreviewed hook cannot report itself.
6. **Every hook DEFINITION change is a breaking change for Codex users** (silent until re-review). Keep
   definitions stable and put behaviour in the scripts they call.
7. **Layer 2 can be stronger than "accidental overwrites"** for `reference\`: deny-delete plus the
   read-only bit. It is not suitable for the Steam-managed install or for git-tracked trees without
   an unlock step (both INFERRED, unmeasured).

## Not done in this spike

Steam "verify files" against a protected tree; the deny on any real path; git interplay; OpenCode (M8);
Linux/macOS Codex (Codex runs bash there, so the shell routing differs — unmeasured).
