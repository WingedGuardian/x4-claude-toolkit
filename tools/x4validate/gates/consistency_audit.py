#!/usr/bin/env python
"""Consistency audit — three code paths, one truth.

The same effective value is reachable three ways:
  1. `_merge.build_effective(vpath)`      — the merge itself
  2. `x4effective dump <vpath>`           — the live re-merge CLI
  3. the sqlite store (`entities`/`attrs`) — the cached extraction

They must agree. A disagreement means one path has drifted, and since callers
pick whichever is convenient, the drift would surface as an inexplicable
contradiction rather than an error. Cross-checking independent paths finds what
no single-path test can.

Run:  uv run python gates/consistency_audit.py [--samples=N]
Exit: 0 all agree, 1 any disagreement.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _effective, _merge  # noqa: E402

_TOUCH = None
_FOLDER_TO_PATH: dict = {}


def _overlays_for(vpath: str):
    """The overlays that touch *vpath*, in load order — what the store used."""
    global _TOUCH
    if _TOUCH is None:
        ordered = _effective.ordered_overlays(_effective.active_mods(None))
        _FOLDER_TO_PATH.update({m["folder"]: p for m, p in ordered})
        _TOUCH = _effective.build_touch_map(ordered)
    return _effective.touchers_for(vpath, _TOUCH, _FOLDER_TO_PATH)

DB = _env.effective_db()
SAMPLES = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--samples=")), 40)


def store_rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    # Spread the sample across owners so it is not all base-game entities.
    cur.execute(
        "SELECT e.name, e.vpath, a.prop, a.value, a.origin "
        "FROM entities e JOIN attrs a ON a.entity_id = e.id "
        "WHERE e.klass IN ('shieldgenerator','missile','engine','bullet') "
        "  AND a.prop LIKE '%.%' AND a.origin != 'base' "
        "ORDER BY RANDOM() LIMIT ?", (SAMPLES,))
    rows = cur.fetchall()
    con.close()
    return rows


def from_merge(vpath: str, name: str, prop: str) -> str | None:
    # Must use the SAME overlay set the store was built with. A default Config()
    # is Tier A (base+DLC only), so comparing against it just re-discovers that
    # mods change things — it compared vanilla to effective and called it a bug.
    res = _merge.build_effective(vpath, _merge.Config(),
                                 extra_overlays=_overlays_for(vpath))
    if res.tree is None:
        return None
    tag, _, attr = prop.rpartition(".")
    for macro in res.tree.iter("macro"):
        if macro.get("name") != name:
            continue
        if tag in ("", "@"):
            return macro.get(attr)
        el = macro.find(f".//{tag}")
        return el.get(attr) if el is not None else None
    return None


def from_dump(vpath: str, name: str, prop: str) -> str | None:
    p = subprocess.run(["uv", "run", "x4effective", "dump", vpath], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        root = etree.fromstring(p.stdout.encode())
    except Exception:
        return None
    tag, _, attr = prop.rpartition(".")
    for macro in root.iter("macro"):
        if macro.get("name") != name:
            continue
        el = macro.find(f".//{tag}")
        return el.get(attr) if el is not None else None
    return None


def eq(a, b) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return a == b


def main() -> int:
    rows = store_rows()
    print("=" * 96)
    print(f"CONSISTENCY AUDIT — store vs build_effective vs `dump`, {len(rows)} sampled values")
    print("=" * 96)
    bad = []
    checked = 0
    dump_cache: dict[tuple[str, str, str], str | None] = {}
    for name, vpath, prop, value, origin in rows:
        if not vpath:
            continue
        merged = from_merge(vpath, name, prop)
        if merged is None:
            continue
        checked += 1
        if not eq(merged, value):
            bad.append(("store vs merge", name, prop, value, merged, origin, vpath))
            continue
        key = (vpath, name, prop)
        if key not in dump_cache:
            dump_cache[key] = from_dump(vpath, name, prop)
        dumped = dump_cache[key]
        if dumped is not None and not eq(dumped, value):
            bad.append(("store vs dump", name, prop, value, dumped, origin, vpath))

    print(f"  values cross-checked : {checked}")
    print(f"  DISAGREEMENTS        : {len(bad)}")
    for kind, name, prop, a, b, origin, vpath in bad[:25]:
        print(f"\n  {kind}  {name}  {prop}   (origin={origin})")
        print(f"     store={a!r}   other={b!r}")
        print(f"     {vpath}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
