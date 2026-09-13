#!/usr/bin/env python
"""Is every CLI this package installs named in CLAUDE.md's routing table?

WHY THIS EXISTS. Whether a tool is routed was a PROSE property that no check
tested, and it drifted: MEASURED 2026-09-12, **5 of 11 CLIs** -- x4modlist,
x4stats, x4diff, x4save, x4live -- were absent from the routing table's `Use`
column, through a full CLAUDE.md rewrite that was a natural moment to fix it.

WHAT THIS GATE CLAIMS, AND WHAT IT MUST NOT CLAIM. It enforces RESIDENT ROUTING:
a cold session should reach any tool without searching. It does **not** claim a
missing row makes a tool undiscoverable. MEASURED by experiment the same day: a
cold agent given the workspace and no hint found an unrouted CLI and answered a
live question correctly in 193 s, via KNOWLEDGEBASE.md and the toolkit README,
before its row existed. The cost of a missing row is **search** -- 39 tool calls
and ~74k tokens -- not unreachability. The stronger claim came from measuring
"mentions" over CLAUDE.md + skills only while concluding something about every
surface a reader has, and restating it here would re-introduce that error.

THE SURFACE IS AN EXPLICIT INPUT, not an inference. Today it is CLAUDE.md's
routing table. When the tool inventory moves to a generated MCP registry, change
SURFACE and its test -- a gate that INFERRED its surface would start passing for
the wrong reason the moment that landed.

Run:  uv run python gates/routing_coverage.py
Exit: 0 every CLI routed - 1 one or more unrouted, named - 2 could not determine
      the roster or read the table (a sweep over nothing is not a clean sweep).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from x4validate import _paths, _surface  # noqa: E402

#: The resident routing surface. See the docstring: explicit, never inferred.
SURFACE = "CLAUDE.md routing table"

#: A row's cells are pipe-separated, but `\|` is a LITERAL pipe -- the correct
#: markdown escape. Built from the byte value: writing the backslash as a literal
#: inside an inline interpreter string is how it gets eaten at a tool boundary,
#: and a peer lost one the same day building this very check.
_BSLASH = chr(92)
_ESC_PIPE = _BSLASH + "|"
_SENTINEL = "\x00"


class TableUnreadable(Exception):
    """The routing table could not be read, so no verdict about it is admissible."""


def table_rows(text: str) -> list[list[str]]:
    """Data rows of the routing table, each as its cells. Escaped pipes stay data.

    Raises TableUnreadable rather than returning [] -- zero rows would make every
    CLI read as unrouted, which is a different finding from "I could not read it".
    """
    # No CRLF normalisation: MEASURED 2026-09-12 by mutation, removing it changes
    # nothing. The lookahead below still terminates on "\r\n\r\n", and a trailing CR is
    # removed by the .strip() in the cell split, not here. A line kept "just in case"
    # that no test can distinguish is a line the next reader has to reason about.
    m = re.search(r"^\|\s*Question shape.*?(?=\n\s*\n|\Z)", text, re.S | re.M)
    if not m:
        raise TableUnreadable(
            "no routing table found (expected a row starting '| Question shape')")
    out: list[list[str]] = []
    for line in m.group(0).split("\n"):
        if not line.startswith("|"):
            continue
        if re.fullmatch(r"\|[\s|:-]+\|", line.strip()):
            continue                      # the |---|---| separator
        if "Question shape" in line:
            continue                      # the header
        cells = [c.replace(_SENTINEL, _ESC_PIPE)
                 for c in line.replace(_ESC_PIPE, _SENTINEL).strip().strip("|").split("|")]
        out.append(cells)
    if not out:
        raise TableUnreadable("routing table found but it has no data rows")
    return out


def routed_clis(text: str) -> set[str]:
    """CLI names appearing in the `Use` column. The `Not` column does not count --
    a tool named only as an anti-pattern is not routed TO."""
    names: set[str] = set()
    for cells in table_rows(text):
        if len(cells) < 2:
            continue
        for tok in re.findall(r"x4[a-z]+", cells[1]):
            names.add(tok)
    return names


def roster() -> list[str]:
    return _surface.cli_roster()


def missing(clis, text: str) -> list[str]:
    routed = routed_clis(text)
    return sorted(c for c in clis if c not in routed)


#: `<repo>/tools/x4validate/gates/this.py` -> `<repo>`. From __file__, never $X4_TOOLKIT.
REPO_ROOT = Path(__file__).resolve().parents[3]


def claude_md_paths() -> list[tuple[str, Path]]:
    """(label, path) for every CLAUDE.md that resolves: the SHIPPED copy at the repo
    root (present in every clone, and what install.sh copies into every user's game
    root) plus the configured game root's copy if any.

    The first version read ONLY the game-root file, so the gate was green solely
    because the author's personal copy had been hand-edited while the shipped file
    stayed 5-unrouted. Found by review; the shipped copy is now always in the
    population.
    """
    out: list[tuple[str, Path]] = []
    shipped = REPO_ROOT / "CLAUDE.md"
    if shipped.is_file():
        out.append(("shipped (repo root)", shipped))
    root = _paths.game_root()
    if root is not None:
        gm = Path(root) / "CLAUDE.md"
        if gm.is_file() and gm.resolve() != shipped.resolve():
            out.append(("game root", gm))
    return out


def _read(p: Path) -> str:
    """Bytes then decode. `read_text()` applies UNIVERSAL NEWLINES, which deletes
    one character per line -- harmless for a regex, fatal for a size check, and
    the habit is what matters."""
    return p.read_bytes().decode("utf-8")


def main() -> int:
    try:
        clis = roster()
    except _surface.SurfaceUnavailable as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    paths = claude_md_paths()
    if not paths:
        print("REFUSING: no CLAUDE.md resolved -- expected one at the repo root and/or "
              "via the configured game root ($X4_GAME)", file=sys.stderr)
        return 2
    print(f"ROUTING COVERAGE -- surface: {SURFACE}")
    per_file: dict[str, list[str]] = {}
    try:
        for label, path in paths:
            per_file[label] = missing(clis, _read(path))
            print(f"  {label:22s} routed {len(clis) - len(per_file[label])}/{len(clis)}   {path}")
    except (TableUnreadable, OSError, UnicodeDecodeError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    gaps = sorted({c for g in per_file.values() for c in g})

    # Subcommand coverage is INFO, never gating: uncalibrated, and a gate that
    # floods is worse than no gate ("sub-90% buys a MEASUREMENT, not a gate").
    total = refused = 0
    for c in clis:
        subs, note = _surface.subcommands(c)
        if subs is None:
            refused += 1
            print(f"  INFO  {c}: surface not enumerable -- {note}")
        else:
            total += len(subs)
    print(f"  INFO  {total} subcommand(s) enumerated across the roster; "
          f"{refused} CLI(s) refused. Subcommand routing is NOT gated.")

    if gaps:
        for label, g in per_file.items():
            if g:
                print(f"\nUNROUTED in {label} -- absent from the {SURFACE}'s Use column: "
                      f"{', '.join(g)}", file=sys.stderr)
        print("  A cold session must search for these instead of looking them up.",
              file=sys.stderr)
        return 1
    print(f"  all {len(clis)} routed in every file checked")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
