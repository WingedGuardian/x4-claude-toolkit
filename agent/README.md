# agent/ — the neutral source for every agent-facing file

Edit here, never in `.claude/` or `CLAUDE.md`. Regenerate with
`cd tools/x4validate && uv run python scripts/gen-agent-trees.py`.
The design is `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md`.

## The guards

`agent/guards/claude-hooks/` holds the hook scripts. `gen-agent-trees.py` copies them
**byte-identical** (modes included) into `.claude/hooks/`, which is now generated: an edit made
there fails `tests/test_gen_agent_trees.py` and is overwritten by the next regeneration. Edit
the files here, regenerate, then deploy with `deploy-claude-dir.py --apply`.
