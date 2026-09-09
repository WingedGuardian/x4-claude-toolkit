"""Load order: which mod folder the engine reads first.

WHY THIS MODULE EXISTS, AND IT IS NOT TIDINESS. `compute_load_order` decides which
mod wins every collision -- CLAUDE.md gotcha #13 measures the same macro reading 0
alphabetically and 200 in true load order -- so editing it changes the merged answer
for byte-identical inputs. That is exactly what `_freshness`'s ENGINE axis exists to
detect, and it could not: the function lived in `_compat.py`, which also carries the
`x4compat` CLI, and `tests/test_engine_sources_carry_no_cli.py` (F69) measured the
cost of naming a CLI module there -- a CLI-text change and a DOCSTRING change each
invalidated the effective store and BaseX `x4eff` for rebuilds that could not change
one row. A hash that cries wolf trains you to ignore the banner.

F69's own remedy, quoted at the constant it guards: *"make the POPULATION right, not
the hash clever -- lift `compute_load_order` into a CLI-free module and name THAT."*
This is that module. It imports `pathlib` and `lxml.etree` and nothing else, so it
carries no argparse, no entry point and no `print`, and satisfies all four of F69's
checks by construction rather than by exemption.

`_compat` re-exports both names, so every existing caller and
`gates/mutation_probe.py`'s source-string mutant are unaffected.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree


def mod_deps(mod_path: Path, dropped: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (mod_id, [dependency_ids]) from a mod's content.xml.

    A manifest that will not parse yields ZERO dependencies, and dependencies are
    what force a mod to load EARLIER -- so silently swallowing the failure changes
    the computed load order, which decides every collision winner. Report it through
    *dropped* (same convention as `_registry.scan_installed`, which already handles
    this case correctly). MEASURED 2026-08-12: 0 of 122 installed manifests are
    malformed, so this is a latent defect -- the cost is zero today and unbounded
    the day it isn't.
    """
    cx = mod_path / "content.xml"
    if not cx.is_file():
        if dropped is not None:
            dropped.append(f"{mod_path.name}: no content.xml -- assuming no dependencies")
        return mod_path.name, []
    try:
        root = etree.parse(str(cx)).getroot()
    except etree.XMLSyntaxError as exc:
        if dropped is not None:
            dropped.append(f"{mod_path.name}: content.xml will not parse ({exc}) -- "
                           "load-order position assumed alphabetical")
        return mod_path.name, []
    mod_id = root.get("id") or mod_path.name
    deps = [d.get("id") for d in root.findall(".//dependency") if d.get("id")]
    return mod_id, deps


def compute_load_order(mods: list[dict], dropped: list[str] | None = None) -> list[str]:
    """Order mod FOLDERS as X4 loads them: alphabetical, dependencies forced earlier.

    Kahn topological sort with an alphabetical tiebreak on the ready set, so the
    result is deterministic and matches "alphabetical unless a dependency requires
    otherwise". *mods* are entries from `_registry.scan_installed()`.

    Pass *dropped* to receive manifests whose dependencies could not be read --
    those mods fall back to alphabetical placement, which can silently change who
    wins a collision. See `mod_deps`.
    """
    folders = [m["folder"] for m in mods]
    # A REPEATED FOLDER COLLAPSES SILENTLY, AND IT TAKES THE MOD WITH IT.
    # `incoming` below is keyed by folder, so two entries with the same folder
    # become ONE node: the mod disappears from the load order, from the effective
    # tree built over it, and from every provenance answer -- nothing raised,
    # nothing recorded. Reachable by the profile-vs-game-root mistake CLAUDE.md
    # warns about, where one folder exists under two configured roots.
    #
    # MEASURED 2026-09-08 on this install: 3 configured roots, 133 folders, ZERO
    # names in more than one root, ZERO duplicates in the computed order, ZERO mods
    # lost. Verified reachable anyway: three mods, two sharing a folder, produce an
    # order of length TWO. So this RECORDS rather than restructures -- it costs
    # nothing today, and changing behaviour during close-out is how earlier rounds
    # introduced defects. What it must never do again is happen with no channel.
    _seen_folder: set[str] = set()
    id_to_folder: dict[str, str] = {}
    deps_by_folder: dict[str, list[str]] = {}
    for m in mods:
        if m["folder"] in _seen_folder and dropped is not None:
            dropped.append(
                "%s: folder appears more than once in the mod set, so one entry "
                "collapses onto the other and vanishes from the load order, the "
                "effective tree and every provenance answer" % m["folder"])
        _seen_folder.add(m["folder"])
        mod_id, deps = mod_deps(Path(m["path"]), dropped)
        # `mod_id` truthy FIRST: `mod_deps` returns "" for a mod with no
        # content.xml, and an ABSENT id is not a claimed one. Without this the
        # record fires for every second manifest-less mod -- caught by the twin,
        # which recorded a clash between two folders that share nothing.
        _clash = (mod_id
                  and mod_id in id_to_folder
                  and id_to_folder[mod_id] != m["folder"])
        if _clash and dropped is not None:
            dropped.append(
                "manifest id %r is claimed by both %r and %r; the later one wins "
                "the id, so a dependency naming it resolves to only one of them"
                % (mod_id, id_to_folder[mod_id], m["folder"]))
        id_to_folder[mod_id] = m["folder"]
        deps_by_folder[m["folder"]] = deps

    # Edges: dep_folder -> folder (dependency loads first). Ignore uninstalled deps.
    incoming: dict[str, set[str]] = {f: set() for f in folders}
    for folder, dep_ids in deps_by_folder.items():
        for dep_id in dep_ids:
            dep_folder = id_to_folder.get(dep_id)
            if dep_folder and dep_folder != folder:
                incoming[folder].add(dep_folder)

    ordered: list[str] = []
    resolved: set[str] = set()
    remaining = set(folders)
    while remaining:
        ready = sorted(f for f in remaining if incoming[f] <= resolved)
        if not ready:  # dependency cycle -- fall back to alphabetical for the rest
            # RECORDED: the fallback silently changes who wins a collision. The
            # docstring already says so; nothing said it at the moment it happened.
            if dropped is not None:
                dropped.append(
                    "dependency cycle among %d mod(s) (%s); their load order falls "
                    "back to ALPHABETICAL, which can change which mod wins a "
                    "collision" % (len(remaining), ", ".join(sorted(remaining)[:5])))
            ready = sorted(remaining)
        nxt = ready[0]
        ordered.append(nxt)
        resolved.add(nxt)
        remaining.discard(nxt)
    return ordered
