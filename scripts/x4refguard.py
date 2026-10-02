#!/usr/bin/env python3
r"""Layer 2 for `reference/`: an OS-level protection that holds against EVERY process,
hooks or no hooks -- and that reports each state as itself, never as "protected" by default.

WHY. `reference/` is the unpacked base game + DLC: ~510,000 files, a 27 GB re-unpack to
replace. Until this tool its only protection was the `.unpacked-and-locked` sentinel
(which the toolkit's own scripts respect) and the Claude hooks (which see only commands
Claude types). An interpreter write -- `python -c "open(p, 'w')"` -- passed both.

WHAT IT APPLIES

  Windows   one inherited deny ACE on the root, for the CURRENT USER'S SID:
                icacls <root> /deny *<SID>:(OI)(CI)(DE,DC,WD,AD)
            = Delete + DeleteSubdirectoriesAndFiles + WriteData + AppendData
            = numeric mask 65606 (EXPECTED_MASK). Never W, S, WDAC, WO or F: `W` carries
            SYNCHRONIZE and denied READS; WDAC made an earlier deny unremovable (see
            x4lock.py, "WHY THERE IS NO ACL HERE").
            MEASURED 2026-10-02 on scratch trees (docs/superpowers/measurements):
            reads 12/12 still work; writes 20/20 and deletes/renames 15/15 blocked;
            removable by the same unelevated user 47/47 with 0 deny entries left;
            ~8 s per 100k files to apply or remove; mtime/size unchanged 100k/100k.
  Linux     BEST EFFORT, NOT DEVICE-TESTED. As root with `chattr`: `chattr -R +i`
            (immutable). Otherwise: `chmod a-w` on every directory and file -- a
            directory without write permission refuses unlink/rename/create inside it,
            a file without it refuses an overwrite.
  macOS     BEST EFFORT, NOT DEVICE-TESTED. `chflags -R uchg` (owner-settable
            immutable flag), else the same chmod fallback.
  other     exit 3 `unsupported` -- the ONLY case that exit 3 means.

`status` names the mechanism found, what it stops, and what it does NOT stop. It never
reports a layer it could not confirm by re-reading the filesystem.

WHAT IT DOES NOT STOP (the honest gaps)
  * Renaming the reference ROOT itself: the PARENT directory grants that (MEASURED on
    Windows; INFERRED on POSIX for chmod). `status` then reports the configured root
    missing, never "protected".
  * The same user deliberately lifting it -- `remove` below, or the raw commands in the
    escape hatch. This stops ACCIDENTS, not intent. Agent harnesses gate `remove` (a
    Claude `ask`, a Codex `.rules` prompt).
  * Windows: an Administrator; changing ACLs/attributes (WRITE_DAC is deliberately not
    denied, so the deny stays removable). POSIX chmod: root, and `chmod u+w` by the owner.

USAGE
    python scripts/x4refguard.py status [--json] [--full]
    python scripts/x4refguard.py apply  [--path P]     P must be the configured root
    python scripts/x4refguard.py remove [--path P]     the escape hatch, step 1/2

`status` samples: the root, the sentinel, and the first file found depth-first in each
top-level directory -- NOT a census, and it says so on every run. `--full` walks every
object (slow on Windows: one Get-Acl per object) and says how many it walked.

EXIT CODES (the toolkit's contract)
    0  protected, or the action succeeded AND was verified by re-reading
    1  absent or partial, or the action ran but verification disagrees
    2  unconfigured, refused, or the state could not be read
    3  unsupported platform (no mechanism exists here)

ESCAPE HATCH -- how a USER lifts it (never an agent on its own):
    1. python scripts/x4refguard.py remove
    2. if the configured root has changed since:  ... remove --path <old root>
       (accepted only if that path carries THIS tool's exact protection)
    3. if this tool is broken, Windows, from cmd.exe:
           icacls "<root>" /remove:d *<your SID>      (`whoami /user` prints the SID)
       Linux: sudo chattr -R -i "<root>"  /  chmod -R u+w "<root>"
       macOS: chflags -R nouchg "<root>"  /  chmod -R u+w "<root>"
    4. last resort, Windows, elevated:  icacls "<root>" /reset /T /C
       (discards every explicit ACE in the tree and restores inheritance)

TEST SAFETY. When `X4_REFGUARD_SANDBOX` is set, every mutating call (icacls, chattr,
chflags, chmod) first asserts its target is strictly under that directory and raises
SandboxViolation -- deliberately not an Exception subclass, so nothing swallows it --
otherwise. The test suites set it to their tmp dir.

Stdlib only; imports on Python 3.10.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLKIT = _HERE.parent
sys.path.insert(0, str(_TOOLKIT / "tools" / "x4validate"))

try:
    from x4validate import _paths
except ImportError:                     # pragma: no cover - packaging accident
    _paths = None

#: Delete 0x10000 + DeleteSubdirectoriesAndFiles 0x40 + WriteData 0x2 + AppendData 0x4.
EXPECTED_MASK = 0x10000 | 0x40 | 0x2 | 0x4          # 65606, MEASURED as Get-Acl reports it
ICACLS_SPEC = "(OI)(CI)(DE,DC,WD,AD)"
#: ObjectInherit | ContainerInherit, as Get-Acl reports InheritanceFlags.
_INHERIT_BOTH = 3
SENTINEL = ".unpacked-and-locked"
SANDBOX_ENV = "X4_REFGUARD_SANDBOX"
SUPPORTED = ("windows", "linux", "darwin")

SAMPLE_SCOPE = ("root + sentinel + first file of each top-level dir "
                "(not a census; use --full)")

ESCAPE_HATCH = """\
To lift it (a USER's step, never an agent's on its own):
  1. python scripts/x4refguard.py remove
  2. root moved since?  python scripts/x4refguard.py remove --path <old root>
  3. tool broken? Windows, from cmd.exe: icacls "<root>" /remove:d *<your SID>  (whoami /user)
     Linux: sudo chattr -R -i "<root>" or chmod -R u+w "<root>"; macOS: chflags -R nouchg "<root>"
  4. last resort, Windows, elevated: icacls "<root>" /reset /T /C"""


class Refused(Exception):
    """The target is not one this tool may act on. Exit 2."""


class Unresolvable(RuntimeError):
    """The configuration could not be READ -- distinct from "nothing is configured"."""


class SandboxViolation(BaseException):
    """A mutating call aimed outside $X4_REFGUARD_SANDBOX. BaseException on purpose:
    an `except Exception` anywhere on the path must not turn it into a refusal."""


# ------------------------------------------------------------------- seams

def _platform() -> str:
    """'windows' | 'linux' | 'darwin' | anything else. The ONE platform seam: tests steer
    it here instead of patching `os.name`, which pathlib also dispatches on."""
    if os.name == "nt":
        return "windows"
    return sys.platform if sys.platform in ("linux", "darwin") else sys.platform


def _geteuid() -> int:
    fn = getattr(os, "geteuid", None)
    return fn() if fn else -1


def _which(name: str):
    return shutil.which(name)


def _configured_root():
    """The configured reference root, or None when NOTHING configures it.

    Raises Unresolvable when the configuration could not be read at all, exactly like
    x4lock: "could not look" must never be reported as "nothing to protect"."""
    if _paths is None:
        raise Unresolvable(
            "x4validate._paths could not be imported, so the configured reference root "
            "is unknown.")
    return _paths.reference()


def _norm(p) -> str:
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(p)))


def _is_same_or_ancestor(a, b) -> bool:
    """True when `a` is `b` or contains it."""
    na, nb = _norm(a), _norm(b)
    return nb == na or nb.startswith(na.rstrip("\\/") + os.sep)


def _sandbox_check(target) -> None:
    box = os.environ.get(SANDBOX_ENV)
    if not box:
        return
    t, b = _norm(target), _norm(box)
    if t == b or not t.startswith(b.rstrip("\\/") + os.sep):
        raise SandboxViolation(
            "x4refguard: refusing a mutating call on %s -- it is not strictly under "
            "%s=%s" % (target, SANDBOX_ENV, box))


def _mutate_run(argv: list, target) -> subprocess.CompletedProcess:
    """THE choke point for every icacls/chattr/chflags call that changes anything."""
    _sandbox_check(target)
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                          errors="replace")


def _mutate_chmod(path, mode: int) -> None:
    """THE choke point for every chmod."""
    _sandbox_check(path)
    os.chmod(path, mode)


# -------------------------------------------------------------- resolution

def _dangerous(root: Path):
    """A reason this root must never be protected, or None."""
    if _norm(root) == _norm(root.anchor):
        return "it is a drive/filesystem root"
    home = Path.home()
    if _is_same_or_ancestor(root, home):
        return "it is your home directory or contains it"
    game = None
    if _paths is not None:
        try:
            game = _paths.game_root()
        except Exception:                   # noqa: BLE001 - a broken config is not a pass
            game = None
    if game and _is_same_or_ancestor(root, game):
        return "it is the game root or contains it (%s)" % game
    toolkits = [_TOOLKIT]
    if os.environ.get("X4_TOOLKIT"):
        toolkits.append(Path(os.environ["X4_TOOLKIT"]))
    for tk in toolkits:
        if _is_same_or_ancestor(root, tk):
            return "it is the toolkit root or contains it (%s)" % tk
    if (root / ".git").exists():
        return "it is a git checkout (.git at its root)"
    return None


def resolve_target(path, action: str) -> Path:
    """The directory `action` may act on, or raise Refused / Unresolvable.

    Order: unsupported platform is decided by the caller (exit 3); then unconfigured;
    then an explicit --path that is not the configured root (remove alone accepts one
    that carries this tool's exact protection); then, for apply, not a directory,
    dangerous roots, and a missing sentinel.
    """
    configured = _configured_root()
    if configured is None:
        raise Refused("no reference root is configured (set X4_REFERENCE, see "
                      "`x4validate --paths`)")
    if path is not None and _norm(path) != _norm(configured):
        if action == "remove" and Path(path).is_dir() and _carries_our_protection(Path(path)):
            return Path(path).resolve()
        raise Refused("%s is not the configured reference root (%s)" % (path, configured))
    root = Path(configured)
    if not root.is_dir():
        raise Refused("the configured reference root %s is not an existing directory "
                      "(renamed or moved? status cannot vouch for it)" % root)
    root = root.resolve()
    if action == "apply":
        why = _dangerous(root)
        if why:
            raise Refused("refusing to protect %s: %s" % (root, why))
        if not (root / SENTINEL).is_file():
            raise Refused("%s has no %s sentinel, so it is not a finished unpack -- "
                          "protecting it would lock a broken tree" % (root, SENTINEL))
    return root


def _carries_our_protection(p: Path) -> bool:
    """Does `p` carry exactly what THIS tool applies? Used only to let `remove --path`
    lift a root that is no longer configured, never an arbitrary directory."""
    return False          # mechanisms land in the next commit


# ------------------------------------------------------------------ report

def _blank(state: str, root=None, detail: str = "") -> dict:
    return {
        "state": state, "root": str(root) if root is not None else None,
        "platform": _platform(), "mechanism": None,
        "mask": None, "mask_expected": EXPECTED_MASK if _platform() == "windows" else None,
        "sentinel": bool(root is not None and (Path(root) / SENTINEL).is_file()),
        "owner_is_user": None, "sampled": 0, "sample_ok": 0,
        "sample_scope": SAMPLE_SCOPE, "stops": [], "does_not_stop": [],
        "detail": detail,
    }


def report(full: bool = False, path=None) -> dict:
    """The status object (see `status --json`). Never raises for an expected state."""
    plat = _platform()
    if plat not in SUPPORTED:
        return _blank("unsupported", detail="no protection mechanism exists for platform "
                      "%r; reference/ is NOT OS-protected here (disclosed gap)" % plat)
    try:
        configured = _configured_root()
    except Unresolvable as exc:
        return _blank("error", detail=str(exc))
    if configured is None and path is None:
        return _blank("unconfigured", detail="no reference root is configured")
    root = Path(path) if path is not None else Path(configured)
    if not root.is_dir():
        return _blank("unconfigured", root, "the configured reference root %s does not "
                      "exist (renamed or moved?)" % root)
    return _blank("error", root.resolve(), "mechanism not implemented yet")


_EXIT = {"protected": 0, "absent": 1, "partial": 1, "foreign": 2, "unconfigured": 2,
         "error": 2, "unsupported": 3}


# ---------------------------------------------------------------- commands

def _human(r: dict) -> str:
    return "reference deny-delete: %s -- %s" % (r["state"], r["detail"])


def cmd_status(args) -> int:
    r = report(full=args.full, path=getattr(args, "path", None))
    if args.json:
        print(json.dumps(r, sort_keys=True))
    else:
        print(_human(r))
        print("  sample scope: %s; %d of %d sampled object(s) protected" % (
            "FULL walk" if args.full else r["sample_scope"], r["sample_ok"], r["sampled"]))
        if r["state"] not in ("protected", "unsupported"):
            print(ESCAPE_HATCH)
    return _EXIT.get(r["state"], 2)


def _act(args, action: str) -> int:
    if _platform() not in SUPPORTED:
        print("UNSUPPORTED: no protection mechanism exists for platform %r; nothing was "
              "%s." % (_platform(), "applied" if action == "apply" else "removed"),
              file=sys.stderr)
        return 3
    try:
        root = resolve_target(args.path, action)
    except (Refused, Unresolvable) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        print(ESCAPE_HATCH, file=sys.stderr)
        return 2
    print("ERROR: mechanism not implemented yet for %s" % root, file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="x4refguard",
        description="Layer-2 OS protection of the reference/ tree (see the module "
                    "docstring for what it stops, what it does not, and the escape hatch).",
        epilog=ESCAPE_HATCH, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("status", help="report the protection state")
    st.add_argument("--json", action="store_true")
    st.add_argument("--full", action="store_true", help="walk every object, not a sample")
    ap_ = sub.add_parser("apply", help="protect the configured reference root")
    ap_.add_argument("--path")
    rm = sub.add_parser("remove", help="lift the protection (the escape hatch)")
    rm.add_argument("--path")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd in ("apply", "remove"):
        return _act(args, args.cmd)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
