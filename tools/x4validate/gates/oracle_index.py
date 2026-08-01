"""INDEX ORACLE — measure x4validate's index layer against the engine's own verdict.

`gates/oracle.py` measures the DIFF layer: for each op the engine rejected, do we
reject it too? That is what made the merge model trustworthy (234/234, 0 FALSE OK).
The INDEX layer — "does this macro name resolve to a file the engine can load?" —
had never been measured at all. This is the same experiment one layer up.

Ground truth is debug.txt shape G:

    [=ERROR=] 0.00 Cannot find XML file component macro 'X' in index 'index\\macros'

Every name the engine prints there is a name it could NOT resolve. So for each one:

    agree       we also say it does not resolve
    FALSE OK    we resolve it — our index is more generous than the engine's
    (a false alarm is not observable from this direction: the log lists only
     failures, so a name we call missing and the engine never mentions may simply
     never have been referenced at runtime. Stated, not glossed.)

Two trees are compared, because that is the open L9 question:

    final       every installed extension (the runtime tree — the engine resolves
                index/macros.xml after all extensions have loaded)
    patch-time  truncated at the referencing mod's own load-order position, which is
                what `_check.tier_b_overlays` builds today

If the two disagree and `final` is the one that matches the engine, L9 is confirmed
and the trees must be split. If they agree, L9 is refuted and gets withdrawn.
"""
from collections import Counter, defaultdict
from pathlib import Path

import _env
from lxml import etree

from x4validate import _check, _compat, _debuglog, _merge, _registry, _resolve, _scan

EXT = _env.extensions()
LOG = _env.oracle_log()


def verdict(cfg, name):
    """Our answer to the engine's question, in the engine's own two steps.

    The engine's message is 'cannot find the FILE for macro X in index/macros' — so
    a name can fail two distinct ways, and collapsing them would hide which half is
    broken: unregistered (no index entry at all) vs registered-but-unloadable (entry
    points at a file that is not there, loose or packed).
    """
    index = _resolve.build_index(cfg, [], _resolve.MACRO_INDEX)
    if name not in index:
        return "unregistered"
    return "ok" if _resolve.read_indexed(index, name) is not None else "dangling"


def main():
    entries = [e for e in _debuglog.parse_debug(LOG) if e.lookup]
    names = sorted({e.lookup for e in entries})
    hits = Counter(e.lookup for e in entries)
    print(f"index-miss lines in log: {len(entries)} across {len(names)} distinct name(s)")
    if not entries:
        raise SystemExit("no shape-G entries parsed — the oracle has no ground truth")

    mods = _registry.scan_installed()
    order = _compat.compute_load_order(mods)
    by_folder = {m["folder"]: m for m in mods}
    all_dirs = tuple(Path(by_folder[n]["path"]) for n in order
                     if n in by_folder and Path(by_folder[n]["path"]).is_dir())
    print(f"installed extensions: {len(all_dirs)} (load-ordered)\n")

    final_cfg = _merge.Config(overlays=all_dirs)

    # --- attribution: who REFERENCES each missing name? -----------------------
    # The engine never says. Without this the L9 arm has no mod to truncate at, and
    # a FALSE OK has no owner to report. It is a search over every installed mod's
    # XML, loose and packed, so it is the slow part of this gate.
    #
    # `iter_mod_xml` yields (vpath, PARSED ROOT) — not bytes. The first cut of this
    # gate treated it as bytes and wrapped the mismatch in a bare `except: continue`,
    # so all 101 mods silently produced zero references and every row read '?'. It
    # looked like a clean result. That is precisely the class this whole effort
    # exists to kill, reproduced inside its own gate — hence: no blanket except, and
    # unreadable files go to a channel that gets printed.
    refs = defaultdict(set)
    unreadable: list[_scan.Unreadable] = []
    scanned = 0
    for d in all_dirs:
        for vpath, root in _scan.iter_mod_xml(d, unreadable=unreadable):
            scanned += 1
            text = etree.tostring(root, encoding="unicode")
            for n in names:
                if n in text:
                    refs[n].add(d.name)
    print(f"attribution scan: {scanned} XML documents across {len(all_dirs)} mods, "
          f"{len(unreadable)} unreadable")
    if not any(refs.values()):
        raise SystemExit(
            "attribution found no reference to ANY missing name across "
            f"{scanned} documents — that is not credible; the scan is broken")

    # --- the measurement -------------------------------------------------------
    tot = Counter()
    rows = []
    for name in names:
        owners = sorted(refs.get(name, ()))
        v_final = verdict(final_cfg, name)

        # patch-time tree: truncate at the FIRST mod that references it (the earliest
        # point the engine would need it). No owner -> not applicable.
        v_patch = "-"
        if owners:
            first = EXT / owners[0]
            if first.is_dir():
                ov, _ = _check.tier_b_overlays(first)
                v_patch = verdict(_merge.Config(overlays=tuple(ov)), name)

        false_ok = v_final == "ok"
        tot["names"] += 1
        tot["false_ok"] += bool(false_ok)
        tot["agree"] += (not false_ok)
        if v_patch != "-" and v_patch != v_final:
            tot["tree_disagree"] += 1
        rows.append((name, hits[name], v_final, v_patch, ",".join(owners) or "?"))

    print(f"{'macro':<44}{'log':>4}  {'final':<13}{'patch-time':<13}referenced by")
    print("-" * 108)
    for name, n, vf, vp, own in rows:
        flag = "  <== FALSE OK" if vf == "ok" else ""
        print(f"{name:<44}{n:>4}  {vf:<13}{vp:<13}{own[:36]}{flag}")

    print("-" * 108)
    print(f"\nnames: {tot['names']}   agree: {tot['agree']}   FALSE OK: {tot['false_ok']}")
    print(f"final vs patch-time tree disagreements: {tot['tree_disagree']}")
    if not tot["tree_disagree"]:
        print("  -> L9 makes no difference to any engine-confirmed name in this log.")
    print("\nNote: this log lists only FAILURES, so 'false alarm' (we say missing, the "
          "engine is happy) is not observable from here — it needs a second source.")


if __name__ == "__main__":
    main()
