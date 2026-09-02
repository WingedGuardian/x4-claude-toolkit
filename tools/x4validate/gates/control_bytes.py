"""Find collapsed-escape control bytes in permanent-record text files.

MEASURED 2026-08-30, three files in two days, all one cause: content written
through an inline interpreter string, where a backslash escape (b, v, f, a)
collapsed to 0x08 / 0x0B / 0x0C / 0x07 on the way to disk -- in one case inside
the very sentence documenting an escaping defect. None was visible in any normal
view of the file. A peer session found the third with a one-line byte sweep;
this makes that sweep a gate.

Run:  uv run python gates/control_bytes.py [extra paths...]
      Scans every git-tracked text file in this repo (by extension) plus any
      extra paths given -- pass the game root's CLAUDE.md / KNOWLEDGEBASE.md and
      the memory directory to cover permanent record outside the repo.
Exit: 0 clean / 1 control bytes found / 2 nothing scanned (a sweep over zero
      files is not a clean sweep).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: The REPOSITORY root, not the package root. MEASURED 2026-09-02: this was
#: `parent.parent` (= tools/x4validate) and `git ls-files` ran there, so the sweep
#: covered **171 of 241** tracked files. Everything outside the package was invisible
#: -- including the whole of `.claude/hooks/` and `scripts/`, which is precisely where
#: content is written through interpreter strings and where the escapes collapse. The
#: gate could not see the file that carried the defect it exists to find: a literal
#: 0x08 sat in `scripts/fuzz-guard.py` for a release and this sweep reported clean.
_PKG = Path(__file__).resolve().parent.parent
ROOT = _PKG.parent.parent
# Labels built from the byte value of a backslash, deliberately: the first draft wrote
# "\a"-style literals and the tool boundary collapsed them to the very control
# characters this gate hunts, and the tests passed because their expectations had
# collapsed the same way. test_labels_are_two_char_escapes pins the shape.
ESCAPES = {c: chr(92) + ch for c, ch in ((0x07, "a"), (0x08, "b"), (0x0B, "v"), (0x0C, "f"), (0x1B, "e"))}
#: Used ONLY to pick files out of a DIRECTORY argument (the memory dir, the game
#: root's docs). Tracked files are no longer filtered by extension at all -- see
#: `looks_binary`. An extension allowlist is a narrowing step that reports success,
#: and this one silently excluded .xml, .lua and .ps1 from a repo that ships all three.
TEXT = {".md", ".py", ".sh", ".txt", ".toml", ".yaml", ".yml", ".json", ".tsv", ".env",
        ".xml", ".lua", ".ps1", ".example", ".lock", ".cfg", ".ini", ".bat"}


def looks_binary(data: bytes) -> bool:
    """A NUL byte. MEASURED 2026-09-02 over all 241 tracked files: 240 contain no NUL
    and exactly one does (BaseX.jar). Sniffing content instead of trusting a suffix
    means a new file type is covered the day it is added, with no list to update."""
    return bytes([0]) in data


def scan_bytes(data: bytes) -> list[tuple[int, int, str]]:
    """(offset, byte, the escape it almost certainly was) for every control byte
    that is not TAB, LF or CR."""
    return [(i, c, ESCAPES[c]) for i, c in enumerate(data) if c in ESCAPES]


def expand(paths) -> list:
    """Directories become their text files, recursively.

    MEASURED 2026-08-31: this gate's own docstring says to pass the memory DIRECTORY, and
    doing so scanned NONE of it -- `read_bytes()` on a directory raises OSError, so all 70
    files were counted as one "unreadable" and skipped. The sweep then reported a clean
    184 files, which is exactly what a clean sweep of the repo alone looks like. The
    documented invocation was the broken one, and the only tell was a `1` in a column
    nobody reads.
    """
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*")
                              if f.is_file() and f.suffix.lower() in TEXT))
        else:
            out.append(p)
    return out


def scan_paths(paths) -> dict:
    hits, scanned, unreadable, binary = [], 0, [], []
    for p in expand(paths):
        p = Path(p)
        try:
            data = p.read_bytes()
        except OSError:
            # NAMED, not merely counted. A count tells you something was skipped; only a
            # name tells you whether it mattered.
            unreadable.append(str(p))
            continue
        if looks_binary(data):
            # A separate bucket from `unreadable`: a binary is CORRECTLY not scanned,
            # so it must not trip the hole-in-the-denominator refusal below. Still
            # named, because "skipped" with no name is how a hole hides.
            binary.append(str(p))
            continue
        scanned += 1
        for off, c, esc in scan_bytes(data):
            ctx = data[max(0, off - 30):off].decode("utf-8", "replace") + "<" + esc + ">" \
                + data[off + 1:off + 20].decode("utf-8", "replace")
            hits.append({"path": str(p), "offset": off, "byte": c, "escape": esc,
                         "context": ctx.replace("\r", "").replace("\n", " ")})
    return {"scanned": scanned, "unreadable": unreadable, "binary": binary,
            "hits": hits}


def tracked_text_files() -> list[Path]:
    """EVERY git-tracked file, or [] when this is not a git checkout.

    No extension filter: binaries are separated by CONTENT in scan_paths. The name is
    kept for its callers.

    MEASURED 2026-09-01 in a `git archive` extract -- which is exactly what a release
    tarball is: `check=True` raised CalledProcessError, the gate exited 1, and
    run-gates.sh buckets 1 as FAIL. The refusal path this file already implements
    (rc 2 = CANNOT) was unreachable because the crash preceded it, so a user running the
    gates from a tarball saw a failure where the honest answer is "not applicable here".
    """
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        # silent-ok: not a git checkout. The caller REFUSES on scanned==0 with rc 2 and
        # names this cause, so nothing is lost here -- returning [] simply lets that one
        # refusal speak instead of two. Raising would exit 1 (=FAIL), which is the very
        # confusion this fix removes: a tarball is "cannot check", not "found a defect".
        return []
    names = out.stdout.decode("utf-8", "replace").split("\0")
    return [ROOT / n for n in names if n]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths = tracked_text_files() + [Path(a) for a in argv]
    rep = scan_paths(paths)
    print(f"control-byte sweep: scanned {rep['scanned']} file(s), "
          f"binary-skipped {len(rep['binary'])}, "
          f"unreadable {len(rep['unreadable'])}, hits {len(rep['hits'])}")
    for b in rep["binary"]:
        print(f"  binary (correctly not scanned): {b}")
    for u in rep["unreadable"]:
        print(f"  UNREADABLE (not scanned): {u}")
    for h in rep["hits"]:
        print(f"  {h['path']} @{h['offset']} 0x{h['byte']:02x} (was {h['escape']}): ...{h['context']}...")
    if rep["scanned"] == 0:
        print("REFUSING: nothing was scanned, so this is not a clean sweep. (Outside a "
              "git checkout, pass the paths to scan explicitly.)", file=sys.stderr)
        return 2
    # An UNREADABLE path is a hole in the denominator, not a pass. Reporting "0 hits"
    # beside a file nobody opened is the shape this whole gate exists to catch.
    if rep["unreadable"]:
        print(f"REFUSING: {len(rep['unreadable'])} path(s) could not be read, so this is a "
              f"sweep with a hole in it, not a clean sweep.", file=sys.stderr)
        return 2
    return 1 if rep["hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
