r"""x4compat: detect how installed mods collide over the effective XML tree.

Unlike a naive file-overlap check (which flags every mod that touches, say,
``t/0001-l007.xml`` — 15 of them, all harmlessly union-merged), this resolves each
mod's intent against the real base+DLC effective tree and dispatches by the engine's
actual merge semantics:

- ``libraries/`` ``index/`` ``t/`` are additively UNIONED by ``@id``/``@name`` — two
  mods co-existing there is normal; only two mods defining the SAME key collide
  (UNION-KEY: later load-order wins).
- Everywhere else, a mod's ``<diff>`` ops resolve to concrete nodes; two mods
  resolving to the same node where at least one replaces/removes it is a HARD
  collision (later wins, the earlier effect is lost or compounded). Two mods only
  ``<add>``-ing under the same parent is SOFT (they coexist).
- Two non-diff full files at the same non-union path FULL-OVERRIDE (later clobbers).

Load order (who wins): X4 loads extensions alphabetically by folder, with a mod's
declared ``content.xml`` dependencies forced earlier. That order is community-reported
(not officially documented), so winners are stated with that caveat.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _cat, _merge, _registry, _xpath, _input

UNION_DIRS = ("libraries/", "index/", "t/")
_OPS = ("add", "replace", "remove")
# Files the engine loads once PER EXTENSION (never shared/overridden across mods),
# so multiple mods "shipping" one is normal, not a full-file-override collision.
_PER_EXTENSION_FILES = {"ui.xml"}


@dataclass
class Collision:
    vpath: str
    kind: str            # HARD | UNION-KEY | FULL-OVERRIDE | SOFT
    target: str          # node identity / registry key / file path
    mods: list[str]      # involved mod folders, in load order (winner last)
    winner: str
    detail: str = ""


@dataclass
class CompatReport:
    collisions: list[Collision] = field(default_factory=list)
    mods_scanned: int = 0
    files_examined: int = 0
    load_order: list[str] = field(default_factory=list)
    #: Ops whose sel= could not be EVALUATED (malformed XPath), so the mod
    #: contributed no targets and cannot participate in collision detection.
    #: For a conflict detector, silently contributing nothing is the worst
    #: failure mode there is: it renders as "these mods do not collide".
    unresolvable: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Collision]:
        return [c for c in self.collisions if c.kind == kind]

    @property
    def hard(self) -> list[Collision]:
        return self.by_kind("HARD") + self.by_kind("FULL-OVERRIDE")


# --- mod discovery + load order ----------------------------------------------

def _mod_deps(mod_path: Path) -> tuple[str, list[str]]:
    """Return (mod_id, [dependency_ids]) from a mod's content.xml."""
    cx = mod_path / "content.xml"
    if not cx.is_file():
        return mod_path.name, []
    try:
        root = etree.parse(str(cx)).getroot()
    except etree.XMLSyntaxError:
        return mod_path.name, []
    mod_id = root.get("id") or mod_path.name
    deps = [d.get("id") for d in root.findall(".//dependency") if d.get("id")]
    return mod_id, deps


def compute_load_order(mods: list[dict]) -> list[str]:
    """Order mod FOLDERS as X4 loads them: alphabetical, dependencies forced earlier.

    Kahn topological sort with an alphabetical tiebreak on the ready set, so the
    result is deterministic and matches "alphabetical unless a dependency requires
    otherwise". *mods* are entries from `_registry.scan_installed()`.
    """
    folders = [m["folder"] for m in mods]
    id_to_folder: dict[str, str] = {}
    deps_by_folder: dict[str, list[str]] = {}
    for m in mods:
        mod_id, deps = _mod_deps(Path(m["path"]))
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
        if not ready:  # dependency cycle — fall back to alphabetical for the rest
            ready = sorted(remaining)
        nxt = ready[0]
        ordered.append(nxt)
        resolved.add(nxt)
        remaining.discard(nxt)
    return ordered


def _mod_xml_paths(mod_path: Path) -> dict[str, str]:
    """Return ``{lowercased_vpath: real_vpath}`` for a mod's XML (packed + loose)."""
    out: dict[str, str] = {}
    for vpath in _cat.mod_vfs(mod_path):
        out[vpath.lower()] = vpath
    for f in mod_path.rglob("*.xml"):
        if f.is_file():
            vpath = f.relative_to(mod_path).as_posix()
            out[vpath.lower()] = vpath
    out.pop("content.xml", None)
    return out


