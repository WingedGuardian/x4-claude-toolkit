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


#: git's C-style path quoting, decoded. `git status --porcelain` wraps a path in
#: double quotes and escapes it whenever it contains a byte outside plain ASCII --
#: and `core.quotePath` defaults to TRUE, so "cafe<acute>.txt" arrives as
#: "caf\303\251.txt". The old reader did `.strip('"')` and nothing else, so the
#: escaped form never matched a real file, `p.exists()` was False, and an ordinary
#: MODIFICATION was reported as `DELETED (tracked, now missing)` -- firing the
#: SessionStart banner "A TRACKED IRREPLACEABLE FILE HAS BEEN LOST". REPRODUCED in a
#: sandbox repo: a 400-byte file renamed to nothing, only edited, gave rc 1 and
#: `*** DATA LOSS in 1 tracked file(s) ***`. This tool's own docstring argues that a
#: check which cries wolf gets ignored, "which is how the last one failed".
#:
#: `-c core.quotePath=false` on the status call removes the octal class outright;
#: this decoder covers what git STILL quotes after that -- a path containing a quote,
#: a backslash or a control character.
_C_ESCAPES = {"n": 10, "t": 9, "r": 13, "f": 12, "b": 8, "v": 11, "a": 7,
              '"': 34, "\\": 92}


