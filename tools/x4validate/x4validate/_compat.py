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

import re

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _paths, _cat, _merge, _registry, _scan, _xpath, _input
from x4validate import __version__

#: `{page,text}` localized reference - display text, never a registry identity.
_TEXTREF_KEY = re.compile(r"#\{\d+,\s*\d+\}$")

UNION_DIRS = ("libraries/", "index/", "t/")
_OPS = ("add", "replace", "remove")
# Files the engine loads once PER EXTENSION (never shared/overridden across mods),
# so multiple mods "shipping" one is normal, not a full-file-override collision.
_PER_EXTENSION_FILES = {"ui.xml"}


@dataclass
class Collision:
    """One way two mods contend over the same effective XML.

    ⚠ **`winner` does NOT mean the same thing for every kind, and for two kinds it
    is deliberately empty.** Reading it as "the mod whose value is live" is wrong
    for SUBTREE and NAME-CLASH; use :meth:`live_value_owner` instead, which cannot
    give a confident wrong answer.
    """
    vpath: str
    kind: str            # HARD | UNION-KEY | FULL-OVERRIDE | SUBTREE | NAME-CLASH | SOFT
    target: str          # node identity / registry key / file path
    mods: list[str]      # involved mod folders, in load order (winner last)
    winner: str          # the mod whose value is LIVE — empty for SUBTREE/NAME-CLASH
    detail: str = ""
    #: SUBTREE only: the mod that did the WIPING. It is not the owner of the final
    #: value — a third mod loading later can re-supply what was wiped — which is
    #: exactly why it is not called `winner`.
    wiped_by: str = ""

    def live_value_owner(self) -> str | None:
        """The mod whose value is live, or ``None`` when that is unknowable here.

        =============== ==========================================================
        kind            meaning
        =============== ==========================================================
        FULL-OVERRIDE   the mod that clobbers — its file is the document
        HARD            the mod that loads last at the clashing node
        UNION-KEY       the mod that defines the surviving registry entry
        SUBTREE         ``None`` — `winner` was the WIPER, and a later mod may
                        have restored the values (MEASURED: 3 of 148, 2.0%)
        NAME-CLASH      ``None`` — ``index/macros.xml`` decides, not load order
        SOFT            ``None`` — benign coexistence, nobody "wins"
        =============== ==========================================================

        Added 2026-08-13 after an inbound report compared a SUBTREE `winner`
        against `x4effective`'s per-attribute origin and concluded x4compat was
        wrong. It was not: the two answer different questions. This method is the
        one place that distinction lives. See CLAUDE.md gotcha #18.
        """
        if self.kind in ("SUBTREE", "NAME-CLASH", "SOFT"):
            return None
        return self.winner or None


@dataclass
class Skipped:
    """A file x4compat could NOT analyse. Mirrors `_check.Skipped`'s contract.

    Defined here rather than imported because `_check` imports `_compat`, so the
    dependency only runs one way. Keep the two in step: *degraded* means a whole
    file contributed ZERO collisions, so a clean report is not evidence of
    compatibility and the CLI exits 3.
    """
    what: str       # the vpath / input that could not be analysed
    why: str        # the concrete reason
    degraded: bool = False


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
    #: Files that produced no comparison at all. Until 2026-08-01 `_analyze_vpath`
    #: simply `continue`d past every mod when the base tree could not be built,
    #: so 140 of 523 examined files contributed zero collisions and rendered
    #: identically to "analysed, no conflicts". Same failure family as F4.
    skipped: list[Skipped] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Collision]:
        """Collisions of *kind*, in a STABLE order.

        Sorted here rather than at each call site because every consumer — the
        renderer, the JSON dump, a saved baseline — must agree run to run. An
        upstream set-iteration made two identical runs emit the same collisions
        in different orders, which turns a baseline diff into noise and lets a
        real change hide in it.
        """
        return sorted((c for c in self.collisions if c.kind == kind),
                      key=lambda c: (c.vpath, c.target, tuple(c.mods)))

    @property
    def hard(self) -> list[Collision]:
        # SUBTREE counts as hard-ish by user decision (2026-08-02): a later mod
        # provably wiping an earlier mod's applied change gates, with the
        # load-order-is-convention caveat carried in every row's detail text.
        return (self.by_kind("HARD") + self.by_kind("FULL-OVERRIDE")
                + self.by_kind("SUBTREE"))

    @property
    def degraded(self) -> list[Skipped]:
        """Skips that cost a whole file — the clean parts prove nothing about them."""
        return [s for s in self.skipped if s.degraded]

    def skip(self, what: str, why: str, degraded: bool = False) -> None:
        self.skipped.append(Skipped(what, why, degraded))