# --- node-identity resolution -------------------------------------------------

def _canonical(node) -> str | None:
    """Stable identity of an xpath result within a fixed tree.

    Element -> its absolute getpath; attribute -> parent getpath + '/@name'.
    Two mods selecting the same node via different sel syntax resolve to the same
    element object in the shared tree, hence the same string.
    """
    if isinstance(node, etree._Element):
        return node.getroottree().getpath(node)
    # lxml attribute / text smart-string
    if getattr(node, "is_attribute", False):
        parent = node.getparent()
        if parent is not None:
            return parent.getroottree().getpath(parent) + "/@" + node.attrname
    return None


def _resolve_op_targets(tree: etree._Element, sel: str) -> list[str] | None:
    """Canonical ids the sel resolves to in *tree*, or **None** if un-evaluable.

    Uses _xpath.evaluate so a malformed expression raises rather than passing as
    a no-match. The old contract was literally "empty on no-match/invalid" — one
    value for two states, which in a COLLISION detector means an unparseable sel
    contributes no targets and the mods silently read as compatible.
    """
    try:
        results = _xpath.evaluate(tree, sel)
    except etree.XPathEvalError:
        # silent-ok: None is this function's documented sentinel for "un-evaluable",
        # distinct from [] for "evaluated, matched nothing". _analyze_vpath records
        # every None in CompatReport.unresolvable and render() prints them.
        return None
    if not isinstance(results, list):  # scalar result (count(), name(), ...)
        return []
    ids = []
    for r in results:
        cid = _canonical(r)
        if cid is not None:
            ids.append(cid)
    return ids


def _added_child_keys(op: etree._Element) -> list[str]:
    """@name/@id of an <add>'s child elements (for duplicate-add detection)."""
    keys = []
    for child in op:
        if isinstance(child.tag, str):
            k = child.get("name") or child.get("id")
            if k:
                keys.append(f"{child.tag}#{k}")
    return keys


def _child_keys(root: etree._Element) -> set[str]:
    """@id/@name keys of a full-file registry root's direct children (union case)."""
    keys = set()
    for child in root:
        if not isinstance(child.tag, str):
            continue
        k = child.get("id") or child.get("name")
        if k:
            keys.add(f"{child.tag}#{k}")
    return keys


# --- analysis -----------------------------------------------------------------

