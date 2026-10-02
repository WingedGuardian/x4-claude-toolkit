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
## Codex (`.codex/`)

`gen-agent-trees.py` also writes the Codex target:

- `.codex/hooks/` = every file of `guards/claude-hooks/` **byte-identical**, plus the adapter
  files from `guards/adapters/` (`codex.py` is rendered as `codex_adapter.py`; `patch_paths.py`,
  `codex_trust.py`, `codex-entry.ps1`, `codex-entry.sh` keep their names). The adapter only
  translates: the guards decide, for Codex exactly as for Claude Code.
- `.codex/rules/x4.rules` from `rules/codex-rules.yaml`, which classifies EVERY verdict site in
  `protect-bash.sh` as `forbidden`, `prompt` or `hook_only`. A prefix rule is never stricter
  than the guard (`tests/test_codex_rules.py` proves it against the live guard).
- `.codex/hooks.json` is **not** generated or committed: it carries the absolute project root,
  which is part of Codex's trust hash. Deploy and the installers render it from the FROZEN
  template `targets/codex/hooks.json.tmpl` with `render_codex_hooks_json(root)`. Changing the
  template switches every user's hooks off until they re-review them, so its hash is pinned
  (`tests/test_gen_codex_tree.py`) and a change needs a CHANGELOG entry headed
  `Codex users must re-review hooks` carrying `codex-hooks-template: <sha256>`.

What Codex does and does not guard (measured on 0.160.0): `docs/superpowers/measurements/2026-10-02-codex-0160.md`.
