# Plan 2 -- user decisions (2026-10-02). Binding for every lane.

The user accepted every recommendation EXCEPT #15, and #2 changes as a consequence:

1. Yes -- the 6 maintainer-only routing rows move to the x4-toolkit-dev skill (lane A).
2. **CHANGED.** Generated Codex skills/agents keep the `{{TOOLKIT}}`-style token form; the
   INSTALLER renders it per OS: `install.ps1` -> `$env:X4_TOOLKIT`, `install.sh` -> `$X4_TOOLKIT`
   (reuse the existing installer-rewrite mechanism that already rewrites `$CLAUDE_PROJECT_DIR`).
   The toolkit-repo copy (used in place) renders `$env:X4_TOOLKIT` on Windows only if the
   generator can know the OS -- otherwise keep the AGENTS.md note telling Codex on Windows to
   use `$env:X4_TOOLKIT`. Lanes A, B and C agree the token and the rewrite before building.
3. Yes -- Windows Codex hook entry via PowerShell (pwsh, else powershell); bash entry on Linux/macOS.
4. Yes -- full guard copy under `.codex/hooks/`.
5. Yes -- unknown tools allowed and their names recorded; `write_stdin` text with a newline is
   checked as a shell command.
6. Yes -- guards deny agent edits to `.codex/hooks.json` and `~/.codex/config.toml`.
7. Yes -- live E2E uses `--dangerously-bypass-hook-trust` for behaviour + one manual review per release.
8. Yes -- Codex subagents deferred past v4.0.
9. Yes -- an installed toolkit is runtime-only (no `agent/`).
10. Installer `--agent` defaults to `all`.
11. Yes -- x4lock also locks `.agents/skills/*/SKILL.md`.
12. Yes, later -- generator hash manifest for x4doctor (not in this plan unless trivial).
13. Update -- the game-root AGENTS.md is regenerated from lane A's output (it currently points at
    the archived Desktop tools\x4validate).
14. **RESOLVED by measurement: delete+WRITE deny `(OI)(CI)(DE,DC,WD,AD)`, mask 65606** -- reads 12/12 OK, writes 20/20 + deletes 15/15 blocked, removable 47/47 (measure-D.md).
15. **CHANGED: Linux/macOS get BEST-EFFORT support now -- not Windows-only.** No full device
    testing, but implement what we can: lane D adds the POSIX equivalent (Linux `chattr +i` when
    privileged, else a `chmod a-w` fallback on dirs+files; macOS `chflags uchg` / `chmod`), with
    status reporting exactly what was applied and what was not. Unit tests with fakes/disposable
    dirs; run on the CI ubuntu leg where possible and READ those results per test. README labels
    POSIX support "best effort, not device-tested". Every lane: do not write Windows-only code
    where a portable form is cheap; where it is not, implement the POSIX branch best-effort and
    disclose the gap. (Lane E: the POSIX process-group kill is in scope, tested on CI ubuntu.)
16. Yes -- lifting the deny: Claude `ask`, Codex `.rules` prompt.
17. Yes -- `X4_XRCAT` override in unpack-reference.sh as a test hook.
18. Yes -- strict agent names `^[a-z0-9][a-z0-9-]*$`.
19. Yes -- implement `X4_GUARD=off` (the documented escape hatch) in lane E.

## Merge order (shared files)
E -> A -> C -> D -> B. Measurement-only tasks may run in any lane at any time.
Shared files: gen-agent-trees.py (E, A, B), x4guard.py (E, B), x4lock.py (C then D),
.gitignore (A, B), ci.yml (B, D), CHANGELOG.md (all -- append-only entries).