def _analyze_vpath(
    vpath: str,
    mod_folders: list[str],
    folder_to_path: dict[str, Path],
    rank: dict[str, int],
    config: _merge.Config,
    unresolvable: list[str] | None = None,
) -> list[Collision]:
    """Classify collisions among mods touching a single virtual path.

    *unresolvable* accumulates ops whose sel= could not be evaluated — they
    contribute no targets, so without this channel they read as "no collision".
    """
    base_tree = _merge.build_effective(vpath, config).tree
    is_union = vpath.lower().startswith(UNION_DIRS)

    # Per mod: resolved diff-target ids (tag -> ids), union keys, and full-override flag.
    diff_targets: dict[str, dict[str, list[str]]] = {}   # folder -> {node_id: [tags]}
    add_child_keys: dict[str, dict[str, list[str]]] = {}  # folder -> {parent_id: [childkeys]}
    union_keys: dict[str, set[str]] = {}
    overriders: list[str] = []

    for folder in sorted(mod_folders, key=lambda f: rank[f]):
        root = _merge.overlay_root(folder_to_path[folder], vpath)
        if root is None:
            continue
        if root.tag == "diff":
            if base_tree is None:
                continue
            node_map: dict[str, list[str]] = defaultdict(list)
            child_map: dict[str, list[str]] = defaultdict(list)
            for op in root:
                if not isinstance(op.tag, str) or op.tag not in _OPS:
                    continue
                sel = op.get("sel", "")
                # xpath resolution is read-only; resolve against the shared base tree
                # (no copy) so positional node ids are comparable across mods.
                cids = _resolve_op_targets(base_tree, sel)
                if cids is None:
                    if unresolvable is not None:
                        unresolvable.append(
                            f"{folder}/{vpath}:{op.sourceline or 0}: sel={sel!r} is not "
                            "valid XPath — this op was excluded from collision detection")
                    continue
                for cid in cids:
                    node_map[cid].append(op.tag)
                    if op.tag == "add":
                        child_map[cid].extend(_added_child_keys(op))
            if node_map:
                diff_targets[folder] = dict(node_map)
            if child_map:
                add_child_keys[folder] = dict(child_map)
        elif is_union and base_tree is not None and root.tag == base_tree.tag:
            union_keys[folder] = _child_keys(root)
        elif vpath.lower() not in _PER_EXTENSION_FILES:
            overriders.append(folder)

    collisions: list[Collision] = []

    def winner(fs: list[str]) -> str:
        return max(fs, key=lambda f: rank[f])

    # 1. diff-target node collisions
    node_to_mods: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for folder, nmap in diff_targets.items():
        for cid, tags in nmap.items():
            node_to_mods[cid][folder] = tags
    for cid, per_mod in node_to_mods.items():
        if len(per_mod) < 2:
            continue
        all_tags = {t for tags in per_mod.values() for t in tags}
        fs = sorted(per_mod, key=lambda f: rank[f])
        if all_tags == {"add"}:
            # Same-parent adds: SOFT, unless two mods add a child with the same key.
            dup = _dup_add_key(cid, fs, add_child_keys)
            if dup:
                collisions.append(Collision(
                    vpath, "HARD", cid, fs, winner(fs),
                    f"both add {dup} under the same parent (duplicate)"))
            else:
                collisions.append(Collision(
                    vpath, "SOFT", cid, fs, winner(fs),
                    "multiple mods <add> under the same node (usually coexist)"))
        else:
            ops_desc = "; ".join(f"{f}:{'/'.join(per_mod[f])}" for f in fs)
            collisions.append(Collision(
                vpath, "HARD", cid, fs, winner(fs),
                f"{ops_desc} — '{winner(fs)}' loads last and wins"))

    # 2. union-key collisions (two mods define the same registry entry)
    key_to_mods: dict[str, list[str]] = defaultdict(list)
    for folder, keys in union_keys.items():
        for k in keys:
            key_to_mods[k].append(folder)
    for k, fs_ in key_to_mods.items():
        if len(fs_) < 2:
            continue
        fs = sorted(fs_, key=lambda f: rank[f])
        collisions.append(Collision(
            vpath, "UNION-KEY", k, fs, winner(fs),
            f"same registry entry {k} defined by {len(fs)} mods — '{winner(fs)}' wins"))

    # 3. full-file override collisions
    if len(overriders) >= 2:
        fs = sorted(overriders, key=lambda f: rank[f])
        collisions.append(Collision(
            vpath, "FULL-OVERRIDE", vpath, fs, winner(fs),
            f"{len(fs)} mods ship a full non-diff file here — '{winner(fs)}' clobbers the rest"))

    return collisions


def _dup_add_key(parent_id: str, folders: list[str],
                 add_child_keys: dict[str, dict[str, list[str]]]) -> str | None:
    """If two mods add a child with the same key under *parent_id*, return that key."""
    seen: dict[str, str] = {}
    for f in folders:
        for k in add_child_keys.get(f, {}).get(parent_id, []):
            if k in seen and seen[k] != f:
                return k
            seen[k] = f
    return None


def analyze(
    ext_dir: Path,
    candidate: Path | None = None,
    config: _merge.Config | None = None,
) -> CompatReport:
    """Analyze collisions across installed mods (optionally focused on *candidate*).

    If *candidate* is given, only collisions that involve it are reported (the
    "before I add this mod" mode); its folder is included in the scanned set.
    """
    config = config or _merge.Config()
    mods = _registry.scan_installed([ext_dir])
    folder_to_path = {m["folder"]: Path(m["path"]) for m in mods}

    cand_folder = None
    if candidate is not None:
        candidate = Path(candidate)
        cand_folder = candidate.name
        if cand_folder not in folder_to_path:
            folder_to_path[cand_folder] = candidate
            mods = mods + [{"folder": cand_folder, "path": str(candidate),
                            "id": cand_folder}]

    order = compute_load_order(mods)
    rank = {f: i for i, f in enumerate(order)}

    # Invert: lowercased vpath -> {folder: real_vpath}
    inv: dict[str, dict[str, str]] = defaultdict(dict)
    for m in mods:
        for low, real in _mod_xml_paths(Path(m["path"])).items():
            inv[low][m["folder"]] = real

    report = CompatReport(mods_scanned=len(mods), load_order=order)
    for low, per_mod in inv.items():
        if len(per_mod) < 2:
            continue
        if cand_folder is not None and cand_folder not in per_mod:
            continue  # candidate-focused: only files the candidate also touches
        report.files_examined += 1
        real_vpath = next(iter(per_mod.values()))
        found = _analyze_vpath(real_vpath, list(per_mod), folder_to_path, rank, config,
                               report.unresolvable)
        if cand_folder is not None:
            found = [c for c in found if cand_folder in c.mods]
        report.collisions.extend(found)
    return report


