#!/usr/bin/env python
"""Does the game root's `.claude/` match the repo's? Any difference fails.

WHY THIS EXISTS. The repo is the SOURCE of every hook, skill, agent and setting; the
`.claude/` directory in a configured game root is a DEPLOYED copy, and it is the one this
machine's sessions actually load. MEASURED 2026-09-13: 25 files there vs 23 here, five
drifted, in three different directions --

  * two skills written straight into the game root and never shipped (`x4-live`,
    `x4-xml-patching`, the latter being the most-used skill in the workspace);
  * one skill NEWER in the game root (`x4-probe`, +27 lines, a whole rung of procedure);
  * two agents hand-edited in the game root to hard-code a personal absolute path,
    working around a rewrite the deployment never applied.

Every one came from writing ONCE in the wrong place. A rule to write twice fails the same
way -- the forgotten second write IS the drift -- so this is a check that refuses.

LIFTED FROM dev's `published_surface_drift.py`, keeping its two hard-won properties and
dropping the defect that let this drift live:

  * LINE ENDINGS ARE NOT DRIFT (raw bytes once made every skill "differ", which buried
    the real findings);
  * REPORT THE DIRECTION, NEVER A WINNER. "Newer" copies have destroyed cross-platform
    work before. This gate names lines-only-here and lines-only-there; the deploy script
    (`scripts/deploy-claude-dir.py`) is what acts, and it refuses to overwrite an edit
    that was never ported back.
  * ⛔ NO ACCEPT-BASELINE. The dev gate had one, and an accepted drift is a drift nobody
    reads again. Any non-identical row is rc 1.

THE POPULATION is what the game-root repository's own `.gitignore` whitelists as the
deployment: `settings.json`, `settings.local.json.example`, and everything under `hooks/`,
`skills/`, `agents/`, `commands/`. Per-machine files (install.sh's `X4_KEEP_LOCAL`:
`x4-paths.env`, `settings.local.json`, `backups/`) are outside it by construction, and
caches and editor backups are excluded explicitly.

THE INSTALLER'S REWRITE IS NOT DRIFT. `install.sh` rewrites `$CLAUDE_PROJECT_DIR` to
`$X4_TOOLKIT` when the toolkit does not live inside the directory the skills run from. A
deployed file equal to the repo file after that rewrite is the same file. The rewrite
goes ONE way: a repo file carrying `$X4_TOOLKIT` is drift, because it would break every
in-game install.

Run:  uv run python gates/deploy_parity.py
Exit: 0 every file identical - 1 drift, each file named with its direction - 2 could not
      compare (no game root configured, or nothing to compare; never "at parity").
"""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from x4validate import _paths  # noqa: E402

#: `<repo>/tools/x4validate/gates/this.py` -> `<repo>`. From __file__, never $X4_TOOLKIT.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The deployment, as the game-root repository's `.gitignore` whitelists it.
#: `x4-paths.env.example` left in Plan 3 lane I: it lives at the toolkit root now, beside
#: the `x4-paths.env` 4.x reads, so a game root's `.claude/` no longer carries it.
TOP_FILES = ("settings.json", "settings.local.json.example")
SUBTREES = ("hooks", "skills", "agents", "commands")

#: Never part of a deployment, wherever they appear.
_EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}
_EXCLUDED_SUFFIXES = (".pyc", ".bak")

REWRITE_FROM = b"$CLAUDE_PROJECT_DIR"
REWRITE_TO = b"$X4_TOOLKIT"

#: The ONLY subtrees the installer rewrites -- install.sh loops over `skills/x4-*` and
#: `agents/*.md` and nothing else. `settings.json` and the hooks keep
#: `$CLAUDE_PROJECT_DIR` on purpose: it resolves to the directory the session is
#: running in, which is where the deployed hooks live. MEASURED 2026-09-13 by the
#: deploy script's first dry run: an unscoped rewrite planned to point the game root's
#: settings.json at the REPO's hooks, i.e. to swap which guards every session runs.
REWRITE_SCOPE = ("skills/", "agents/")



@dataclass(frozen=True)
class TargetSpec:
    """One agent's deployed tree: where it lives under a root, what its population is,
    and which subtrees the installer rewrites (from one token to any of its renderings).

    Only `claude` is defined: deploy-claude-dir.py deploys `.claude/` and nothing else,
    so no other agent tree HAS a deploy workflow to be at parity with (`.codex/` and
    `.opencode/` reach a root only through the installer). x4doctor reads the same table
    and reports a target with no entry here as N/A, naming that reason (v4.0.0 review
    R4-2/R5-10: this docstring promised a Codex entry "appended by the Codex adapter
    lane", and nothing ever appended one). Add an entry only together with a deploy
    workflow that writes that tree.
    """
    name: str
    root_rel: str
    top_files: tuple[str, ...]
    subtrees: tuple[str, ...]
    rewrite_scope: tuple[str, ...]
    rewrite_from: bytes = REWRITE_FROM
    rewrite_to: tuple[bytes, ...] = (REWRITE_TO,)


