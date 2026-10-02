# agent/ — the neutral source for every agent-facing file

Edit here, never in `.claude/` or `CLAUDE.md`. Regenerate with
`cd tools/x4validate && uv run python scripts/gen-agent-trees.py`.
The design is `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md`.
An INSTALLED toolkit is runtime-only: the installers copy the generated files, never `agent/`.

## The guards

`agent/guards/claude-hooks/` holds the hook scripts. `gen-agent-trees.py` copies them
**byte-identical** into `.claude/hooks/` (executable bits are pinned by a test against git's
index; the generator itself does not set modes), which is now generated: an edit made
there fails `tests/test_gen_agent_trees.py` and is overwritten by the next regeneration. Edit
the files here, regenerate, then deploy with `deploy-claude-dir.py --apply`.

## The instructions: one core, one addendum per agent

`instructions/core.md` is the agent-neutral core. It has no H1 and holds exactly ONE line
`{{AGENT_ADDENDUM}}`. `instructions/<agent>.md` is that agent's addendum: line 1 is an H1 and
becomes the entry file's title (followed by the GENERATED banner), and lines 2+ replace the
marker line. `claude.md` renders `CLAUDE.md`, `codex.md` renders `AGENTS.md`. The generator
refuses (rc 2), never truncates: a missing or doubled marker, an addendum without an H1, a
`{{TOKEN}}` left after rendering, `CLAUDE.md` over 40,000 characters or `AGENTS.md` over
32,768 bytes. Every run prints both sizes.