# --- CLI ----------------------------------------------------------------------

_KIND_ORDER = ["HARD", "FULL-OVERRIDE", "UNION-KEY", "SOFT"]


def render(report: CompatReport, show_soft: bool = False) -> str:
    lines = [
        f"x4compat: {report.mods_scanned} mods, {report.files_examined} shared files examined.",
        "Load order (winner = last): community-reported alphabetical + dependency-first.\n",
    ]
    shown_any = False
    for kind in _KIND_ORDER:
        group = report.by_kind(kind)
        if kind == "SOFT" and not show_soft:
            if group:
                lines.append(f"[SOFT]  {len(group)} benign same-parent <add> overlaps "
                             "(coexist; use --soft to list).\n")
            continue
        if not group:
            continue
        shown_any = True
        lines.append(f"=== {kind}  ({len(group)}) ===")
        for c in sorted(group, key=lambda x: x.vpath):
            lines.append(f"  {c.vpath}")
            lines.append(f"     node/key : {c.target}")
            lines.append(f"     mods     : {', '.join(c.mods)}")
            lines.append(f"     winner   : {c.winner}")
            if c.detail:
                lines.append(f"     note     : {c.detail}")
        lines.append("")
    hard = report.hard
    if not hard and not shown_any:
        lines.append("No HARD / UNION-KEY / FULL-OVERRIDE collisions found."
                     + (" (but see NOT CHECKED below — that clean result is partial)"
                        if report.unresolvable else ""))
    if report.unresolvable:
        lines.append(f"\n=== NOT CHECKED  ({len(report.unresolvable)}) ===")
        lines.append("  These ops could not be resolved, so they took no part in collision")
        lines.append("  detection. A conflict involving them would NOT appear above.")
        for u in report.unresolvable:
            lines.append(f"  !! {u}")
    lines.append(f"\nSummary: {len(report.hard)} hard-ish "
                 f"(HARD+FULL-OVERRIDE), {len(report.by_kind('UNION-KEY'))} union-key, "
                 f"{len(report.by_kind('SOFT'))} soft.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.

    p = argparse.ArgumentParser(
        prog="x4compat",
        description="Detect how installed X4 mods collide over the effective XML tree.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("check", help="analyze collisions across the installed modlist")
    pc.add_argument("candidate", nargs="?",
                    help="a mod folder to focus on ('before I add this'); omit for --all")
    pc.add_argument("--all", action="store_true", help="analyze the whole installed set")
    pc.add_argument("--ext-dir", help="extensions dir to scan "
                    "(default: game-root extensions\\ from _registry)")
    pc.add_argument("--reference", help="unpacked base+DLC reference tree ($X4_REFERENCE)")
    pc.add_argument("--soft", action="store_true", help="also list benign SOFT overlaps")
    pc.add_argument("--json", action="store_true", help="machine-readable output")

    args = p.parse_args(argv)

    ext_dir = Path(args.ext_dir) if args.ext_dir else _registry.GAME_EXTENSIONS
    if not ext_dir.is_dir():
        print(f"error: extensions dir not found: {ext_dir}", file=sys.stderr)
        return 2
    config = _merge.Config(reference=Path(args.reference)) if args.reference else _merge.Config()
    candidate = Path(args.candidate) if args.candidate else None
    if candidate is not None:
        _input.require_mod_dir(candidate, "candidate mod folder")

    report = analyze(ext_dir, candidate=candidate, config=config)

    if args.json:
        import dataclasses
        import json
        payload = {
            "mods_scanned": report.mods_scanned,
            "files_examined": report.files_examined,
            "load_order": report.load_order,
            "collisions": [dataclasses.asdict(c) for c in report.collisions],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render(report, show_soft=args.soft))

    # Non-zero exit when there are real (hard-ish) collisions — usable as a gate.
    return 1 if report.hard else 0