TARGETS: dict[str, TargetSpec] = {
    "claude": TargetSpec("claude", ".claude", TOP_FILES, SUBTREES, REWRITE_SCOPE),
}
CLAUDE = TARGETS["claude"]


def in_rewrite_scope(name: str, spec: TargetSpec = CLAUDE) -> bool:
    return bool(spec.rewrite_scope) and name.startswith(spec.rewrite_scope)

IDENTICAL = "identical"
IDENTICAL_REWRITTEN = "identical (after the installer rewrite)"
DRIFT = "drift"
ONLY_REPO = "only in repo"
ONLY_GAME = "only in game root"


@dataclass(frozen=True)
class Row:
    name: str
    state: str
    game_only: int = 0
    repo_only: int = 0

    @property
    def at_parity(self) -> bool:
        return self.state in (IDENTICAL, IDENTICAL_REWRITTEN)


def repo_claude_dir() -> Path:
    return REPO_ROOT / ".claude"


def game_claude_dir() -> Path | None:
    root = _paths.game_root()
    if root is None:
        return None
    d = Path(root) / ".claude"
    return d if d.is_dir() else None


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def population(claude: Path, spec: TargetSpec = CLAUDE) -> set[str]:
    """Deployment-relative posix paths that exist under one deployed agent directory
    (`.claude/` unless `spec` names another target)."""
    out: set[str] = set()
    for name in spec.top_files:
        if (claude / name).is_file():
            out.add(name)
    for sub in spec.subtrees:
        base = claude / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(claude)
            if any(part in _EXCLUDED_DIRS for part in rel.parts):
                continue
            if p.name.endswith(_EXCLUDED_SUFFIXES):
                continue
            out.add(rel.as_posix())
    return out


def compare_file(repo_file: Path, game_file: Path, name: str,
                 spec: TargetSpec = CLAUDE) -> Row:
    if not game_file.is_file():
        return Row(name, ONLY_REPO)
    if not repo_file.is_file():
        return Row(name, ONLY_GAME)
    repo, game = _norm(repo_file.read_bytes()), _norm(game_file.read_bytes())
    if repo == game:
        return Row(name, IDENTICAL)
    if in_rewrite_scope(name, spec) and any(
            repo.replace(spec.rewrite_from, to) == game for to in spec.rewrite_to):
        return Row(name, IDENTICAL_REWRITTEN)
    r = repo.decode("utf-8", "replace").split("\n")
    g = game.decode("utf-8", "replace").split("\n")
    diff = list(difflib.unified_diff(r, g, n=0, lineterm=""))
    game_only = sum(1 for x in diff if x.startswith("+") and not x.startswith("+++"))
    repo_only = sum(1 for x in diff if x.startswith("-") and not x.startswith("---"))
    return Row(name, DRIFT, game_only, repo_only)


def compare_trees(repo_claude: Path, game_claude: Path,
                  spec: TargetSpec = CLAUDE) -> list[Row]:
    names = sorted(population(repo_claude, spec) | population(game_claude, spec))
    return [compare_file(repo_claude / n, game_claude / n, n, spec) for n in names]


def describe(row: Row) -> str:
    if row.state == DRIFT:
        return (f"{row.name}: {row.game_only} line(s) only in the game root, "
                f"{row.repo_only} only in the repo")
    return f"{row.name}: {row.state}"


def main() -> int:
    repo = repo_claude_dir()
    game = game_claude_dir()
    if not repo.is_dir():
        print(f"REFUSING: no repo .claude/ at {repo}", file=sys.stderr)
        return 2
    if game is None:
        print("REFUSING: no game root configured (or it has no .claude/), so there is no "
              "deployed copy to compare. This is not 'at parity'.", file=sys.stderr)
        return 2
    if game.resolve() == repo.resolve():
        print(f"REFUSING: the game root's .claude/ IS the repo's ({repo}); comparing a "
              "tree to itself proves nothing.", file=sys.stderr)
        return 2
    rows = compare_trees(repo, game)
    if not rows:
        print("REFUSING: nothing to compare -- both deployment populations are empty.",
              file=sys.stderr)
        return 2

    off = [r for r in rows if not r.at_parity]
    rewritten = sum(1 for r in rows if r.state == IDENTICAL_REWRITTEN)
    print("DEPLOY PARITY -- repo .claude/ (source) vs game root .claude/ (deployed)")
    print(f"  repo:      {repo}")
    print(f"  game root: {game}")
    print(f"  {len(rows)} file(s) compared on normalised content: "
          f"{len(rows) - len(off)} at parity ({rewritten} via the installer rewrite), "
          f"{len(off)} not")
    if off:
        print("", file=sys.stderr)
        print(f"DRIFT -- {len(off)} file(s). The gate names no winner; read both "
              "directions, then:", file=sys.stderr)
        print("  * a change that belongs in the toolkit: make it in the REPO, then run "
              "scripts/deploy-claude-dir.py --apply", file=sys.stderr)
        print("  * a repo change not yet deployed: run scripts/deploy-claude-dir.py "
              "--apply", file=sys.stderr)
        for r in off:
            print(f"    {describe(r)}", file=sys.stderr)
        return 1
    print("  at parity.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
