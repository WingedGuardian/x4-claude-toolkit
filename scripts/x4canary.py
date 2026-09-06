#!/usr/bin/env python3
"""Notice when an irreplaceable file has shrunk, and REFUSE rather than report OK.

WHY THIS EXISTS. On 2026-09-03 the mod registry went from 196,363 bytes and 258
hand-triaged entries to 46 bytes. `dev/` is a git repository. `git status` showed
` M _registry/modlist.yaml`, 8,222 deletions, from the moment it happened. Nobody ran
it, and the loss was found six hours later by accident while investigating something
else.

That is the whole problem with detection here: the evidence existed and no one looked.
So this is built to be run BY something, not by a person remembering -- at session
start, and around any batch of subagents -- and to be cheap enough that running it
often is free. MEASURED: the game-root repo's `git status` is 35 ms, because its
`.gitignore` is a whitelist and git never descends into the 60 GB of game data.

WHAT IT REFUSES ON. Not "something changed" -- a changed file is the normal case, and a
check that cries wolf gets ignored, which is how the last one failed. It refuses on the
specific shape of a LOSS:

  * a tracked file that is now missing
  * a tracked file that is now empty while HEAD had content
  * a tracked file that lost more than half its bytes

Anything else is reported as ordinary drift and does not fail the run.

It also refuses when it CANNOT check -- an unreadable repo, a path that is not a
repository, a `git` that is not there. "Could not look" must never render as "nothing
wrong": that conflation is the single most repeated defect in this workspace.

USAGE
    python scripts/x4canary.py              check every configured repo
    python scripts/x4canary.py --verbose    also list what changed benignly

Repositories come from `X4_CANARY_REPOS` (an os.pathsep-separated list) when set, else
the game root and the mods root as resolved by `_paths`.

Exit: 0 nothing lost - 1 A LOSS, or drift that could not be classified - 2 could not
check something, so no verdict is possible.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# EVERYTHING HERE RUNS BEFORE main() CAN GUARD IT, and this script exits 1 to
# mean A TRACKED FILE HAS BEEN LOST -- the SessionStart hook renders that as
# "*** A TRACKED IRREPLACEABLE FILE HAS BEEN LOST ***". An uncaught exception
# also exits 1, so a canary that merely failed to LOAD reported the worst
# possible verdict about the user's files. `repos()` and `check()` were guarded
# (bd0d714 and earlier); import time was the last unguarded path.
#
# `Path.resolve()` can raise OSError or ValueError (a NUL byte in a path), and the
# `except ImportError` below is narrower than the ways an import can fail: a
# SyntaxError, AttributeError or OSError raised WHILE executing _paths.py
# propagates straight out. Both now degrade to "could not check", never to a
# loss claim.
try:
    _HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(_HERE.parent / "tools" / "x4validate"))
except Exception as _exc:  # noqa: BLE001 -- silent-ok: re-raised as rc 2 below
    _HERE, _BOOT_ERROR = None, _exc
else:
    _BOOT_ERROR = None

try:
    from x4validate import _paths
except Exception:                       # pragma: no cover - packaging accident
    # NOT just ImportError. A broken _paths.py is a reason to say "could not
    # check", never a reason to claim data loss -- and never a reason to crash
    # the session start.
    _paths = None

#: A tracked file that keeps less than this fraction of its committed size is treated
#: as a loss rather than an edit. The incident it is calibrated against went to 0.02%.
SHRINK_FLOOR = 0.5


def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def repos() -> list[Path]:
    """The resolved roots PLUS anything configured, never one instead of the other.

    `X4_CANARY_REPOS` extends rather than replaces, matching `X4_PROTECTED` in
    x4lock. Two sibling tools whose env vars mean opposite things is a trap: setting
    the memory directory here would otherwise silently stop checking the game root.
    """
    out: list[Path] = []
    if _paths is not None:
        for fn in ("game_root", "mods"):
            got = getattr(_paths, fn)()
            if got:
                out.append(Path(got))
    for extra in (os.environ.get("X4_CANARY_REPOS") or "").split(os.pathsep):
        if extra.strip():
            out.append(Path(extra.strip()))
    seen, uniq = set(), []
    for p in out:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def check(repo: Path, verbose: bool = False) -> tuple[list[str], list[str], int]:
    """Return (losses, drift, unreadable) for one repository."""
    losses: list[str] = []
    drift: list[str] = []

    if not repo.is_dir():
        return ["%s: not a directory" % repo], [], 1
    rc, _out = _git(repo, "rev-parse", "--git-dir")
    if rc != 0:
        return (["%s: not a git repository (nothing is versioned there)" % repo], [], 1)
    # AN UNBORN HEAD IS THE SAME CONDITION. `rev-parse --git-dir` succeeds the moment
    # `git init` has run, so a repo with NO COMMITS passed every check below: every
    # file shows as `??`, which is drift rather than loss, and the banner read
    # "no tracked file lost" over a directory where nothing is tracked at all.
    # MEASURED 2026-09-04. It is reachable in the scenario this tool exists for --
    # the game-root repo was created in RESPONSE to these losses, and an
    # `rm -rf .git && git init` recovery would turn the canary permanently green.
    rc, _out = _git(repo, "rev-parse", "--verify", "HEAD")
    if rc != 0:
        return (["%s: git repository with NO COMMITS -- nothing is versioned there, "
                 "so nothing can be compared" % repo], [], 1)

    rc, out = _git(repo, "status", "--porcelain")
    if rc != 0:
        return (["%s: git status failed -- %s" % (repo, out.strip()[:120])], [], 1)

    for line in out.splitlines():
        if len(line) < 4:
            continue
        code, rel = line[:2], line[3:].strip().strip('"')
        # A RENAME/COPY carries TWO paths in one field: `R  old.yaml -> new.yaml`.
        # Read whole, `p.exists()` is False and an ordinary `git mv` was reported as
        # "DELETED (tracked, now missing)" -- firing the SessionStart banner "A TRACKED
        # IRREPLACEABLE FILE HAS BEEN LOST". MEASURED 2026-09-04; the watched `dev`
        # history contains 2 real renames. The docstring's own argument is that a check
        # which cries wolf gets ignored, "which is how the last one failed".
        # The DESTINATION is the file that now exists and is what must be checked.
        if code and code[0] in ("R", "C") and " -> " in rel:
            rel = rel.split(" -> ", 1)[1].strip().strip('"')
        p = repo / rel
        if "D" in code or not p.exists():
            losses.append("%s: DELETED (tracked, now missing)" % rel)
            continue
        if code.strip() not in ("M", "MM", "AM", "T"):
            drift.append("%s: %s" % (rel, code.strip() or "?"))
            continue
        rc2, blob = _git(repo, "cat-file", "-s", "HEAD:" + rel)
        if rc2 != 0:
            drift.append("%s: modified (no HEAD blob to compare)" % rel)
            continue
        try:
            was, now = int(blob.strip()), p.stat().st_size
        except (ValueError, OSError) as exc:
            return ["%s: cannot size %s -- %s" % (repo, rel, exc)], drift, 1
        if was > 0 and now == 0:
            losses.append("%s: EMPTIED (%d bytes -> 0)" % (rel, was))
        elif was > 0 and now < was * SHRINK_FLOOR:
            losses.append("%s: SHRANK %d -> %d bytes (%.0f%% lost)"
                          % (rel, was, now, 100 * (1 - now / was)))
        elif verbose:
            drift.append("%s: %d -> %d bytes" % (rel, was, now))
    return losses, drift, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="x4canary",
        description="Refuse if an irreplaceable tracked file has been lost.")
    ap.add_argument("--verbose", action="store_true",
                    help="also list benign modifications")
    args = ap.parse_args(argv)

    if _BOOT_ERROR is not None:
        # Import-time failure, surfaced here instead of as an uncaught traceback.
        # rc 2 is "could not check"; rc 1 would tell the user a file is GONE.
        print("REFUSING A VERDICT: the canary could not finish loading: %s: %s"
              % (type(_BOOT_ERROR).__name__, _BOOT_ERROR), file=sys.stderr)
        return 2

    try:
        rs = repos()
    except Exception as exc:  # noqa: BLE001 -- silent-ok: converted to rc 2 here, never swallowed
        # The guard below covers a broken check(), but check() runs INSIDE the loop that
        # this call decides the contents of -- so it could never cover this. repos()
        # resolves _paths.game_root() and calls Path(...).resolve() on $X4_CANARY_REPOS,
        # where the `except OSError` does not catch the ValueError a NUL byte in a path
        # raises. An exception escaping main() exits 1, and the SessionStart hook renders
        # rc 1 as "A TRACKED IRREPLACEABLE FILE HAS BEEN LOST" -- the worst possible
        # verdict about the user's files, reached by the canary merely failing to
        # enumerate its own inputs. Could-not-look is rc 2, as the docstring states.
        print("REFUSING A VERDICT: the canary could not work out what to check: %s: %s"
              % (type(exc).__name__, exc), file=sys.stderr)
        return 2

    if not rs:
        print("REFUSING A VERDICT: no repositories configured, so 'nothing lost' would "
              "be a statement about nothing.", file=sys.stderr)
        print("       Set X4_CANARY_REPOS, or configure X4_GAME / X4_MODS.",
              file=sys.stderr)
        return 2

    all_losses: list[str] = []
    all_drift: list[str] = []
    unreadable = 0
    for repo in rs:
        try:
            losses, drift, bad = check(repo, args.verbose)
        except Exception as exc:  # noqa: BLE001 -- silent-ok: converted to rc 2 below, never swallowed
            # The SessionStart hook renders rc 1 as "A TRACKED IRREPLACEABLE FILE HAS
            # BEEN LOST -- recover it before doing anything else". An uncaught
            # exception ALSO exits 1, so a canary that itself broke was reported as
            # the worst possible verdict about the user's files. "Could not look" is
            # rc 2 here, the same contract every gate in this repo uses. MEASURED by
            # the 2026-09-05 delta review with a stub that raised PermissionError.
            print("REFUSING A VERDICT: the canary itself failed on %s: %s: %s"
                  % (repo.name, type(exc).__name__, exc), file=sys.stderr)
            unreadable += 1
            continue
        unreadable += bad
        all_losses += ["%s :: %s" % (repo.name, m) for m in losses] if not bad else losses
        all_drift += ["%s :: %s" % (repo.name, m) for m in drift]

    if unreadable:
        print("REFUSING A VERDICT: %d of %d repositories could not be checked. "
              "'Could not look' is not 'nothing wrong'." % (unreadable, len(rs)),
              file=sys.stderr)
        for m in all_losses:
            print("   " + m, file=sys.stderr)
        return 2

    if all_drift:
        print("changed (not a loss):")
        for m in all_drift:
            print("   " + m)

    if all_losses:
        print(file=sys.stderr)
        print("*** DATA LOSS in %d tracked file(s) ***" % len(all_losses),
              file=sys.stderr)
        for m in all_losses:
            print("   " + m, file=sys.stderr)
        print(file=sys.stderr)
        print("Recover the file, do not re-run whatever wrote it:", file=sys.stderr)
        print("   git -C <repo> checkout -- <path>", file=sys.stderr)
        return 1

    print("canary: %d repositor%s checked, no tracked file lost."
          % (len(rs), "y" if len(rs) == 1 else "ies"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
