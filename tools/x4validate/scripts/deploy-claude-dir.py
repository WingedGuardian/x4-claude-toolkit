#!/usr/bin/env python
"""Deploy the repo's `.claude/` into the configured game root. One direction, dry-run first.

WHY THIS EXISTS. The repo is the source of every hook, skill, agent and setting; a game
root's `.claude/` is a deployed copy. Editing both by hand is how they drifted (five files,
three directions, measured 2026-09-13 -- see `gates/deploy_parity.py`). This is the
"synchronous write" as ONE command: edit in the repo, then run this.

    uv run python scripts/deploy-claude-dir.py                 # dry run: what would change
    uv run python scripts/deploy-claude-dir.py --apply         # do it
    uv run python scripts/deploy-claude-dir.py --apply --force skills/x/SKILL.md

WHAT IT WILL NOT DO:

* OVERWRITE AN EDIT THAT WAS NEVER PORTED BACK. A destination file is replaced only if its
  content matches the repo's current file or ANY version of it the repo ever committed
  (either spelling of the installer rewrite). Anything else is a change somebody made in
  the deployed copy, and replacing it would destroy work -- `x4-probe` in the game root
  carried a whole rung of procedure the repo never had. It is REFUSED with the reason;
  port it to the repo first, or `--force <name>` that one file.
* DELETE. A file only in the game root is reported, never removed.
* TOUCH a per-machine file. The population is `deploy_parity.population()` -- the
  deployment as the game-root repository whitelists it -- so `x4-paths.env`,
  `settings.local.json` and `backups/` are outside it by construction.

HOW IT WRITES, each measured as a failure mode somewhere in this workspace:

* the installer rewrite (`$CLAUDE_PROJECT_DIR` -> `$X4_TOOLKIT`) is applied when the
  destination does NOT contain `tools/x4validate` -- install.sh's rule, and the reason the
  game root's five path-carrying skills pointed at a directory that does not exist there;
* the destination file's line endings are kept (a CRLF file stays CRLF): flipping every
  line ending for a one-line change is an unreviewable diff;
* an x4lock'd (read-only) file is unlocked, written, re-read and RE-LOCKED, with the lock
  verified through `x4lock._apply`, which never reports a lock it did not confirm;
* content is encoded before any write, so a failed encode cannot truncate.

Exit: 0 nothing refused (dry run) / everything applied - 1 at least one file refused or
failed, named - 2 could not run (no game root, or the destination IS the repo).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]          # tools/x4validate
REPO_ROOT = PKG.parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # REGISTER BEFORE EXECUTING. `@dataclass` under `from __future__ import annotations`
    # looks its own module up in sys.modules while the class is being built; an
    # unregistered module is None there and the import dies with an AttributeError.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


parity = _load("deploy_parity_for_deploy", PKG / "gates" / "deploy_parity.py")
x4lock = _load("x4lock_for_deploy", REPO_ROOT / "scripts" / "x4lock.py")

CREATE, UPDATE, SKIP, REFUSE, REPORT = "create", "update", "identical", "REFUSED", "only in game root"


@dataclass
class Action:
    name: str
    kind: str
    reason: str = ""


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def _rewrite(b: bytes) -> bytes:
    return b.replace(parity.REWRITE_FROM, parity.REWRITE_TO)


def _is_crlf(b: bytes) -> bool:
    return b.count(b"\r\n") * 2 > b.count(b"\n")


def needs_rewrite(dest_claude: Path) -> bool:
    """install.sh's rule: the toolkit is NOT inside the directory the skills run from."""
    return not (dest_claude.parent / "tools" / "x4validate").is_dir()


