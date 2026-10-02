# AGENTS.md — X4 AI Assistant Toolkit (instructions for Codex and other agents)

<!-- GENERATED from agent/ -->

This is a stopgap. The full instructions will be generated here once the shared core fits
Codex's 32 KiB limit (see the spec named at the end). Until then, these rules are the minimum.
Each one exists because breaking it has cost real work in this repo.

## 1. Read `CLAUDE.md` in full before you work

`CLAUDE.md` in this repo root is the project's rulebook: evidence standards, safety rules, how to
check your own work, how changes are made here. It is written for Claude Code but applies to
every agent. **It is too large for your automatic instruction load, so open and read the whole
file yourself.** Where it names a Claude-only mechanism (hooks, skills, `/` commands), follow
the rule's intent with the tools you have.

## 2. Edit `agent/`, never the generated files

`CLAUDE.md`, `AGENTS.md` and `.claude/` (agents, skills, `settings.json`, hooks; not the
per-machine `x4-paths.env*`, `settings.local.json` or `backups/`) are **generated** from `agent/`:

- hook scripts: `agent/guards/claude-hooks/`
- skills: `agent/skills/<name>/` (skill bodies name the toolkit root through a `TOOLKIT`
  placeholder in double curly braces, which the generator renders; keep it, and never write
  an agent-specific variable there instead)
- subagents: `agent/agents/<name>/`
- `CLAUDE.md`: `agent/instructions/core.md`
- this file: `agent/instructions/codex.md`

After editing, regenerate:

    cd tools/x4validate && uv run python scripts/gen-agent-trees.py

A direct edit to a generated file is overwritten by the next regeneration, and
`tests/test_gen_agent_trees.py` fails on it.

## 3. The guards do not protect you under Codex

The toolkit's guards are Claude Code hooks. **Measured on Codex 0.159.2: Codex hooks fail open.**
If a hook crashes, times out, prints bad output or asks a question, Codex runs the command
anyway, and unreviewed hooks do not run at all. So keep these rules by your own discipline:

- never write, move or delete anything in `reference/`, the read-only unpacked game data;
- never write a `.cat` or `.dat` archive directly;
- never write into the game installation;
- never delete inside an X4 directory, the user profile or saves without the user's explicit
  go-ahead.

To ask the guards for a verdict before acting (nothing is executed, nothing is written):

    python .claude/hooks/x4guard.py check --kind shell --shell powershell --command "<cmd>"
    python .claude/hooks/x4guard.py check --kind write --path "<file>"

On Windows, Codex runs its shell commands in **PowerShell**, so pass `--shell powershell`.
Judged as bash, a PowerShell write into `reference/` was measured to pass. Treat `deny` and
`ask` as a stop: ask the user. Treat `inert: true` as "nothing was checked", never as a pass.

## 4. Git

- Stage explicit paths. **Never `git add -A` or `git add .`**: other sessions share this repo.
- Commit finished work on `master`, in small commits. **Never push** unless the user asks.
- Gate a commit on a check's real exit code: run the check bare, capture `rc=$?`, then commit.
  Never `check | tail && git commit`.

## 5. Tests

    cd tools/x4validate && uv run --frozen python -m pytest -q -rs

Bare `python` on the author's machine is 3.10; the toolkit needs 3.13 through `uv`.

## Where the design lives

- `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (why this file exists,
  and what replaces it)
- `docs/superpowers/measurements/2026-09-30-codex-spike.md` (what Codex was measured to do)
