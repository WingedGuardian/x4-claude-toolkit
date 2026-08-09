#!/usr/bin/env python
"""Corpus-wide hunt for the false-OK class: ops reported applied that change nothing.

Generalises the defect found 2026-08-08 (a `<replace>` on the document root was
discarded by a bare `continue` while apply_diff reported applied=True). Instead
of trusting that one instance was the only one, apply EVERY op of EVERY installed
mod against its real base document and compare what the tool SAYS against what
the tree DOES.

Two directions, both real defects:
  * FALSE OK    — ok=True but the tree is byte-identical after the op
  * FALSE ALARM — ok=False but the tree changed anyway

An attribute <replace> that sets a value it already had is genuinely idempotent,
so those are excluded; only STRUCTURAL ops (element payloads, removes) are held
to "must change something".

Run:  uv run python gates/noop_audit.py [--limit=N] [--verbose]
Exit: 0 clean, 1 any false OK / false alarm.
"""
from __future__ import annotations

import copy
import glob
import os
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _cat, _merge  # noqa: E402

REF = _env.reference()
EXT = _env.extensions()
VERBOSE = "--verbose" in sys.argv
LIMIT = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)


def vanilla_index() -> dict[str, str]:
    out = {}
    for p in glob.iglob(str(REF / "**" / "*.xml"), recursive=True):
        out[os.path.relpath(p, REF).replace("\\", "/").lower()] = p
    return out


def mod_docs(mod: Path):
    """(vpath, bytes) for every XML the mod ships, packed or loose."""
    try:
        for vp, mem in _cat.mod_vfs(mod).items():
            try:
                yield vp, _cat.read_member(mem, verify=False)
            except Exception as exc:                    # a reader failure is itself a finding
                print(f"  ! unreadable {mod.name}/{vp}: {exc!r}")
    except Exception:
        pass
    for p in glob.iglob(str(mod / "**" / "*.xml"), recursive=True):
        try:
            yield os.path.relpath(p, mod).replace("\\", "/"), open(p, "rb").read()
        except Exception as exc:
            print(f"  ! unreadable {mod.name}/{p}: {exc!r}")


def cross_mod_base(vpath: str, mods_by_name: dict) -> etree._Element | None:
    """Resolve `extensions/<owner>/<rel>` against the OWNER mod's own copy.

    A cross-mod patch targets a file another mod ships, so there is no vanilla
    document to apply it to — but there IS a real base, and without it a third
    of the corpus's cross-mod ops go unaudited.
    """
    parts = vpath.split("/")
    if len(parts) < 3 or parts[0].lower() != "extensions":
        return None
    owner = mods_by_name.get(parts[1].lower())
    if owner is None:
        return None
    rel = "/".join(parts[2:])
    data = None
    loose = owner / rel
    if loose.is_file():
        try:
            data = loose.read_bytes()
        except OSError:
            return None
    else:
        try:
            data = _cat.read_path(owner, rel, verify=False)
        except Exception:
            return None
    if not data:
        return None
    try:
        root = etree.fromstring(data)
    except Exception:
        return None
    # The owner's own file must be a real document, not itself a diff.
    return root if root.tag != "diff" else None


def is_structural(op: etree._Element) -> bool:
    """Ops that MUST alter the tree when applied."""
    kids = [c for c in op if isinstance(c.tag, str)]
    if op.tag == "remove":
        return True
    if op.tag in ("replace", "add"):
        return bool(kids)
    return False


def main() -> int:
    van = vanilla_index()
    false_ok, false_alarm, unparseable = [], [], []
    stats = Counter()
    mods = [d for d in sorted(EXT.iterdir()) if d.is_dir()]
    mods_by_name = {d.name.lower(): d for d in mods}
    if LIMIT:
        mods = mods[:LIMIT]

    for mod in mods:
        for vp, data in mod_docs(mod):
            if b"<diff" not in data:
                continue
            try:
                droot = etree.fromstring(data)
            except Exception as exc:
                stats["unparseable diff"] += 1
                unparseable.append((mod.name, vp, str(exc).split("\n")[0]))
                continue
            if droot.tag != "diff":
                continue
            key = vp.lower()
            base_path = van.get(key)
            base = None
            if base_path is None and key.startswith("extensions/"):
                parts = vp.split("/")
                if len(parts) > 2 and not parts[1].lower().startswith("ego_dlc_"):
                    base_path = van.get("/".join(parts[2:]).lower())
            if base_path is None:
                # CROSS-MOD: the target is another MOD's file, not a vanilla one.
                # Skipping these left 433 ops unaudited — a third of the corpus's
                # cross-mod surface, and exactly where a patch is most fragile.
                base = cross_mod_base(vp, mods_by_name)
                if base is None:
                    stats["no base doc anywhere"] += 1
                    continue
                stats["cross-mod base resolved"] += 1
            if base is None:
                try:
                    base = etree.parse(base_path).getroot()
                except Exception:
                    stats["unparseable base"] += 1
                    continue

            for op in droot:
                if not isinstance(op.tag, str) or op.tag not in ("add", "replace", "remove"):
                    continue
                tree = copy.deepcopy(base)
                before = etree.tostring(tree)
                try:
                    applied = _merge.apply_diff(tree, _wrap(op))
                except Exception as exc:
                    false_ok.append((mod.name, vp, op.get("sel"), f"CRASH {exc!r}"))
                    continue
                if not applied:
                    continue
                rec = applied[0]
                changed = etree.tostring(tree) != before
                stats["ops checked"] += 1
                if getattr(rec, "skipped_if", False):
                    stats["if= guard skipped (by design)"] += 1
                elif rec.ok and not changed and is_structural(op):
                    false_ok.append((mod.name, vp, op.get("sel"), rec.detail))
                elif not rec.ok and changed:
                    false_alarm.append((mod.name, vp, op.get("sel"), rec.detail))

    print("=" * 92)
    print("NO-OP AUDIT — does what the tool REPORTS match what the tree DOES?")
    print("=" * 92)
    for k, v in stats.most_common():
        print(f"  {k:<28}{v}")
    print(f"\n  FALSE OK    (said applied, changed nothing): {len(false_ok)}")
    print(f"  FALSE ALARM (said not applied, changed it):  {len(false_alarm)}")

    for label, rows in (("FALSE OK", false_ok), ("FALSE ALARM", false_alarm)):
        for mod, vp, sel, detail in rows[:40]:
            print(f"\n  {label}  {mod}")
            print(f"     {vp}")
            print(f"     sel={sel!r}  detail={detail!r}")
        if len(rows) > 40:
            print(f"  ... and {len(rows) - 40} more")

    if unparseable:
        print(f"\n  UNPARSEABLE mod XML ({len(unparseable)}) — upstream defects:")
        for mod, vp, why in unparseable:
            print(f"     {mod:<28} {vp}")
            print(f"        {why}")

    return 1 if (false_ok or false_alarm) else 0


def _wrap(op: etree._Element) -> etree._Element:
    d = etree.Element("diff")
    d.append(copy.deepcopy(op))
    return d


if __name__ == "__main__":
    raise SystemExit(main())