# --- mod discovery + load order ----------------------------------------------

def _mod_deps(mod_path: Path, dropped: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (mod_id, [dependency_ids]) from a mod's content.xml.

    A manifest that will not parse yields ZERO dependencies, and dependencies are
    what force a mod to load EARLIER — so silently swallowing the failure changes
    the computed load order, which decides every collision winner this module
    reports. Report it through *dropped* (same convention as
    `_registry.scan_installed`, which already handles this case correctly).
    MEASURED 2026-08-12: 0 of 122 installed manifests are malformed, so this is a
    latent defect — the cost is zero today and unbounded the day it isn't.
    """
    cx = mod_path / "content.xml"
    if not cx.is_file():
        if dropped is not None:
            dropped.append(f"{mod_path.name}: no content.xml — assuming no dependencies")
        return mod_path.name, []
    try:
        root = etree.parse(str(cx)).getroot()
    except etree.XMLSyntaxError as exc:
        if dropped is not None:
            dropped.append(f"{mod_path.name}: content.xml will not parse ({exc}) — "
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

    Pass *dropped* to receive manifests whose dependencies could not be read —
    those mods fall back to alphabetical placement, which can silently change who
    wins a collision. See `_mod_deps`.
    """
    folders = [m["folder"] for m in mods]
    id_to_folder: dict[str, str] = {}
    deps_by_folder: dict[str, list[str]] = {}
    for m in mods:
        mod_id, deps = _mod_deps(Path(m["path"]), dropped)
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
    for vpath in _cat.mod_vfs(mod_path, packed_only=True):  # packed-ok: loose added below
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
    """@id/@name of an <add>'s child elements (for duplicate-add detection).

    ID FIRST, matching `_child_keys` — this was `name or id` until 2026-08-02,
    which is the wrong identity for the two biggest registries: a ware's or
    job's `name=` is a localized `{page,t}` TEXT REFERENCE, not its key. The
    measured consequence of the mismatch: the engine-confirmed duplicate
    `ware#shield_xen_xl_standard_02_mk1` (`WareDB::Import(): Duplicate
    definition`, two log runs) was invisible, because the diff-add side keyed it
    `ware#{20204,...}` while the union side keyed it `ware#<id>` — and jobs
    compared by display name, which collides across UNRELATED jobs."""
    keys = []
    for child in op:
        if isinstance(child.tag, str):
            k = child.get("id") or child.get("name")
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

def _owner_aware_config(vpath: str, folder_to_path: dict[str, Path],
                        config: _merge.Config) -> _merge.Config:
    """Add the OWNER mod to *config*.overlays when *vpath* is a cross-mod patch.

    For `extensions/<owner>/<rel>` the base is `<owner>`'s own `<rel>` — it is not
    in `reference/`. `_merge._build_owned` finds the owner by scanning
    `dlc_dirs() + config.overlays`, so with the bare `Config()` x4compat used to
    pass, the owner was NEVER in that list: `owner_dir` came back None, the tree
    came back None, and `_analyze_vpath` dropped every mod on the file.

    Measured before this fix: **140 of 523 examined files** produced no comparison,
    silently discarding 144 `<diff>` mods across 10 mods — i.e. x4compat could not
    analyse a single cross-mod nested patch, the construct its own module docstring
    calls the most collision-prone in X4 modding. F10 (wave 2) made those files
    visible; they all landed in the drop.

    Only the owner is added, never the other patchers: every mod's `sel=` must
    resolve against the same UNPATCHED base, exactly as the non-nested path does
    (base+DLC, no mods). Folding the patchers in would let one mod's `<remove>`
    hide the very node another mod collides on.
    """
    nested = _merge._nested_target(vpath, config.packed_dlc_names())
    if nested is None:
        return config
    owner = nested[0].lower()
    owner_dir = next((p for f, p in folder_to_path.items() if f.lower() == owner), None)
    if owner_dir is None or owner_dir in tuple(config.overlays):
        return config
    return _merge.replace(config, overlays=tuple(config.overlays) + (owner_dir,))


def _no_base_reason(vpath: str, folder_to_path: dict[str, Path],
                    config: _merge.Config) -> str:
    """Say WHY no base tree exists, computed — never guessed.

    An earlier draft of this message asserted "the owning mod is not installed"
    for every nested path. That is only one of three causes, and stating an
    unverified one is worse than stating none: a wrong reason is what stops the
    next person checking (the F1 lesson).
    """
    nested = _merge._nested_target(vpath, config.packed_dlc_names())
    if nested is None:
        return f"no file at {vpath} in the base+DLC reference tree"
    owner, rel = nested
    owner_dir = next((p for f, p in folder_to_path.items() if f.lower() == owner.lower()),
                     None)
    if owner_dir is None:
        return f"the owning mod '{owner}' is not installed"
    oroot = _merge.overlay_root(owner_dir, rel)
    if oroot is None:
        return f"'{owner}' does not ship {rel}, or it could not be parsed"
    if oroot.tag == "diff":
        return (f"'{owner}' ships {rel} as a <diff> itself, so it is a patch rather "
                "than a base")
    return f"'{owner}' supplies {rel} but the merge produced no tree"


def _analyze_vpath(
    vpath: str,
    mod_folders: list[str],
    folder_to_path: dict[str, Path],
    rank: dict[str, int],
    config: _merge.Config,
    unresolvable: list[str] | None = None,
    per_mod_vpath: dict[str, str] | None = None,
    report: CompatReport | None = None,
) -> list[Collision]:
    """Classify collisions among mods touching a single virtual path.

    *unresolvable* accumulates ops whose sel= could not be evaluated — they
    contribute no targets, so without this channel they read as "no collision".

    *per_mod_vpath* gives each mod's OWN path to the same effective file, which
    differ for a cross-mod nested patch: the overlay ships
    `extensions/<target>/<rel>` while the target itself ships `<rel>`. Reading
    every mod at one shared path missed that collision entirely — and it is the
    most collision-prone construct in X4 modding, one mod deliberately
    overwriting another's file. Defaults to *vpath* for every mod.

    *report* receives the files that could not be analysed at all.
    """
    config = _owner_aware_config(vpath, folder_to_path, config)
    base_tree = _merge.build_effective(vpath, config).tree
    is_union = vpath.lower().startswith(UNION_DIRS)
    at = per_mod_vpath or {}

    # Per mod: resolved diff-target ids (tag -> ids), union keys, and full-override flag.
    diff_targets: dict[str, dict[str, list[str]]] = {}   # folder -> {node_id: [tags]}
    add_child_keys: dict[str, dict[str, list[str]]] = {}  # folder -> {parent_id: [childkeys]}
    union_keys: dict[str, set[str]] = {}
    diff_add_doc_keys: dict[str, set[str]] = {}  # folder -> doc-wide added keys (F12)
    overriders: list[str] = []
    no_base_reported: set[str] = set()  # one skip per mod, not one per op

    for folder in sorted(mod_folders, key=lambda f: rank[f]):
        mod_vpath = at.get(folder, vpath)
        root = _merge.overlay_root(folder_to_path[folder], mod_vpath)
        if root is None:
            if report is not None:
                report.skip(
                    f"{folder} at {mod_vpath}",
                    "the mod lists this file but it could not be read or parsed, so "
                    "this mod took no part in the comparison")
            continue
        if root.tag == "diff":
            if base_tree is None:
                if report is not None and folder not in no_base_reported:
                    no_base_reported.add(folder)
                    report.skip(
                        vpath,
                        f"{folder} ships a <diff> here but no base tree could be built "
                        f"({_no_base_reason(vpath, folder_to_path, config)}), so its ops "
                        "could not be resolved to nodes",
                        degraded=True)
                continue
            node_map: dict[str, list[str]] = defaultdict(list)
            child_map: dict[str, list[str]] = defaultdict(list)
            doc_keys: set[str] = set()
            for op in root:
                if not isinstance(op.tag, str) or op.tag not in _OPS:
                    continue
                # Document-wide registry keys (F12): the engine's uniqueness is
                # per-DOCUMENT (WareDB/GroupDB import), but the same-anchor check
                # below only compares adds under one parent cid — two mods adding
                # the same ware anchored at DIFFERENT siblings never met. Guarded
                # adds are designed conditionals and contribute nothing.
                if op.tag == "add" and not op.get("if"):
                    doc_keys.update(_added_child_keys(op))
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
            # Diff-adds join the registry-key comparison for union files. t/ is
            # check_text's domain; wildcard keys (icon#upgrade_*, icon#ship_*)
            # are the generic-icon idiom — 32 of 37 measured document-wide
            # duplicates, none engine-complained — so they are excluded HERE
            # (the new mechanism) while full-file-vs-full-file keys keep their
            # existing behavior unchanged.
            if (is_union and doc_keys
                    and not vpath.lower().lstrip("/").startswith("t/")):
                # Two key classes are NOT identities and must not join:
                # wildcards (icon#upgrade_* — the generic-icon idiom) and
                # {page,text} references (a <production>'s name= is localized
                # display text; keying on it matched production stages of
                # UNRELATED wares in the measurement).
                diff_add_doc_keys[folder] = {
                    k for k in doc_keys
                    if "*" not in k and not _TEXTREF_KEY.search(k)}
        elif is_union and base_tree is not None and root.tag == base_tree.tag:
            union_keys[folder] = _child_keys(root)
        elif vpath.lower() not in _PER_EXTENSION_FILES:
            overriders.append(folder)

    collisions: list[Collision] = []
    # Keys pass 1 already reported as HARD duplicates, with the mods of that
    # row: a union-key row is folded only when it names NO mod the hard row
    # missed (icons: the full-file shippers of icon#upgrade_* are different
    # mods from the same-anchor adders — folding them would lose information).
    hard_dup_keys: dict[str, set[str]] = {}

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
                hard_dup_keys.setdefault(dup, set()).update(fs)
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

    # 2. union-key collisions (two mods define the same registry entry).
    # Since 2026-08-02 diff-ADDED keys participate too (document-wide, any
    # anchor): registry uniqueness is per-document, and the engine-confirmed
    # `ware#shield_xen_xl_standard_02_mk1` duplicate was an add-vs-add pair
    # anchored at different siblings — invisible to both the same-anchor HARD
    # check and the full-file-only comparison here. Keys pass 1 already
    # reported as HARD duplicates are skipped (one finding per fact).
    key_to_mods: dict[str, list[str]] = defaultdict(list)
    for source in (union_keys, diff_add_doc_keys):
        for folder, keys in source.items():
            # `keys` is a set, and set iteration order varies between processes
            # (hash randomization). Unsorted, that leaked into key_to_mods'
            # insertion order and out into the report, so two identical runs
            # emitted the same 419 collisions in different orders — enough to
            # make a baseline diff look like a change.
            for k in sorted(keys):
                if folder not in key_to_mods[k]:
                    key_to_mods[k].append(folder)
    for k, fs_ in sorted(key_to_mods.items()):
        if len(fs_) < 2 or set(fs_) <= hard_dup_keys.get(k, set()):
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

    # 4. subtree clobbers (F18): _canonical gives an element and its own
    # attribute unrelated ids, so a mod replacing an ELEMENT and a mod patching
    # INSIDE that element never registered as colliding — though the later
    # replace plainly wipes the earlier edit. Order-aware by construction: only
    # a wipe that loads AFTER the victim destroys an applied change (a wipe
    # that loads first merely changes what the victim's sel sees, which the
    # Tier B sel check already covers). Measured 2026-08-02 on the 101-mod
    # install: 184 raw pair-hits → 165 real clobbers, and the order filter
    # proved itself by correctly clearing ebi_m0_vro (its ws_ dependency on VRO
    # resolves, so it loads after the wipe it would otherwise be a victim of).
    for a, amap in diff_targets.items():
        wipes = [cid for cid, tags in amap.items()
                 if ("replace" in tags or "remove" in tags) and "/@" not in cid]
        if not wipes:
            continue
        for b, bmap in diff_targets.items():
            if b == a or rank[a] < rank[b]:
                continue
            hits = [(w, cb) for w in wipes for cb in bmap if cb.startswith(w + "/")]
            if hits:
                w0, cb0 = hits[0]
                # winner is deliberately EMPTY, exactly as NAME-CLASH is: for a
                # SUBTREE the load-order "winner" is the mod that WIPED, which is
                # not the owner of the final value, and reporting it in the winner
                # field is a confident wrong answer waiting to be compared against
                # x4effective's origin. The wiper keeps its own field.
                collisions.append(Collision(
                    vpath, "SUBTREE", w0, [b, a], "",
                    f"'{a}' loads after '{b}' and replace/removes {w0}, wiping "
                    f"{len(hits)} of '{b}'s change(s) inside it (e.g. {cb0}) — "
                    "load order is community convention, so this is advisory",
                    wiped_by=a))

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


def _macro_defs(mod_path: Path) -> dict[str, str]:
    """`{macro_name_lower: vpath}` for macros this mod DEFINES (not diffs).

    Narrowed to files under a `macros/` directory — the engine-wide convention
    (`assets/.../macros/<name>_macro.xml`) that every observed case follows.
    Parsing every XML of every mod would roughly double `analyze`'s runtime for
    definitions that do not live there.
    """
    out: dict[str, str] = {}
    for vpath, root in _scan.iter_mod_xml(
            mod_path, lambda v: "/macros/" in v.replace("\\", "/").lower(), None):
        if root.tag == "diff":
            # A <diff> can still DEFINE macros: `<replace sel="//macros">` with a
            # fresh <macros> payload is the standard whole-file override idiom
            # (VRO ships 848 of them). Skipping all diffs missed the very case
            # this check was built for — `missile_flagship_light_mk1_macro`,
            # where VRO's definition arrives exactly that way. Only count a macro
            # the op actually SUPPLIES; a bare `<replace sel=".../@attr">` tweak
            # names no macro and defines nothing.
            for op in root:
                if not isinstance(op.tag, str) or op.tag not in ("add", "replace"):
                    continue
                for m in op.iter("macro"):
                    name = m.get("name")
                    if name:
                        out.setdefault(name.lower(), vpath)
            continue
        for m in root.iter("macro"):
            name = m.get("name")
            if name:
                out.setdefault(name.lower(), vpath)
    return out


def _strip_nesting(vpath: str) -> str:
    """`extensions/<owner>/<rel>` -> `<rel>`; anything else unchanged (lowercased).

    The nested form is a PATCH INTO <owner>'s file, so both spellings name the
    same logical file. Unpacked `ego_dlc_*` content genuinely lives under
    `extensions/`, so it is left alone.
    """
    v = vpath.replace("\\", "/").lower().lstrip("/")
    parts = v.split("/")
    if len(parts) > 2 and parts[0] == "extensions" and not parts[1].startswith("ego_dlc_"):
        return "/".join(parts[2:])
    return v


def _name_clashes(mods: list[dict], rank: dict[str, int],
                  cand_folder: str | None) -> list[Collision]:
    """Macro NAMES defined by 2+ mods in DIFFERENT files.

    A collision class the per-vpath scan structurally cannot see: the two mods
    never share a path, so nothing ever compares them — yet X4 resolves macros by
    NAME through `index/macros.xml`, so only ONE definition is ever loaded and the
    other is dead content the author cannot tell is dead.

    Found 2026-08-09 by re-deriving the missile roster:
    `missile_flagship_light_mk1_macro` is defined by both `rackham` and `vro` at
    different paths, and the effective index points at VRO's — so rackham's file
    is never read. Measured extent: 22 names across the installed set.

    Base/DLC are excluded: vanilla itself ships `cluster_sm3_background_macro` at
    six paths, so the pattern is legal and only becomes a question between mods.

    **The winner is NOT decided by load order** — `index/macros.xml` decides, and
    that file is itself patchable. So `winner` is left empty and the detail says
    to resolve it with `x4effective dump index/macros.xml`. Naming a load-order
    winner here would be a confident wrong answer.
    """
    defs: dict[str, dict[str, str]] = defaultdict(dict)
    for m in mods:
        folder = m["folder"]
        if folder.lower().startswith("ego_dlc_"):
            continue
        for name, vpath in _macro_defs(Path(m["path"])).items():
            defs[name][folder] = vpath

    out: list[Collision] = []
    for name, per_mod in sorted(defs.items()):
        if len(per_mod) < 2:
            continue
        # Compare LOGICAL files. `extensions/<owner>/<rel>` is the nested
        # cross-mod patch form of `<rel>` — the engine merges it INTO the owner's
        # file, so it is the same file, not a rival definition. Without this
        # every cross-mod patch pair looked like a name clash (measured: 57 rows,
        # of which 35 were this).
        if len({_strip_nesting(v) for v in per_mod.values()}) < 2:
            continue          # same logical file -> already a file-level collision
        if cand_folder is not None and cand_folder not in per_mod:
            continue
        folders = sorted(per_mod, key=lambda f: rank.get(f, len(rank)))
        out.append(Collision(
            vpath=" | ".join(f"{f}:{per_mod[f]}" for f in folders),
            kind="NAME-CLASH", target=name, mods=folders, winner="",
            detail=("same macro name defined in DIFFERENT files; X4 loads only the one "
                    "index/macros.xml points at, so the others are dead. Resolve with "
                    "`x4effective dump index/macros.xml` — load order does NOT decide this."),
        ))
    return out


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
    # ACTIVE: two mods only collide if the engine loads both. The on-disk set
    # named a disabled mod as a participant in 4 collision rows of the 2026-08-22
    # baseline. The "what if I added this" case is *candidate*, below -- an
    # explicit opt-in, not a side effect of how the world is enumerated.
    mods = _registry.mods("active", [ext_dir])
    folder_to_path = {m["folder"]: Path(m["path"]) for m in mods}

    cand_folder = None
    if candidate is not None:
        candidate = Path(candidate)
        cand_folder = candidate.name
        if cand_folder not in folder_to_path:
            folder_to_path[cand_folder] = candidate
            mods = mods + [{"folder": cand_folder, "path": str(candidate),
                            "id": cand_folder}]

    order_dropped: list[str] = []
    order = compute_load_order(mods, order_dropped)
    rank = {f: i for i, f in enumerate(order)}

    # Invert: lowercased vpath -> {folder: that mod's OWN real vpath}
    #
    # Each owned file is ALSO registered under extensions/<owner>/<rel>, the form
    # a cross-mod nested patch uses to target it. Without the alias the two never
    # share a key — the patching mod ships `extensions/<owner>/md/somefile.xml`
    # while the owner ships `md/SomeFile.xml` (note the case, which the engine
    # ignores and a naive key does not) — so a mod that exists purely to patch
    # another reported "0 shared files examined … no collisions" and exit 0.
    inv: dict[str, dict[str, str]] = defaultdict(dict)
    for m in mods:
        folder = m["folder"]
        for low, real in _mod_xml_paths(Path(m["path"])).items():
            inv[low][folder] = real
            if not low.startswith("extensions/"):
                inv[f"extensions/{folder.lower()}/{low}"][folder] = real

    report = CompatReport(mods_scanned=len(mods), load_order=order)
    for msg in order_dropped:
        # degraded=True: an unreadable manifest costs this mod its dependency
        # edges, so its load-order position — and therefore every collision
        # winner involving it — is a guess. The clean rows prove nothing about it.
        report.skip(msg, "load order degraded to alphabetical for this mod",
                    degraded=True)
    for low, per_mod in inv.items():
        if len(per_mod) < 2:
            continue
        if cand_folder is not None and cand_folder not in per_mod:
            continue  # candidate-focused: only files the candidate also touches
        report.files_examined += 1
        # The canonical path is the NESTED form when one exists: build_effective
        # understands extensions/<owner>/<rel> and resolves it to the owner's own
        # file, which is the base every op here is really patching.
        real_vpath = next((v for v in per_mod.values() if v.lower().startswith("extensions/")),
                          next(iter(per_mod.values())))
        found = _analyze_vpath(real_vpath, list(per_mod), folder_to_path, rank, config,
                               report.unresolvable, per_mod_vpath=per_mod,
                               report=report)
        if cand_folder is not None:
            found = [c for c in found if cand_folder in c.mods]
        report.collisions.extend(found)

    # Entity-level pass: same macro NAME, different files. Structurally invisible
    # to the loop above, which keys on vpath.
    report.collisions.extend(_name_clashes(mods, rank, cand_folder))
    return report


# --- CLI ----------------------------------------------------------------------

_KIND_ORDER = ["HARD", "FULL-OVERRIDE", "SUBTREE", "NAME-CLASH", "UNION-KEY", "SOFT"]


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
            # A SUBTREE has no live-value winner; showing the WIPER under a
            # "winner" label is what made an inbound report mis-read this row.
            if c.wiped_by:
                lines.append(f"     wiped by : {c.wiped_by}  (NOT the owner of the "
                             f"final value — a later mod may re-supply it)")
            else:
                lines.append(f"     winner   : {c.winner}")
            if c.detail:
                lines.append(f"     note     : {c.detail}")
        lines.append("")
    hard = report.hard
    if not hard and not shown_any:
        lines.append("No HARD / FULL-OVERRIDE / SUBTREE / UNION-KEY collisions found."
                     + (" (but see NOT CHECKED below — that clean result is partial)"
                        if report.unresolvable or report.skipped else ""))
    if report.skipped:
        deg = report.degraded
        lines.append(f"\n=== NOT ANALYSED  ({len(report.skipped)}, "
                     f"{len(deg)} cost a whole file) ===")
        lines.append("  These produced no comparison at all. A collision here would NOT")
        lines.append("  appear above — this is not the same as 'checked, no conflict'.")
        for s in report.skipped:
            lines.append(f"  {'!!' if s.degraded else ' -'} {s.what}")
            lines.append(f"       {s.why}")
    if report.unresolvable:
        lines.append(f"\n=== NOT CHECKED  ({len(report.unresolvable)}) ===")
        lines.append("  These ops could not be resolved, so they took no part in collision")
        lines.append("  detection. A conflict involving them would NOT appear above.")
        for u in report.unresolvable:
            lines.append(f"  !! {u}")
    lines.append(f"\nSummary: {len(report.hard)} hard-ish "
                 f"(HARD+FULL-OVERRIDE+SUBTREE), {len(report.by_kind('UNION-KEY'))} union-key, "
                 f"{len(report.by_kind('SOFT'))} soft, "
                 f"{len(report.degraded)} file(s) not analysed.")
    if report.degraded:
        lines.append("DEGRADED: some files yielded no comparison — see NOT ANALYSED "
                     "above. Exit 3.")
    return "\n".join(lines)


@_paths.refuses_unconfigured
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
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
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

    ext_dir = Path(args.ext_dir) if args.ext_dir else _registry.require(
        _registry.GAME_EXTENSIONS, "the game extensions dir",
        "set X4_GAME (or X4_EXTENSIONS), or pass --ext-dir")
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
            "skipped": [dataclasses.asdict(s) for s in report.skipped],
            "degraded": bool(report.degraded),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render(report, show_soft=args.soft))

    # Same contract as x4validate: 1 = real findings, 3 = a check could not run so a
    # clean result proves nothing, 0 = clean AND something was actually compared.
    # Findings outrank degradation — you fix what is known broken first.
    if report.hard:
        return 1
    return 3 if report.degraded else 0
