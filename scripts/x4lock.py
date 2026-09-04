#!/usr/bin/env python3
"""Make the irreplaceable files unwritable by accident, and say so honestly.

WHY THIS EXISTS. Four times in twelve days this workspace's own tooling destroyed a
live, irreplaceable file: a memory file and a 375-line module truncated to 0 bytes by
text-mode writes that raised mid-encode, the game-root CLAUDE.md and KNOWLEDGEBASE.md
overwritten by a reviewer's installer probe, and a 258-entry mod registry replaced by a
46-byte fresh one. None was a decision. Each was a command that ran, resolved to a live
path, and met nothing in the way.

Prose did not stop any of them -- 150 KB of instructions were in context every time. The
two locations on this machine that have a MECHANISM have never been lost: `reference/`
(a sentinel the tools refuse past) and the user profile (git plus a confirming hook).
This gives the rest of the irreplaceable set protection at the only layer that can see a
write from inside another process: the filesystem.

WHAT STOPS A WRITE (measured here, Windows 11, 14 primitives, each with a control
proving the same primitive DOES change the file when it is unlocked):

    primitive                                     read-only attribute
    python open("w") / write_text / write_bytes   blocked
    python os.truncate / os.replace               blocked
    python shutil.copy2 / os.remove               blocked
    bash > / cp / tee                             blocked
    pwsh Set-Content                              blocked
    bash rm -f                                    NOT blocked
    pwsh Copy-Item -Force / Remove-Item -Force    NOT blocked

11 of 14. The three that get through are DELETES and force-overwrites: POSIX `unlink`
is authorised by write permission on the DIRECTORY, not the file, and `-Force` clears
the attribute before writing. Those are covered a layer up -- the Bash guard asks
before a delete inside an X4 directory, and `x4canary` notices a file that shrank.

The number that decided the design: ALL FOUR real incidents are in the blocked set.
Every one was a python text write or an installer's `cp`; not one was `rm -f` or
`-Force`. This stops what has actually happened, not what is imaginable.

⚠ An earlier version of this table said `rm -f` was blocked. It was measured with the
`bash` on Windows PATH, which is the WSL stub: it cannot open a `C:/...` path, so its
failure READ AS the lock working. Always pair such a probe with a control on an
unlocked file -- the control is what turned that row from a pass into a non-answer.

WHY THERE IS NO ACL HERE, THOUGH AN ACL WOULD CLOSE THAT GAP. The first version of this
tool also applied `icacls /deny <user>:(W,D,WDAC,WO)`, which does block `-Force`. It was
withdrawn after it locked this machine out of two of its own files:

  * `W` in icacls shorthand is FILE_GENERIC_WRITE, which INCLUDES SYNCHRONIZE. Every
    synchronous open needs SYNCHRONIZE, so a "write deny" denies READING as well. The
    files became completely inaccessible, one of them a hook that runs on every edit.
  * The deny includes WDAC, so it removes the permission needed to remove itself. On a
    file owned by BUILTIN\\Administrators rather than the user -- which is ordinary under
    Program Files -- `icacls /remove:d`, `Set-Acl`, `takeown` and even rename all fail
    unelevated. Repair required an administrator.

A protection whose failure mode is "you can no longer read your own file, and cannot
undo it without elevation" is worse than the accident it prevents. The read-only bit
cannot deny a read, cannot be un-removable, and works the same on every platform.

The lock is meant to stop an ACCIDENT, not a determined process. Any code that really
means it can clear the bit -- but it has to MEAN it, in a separate visible step, which
is exactly what none of the four incidents did.

USAGE
    python scripts/x4lock.py status            what is protected, and is it locked
    python scripts/x4lock.py lock              lock every file in the manifest
    python scripts/x4lock.py unlock <path>     unlock ONE file (the choke point)
    python scripts/x4lock.py unlock --all      unlock everything

The manifest is derived from the configured roots, never hard-coded to one machine, and
is extended by `X4_PROTECTED` (an os.pathsep-separated list) for anything site-specific.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "tools" / "x4validate"))

try:
    from x4validate import _paths
except ImportError:                     # pragma: no cover - packaging accident
    _paths = None

#: Files whose loss cannot be undone by re-running anything. Deliberately NOT whole
#: directories: `.claude/backups/`, `settings.local.json` and Claude Code's own lock
#: files are written during normal operation, and a lock that breaks routine work gets
#: switched off -- which protects nothing.
_GAME_RELATIVE = (
    "CLAUDE.md",
    "KNOWLEDGEBASE.md",
    ".claude/settings.json",
)

#: The guards themselves. A protection that can silently disable itself is not one.
#: These are edited rarely and deliberately, so the unlock step costs nothing.
_GAME_GLOBS = (
    ".claude/hooks/*.sh",
    ".claude/hooks/*.py",
    ".claude/skills/*/SKILL.md",
    ".claude/agents/*.md",
)


def _cfg(name: str):
    """Resolve one configured root, and REFUSE to invent an answer for a name that
    does not exist.

    The first draft was `getattr(_paths, name, lambda: None)()`. It asked for `game`
    and `toolkit`, neither of which is a function in `_paths`, so it silently produced
    a two-file manifest and reported it as a complete one -- a step that narrows the
    data and reports success anyway, which is the bug class this tool exists to end.
    A typo must be a crash, never a smaller answer.
    """
    if _paths is None:
        return None
    fn = getattr(_paths, name, None)
    if not callable(fn):
        raise AttributeError(
            "x4lock asked _paths for %r, which does not exist. Refusing to build a "
            "manifest from a name that resolves to nothing." % name)
    return fn()


def manifest() -> list[Path]:
    """Every protected file that currently exists, deduplicated and sorted.

    An absent path is simply not listed: this reports on the machine it runs on, and
    an unconfigured root yields a smaller manifest, never a crash.
    """
    out: list[Path] = []

    game = _cfg("game_root")
    if game:
        game = Path(game)
        for rel in _GAME_RELATIVE:
            out.append(game / rel)
        for pat in _GAME_GLOBS:
            out.extend(sorted(game.glob(pat)))

    reg = _cfg("registry")
    if reg:
        out.append(Path(reg))

    # Every `x4-paths.env` in play: the one this checkout carries, and the one the
    # configured toolkit root carries. They are usually different files, and the
    # second is what every hook actually reads.
    out.append(_HERE.parent / ".claude" / "x4-paths.env")
    env_file = _paths._find_env_file() if _paths is not None else None
    if env_file:
        out.append(Path(env_file))

    for extra in (os.environ.get("X4_PROTECTED") or "").split(os.pathsep):
        if extra.strip():
            out.append(Path(extra.strip()))

    seen: dict[str, Path] = {}
    for p in out:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            continue
        if p.is_file() and key not in seen:
            seen[key] = p
    return [seen[k] for k in sorted(seen)]


# ----------------------------------------------------------------- the mechanism

def state(p: Path) -> str:
    if not p.is_file():
        return "missing"
    return "unlocked" if (p.stat().st_mode & stat.S_IWRITE) else "locked"


def is_locked(p) -> bool:
    """For callers (hooks, tests) that need the state rather than the report."""
    return state(Path(p)) == "locked"


def _apply(p: Path, locked: bool) -> tuple[bool, str]:
    """Set the bit, then VERIFY by re-reading it. Never reports a lock it did not
    confirm -- `chmod` can succeed against a filesystem that does not honour the
    attribute at all, and a protection reported but absent is the worst outcome."""
    try:
        mode = p.stat().st_mode
        p.chmod(mode & ~stat.S_IWRITE if locked else mode | stat.S_IWRITE)
    except OSError as exc:
        return False, type(exc).__name__ + ": " + str(exc)
    want = "locked" if locked else "unlocked"
    got = state(p)
    if got != want:
        return False, "verification says " + got + ", not " + want
    return True, ""


# ------------------------------------------------------------------------ commands

def cmd_status(_args) -> int:
    items = manifest()
    if not items:
        print("NOTHING PROTECTED: no roots are configured, so the manifest is empty.",
              file=sys.stderr)
        print("       Set X4_GAME / X4_MODS (see `x4validate --paths`), or list files "
              "in X4_PROTECTED.", file=sys.stderr)
        return 2
    counts: dict[str, int] = {}
    for p in items:
        s = state(p)
        counts[s] = counts.get(s, 0) + 1
        print("  %-9s %s" % (s, p))
    print()
    print("%d protected file(s): %s" % (
        len(items), ", ".join("%s %s" % (v, k) for k, v in sorted(counts.items()))))
    return 1 if counts.get("unlocked", 0) else 0


def _run(items: list[Path], locked: bool) -> int:
    verb = "locked" if locked else "unlocked"
    done = failed = 0
    for p in items:
        ok, msg = _apply(p, locked)
        if ok:
            done += 1
            print("  %-8s %s" % (verb, p))
        else:
            failed += 1
            print("  FAILED   %s  -- %s" % (p, msg), file=sys.stderr)
    print()
    print("%d %s, %d failed, of %d" % (done, verb, failed, len(items)))
    if failed:
        print("A file this could not change is NOT in the state reported for it. Fix "
              "it, or take it out of the manifest -- never leave it counted as done.",
              file=sys.stderr)
    return 1 if failed else 0


def cmd_lock(_args) -> int:
    items = manifest()
    if not items:
        print("REFUSING: the manifest is empty, so 'locked' would mean nothing.",
              file=sys.stderr)
        return 2
    return _run(items, True)


def cmd_unlock(args) -> int:
    if args.all:
        items = manifest()
        if not items:
            print("REFUSING: the manifest is empty.", file=sys.stderr)
            return 2
        return _run(items, False)
    if not args.path:
        print("unlock needs a path, or --all. One file at a time is the point: that is "
              "the moment a human decides.", file=sys.stderr)
        return 2
    p = Path(args.path)
    if not p.is_file():
        print("no such file: " + str(p), file=sys.stderr)
        return 2
    known = {str(q.resolve()).lower() for q in manifest()}
    try:
        if str(p.resolve()).lower() not in known:
            print("note: %s is not in the protected manifest (nothing to unlock)." % p)
            return 0
    except OSError:
        pass
    return _run([p], False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="x4lock",
        description="Lock the irreplaceable files against accidental overwrite by any "
                    "process.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", help="list protected files and whether each is locked")
    sub.add_parser("lock", help="lock every file in the manifest")
    un = sub.add_parser("unlock", help="unlock ONE file (or --all)")
    un.add_argument("path", nargs="?")
    un.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "lock":
        return cmd_lock(args)
    if args.cmd == "unlock":
        return cmd_unlock(args)
    if args.cmd == "status":
        return cmd_status(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
