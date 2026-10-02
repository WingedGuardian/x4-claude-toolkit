# Codex 0.160.0 hook fixtures — provenance

Every `*.json` here is a REAL hook payload, captured from `codex-cli 0.160.0` on 2026-10-02 by a
capture hook (`scripts/capture-codex-fixtures.py hook`) in a scratch project driven with
`codex exec --dangerously-bypass-hook-trust`, then sanitised with
`scripts/capture-codex-fixtures.py sanitise`. Re-running the sanitiser over the raw captures
reproduced all 14 files byte for byte (MEASURED 2026-10-02). The raw captures carry personal
paths and are not in the repo.

Sanitised: `cwd` -> `<CWD>` (also inside `tool_input`), `transcript_path` -> `<TRANSCRIPT>`, the
`session_id`/`turn_id`/`tool_use_id`/`agent_id` values -> `<SESSION_ID>`..., and the encrypted
`spawn_agent` message -> `<OPAQUE-ENCRYPTED-BLOB>`. Nothing else changed.

| fixture | probe | what it shows |
|---|---|---|
| `session_start.json` | P1 | SessionStart input (`source: startup`) |
| `bash_powershell.json` | P1 | a PowerShell command arrives as `tool_name: "Bash"`, `tool_input` = `{command}` only |
| `post_tool_use_bash.json` | P1 | PostToolUse for a shell call; `tool_response` is the raw output |
| `apply_patch_add.json` / `_update` / `_delete` / `_move` / `_multi` | P2 | `tool_name: "apply_patch"`, the patch text under `tool_input.command`, paths RELATIVE to `cwd` |
| `post_tool_use_apply_patch.json` | P11 | PostToolUse after a patch; `tool_response` is a string with `A`/`M`/`D <path>` lines |
| `bash_shell_heredoc_patch.json` | P3 | `apply_patch <<'PATCH' ...` through the shell arrives as `Bash`, NOT `apply_patch` |
| `bash_exec_command_tty.json` | P4 | an interactive `python -i` start; its two `write_stdin` calls fired NO PreToolUse (0/2) |
| `bash_subagent.json` | P5 | a subagent's shell call is hooked and carries `agent_id`/`agent_type` |
| `spawn_agent.json` / `wait_agent.json` | P5 | the parent's subagent tools arrive as `collaborationspawn_agent` / `collaborationwait_agent` |

`schemas/` holds the per-event command input/output JSON schemas extracted from the 0.160.0
binary (all events, not only the three the adapter uses). The PreToolUse output schema is
`additionalProperties: false` at both levels: an extra key makes the hook `Failed`, and a
failed hook lets the call run.

Measurements and the probe table: `docs/superpowers/measurements/2026-10-02-codex-0160.md`.