def _unquote(field: str) -> str:
    """Decode one C-quoted path field from `git status --porcelain`."""
    if len(field) < 2 or not (field.startswith('"') and field.endswith('"')):
        return field
    body, out, i = field[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.extend(c.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(body):
            break
        n = body[i]
        if n in _C_ESCAPES:
            out.append(_C_ESCAPES[n])
            i += 1
        elif n.isdigit() and len(body) - i >= 3:
            try:
                out.append(int(body[i:i + 3], 8))
                i += 3
            except ValueError:          # not octal after all; take it literally
                out.extend(n.encode("utf-8"))
                i += 1
        else:
            out.extend(n.encode("utf-8"))
            i += 1
    return out.decode("utf-8", "surrogateescape")


def _git(repo: Path, *args: str) -> tuple[int, str]:
    """Run git and decode its output as UTF-8, which is what git emits.

    ★ `text=True` ALONE DECODES WITH THE LOCALE CODEPAGE — cp1252 on this
    machine — and git writes paths as UTF-8 on every platform. So a tracked
    file named `cafe<acute>.txt` came back as the mojibake `cafA<tilde>c.txt`,
    `p.exists()` was False, and an ordinary MODIFICATION was reported as
    `DELETED (tracked, now missing)` — rc 1, and the SessionStart banner "A
    TRACKED IRREPLACEABLE FILE HAS BEEN LOST". REPRODUCED in a sandbox repo.

    ⚠ AND THE FIRST FIX FOR THIS WAS THE ADJACENT ONE. Disabling `core.quotePath`
    and decoding git's octal escapes was necessary and NOT sufficient: the path
    then arrived unescaped and was still mangled one layer down, at this call.
    MEASURED by printing the codepoints — `0xc3 0xa9` where the file on disk
    has `0xe9` — after the verdict had already been declared fixed. Both
    layers are kept: quoting is a git-side transform, decoding is a Python-side
    one, and each is wrong on its own.

    `surrogateescape` rather than `replace`: an undecodable byte must survive
    round-trip to a path lookup, not be silently turned into a different name.
    """
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="surrogateescape")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


#: Roots `_paths` knows about but could not resolve on this machine. Populated
#: by `repos()`, reported by `main()` beside the repository count.
UNRESOLVED: list[str] = []


def repos() -> list[Path]:
    """The resolved roots PLUS anything configured, never one instead of the other.

    `X4_CANARY_REPOS` extends rather than replaces, matching `X4_PROTECTED` in
    x4lock. Two sibling tools whose env vars mean opposite things is a trap: setting
    the memory directory here would otherwise silently stop checking the game root.
    """
    UNRESOLVED.clear()
    out: list[Path] = []
    if _paths is not None:
        for fn in ("game_root", "mods"):
            got = getattr(_paths, fn)()
            if got:
                out.append(Path(got))
            else:
                # NAMED, NOT DROPPED. An unresolved root used to vanish here,
                # and the run then printed "1 repository checked, no tracked
                # file lost" — true, and silent about the tree this tool was
                # built to watch. Not an error: an unconfigured root is a real
                # setup state, and making it rc 2 would fire on every cold
                # clone. But the count in the verdict has to be a denominator
                # the reader can check, so the gap is reported beside it.
                UNRESOLVED.append(fn)
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

    rc, out = _git(repo, "-c", "core.quotePath=false",
                   "status", "--porcelain")
    if rc != 0:
        return (["%s: git status failed -- %s" % (repo, out.strip()[:120])], [], 1)

    for line in out.splitlines():
        if len(line) < 4:
            continue
        code, rel = line[:2], _unquote(line[3:].strip())
        # A RENAME/COPY carries TWO paths in one field: `R  old.yaml -> new.yaml`.
        # Read whole, `p.exists()` is False and an ordinary `git mv` was reported as
        # "DELETED (tracked, now missing)" -- firing the SessionStart banner "A TRACKED
        # IRREPLACEABLE FILE HAS BEEN LOST". MEASURED 2026-09-04; the watched `dev`
        # history contains 2 real renames. The docstring's own argument is that a check
        # which cries wolf gets ignored, "which is how the last one failed".
        # The DESTINATION is the file that now exists and is what must be checked.
        was_rel = ""
        if code and code[0] in ("R", "C") and " -> " in rel:
            was_rel, rel = (_unquote(s.strip())
                            for s in rel.split(" -> ", 1))
        p = repo / rel
        if "D" in code or not p.exists():
            losses.append("%s: DELETED (tracked, now missing)" % rel)
            continue
        # AN ALLOW-LIST OF FOUR STATUS CODES, WHERE THE QUESTION IS BINARY.
        # Anything git TRACKS has a HEAD blob to compare against; only "??"
        # (untracked) and "!!" (ignored) do not. The old list -- M, MM, AM, T --
        # sent every other tracked code to drift UNSIZED, so a file that was
        # renamed and then EMPTIED ("RM") reported as a benign change, and so
        # did "MT", "AT" and the rest. A loss inside a renamed file is exactly
        # the shape a bad `mv` produces, and this is the tool that exists to
        # catch it. Inverted: skip what has no HEAD blob, size everything else.
        if code.strip() in ("??", "!!"):
            drift.append("%s: %s" % (rel, code.strip() or "?"))
            continue
        # A RENAME'S HEAD BLOB LIVES AT THE OLD PATH. Asking for
        # `HEAD:<new>` fails, which fell to "no HEAD blob to compare" and
        # therefore to DRIFT — so a file that was renamed and then EMPTIED
        # reported as a benign change. That is exactly the shape a bad `mv`
        # produces, in the tool built to catch it. The old path was already
        # parsed out of the status line and then thrown away.
        ref = "HEAD:" + (was_rel or rel)
        rc2, blob = _git(repo, "cat-file", "-s", ref)
        if rc2 != 0:
            drift.append("%s: modified (no HEAD blob to compare)" % rel)
            continue
        try:
            was, now = int(blob.strip()), p.stat().st_size
        except (ValueError, OSError) as exc:
            return ["%s: cannot size %s -- %s" % (repo, rel, exc)], drift, 1
        named = ("%s (was %s)" % (rel, was_rel)) if was_rel else rel
        if was > 0 and now == 0:
            losses.append("%s: EMPTIED (%d bytes -> 0)" % (named, was))
        elif was > 0 and now < was * SHRINK_FLOOR:
            losses.append("%s: SHRANK %d -> %d bytes (%.0f%% lost)"
                          % (named, was, now, 100 * (1 - now / was)))
        elif verbose:
            drift.append("%s: %d -> %d bytes" % (rel, was, now))
    return losses, drift, 0


#: Per-list cap on every item list this tool prints.
#:
#: MEASURED 2026-09-07, CC 2.1.263: Claude Code files hook output above 10,000
#: CHARACTERS and shows the model a ~2 KB preview -- no error, exit code
#: unchanged. session-canary.sh feeds this tool's whole output into that
#: channel, so the loss report has a ceiling it never knew about. Uncapped, the
#: list crossed it at roughly 81 files against the 473 tracked across the two
#: watched repos (an UPPER bound: a renamed-and-emptied file carries the wider
#: "new.md (was old.md)" form and crosses sooner).
#:
#: The failure was INVERTED AGAINST SEVERITY. One lost file sails under the cap;
#: a directory-level loss -- the case that actually matters -- is the one that
#: gets filed. A warning channel whose output length scales with the severity it
#: reports fails silently exactly when it matters most.
#:
#: 40 keeps all three lists plus their headers well inside the limit even when
#: every one of them is populated. session-canary.sh bounds the whole payload
#: again as a backstop; this cap exists so the truncation happens on a WHOLE-LINE
#: boundary with a count, rather than mid-path in the middle of a filename.
_LIST_CAP = 40


def _emit(items: list[str], stream) -> None:
    """Print a bounded item list that DISCLOSES its own bound.

    A bare `[:n]` slice makes the number wrong, not merely the list -- the same
    rule `_scan.count_line` exists to enforce on the validator side. Anything
    dropped here is named as dropped.
    """
    for m in items[:_LIST_CAP]:
        print("   " + m, file=stream)
    if len(items) > _LIST_CAP:
        print("   ... and %d more NOT LISTED (showing %d of %d; the report is "
              "capped so it survives the 10,000-character hook-output limit)"
              % (len(items) - _LIST_CAP, _LIST_CAP, len(items)), file=stream)


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

    def _report_unresolved(stream=sys.stdout):
        """Print the NOT-CHECKED note. Called on EVERY exit path.

        It used to live inside the rc-0 branch alone — and rc 0 is the one
        branch `session-canary.sh` discards (`0) : ;;  # stay quiet`), so the
        channel added to stop the run being "silent about the tree this tool was
        built to watch" reached nobody at all. MEASURED across all three exit
        paths: printed on rc 0 and swallowed by the hook; absent entirely from
        rc 1 and rc 2. A disclosure with no reachable reader is decoration, and
        this one was added THIS RELEASE to close exactly that shape.
        """
        if not UNRESOLVED:
            return
        print("  NOT CHECKED: %s did not resolve on this machine, so %s not "
              "among the repositories checked above."
              % (" and ".join(UNRESOLVED),
                 "it is" if len(UNRESOLVED) == 1 else "they are"), file=stream)

    if not rs:
        print("REFUSING A VERDICT: no repositories configured, so 'nothing lost' would "
              "be a statement about nothing.", file=sys.stderr)
        print("       Set X4_CANARY_REPOS, or configure X4_GAME / X4_MODS.",
              file=sys.stderr)
        return 2

    all_losses: list[str] = []
    all_drift: list[str] = []
    # TWO CHANNELS, BECAUSE `check()` RETURNS ITS REASON IN THE LOSS SLOT. When a
    # repo is unreadable it comes back as (["<repo>: not a git repository"], [], 1)
    # -- a REASON, not a lost file -- and the old code appended that string to
    # `all_losses` anyway. Harmless while both outcomes returned 2; the moment a
    # found loss was made to outrank an unreadable repo, an unreadable repo started
    # claiming rc 1 = DATA LOSS on the strength of its own explanation. Caught by
    # test_an_UNREADABLE_repo_with_NO_loss_is_still_rc2, which exists as the twin of
    # that very change.
    unreadable_reasons: list[str] = []
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
            unreadable_reasons.append("%s: %s: %s"
                                      % (repo.name, type(exc).__name__, exc))
            continue
        if bad:
            unreadable += bad
            unreadable_reasons += losses
        else:
            all_losses += ["%s :: %s" % (repo.name, m) for m in losses]
        all_drift += ["%s :: %s" % (repo.name, m) for m in drift]

    if unreadable:
        print("REFUSING A VERDICT: %d of %d repositories could not be checked. "
              "'Could not look' is not 'nothing wrong'." % (unreadable, len(rs)),
              file=sys.stderr)
        _emit(unreadable_reasons, sys.stderr)
        # A CONFIRMED LOSS OUTRANKS AN UNREADABLE REPOSITORY, and this returned 2 for
        # both. One unreadable repo therefore DOWNGRADED a real, already detected loss
        # in a DIFFERENT repo from rc 1 to rc 2 — and rc is what the SessionStart
        # hook reads, so the "A TRACKED IRREPLACEABLE FILE HAS BEEN LOST" banner never
        # fired. The losses were printed; nothing acted on them. Falls through to the
        # DATA LOSS block below so the loss is reported in full.
        if not all_losses:
            _report_unresolved(sys.stderr)
            return 2
        print("   — and a loss was FOUND below, not merely suspected, so this run "
              "is rc 1 (DATA LOSS) rather than rc 2.", file=sys.stderr)

    if all_drift:
        print("changed (not a loss):")
        _emit(all_drift, sys.stdout)

    if all_losses:
        print(file=sys.stderr)
        print("*** DATA LOSS in %d tracked file(s) ***" % len(all_losses),
              file=sys.stderr)
        # THE DIRECTIVE GOES BEFORE THE LIST, and that ordering is load-bearing.
        # When this output is filed for length the preview keeps the HEAD, so a
        # directive printed after the inventory is the first thing dropped -- and
        # it is the only actionable sentence here. "do not re-run whatever wrote
        # it" is specifically what stops the recoverable state being destroyed,
        # so it must survive a truncation that eats everything below it.
        print("Recover the file, do not re-run whatever wrote it:", file=sys.stderr)
        print("   git -C <repo> checkout -- <path>", file=sys.stderr)
        print(file=sys.stderr)
        _emit(all_losses, sys.stderr)
        _report_unresolved(sys.stderr)
        return 1

    print("canary: %d repositor%s checked, no tracked file lost."
          % (len(rs), "y" if len(rs) == 1 else "ies"))
    _report_unresolved()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
