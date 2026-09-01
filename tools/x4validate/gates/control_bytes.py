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

ROOT = Path(__file__).resolve().parent.parent
# Labels built from the byte value of a backslash, deliberately: the first draft wrote
# "\a"-style literals and the tool boundary collapsed them to the very control
# characters this gate hunts, and the tests passed because their expectations had
# collapsed the same way. test_labels_are_two_char_escapes pins the shape.
ESCAPES = {c: chr(92) + ch for c, ch in ((0x07, "a"), (0x08, "b"), (0x0B, "v"), (0x0C, "f"), (0x1B, "e"))}
TEXT = {".md", ".py", ".sh", ".txt", ".toml", ".yaml", ".yml", ".json", ".tsv", ".env"}


def scan_bytes(data: bytes) -> list[tuple[int, int, str]]:
    """(offset, byte, the escape it almost certainly was) for every control byte
    that is not TAB, LF or CR."""
    return [(i, c, ESCAPES[c]) for i, c in enumerate(data) if c in ESCAPES]


def scan_paths(paths) -> dict:
    hits, scanned, unreadable = [], 0, 0
    for p in paths:
        p = Path(p)
        try:
            data = p.read_bytes()
        except OSError:
            unreadable += 1
            continue
        scanned += 1
        for off, c, esc in scan_bytes(data):
            ctx = data[max(0, off - 30):off].decode("utf-8", "replace") + "<" + esc + ">" \
                + data[off + 1:off + 20].decode("utf-8", "replace")
            hits.append({"path": str(p), "offset": off, "byte": c, "escape": esc,
                         "context": ctx.replace("\r", "").replace("\n", " ")})
    return {"scanned": scanned, "unreadable": unreadable, "hits": hits}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    names = out.stdout.decode("utf-8", "replace").split("\0")
    return [ROOT / n for n in names if n and Path(n).suffix.lower() in TEXT]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths = tracked_text_files() + [Path(a) for a in argv]
    rep = scan_paths(paths)
    print(f"control-byte sweep: scanned {rep['scanned']} file(s), unreadable {rep['unreadable']}, "
          f"hits {len(rep['hits'])}")
    for h in rep["hits"]:
        print(f"  {h['path']} @{h['offset']} 0x{h['byte']:02x} (was {h['escape']}): ...{h['context']}...")
    if rep["scanned"] == 0:
        print("REFUSING: nothing was scanned, so this is not a clean sweep.", file=sys.stderr)
        return 2
    return 1 if rep["hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
