#!/usr/bin/env python3
"""Verify a Nexus upload pack is in the form the DESTINATION accepts, before a human pastes it.

WHY THIS EXISTS. Every rule this checks was already written down in the `releasing` procedure,
and three of them were broken in a single v3.2.0 pack on consecutive attempts -- each one found
not by a check but by the user pasting the file and seeing it come out wrong:

  1. The description was built in the form the Nexus API HANDS BACK, which is not the form its
     editor ACCEPTS. The API applies nl2br and HTML-escaping on output. MEASURED on mod 2186:
     206 occurrences of "<br />", all 206 immediately following a newline, none standalone --
     the signature of nl2br -- plus zero literal backslashes and 12 "&#92;" entities. Pasting
     that form puts literal "<br />" across the whole page.
  2. The kept "previous version" copy had the same defect, so the revert would have reproduced
     the bug it was there to undo.
  3. The changelog used `Path.write_text`, which translates newlines to CRLF on Windows, and
     its lines carried an issue plus its explanation plus a consequence -- against the
     "one issue per line, never combined" rule, while looking perfectly fine.

A rule you can read past is not a check. This refuses.

⚠ A preview you render yourself does not count as verification when it is built from the same
assumption as the artifact: it will agree with the bug. Every assertion here is phrased in terms
of what the destination accepts, which is the only vantage point that can see this class.

Usage:  python scripts/verify-nexus-pack.py release/nexus/v3.2.0
Exit:   0 every assertion holds · 1 an assertion failed · 2 cannot look (bad path, no files)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENTITY = re.compile(r"&(?:lt|gt|amp|quot|apos|#\d+);")
LINE_LIMIT = 120
# Files whose whole contents a human selects and pastes into a web form.
PASTEABLE_GLOBS = ("NEXUS-DESCRIPTION-*.txt", "NEXUS-CHANGELOG-*.txt",
                   "description-BEFORE-*.txt")
CHANGELOG_GLOB = "NEXUS-CHANGELOG-*.txt"


class Check:
    def __init__(self) -> None:
        self.failed: list[str] = []

    def __call__(self, ok: bool, label: str, detail: str = "") -> None:
        print("  %-5s %-56s %s" % ("ok" if ok else "FAIL", label, detail))
        if not ok:
            self.failed.append(label)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        # FOUND, not indexed: [-3] was the blank line above it, so this printed nothing.
        print(next(l for l in __doc__.splitlines() if l.startswith("Usage")), file=sys.stderr)
        return 2
    pack = Path(argv[0])
    if not pack.is_dir():
        print("REFUSING: not a directory: %s" % pack, file=sys.stderr)
        return 2

    text_files = sorted(f for f in pack.iterdir()
                        if f.is_file() and f.suffix.lower() in (".txt", ".md"))
    if not text_files:
        # An empty pack directory has shipped before (twice). Nothing to check is a FAILURE.
        print("REFUSING: no .txt/.md files in %s -- an empty pack has shipped before" % pack,
              file=sys.stderr)
        return 2

    pasteable = sorted({f for g in PASTEABLE_GLOBS for f in pack.glob(g)})
    check = Check()

    print("PACK: %s" % pack)
    print()
    print("contents (an empty file is a failure, not an absence)")
    for f in sorted(pack.iterdir()):
        if f.is_file():
            check(f.stat().st_size > 0, f.name, "%d bytes" % f.stat().st_size)
    check(bool(list(pack.glob("*.zip"))), "an archive is present",
          ", ".join(p.name for p in pack.glob("*.zip")) or "NONE")

    print()
    print("line endings -- LF only (write_bytes, never write_text, on Windows)")
    for f in text_files:
        n = f.read_bytes().count(b"\r\n")
        check(n == 0, f.name, "CRLF %d" % n)

    print()
    print("pasteable files carry the DESTINATION's form, not the API's read-back form")
    if not pasteable:
        check(False, "at least one pasteable file was identified",
              "globs: %s" % ", ".join(PASTEABLE_GLOBS))
    for f in pasteable:
        s = f.read_text(encoding="utf-8")
        ents = ENTITY.findall(s)
        check("<br" not in s, f.name + " :: no <br", "found %d" % s.count("<br"))
        check(not ents, f.name + " :: no HTML entities",
              "found %d %s" % (len(ents), sorted(set(ents))[:4]))
        check(not s.lstrip().startswith("#"), f.name + " :: no comment header",
              "a '#' preamble gets pasted too")

    print()
    print("changelog shape -- one issue per line, never combined")
    logs = sorted(pack.glob(CHANGELOG_GLOB))
    check(len(logs) == 1, "exactly one changelog", "found %d" % len(logs))
    for f in logs:
        lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        over = [(i, len(l)) for i, l in enumerate(lines, 1) if len(l) > LINE_LIMIT]
        multi = [i for i, l in enumerate(lines, 1) if l.rstrip(".").count(". ") > 0]
        check(bool(lines), "non-empty", "%d lines" % len(lines))
        check(not over, "every line <= %d chars" % LINE_LIMIT,
              ("over: %s" % over[:6]) if over
              else "longest %d" % max((len(l) for l in lines), default=0))
        check(not multi, "one sentence per line",
              ("lines %s carry more than one" % multi[:8]) if multi else "")

    print()
    if check.failed:
        print("PACK CHECK FAILED on %d assertion(s):" % len(check.failed))
        for lbl in check.failed:
            print("   - %s" % lbl)
        print()
        print("Do not hand this pack over. Fix, then re-run.")
        return 1
    print("PACK CHECK PASSED -- the pack is in the form the destination accepts.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
