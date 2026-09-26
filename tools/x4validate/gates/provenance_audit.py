#!/usr/bin/env python
"""Provenance audit — does every CHANGED value name the mod that changed it?

The subtle half of the 2026-08-08 merge defect: a value can become correct while
`origin` still says `base`. Numbers then look right and the "who set this?" answer
is wrong, which is worse than an obvious break because nothing looks suspicious.

Signature hunted: the effective value differs from the vanilla file's value, yet
the store attributes it to `base`. That combination is always a provenance bug.

Run:  uv run python gates/provenance_audit.py
Exit: 0 clean, 1 any mis-attribution, 2 could not judge (no store, a STALE store, or
nothing comparable).

SCOPE: it catches a changed value still attributed to `base`. It does NOT catch a changed
value attributed to the WRONG mod -- that needs a per-mod oracle this gate does not have.
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

DB = _env.effective_db()
REF = _env.reference()

#: prop -> (element tag, attribute) for props cheap to re-read from the vanilla file
PROPS = {
    "recharge.max": ("recharge", "max"),
    "recharge.rate": ("recharge", "rate"),
    "recharge.delay": ("recharge", "delay"),
    "hull.max": ("hull", "max"),
    "explosiondamage.value": ("explosiondamage", "value"),
    "missile.range": ("missile", "range"),
    "missile.lifetime": ("missile", "lifetime"),
    "reload.time": ("reload", "time"),
}


def main() -> int:
    if not DB.exists():
        # rc 2, not 1: a missing store is a gate that could not run, and run-gates.sh
        # reads 1 as "found a defect" (AUDIT-2026-09-24 GT-7).
        print(f"no store at {DB} — run `x4effective build` first", file=sys.stderr)
        return 2
    refused = _env.stale_store_refusal(DB, "provenance_audit")
    if refused is not None:
        return refused
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    cur.execute(
        "SELECT e.name, e.vpath, a.prop, a.value, a.origin "
        "FROM entities e JOIN attrs a ON a.entity_id = e.id "
        "WHERE a.prop IN (%s)" % ",".join("?" * len(PROPS)), list(PROPS))
    rows = cur.fetchall()
    con.close()

    stats = Counter()
    offenders = []
    cache: dict[str, dict[tuple[str, str], str]] = {}

    for name, vpath, prop, value, origin in rows:
        stats["checked"] += 1
        if not vpath:
            stats["no vpath"] += 1
            continue
        path = REF / vpath
        if not path.exists():                     # mod-added entity: nothing vanilla to compare
            stats["mod-added (no vanilla file)"] += 1
            continue
        if vpath not in cache:
            try:
                root = etree.parse(str(path)).getroot()
            except Exception:
                cache[vpath] = {}
                stats["vanilla unparseable"] += 1
            else:
                d = {}
                for macro in root.iter("macro"):
                    mname = macro.get("name") or ""
                    for tag, attr in set(PROPS.values()):
                        el = macro.find(f".//{tag}")
                        if el is not None and el.get(attr) is not None:
                            d[(mname, f"{tag}.{attr}")] = el.get(attr)
                cache[vpath] = d
        vanilla = cache[vpath].get((name, prop))
        if vanilla is None:
            stats["prop absent in vanilla"] += 1
            continue
        same = _num_eq(vanilla, value)
        if same:
            stats["unchanged from vanilla"] += 1
            continue
        stats["changed by a mod"] += 1
        if origin == "base":
            offenders.append((name, prop, vanilla, value, vpath))

    print("=" * 92)
    print("PROVENANCE AUDIT — a changed value must name the mod that changed it")
    print("=" * 92)
    for k, v in stats.most_common():
        print(f"  {k:<32}{v}")
    compared = stats["changed by a mod"] + stats["unchanged from vanilla"]
    if not compared:
        # A FLOOR. Before 2026-09-24 an empty store, or one whose every row fell into
        # an uncompared bucket, printed "MIS-ATTRIBUTED: 0" and exited 0 (GT-3).
        return _env.nothing_checked("provenance_audit",
                                    "no stored value could be compared with vanilla")
    print(f"\n  MIS-ATTRIBUTED (value != vanilla, yet origin='base'): {len(offenders)}")
    for name, prop, van, eff, vpath in offenders[:30]:
        print(f"     {name}  {prop}: vanilla={van} effective={eff}")
        print(f"        {vpath}")
    if len(offenders) > 30:
        print(f"     ... and {len(offenders) - 30} more")
    return 1 if offenders else 0


def _num_eq(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


if __name__ == "__main__":
    raise SystemExit(main())
