"""Reproduce X4's *effective* XML for a virtual path: base + DLC (+ mods).

Per-overlay strategy:
  - root <diff>                         -> apply add/replace/remove ops (pos/if/silent)
  - non-diff under a shared-registry
    dir (libraries/, index/, t/) with
    the same root tag as the base       -> UNION direct children (dedupe by @id/@name,
                                           later-overlay-wins) — engine merges these
  - any other non-diff root             -> full-file override (asset macro/component files)

The union case matters: every DLC ships libraries/ships.xml, character_macros.xml,
wares.xml, loadouts.xml, ... as full files, and the engine merges their entries with
the base. Treating them as full-file overrides (the old behavior) clobbered base-game
ships/macros out of the effective tree, producing phantom "sel matched nothing" errors
for any mod patching a base entry.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _cat
from x4validate._provenance import Origin, Recorder

# --- Workspace defaults (overridable via Config / --reference / $X4_REFERENCE) ---
# Keep this injectable: no hardcoded user path should be the only way to point at
# the reference tree (community-release portability).
REFERENCE = Path(os.environ.get(
    "X4_REFERENCE", "reference"))
_PARSER = etree.XMLParser(remove_blank_text=False, recover=False, resolve_entities=False)


@dataclass
class Config:
    reference: Path = REFERENCE
    #: Tier B — other INSTALLED extension roots to merge in after DLC, in load
    #: order. Empty (Tier A) = base+DLC only, which cannot see content that
    #: another mod adds, removes or overrides. Threaded automatically into every
    #: build_effective() call that receives this Config.
    overlays: tuple[Path, ...] = ()

    def dlc_dirs(self) -> list[Path]:
        ext = self.reference / "extensions"
        if not ext.is_dir():
            return []
        # Deterministic order; inter-DLC order is order-independent in practice
        # (DLC diffs guard with if="not(...)").
        return sorted(p for p in ext.iterdir() if p.is_dir() and p.name.startswith("ego_dlc_"))


@dataclass
class AppliedOp:
    tag: str
    sel: str
    line: int
    ok: bool
    detail: str
    silent: bool = False
    skipped_if: bool = False
    ambiguous: bool = False


@dataclass
class MergeResult:
    tree: etree._Element | None
    sources: list[str] = field(default_factory=list)  # which overlays contributed
    base_found: bool = False


def parse_file(path: Path) -> etree._Element:
    return etree.parse(str(path), _PARSER).getroot()


def parse_bytes(data: bytes) -> etree._Element:
    return etree.fromstring(data, _PARSER)


def overlay_root(odir: Path, vpath: str) -> etree._Element | None:
    """Resolve *vpath* within an overlay dir to a parsed root, or None if absent.

    Loose files take priority over the mod's packed catalog (they do in the engine
    too, and during development you edit loose). Falls back to reading the member
    from the mod's ext_*/subst_* catalogs so packed mods (e.g. VRO) are visible.
    """
    loose = odir / vpath
    if loose.is_file():
        return parse_file(loose)
    data = _cat.read_path(odir, vpath)
    if data is not None:
        return parse_bytes(data)
    return None


def _truthy(val: str | None) -> bool:
    return str(val).lower() in {"true", "1", "yes"}


# --- Diff application ---------------------------------------------------------

_OPS = {"add", "replace", "remove"}


def apply_diff(tree: etree._Element, diff_root: etree._Element,
               recorder: Recorder | None = None, source: str = "") -> list[AppliedOp]:
    """Apply every op in *diff_root* to *tree* in document order. Mutates tree.

    With *recorder*, every mutation is stamped with an Origin(source, op, line)
    at mutation time (see _provenance for the identity model)."""
    applied: list[AppliedOp] = []
    for op in diff_root:
        if not isinstance(op.tag, str) or op.tag not in _OPS:
            continue
        sel = op.get("sel", "")
        line = op.sourceline or 0
        silent = _truthy(op.get("silent"))

        # if= gate: evaluate against the current tree; falsy -> skip the op.
        cond = op.get("if")
        if cond:
            try:
                if not tree.xpath(cond):
                    applied.append(AppliedOp(op.tag, sel, line, True, "if= false: skipped",
                                             silent, skipped_if=True))
                    continue
            except etree.XPathEvalError as exc:
                applied.append(AppliedOp(op.tag, sel, line, False, f"invalid if=: {exc}", silent))
                continue

        try:
            targets = tree.xpath(sel)
        except etree.XPathEvalError as exc:
            applied.append(AppliedOp(op.tag, sel, line, False, f"invalid sel=: {exc}", silent))
            continue

        if not targets:
            applied.append(AppliedOp(op.tag, sel, line, False, "sel matched nothing", silent))
            continue

        # RFC 5261: sel must select exactly ONE node. X4 enforces this — it logs
        # "Multiple matching nodes for path '<sel>' in patch file '<f>'. Skipping
        # node." and applies NOTHING. Modelling that faithfully matters: applying
        # to every match instead would produce an effective tree the game never
        # has (e.g. a material added to both collections named "map").
        if len(targets) > 1:
            applied.append(AppliedOp(op.tag, sel, line, False,
                                     f"sel matched {len(targets)} nodes — engine skips "
                                     "ambiguous ops (RFC 5261: must match exactly one)",
                                     silent, ambiguous=True))
            continue

        # An <add type=...> we do not implement must not be reported as applied.
        # Anything other than RFC 5261's "@attr" form (e.g. a namespace add) would
        # silently change nothing here while the engine acts on it.
        typ = op.get("type", "")
        if op.tag == "add" and typ and not typ.startswith("@"):
            applied.append(AppliedOp(op.tag, sel, line, False,
                                     f"unsupported add type={typ!r} — only RFC 5261 "
                                     "type=\"@attr\" is modelled", silent))
            continue

        origin = Origin(source, op.tag, line) if recorder is not None else None
        if op.tag == "remove":
            _do_remove(targets, recorder, origin)
        elif op.tag == "replace":
            _do_replace(targets, op, recorder, origin)
        elif op.tag == "add":
            _do_add(targets, op, recorder, origin)
        applied.append(AppliedOp(op.tag, sel, line, True, f"{len(targets)} target(s)", silent))
    return applied


def _is_attr(node) -> bool:
    return getattr(node, "is_attribute", False)


def _path_of(node) -> str:
    """Display path for a node/attribute at this instant (removal records only)."""
    if _is_attr(node):
        parent = node.getparent()
        base = parent.getroottree().getpath(parent) if parent is not None else ""
        return f"{base}/@{node.attrname}"
    return node.getroottree().getpath(node)


def _do_remove(targets, recorder: Recorder | None = None, origin: Origin | None = None) -> None:
    for t in targets:
        if recorder is not None:
            recorder.node_removed(_path_of(t), origin)
        if _is_attr(t):
            parent = t.getparent()
            if parent is not None:
                parent.attrib.pop(t.attrname, None)
        else:
            parent = t.getparent()
            if parent is not None:
                parent.remove(t)


def _do_replace(targets, op, recorder: Recorder | None = None,
                origin: Origin | None = None) -> None:
    new_children = [c for c in op if isinstance(c.tag, str)]
    for t in targets:
        if _is_attr(t):
            parent = t.getparent()
            if parent is not None:
                parent.set(t.attrname, op.text or "")
                if recorder is not None:
                    recorder.attr_set(parent, t.attrname,
                                      Origin(origin.source, "replace-attr", origin.line))
        elif new_children:
            parent = t.getparent()
            if parent is None:
                continue
            idx = parent.index(t)
            parent.remove(t)
            for off, child in enumerate(new_children):
                new = copy.deepcopy(child)
                parent.insert(idx + off, new)
                if recorder is not None:
                    if off == 0:  # first inserted child carries the replaced node's lineage
                        recorder.elem_replaced(t, new, origin)
                    else:
                        recorder.elem_created(new, origin)
        else:
            # Replace element's inner text/content.
            t.text = op.text
            for c in list(t):
                t.remove(c)
            if recorder is not None:
                recorder.elem_created(t, Origin(origin.source, "replace-text", origin.line),
                                      prior_chain=recorder.elem_chain(t))


def _do_add(targets, op, recorder: Recorder | None = None,
            origin: Origin | None = None) -> None:
    pos = op.get("pos", "")
    typ = op.get("type", "")
    new_children = [c for c in op if isinstance(c.tag, str)]

    def _record(new):
        if recorder is not None:
            recorder.elem_created(new, origin)

    # RFC 5261 §4.3: type="@name" adds an ATTRIBUTE to each target, valued from the
    # op's text. X4 supports this and installed mods rely on it (da_ku_ai_tweaks,
    # axes10k20kscanshiprange). It is the right tool when another mod owns a sibling
    # attribute you must not clobber — a whole-node <replace> would bake in whatever
    # value happened to be winning at authoring time.
    #
    # Without this branch the op fell through to "append children"; with no element
    # children to append it mutated nothing yet still reported "1 target(s)" — a
    # false OK on precisely the silent-no-op class this tool exists to catch.
    if typ.startswith("@"):
        name = typ[1:]
        if not name:
            return
        for t in targets:
            if _is_attr(t):
                continue  # cannot hang an attribute off an attribute
            t.set(name, op.text or "")
            if recorder is not None and origin is not None:
                recorder.attr_set(t, name, Origin(origin.source, "add-attr", origin.line))
        return

    for t in targets:
        if _is_attr(t):
            continue  # add cannot target an attribute
        if pos == "prepend":
            for i, child in enumerate(new_children):
                new = copy.deepcopy(child)
                t.insert(i, new)
                _record(new)
        elif pos in {"before", "after"}:
            parent = t.getparent()
            if parent is None:
                continue
            idx = parent.index(t) + (1 if pos == "after" else 0)
            for off, child in enumerate(new_children):
                new = copy.deepcopy(child)
                parent.insert(idx + off, new)
                _record(new)
        else:  # append (default)
            for child in new_children:
                new = copy.deepcopy(child)
                t.append(new)
                _record(new)


# --- Effective-tree assembly --------------------------------------------------

# Shared-registry dirs whose same-rooted full files the engine MERGES by entry
# (base + every DLC coexist). Asset files (assets/...) keep full-override semantics.
_ADDITIVE_DIRS = ("libraries/", "index/", "t/")


def _child_key(el: etree._Element) -> tuple[str, str] | None:
    """Dedupe key for a registry entry: (tag, id|name). None if neither attr."""
    for attr in ("id", "name"):
        v = el.get(attr)
        if v is not None:
            return (el.tag, f"{attr}={v}")
    return None


def _union_children(tree: etree._Element, overlay: etree._Element,
                    recorder: Recorder | None = None, source: str = "") -> None:
    """Merge *overlay*'s direct children into *tree* in place.

    Dedupe by _child_key with later-overlay-wins (same id/name -> overlay's element
    replaces the base's); keyless children (e.g. <defaults>, comments) are appended.
    Correct for BOTH additive registries (distinct ids coexist) and a same-vpath
    single-file override (same id/name -> replaced)."""
    index: dict[tuple[str, str], etree._Element] = {}
    for child in tree:
        if isinstance(child.tag, str):
            key = _child_key(child)
            if key is not None:
                index[key] = child
    for child in overlay:
        if not isinstance(child.tag, str):  # comments / PIs
            continue
        key = _child_key(child)
        new = copy.deepcopy(child)
        if key is not None and key in index:
            old = index[key]
            tree.replace(old, new)
            if recorder is not None:
                recorder.elem_replaced(old, new, Origin(source, "union-replace"))
        else:
            tree.append(new)
            if recorder is not None:
                recorder.elem_created(new, Origin(source, "union-add"))
        if key is not None:
            index[key] = new


def apply_overlay(
    tree: etree._Element | None,
    oroot: etree._Element,
    vpath: str,
    source: str,
    recorder: Recorder | None = None,
) -> tuple[etree._Element | None, str]:
    """Apply one overlay root onto *tree*; returns (new tree, mode).

    Mode is one of "diff", "diff(no-base!)", "union", "full" — mirrors the
    source-tag suffixes recorded by build_effective. Extracted so callers other
    than build_effective (e.g. x4effective's mod-owned-base path) reuse the exact
    dispatch semantics."""
    if oroot.tag == "diff":
        if tree is None:
            return None, "diff(no-base!)"  # diff with no base — cannot apply
        apply_diff(tree, oroot, recorder=recorder, source=source)
        return tree, "diff"
    if tree is not None and oroot.tag == tree.tag and vpath.startswith(_ADDITIVE_DIRS):
        _union_children(tree, oroot, recorder=recorder, source=source)
        return tree, "union"
    if recorder is not None:
        recorder.full_override(Origin(source, "full-override"))
    return oroot, "full"  # full-file override (asset files, or no/other base)


def _nested_target(vpath: str) -> tuple[str, str] | None:
    """'extensions/<target>/<rel>' -> ('<target>', '<rel>'); else None.

    This is the cross-mod patch idiom: the path is owned by <target>, not by the
    base game. `ego_dlc_*` is excluded — DLC live under reference/extensions/ and
    are already handled as ordinary base content.
    """
    parts = vpath.split("/")
    if len(parts) < 3 or parts[0].lower() != "extensions":
        return None
    if parts[1].lower().startswith("ego_dlc_"):
        return None
    return parts[1], "/".join(parts[2:])


def _build_owned(owner_name: str, rel: str, vpath: str,
                 overlay_dirs: list[Path],
                 recorder: Recorder | None) -> MergeResult:
    """Merge a file OWNED by another mod: that mod supplies the base at *rel*,
    every other mod patches it at the nested *vpath*."""
    sources: list[str] = []
    tree: etree._Element | None = None

    owner_dir = next((d for d in overlay_dirs if d.name.lower() == owner_name.lower()), None)
    if owner_dir is not None:
        oroot = overlay_root(owner_dir, rel)
        if oroot is not None and oroot.tag != "diff":
            tree = oroot
            sources.append(f"{owner_dir.name}:owner")

    for odir in overlay_dirs:
        if odir is owner_dir:
            continue
        oroot = overlay_root(odir, vpath)
        if oroot is None:
            continue
        tree, mode = apply_overlay(tree, oroot, vpath, odir.name, recorder=recorder)
        if recorder is not None and mode != "full":
            recorder.file_chain.append(Origin(odir.name, mode))
        sources.append(f"{odir.name}:{mode}")

    return MergeResult(tree=tree, sources=sources, base_found=tree is not None)


def build_effective(
    virtual_path: str,
    config: Config | None = None,
    extra_overlays: list[Path] | None = None,
    recorder: Recorder | None = None,
) -> MergeResult:
    """Build the effective tree for *virtual_path* = base + DLC + extra_overlays.

    *extra_overlays* are extension ROOT dirs (e.g. a mod under test, or Tier-B
    enabled mods) applied in the given order, after all DLC.
    """
    config = config or Config()
    vpath = virtual_path.replace("\\", "/").lstrip("/")
    sources: list[str] = []

    # DLC, then the Tier-B installed set (load order), then any explicit extras
    # (e.g. the mod under test) last.
    overlay_dirs = config.dlc_dirs() + list(config.overlays) + list(extra_overlays or [])

    # Cross-mod nesting: a file at  <mymod>/extensions/<target>/<rel>  patches
    # <target>'s OWN <rel>. The base therefore lives inside <target>, not in
    # reference/. Without this, every such patch reports "no base game file"
    # even though the engine applies it (proven: ship_variation_expansion_vro
    # patches ship_variation_expansion this way and its ops take effect).
    owner_rel = _nested_target(vpath)
    if owner_rel is not None:
        owner_name, rel = owner_rel
        return _build_owned(owner_name, rel, vpath, overlay_dirs, recorder)

    base_path = config.reference / vpath
    tree: etree._Element | None = None
    base_found = base_path.is_file()
    if base_found:
        tree = parse_file(base_path)
        sources.append("base")

    for odir in overlay_dirs:
        oroot = overlay_root(odir, vpath)
        if oroot is None:
            continue
        tree, mode = apply_overlay(tree, oroot, vpath, odir.name, recorder=recorder)
        if mode != "diff(no-base!)":
            base_found = base_found or mode in {"union", "full"}
        if recorder is not None and mode != "full":
            # full-override already appended to file_chain inside apply_overlay
            recorder.file_chain.append(Origin(odir.name, mode))
        sources.append(f"{odir.name}:{mode}")

    # Text files (t/0001.xml, t/0001-lNNN.xml) have no single base file in reference
    # — the engine overlays them onto the language tree. A mod's t-diff adds <page>s
    # to /language; synthesize an empty <language> root so /language-targeted ops
    # resolve (page/string collisions are covered separately by check_text).
    if tree is None and vpath.startswith("t/") and vpath.endswith(".xml"):
        tree = etree.Element("language")
        sources.append("synthetic:language")

    return MergeResult(tree=tree, sources=sources, base_found=base_found or tree is not None)
