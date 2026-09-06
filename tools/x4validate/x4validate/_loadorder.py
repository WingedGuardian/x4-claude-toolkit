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
    id_to_folder: dict[str, str] = {}
    deps_by_folder: dict[str, list[str]] = {}
    for m in mods:
        mod_id, deps = mod_deps(Path(m["path"]), dropped)
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
            ready = sorted(remaining)
        nxt = ready[0]
        ordered.append(nxt)
        resolved.add(nxt)
        remaining.discard(nxt)
    return ordered
