#!/usr/bin/env python
"""Reverse oracle — the direction the other two structurally cannot test.

`oracle.py` and `oracle_index.py` replay operations the engine REJECTED and
require us to reject them too. That proves "we never say fine where the engine
said broken" — but a failure-only log can never prove completeness, and both
gates say so in their own output.

This gate asks the other question: **the engine complained about something; do
WE notice it at all?** A miss here is a false OK of the worst kind, because the
user is told their mod is clean while the game is logging errors about it.

Two checkable classes from a real captured log:

  A. `GetText(pageid=P, textid=T) TextID not found!`
     -> the effective `t/` tree must NOT contain that id. If we resolve it, our
        `{page,t}` reference check would tell a user the reference is fine.

  B. `Cannot find referenced part template '<X>' in file 'index\\components'`
     -> `<X>` must NOT be resolvable in the effective component index.

Both are answered from the merged tree, so this needs no game launch — only a
captured log ($X4_ORACLE_LOG, or the live profile log passed explicitly).

Run:  uv run python gates/oracle_reverse.py [path/to/debug.txt]
Exit: 0 we agree with the engine, 1 any disagreement, 2 no log.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _effective, _merge  # noqa: E402

RE_TEXT = re.compile(r"GetText\(pageid=(\d+),\s*textid=(\d+)\)\s*TextID not found")
RE_PART = re.compile(r"Cannot find referenced part template XML file from index '([^']+)'")

_TOUCH = None
_F2P: dict = {}


def overlays_for(vpath: str):
    global _TOUCH
    if _TOUCH is None:
        ordered = _effective.ordered_overlays(_effective.active_mods(None))
        _F2P.update({m["folder"]: p for m, p in ordered})
        _TOUCH = _effective.build_touch_map(ordered)
    return _effective.touchers_for(vpath, _TOUCH, _F2P)


def effective(vpath: str):
    res = _merge.build_effective(vpath, _merge.Config(), extra_overlays=overlays_for(vpath))
    return res.tree


def log_path() -> Path:
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        p = Path(sys.argv[1])
        if p.is_file():
            return p
    try:
        return _env.oracle_log()
    except SystemExit:
        raise


def main() -> int:
    log = log_path()
    text = log.read_text(encoding="utf-8", errors="replace")
    print(f"REVERSE ORACLE — {log.name} ({len(text)//1024} KB)")
    print("=" * 88)

    # ---- A. text ids the engine could not find -------------------------
    missing_ids = {(int(p), int(t)) for p, t in RE_TEXT.findall(text)}
    print(f"\nA. TextIDs the engine reported MISSING: {len(missing_ids)} distinct")
    pages_wanted = {p for p, _ in missing_ids}

    # Build the effective English text tree once. t/ is union-merged, so every
    # mod's page/id entries are already folded in.
    found_ids: set[tuple[int, int]] = set()
    scanned = 0
    for vpath in ("t/0001-l044.xml", "t/0001.xml"):
        tree = effective(vpath)
        if tree is None:
            continue
        scanned += 1
        for page in tree.iter("page"):
            try:
                pid = int(page.get("id") or -1)
            except ValueError:
                continue  # silent-ok: a non-numeric page id cannot match an engine complaint
            if pid not in pages_wanted:
                continue
            for t_el in page.iter("t"):
                try:
                    found_ids.add((pid, int(t_el.get("id") or -1)))
                except ValueError:
                    pass  # silent-ok: a non-numeric text id cannot match an engine complaint
    disagree_a = sorted(missing_ids & found_ids)
    print(f"   effective t/ files scanned : {scanned}")
    print(f"   of those, ids WE resolve   : {len(disagree_a)}")
    for pid, tid in disagree_a[:15]:
        print(f"     DISAGREE  page {pid} text {tid}: engine says missing, we resolve it")

    # ---- B. component templates the engine could not find ---------------
    parts = Counter(RE_PART.findall(text))
    print(f"\nB. component templates the engine could NOT find: {len(parts)} distinct")
    idx = effective("index/components.xml")
    known = set()
    if idx is not None:
        for e in idx.iter("entry"):
            n = e.get("name")
            if n:
                known.add(n)
    disagree_b = sorted(p for p in parts if p in known)
    print(f"   entries in effective index/components : {len(known)}")
    print(f"   of the engine's misses, WE resolve    : {len(disagree_b)}")
    for p in disagree_b[:15]:
        print(f"     DISAGREE  '{p}' x{parts[p]}: engine cannot find it, our index has it")

    total = len(disagree_a) + len(disagree_b)
    print("\n" + "=" * 88)
    print(f"DISAGREEMENTS WITH THE ENGINE: {total}")
    if not total:
        print("  We agree with the engine on every checkable complaint in this log.")
    print("\nScope note: this covers the two error classes a merged tree can answer.")
    print("Classes needing runtime state (MD cue failures, ShipGenerator, construction")
    print("sequences) are NOT checkable statically and are out of scope by construction.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