def committed_versions(repo_root: Path, rel: str) -> list[bytes]:
    """Every committed content of `rel` (repo-root-relative), normalised. [] without git --
    which only makes the refusal STRICTER, never looser."""
    try:
        revs = subprocess.run(["git", "-C", str(repo_root), "rev-list", "HEAD", "--", rel],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []  # silent-ok: no git means fewer known versions, so MORE refusals
    out: list[bytes] = []
    for rev in revs.stdout.split()[:500]:
        blob = subprocess.run(["git", "-C", str(repo_root), "show", f"{rev}:{rel}"],
                              capture_output=True, timeout=60)
        if blob.returncode == 0:
            out.append(_norm(blob.stdout))
    return out


def rewrites(dest_claude: Path, name: str) -> bool:
    """Only skills and agents, and only when the toolkit is not beside the destination --
    exactly install.sh. Hooks and settings.json keep `$CLAUDE_PROJECT_DIR`, which is what
    points a session at its OWN deployed hooks (see `deploy_parity.REWRITE_SCOPE`)."""
    return needs_rewrite(dest_claude) and parity.in_rewrite_scope(name)


def plan(repo_root: Path, dest_claude: Path, force: set[str] | frozenset = frozenset()) -> list[Action]:
    repo_claude = repo_root / ".claude"
    names = sorted(parity.population(repo_claude) | parity.population(dest_claude))
    actions: list[Action] = []
    for n in names:
        src, dst = repo_claude / n, dest_claude / n
        if not src.is_file():
            actions.append(Action(n, REPORT, "not in the repo: port it there, or remove it by hand"))
            continue
        want = _norm(src.read_bytes())
        scoped = parity.in_rewrite_scope(n)
        target = _rewrite(want) if rewrites(dest_claude, n) else want
        if not dst.is_file():
            actions.append(Action(n, CREATE))
            continue
        have = _norm(dst.read_bytes())
        if have == target:
            actions.append(Action(n, SKIP))
            continue
        # A rewritten spelling is only a KNOWN version where the installer would have
        # produced it; a rewritten hook is a hand edit, and must be refused like one.
        known = {want, _rewrite(want)} if scoped else {want}
        for c in committed_versions(repo_root, f".claude/{n}"):
            known.update((c, _rewrite(c)) if scoped else (c,))
        if have in known:
            actions.append(Action(n, UPDATE))
        elif n in force:
            actions.append(Action(n, UPDATE, "--force: a never-ported local edit is overwritten"))
        else:
            actions.append(Action(
                n, REFUSE,
                "the deployed copy matches no version the repo has EVER committed -- an edit "
                "made in the game root that was never ported. Port it to the repo first, or "
                f"pass --force {n}"))
    return actions


def target_bytes(repo_root: Path, dest_claude: Path, name: str) -> bytes:
    data = _norm((repo_root / ".claude" / name).read_bytes())
    # The SAME predicate `plan()` uses. The first version scoped the rewrite in plan()
    # and not here, so the plan said "hooks are not rewritten" while the write rewrote
    # them -- caught by test_HOOKS_and_SETTINGS_are_never_rewritten and, independently,
    # by the parity check this script runs after applying ("0 of 2 at parity").
    if rewrites(dest_claude, name):
        data = _rewrite(data)
    dst = dest_claude / name
    if dst.is_file() and _is_crlf(dst.read_bytes()):
        data = data.replace(b"\n", b"\r\n")
    return data


def _lock_manifest() -> set[str] | None:
    """x4lock's manifest as resolved paths, or None when it cannot be built."""
    try:
        return {str(p.resolve()).lower() for p in x4lock.manifest()}
    except Exception:  # silent-ok: an unbuildable manifest is REPORTED by the caller, not hidden
        return None


def apply(repo_root: Path, dest_claude: Path, actions: list[Action]) -> list[str]:
    """Write every create/update. Returns failure messages; [] means all landed.

    A CREATED file is locked afterwards when x4lock's manifest covers it. The first version
    preserved each file's prior lock state, which is always "unlocked" for a file that did
    not exist -- so a new skill's files stayed writable until someone remembered to run
    `x4lock.py lock` (review, 2026-09-13).
    """
    failures: list[str] = []
    created: list[Path] = []
    for a in actions:
        if a.kind not in (CREATE, UPDATE):
            continue
        dst = dest_claude / a.name
        if a.kind == CREATE:
            created.append(dst)
        data = target_bytes(repo_root, dest_claude, a.name)      # encoded before any write
        was_locked = dst.is_file() and x4lock.state(dst) == "locked"
        if was_locked:
            ok, msg = x4lock._apply(dst, locked=False)
            if not ok:
                failures.append(f"{a.name}: could not unlock ({msg}); NOT written")
                continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        except OSError as exc:
            failures.append(f"{a.name}: write failed ({exc})")
        finally:
            if was_locked:
                ok, msg = x4lock._apply(dst, locked=True)
                if not ok:
                    failures.append(f"{a.name}: WRITTEN BUT NOT RE-LOCKED ({msg})")
        if dst.is_file() and dst.read_bytes() != data:
            failures.append(f"{a.name}: re-read does not match what was written")
    if created:
        wanted = _lock_manifest()
        if wanted is None:
            failures.append("x4lock manifest could not be built: created file(s) left UNLOCKED "
                            "-- run scripts/x4lock.py lock")
        else:
            for dst in created:
                if dst.is_file() and str(dst.resolve()).lower() in wanted:
                    ok, msg = x4lock._apply(dst, locked=True)
                    if not ok:
                        failures.append(f"{dst.name}: created but NOT LOCKED ({msg})")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deploy-claude-dir",
                                 description="Deploy the repo's .claude/ into the game root.")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--force", action="append", default=[], metavar="NAME",
                    help="overwrite this one never-ported file (repeatable)")
    ap.add_argument("--dest", help="a .claude/ directory to deploy into (default: the "
                                   "configured game root's)")
    ap.add_argument("--repo", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    repo_root = Path(args.repo) if args.repo else REPO_ROOT
    dest = Path(args.dest) if args.dest else parity.game_claude_dir()
    if dest is None:
        print("REFUSING: no game root configured (or it has no .claude/). Nothing to deploy "
              "into; pass --dest to name one.", file=sys.stderr)
        return 2
    if dest.resolve() == (repo_root / ".claude").resolve():
        print(f"REFUSING: the destination IS the repo's .claude/ ({dest}).", file=sys.stderr)
        return 2

    actions = plan(repo_root, dest, set(args.force))
    unknown_force = sorted(set(args.force) - {a.name for a in actions})
    if unknown_force:
        print(f"REFUSING: --force names file(s) not in the deployment: {unknown_force}",
              file=sys.stderr)
        return 2

    mode = "APPLY" if args.apply else "DRY RUN (nothing written; --apply to write)"
    print(f"DEPLOY .claude/ -- {mode}")
    print(f"  from {repo_root / '.claude'}")
    print(f"  to   {dest}   (installer rewrite: {'yes' if needs_rewrite(dest) else 'no'})")
    width = max(len(k) for k in (CREATE, UPDATE, SKIP, REFUSE, REPORT))
    for a in actions:
        if a.kind == SKIP:
            continue
        print(f"  {a.kind:<{width}}  {a.name}" + (f"  -- {a.reason}" if a.reason else ""))
    counts = {k: sum(1 for a in actions if a.kind == k)
              for k in (CREATE, UPDATE, SKIP, REFUSE, REPORT)}
    print("  " + ", ".join(f"{v} {k}" for k, v in counts.items()))

    refused = [a for a in actions if a.kind == REFUSE]
    if not args.apply:
        return 1 if refused else 0

    failures = apply(repo_root, dest, actions)
    for f in failures:
        print(f"  FAILED  {f}", file=sys.stderr)
    rows = parity.compare_trees(repo_root / ".claude", dest)
    off = [r for r in rows if not r.at_parity]
    print(f"  parity after apply: {len(rows) - len(off)} of {len(rows)} file(s) at parity")
    for r in off:
        print(f"    {parity.describe(r)}")
    if refused:
        print(f"  {len(refused)} file(s) REFUSED -- see above; nothing was written to them",
              file=sys.stderr)
    # The deploy's OWN files must be at parity afterwards. Printing "N of M" and returning
    # 0 regardless is how a plan/write disagreement (found once already) would pass at
    # runtime; files only in the game root are reported above and are not ours to fix.
    own = {a.name for a in actions if a.kind in (CREATE, UPDATE, SKIP)}
    broken = [r for r in off if r.name in own]
    if broken:
        print(f"  PARITY BROKEN after apply for {len(broken)} file(s) this deploy wrote or "
              "checked -- the plan and the write disagree", file=sys.stderr)
    return 1 if (refused or failures or broken) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
