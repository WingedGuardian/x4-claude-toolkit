r"""Corpus audit: content the game DEFINES but cannot SELL, against a baseline.

WHY A GATE AND NOT JUST THE PER-MOD CHECK.
==========================================
`check_references` reports a mod that references a macro no live ware supplies. That
is REACTIVE: it fires only when someone validates a mod that names one. Nothing
audits the corpus, so the base game's own gaps are invisible until a person goes
looking -- which is exactly how the first 12 were found on 2026-08-28: by a throwaway
script, because the user asked whether we could be sure the toolkit would tell us.

The counts below are facts about THIS game version plus THIS modlist. Knowing them
once is nearly worthless. What matters is when they MOVE -- a game patch deprecating
more content, or a mod introducing references to it. So this records a baseline and
fails on drift, the same shape as `perf_guard.py`.

WHY THE BASELINE IS LOCAL.
==========================
It depends on the installed DLC and modlist, so a committed baseline would be wrong
for every other machine and would fail their first run -- perf_guard's reasoning,
applied to corpus data rather than wall-clock. `--record` writes a gitignored file.

WHAT IT DELIBERATELY DOES NOT COUNT.
====================================
Macros with NO ware at all. MEASURED over the effective tree: that is **3,945 of
5,559 indexed macros (71%)** and it is the NORMAL state -- bullet 170 of 170,
scenery/story 89.5%, storage 80.6%. Counting it would drown the signal. Doing that
half honestly needs a per-class expectation model.

  uv run python gates/obtainability_audit.py [--record]

Exit: 0 unchanged (or recorded) · 1 drift · 2 cannot run (never a guess)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import _env

from lxml import etree

from x4validate import _effective, _merge, _refs, _registry, _scan

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".obtainability-baseline.json"
RECORD = "--record" in sys.argv


def audit() -> dict:
    cfg = _merge.Config()

    vanilla = _merge.build_effective("libraries/wares.xml", cfg, extra_overlays=[]).tree
    if vanilla is None:
        _env.skip("vanilla libraries/wares.xml", "merged to nothing")
    dead = _refs.deprecated_only_macros(vanilla)

    overlays = [p for _m, p in _effective.ordered_overlays(_effective.active_mods())]
    eff = _merge.build_effective("libraries/wares.xml", cfg, extra_overlays=overlays).tree
    dead_eff = _refs.deprecated_only_macros(eff) if eff is not None else {}

    sold = {r for w in vanilla.xpath("//ware") for r in w.xpath("component/@ref")}

    # EVERY base+DLC macro file, loose THEN packed. NOT `reference.rglob`: six of the
    # eight DLC are unpacked under reference\, and the two mini-DLC live only in
    # ext_*.cat -- a plain rglob cannot see them, and that walk has been hand-rolled
    # wrong seven times (F34/F35; it once cost BaseX 119 of 142 mini-DLC documents
    # while its coverage check reported COMPLETE). Scoped to *_macro.xml because
    # <ammunition ref=> only ever appears there.
    tainted, tainted_sold, unreadable = [], [], []
    vpaths = _effective.base_vpaths(cfg, "*_macro.xml")
    for low in sorted(vpaths):
        res = _merge.build_effective(vpaths[low], cfg, extra_overlays=[])
        root = res.tree
        if root is None:
            # NOT a silent continue: a file we could not read is "did not check",
            # and the count below states it so a shrinking denominator is visible.
            unreadable.append(low)
            continue
        own = set(root.xpath("//macro/@name"))
        if not own or own & set(dead):
            continue
        if {h.ref for h in _refs.unobtainable_refs(root, dead)} - own:
            for name in sorted(own):
                tainted.append(name)
                if name in sold:
                    tainted_sold.append(name)

    per_mod = {}
    for m in _registry.mods("installed"):
        n = sum(len(_refs.unobtainable_refs(root, dead))
                for _v, root in _scan.iter_mod_xml(Path(m["path"]), lambda v: True, []))
        if n:
            per_mod[m["folder"]] = n

    return {
        "deprecated_only_macros_vanilla": len(dead),
        "deprecated_only_macros_effective": len(dead_eff),
        "live_macros_with_deprecated_ammo": len(tainted),
        "of_those_sold_by_a_live_ware": len(tainted_sold),
        "base_macro_files_scanned": len(vpaths),
        "base_macro_files_unreadable": len(unreadable),
        "mods_referencing_deprecated": per_mod,
    }


def main() -> int:
    now = audit()
    if RECORD:
        BASELINE.write_text(json.dumps(now, indent=2, sort_keys=True), encoding="utf-8")
        print(f"recorded baseline -> {BASELINE.name}")
        for k, v in now.items():
            print(f"  {k:<38} {v if not isinstance(v, dict) else len(v)}")
        return 0

    if not BASELINE.is_file():
        print(f"no baseline at {BASELINE.name} — run with --record first. "
              "Refusing to report 'unchanged' against nothing.", file=sys.stderr)
        return 2

    was = json.loads(BASELINE.read_text(encoding="utf-8"))
    drift = []
    for key in ("deprecated_only_macros_vanilla", "deprecated_only_macros_effective",
                "live_macros_with_deprecated_ammo", "of_those_sold_by_a_live_ware"):
        if was.get(key) != now[key]:
            drift.append(f"{key}: {was.get(key)} -> {now[key]}")

    # PER ITEM, never the total: a mod losing 3 references while another gains 3 is
    # a net zero that hides both (CLAUDE.md 1b).
    old_m, new_m = was.get("mods_referencing_deprecated", {}), now["mods_referencing_deprecated"]
    for folder in sorted(set(old_m) | set(new_m)):
        if old_m.get(folder) != new_m.get(folder):
            drift.append(f"mod {folder}: {old_m.get(folder, 0)} -> {new_m.get(folder, 0)} reference(s)")

    print("OBTAINABILITY AUDIT — vanilla + installed modlist, against the local baseline")
    for k in ("deprecated_only_macros_vanilla", "deprecated_only_macros_effective",
              "live_macros_with_deprecated_ammo", "of_those_sold_by_a_live_ware"):
        print(f"  {k:<38} {now[k]}")
    print(f"  {'mods referencing deprecated content':<38} {len(new_m)}")
    if not drift:
        print("\nunchanged since the baseline.")
        return 0
    print(f"\nDRIFT ({len(drift)}):")
    for d in drift:
        print(f"  {d}")
    print("\nA game patch or a modlist change moved these. Review, then re-record.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
