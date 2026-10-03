#!/usr/bin/env python3
"""See where the toolkit's path config lives, and move a 3.x one to the 4.x place.

    python scripts/x4config.py status  [--root DIR]
    python scripts/x4config.py migrate [--root DIR] [--apply]

4.x reads `<toolkit>/x4-paths.env`. 3.x kept it at `<toolkit>/.claude/x4-paths.env`; that
location is still read for all of 4.x, with a deprecation notice, and this is the one
command every such notice names. It exists for users who upgrade with `git pull` and
never re-run an installer (the installers and `deploy-claude-dir.py` migrate on their own).

`migrate` is a DRY RUN unless `--apply`. It MOVES the file (never copies: two copies drift
apart on the first edit). A read-only (x4lock-locked) file moves too, and stays locked.
When both files exist and agree, the 3.x one is renamed to `.claude/x4-paths.env.bak-<stamp>`;
when they DIFFER, nothing is changed and the differing KEY names are printed. No value is
ever printed: the file carries `X4_NEXUS_KEY`.

To undo a move (e.g. to go back to 3.x): move `x4-paths.env` back to `.claude/x4-paths.env`.

Exit codes: 0 ok (including "nothing to do") / 1 refused (two differing configs) /
2 could not run (the x4validate package is not importable, or the root is not a directory).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "tools" / "x4validate"))

try:
    from x4validate import _paths
except ImportError as exc:              # pragma: no cover - packaging accident
    _paths = None
    _IMPORT_ERROR = exc


def _root(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    if os.environ.get("X4_TOOLKIT"):
        return Path(_paths.native(os.environ["X4_TOOLKIT"]))
    return _HERE.parent


def _status(root: Path) -> int:
    explicit = os.environ.get("X4_CONFIG")
    if explicit:
        print(f"note: X4_CONFIG is set ({explicit}), so the tools read THAT file and ignore "
              f"the two below.")
    os.environ.pop("X4_CONFIG", None)
    os.environ["X4_TOOLKIT"] = str(root)          # this process only: look in --root
    _paths.reload()
    state = _paths.config_state()
    found = _paths._find_env_file()
    new, old = root / _paths.CONFIG_NAME, root / _paths.LEGACY_CONFIG
    print(f"toolkit:  {root}")
    print(f"state:    {state}")
    print(f"reads:    {found or '(nothing)'}")
    print(f"4.x path: {new}{'' if new.is_file() else '   (absent)'}")
    print(f"3.x path: {old}{'' if old.is_file() else '   (absent)'}")
    if state == "both-differ":
        print(f"differ:   {', '.join(_paths._differing_keys(new, old))} (key names only)")
    if state in ("legacy", "both-agree"):
        print(f"next:     python \"{_HERE / 'x4config.py'}\" migrate --apply")
    elif state == "both-differ":
        print(f"next:     keep the values you want in {new}, then delete or rename {old}")
    elif state == "none":
        print(f"next:     re-run the installer, or copy {root / 'x4-paths.env.example'} to {new}")
    return 0


def _migrate(root: Path, apply: bool) -> int:
    action, msg = _paths.migrate_legacy_config(root, apply=apply)
    print(msg)
    if action == "refused":
        return 1
    if action.startswith("would-"):
        print("(dry run -- nothing changed; add --apply to do it)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="x4config.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "migrate"):
        p = sub.add_parser(name)
        p.add_argument("--root", help="the toolkit root (default: $X4_TOOLKIT, else this checkout)")
        if name == "migrate":
            p.add_argument("--apply", action="store_true", help="do it (default: dry run)")
    args = ap.parse_args(argv)
    if _paths is None:
        print(f"error: cannot run -- the x4validate package is not importable "
              f"({_IMPORT_ERROR})", file=sys.stderr)
        return 2
    root = _root(args.root)
    if not root.is_dir():
        print(f"error: cannot run -- {root} is not a directory", file=sys.stderr)
        return 2
    if args.cmd == "status":
        return _status(root)
    return _migrate(root, args.apply)


if __name__ == "__main__":
    sys.exit(main())
