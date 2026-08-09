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
from dataclasses import dataclass, field, replace
from pathlib import Path

from lxml import etree

from x4validate import _cat, _paths
from x4validate._provenance import Origin, Recorder

# --- Workspace defaults (overridable via Config / --reference / $X4_REFERENCE) ---
# Keep this injectable: no hardcoded user path should be the only way to point at
# the reference tree (community-release portability).
REFERENCE = _paths.reference() or Path("reference")
_PARSER = etree.XMLParser(remove_blank_text=False, recover=False, resolve_entities=False)


def _default_game_root() -> Path:
    """Where the LIVE game's DLC live, for DLC never unpacked into `reference/`.

    Delegates to `_paths`, which accepts the installer's `$X4_GAME` / `$X4_EXTENSIONS`,
    the legacy `$X4_GAME_ROOT` / `$X4_GAME_EXTENSIONS`, and `.claude/x4-paths.env`.
    Before that existed this read only the legacy names, so a user who configured the
    documented ones got packed-DLC support pointed at the wrong place — and it
    degrades quietly back to "cannot verify", which reads like the feature simply
    does not apply to them.

    Falls back to a non-existent relative path rather than raising: `dlc_dirs()`
    treats a missing game root as "no packed DLC", which is the honest answer when
    nothing is configured.
    """
    return _paths.game_root() or Path("x4-game-root-not-configured")


#: Read through `_cat`, never modified.
GAME_ROOT = _default_game_root()


@dataclass
class Config:
    reference: Path = REFERENCE
    #: Tier B — other INSTALLED extension roots to merge in after DLC, in load
    #: order. Empty (Tier A) = base+DLC only, which cannot see content that
    #: another mod adds, removes or overrides. Threaded automatically into every
    #: build_effective() call that receives this Config.
    overlays: tuple[Path, ...] = ()
    #: The RUNTIME tree: every installed extension, including those loading AFTER
    #: the mod under test. `overlays` is truncated at the mod's own position, which
    #: is right for `sel=` (a node a later mod adds is genuinely not there yet) and
    #: wrong for existence questions (does macro X resolve?), which the engine
    #: answers once everything has loaded. Empty = "same as `overlays`", so Tier A
    #: and every existing caller are unaffected. Use via `for_runtime()`.
    final_overlays: tuple[Path, ...] = ()
    #: Also treat DLC that exist only PACKED in the live game install as part of
    #: the Tier A reference tree. Set False for a hermetic, reference-only run.
    include_packed_dlc: bool = True

    def for_runtime(self) -> "Config":
        """This config with the runtime tree swapped in as `overlays`.

        Returns `self` unchanged when no separate runtime tree was supplied, so a
        Tier A run and any caller predating the split behave exactly as before.
        """
        if not self.final_overlays or self.final_overlays == self.overlays:
            return self
        return replace(self, overlays=self.final_overlays)

    def dlc_dirs(self) -> list[Path]:
        """Every DLC root, unpacked-in-reference first, then packed-in-game.

        `reference/` only holds the DLC that were actually unpacked. The two
        mini-DLC (`ego_dlc_mini_01` Hyperion Pack, `ego_dlc_mini_02` Envoy Pack)
        never were — so a patch targeting their content used to report
        "installed but never unpacked — cannot verify". No unpack is needed to
        fix that: `_cat` reads their archives directly (55 and 104 XML members),
        which is exactly how `tools\\basex\\stage.py` already indexes them.

        A packed DLC is included only when reference/ does NOT already have it,
        so an unpacked copy always wins and this can never double-count.

        The supplement applies ONLY to the configured workspace reference
        (`REFERENCE` / `$X4_REFERENCE`), because that is the one tree we know
        mirrors this game install. A caller who passes some other `--reference`
        is deliberately isolating, and grafting the live game's DLC onto their
        tree would inject content that is not part of what they asked about.
        """
        ext = self.reference / "extensions"
        # Deterministic order; inter-DLC order is order-independent in practice
        # (DLC diffs guard with if="not(...)").
        dirs = (sorted(p for p in ext.iterdir()
                       if p.is_dir() and p.name.startswith("ego_dlc_"))
                if ext.is_dir() else [])
        if not self.include_packed_dlc or self.reference != REFERENCE:
            return dirs
        have = {p.name.lower() for p in dirs}
        game_ext = GAME_ROOT / "extensions"
        if not game_ext.is_dir():
            return dirs
        packed = sorted(p for p in game_ext.iterdir()
                        if p.is_dir() and p.name.startswith("ego_dlc_")
                        and p.name.lower() not in have and _cat.is_packed(p))
        return dirs + packed

    def packed_dlc_names(self) -> set[str]:
        """Lowercased names of DLC that exist only PACKED, outside reference/.

        Their content is reached through the DLC's own root (like any packed
        mod), NOT as a plain path under the reference tree — so a vpath of
        `extensions/<name>/<rel>` has to be resolved as OWNED by <name>. Getting
        this wrong turns an honest "cannot verify" into a false
        "no base game file" on every mod that patches them (measured: 4 mods).
        """
        ext = self.reference / "extensions"
        return {p.name.lower() for p in self.dlc_dirs()
                if not (ext / p.name).is_dir()}


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
    # Did the base come from the GAME (reference/ or a DLC layer), as opposed to from
    # another mod? `base_found` deliberately cannot answer that: it degrades to
    # "somebody supplied a tree", so under Tier B an installed mod's full file makes it
    # True and a bare-path cross-mod patch — which the engine never loads at all — looks
    # perfectly well-founded. Keeping the distinction here rather than recomputing it in
    # callers keeps ONE definition of "the game has this file", including the synthetic
    # <language> root for t/*.xml (see build_effective).
    base_from_game: bool = False
    # Work NOT done: overlays that could not be parsed and were left out of the tree.
    # Without this channel a malformed overlay is indistinguishable from an absent
    # one, and the resulting tree looks complete when it is not.
    skipped: list[str] = field(default_factory=list)


def parse_file(path: Path) -> etree._Element:
    return etree.parse(str(path), _PARSER).getroot()


def parse_bytes(data: bytes) -> etree._Element:
    return etree.fromstring(data, _PARSER)


def overlay_root(odir: Path, vpath: str,
                 skipped: list[str] | None = None) -> etree._Element | None:
    """Resolve *vpath* within an overlay dir to a parsed root, or None if absent.

    Loose files take priority over the mod's packed catalog (they do in the engine
    too, and during development you edit loose). Falls back to reading the member
    from the mod's ext_*/subst_* catalogs so packed mods (e.g. VRO) are visible.

    A MALFORMED overlay file is recorded in *skipped* and treated as absent — it must
    be neither a crash nor a silent pass. Before 2026-07-26 the XMLSyntaxError escaped
    and killed the whole run: `cpsdo_faction/t/0001-l088.xml` has a mismatched tag, so
    validating `ship_variation_expansion_vro` (which touches the same vpath) died with
    a traceback. Exit code 1 made that indistinguishable from "found errors".
    Returning a bare None instead would be the opposite failure — a file the engine
    also refuses to load, silently counted as "nothing here".
    """
    loose = odir / vpath
    try:
        if loose.is_file():
            return parse_file(loose)
        data = _cat.read_path(odir, vpath)
        if data is not None:
            return parse_bytes(data)
    except etree.XMLSyntaxError as exc:
        if skipped is not None:
            skipped.append(f"{odir.name}/{vpath}: malformed XML, overlay skipped ({exc})")
        return None
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
        # Comments and processing instructions are legitimately not ops — skip
        # them silently. An ELEMENT that is not add/replace/remove is a different
        # thing: libraries/diff.xsd admits exactly those three and nothing else,
        # so <relace sel="..."> or <modify> is a schema violation the engine
        # ignores. Lumping both into one silent `continue` meant a typo'd op tag
        # vanished without a trace and the file still reported OK.
        if not isinstance(op.tag, str):
            continue
        if op.tag not in _OPS:
            applied.append(AppliedOp(op.tag, op.get("sel", ""), op.sourceline or 0, False,
                                     f"unknown op <{op.tag}> — diff.xsd allows only "
                                     f"{'/'.join(sorted(_OPS))}; the engine ignores it",
                                     _truthy(op.get("silent"))))
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
        # The helpers return a reason string when they could NOT apply the op, else
        # None. Deriving AppliedOp.ok from that (rather than hard-coding True) is
        # what keeps a silent no-op from being reported as success — the failure
        # class that hid 858 dropped ops behind "applied=True".
        if op.tag == "remove":
            reason = _do_remove(targets, recorder, origin)
        elif op.tag == "replace":
            reason = _do_replace(targets, op, recorder, origin)
        elif op.tag == "add":
            reason = _do_add(targets, op, recorder, origin)
        else:
            reason = None
        applied.append(AppliedOp(op.tag, sel, line, reason is None,
                                 reason or f"{len(targets)} target(s)", silent))
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


def _do_remove(targets, recorder: Recorder | None = None,
               origin: Origin | None = None) -> str | None:
    for t in targets:
        if recorder is not None:
            recorder.node_removed(_path_of(t), origin)
        parent = t.getparent()
        if parent is None:
            # No current mod does this, but a bare skip here would be the same
            # silent-no-op class as the root <replace> was. Report it instead.
            return ("remove targets the document root — a document cannot be "
                    "left without one")
        if _is_attr(t):
            parent.attrib.pop(t.attrname, None)
        else:
            parent.remove(t)
    return None


def _do_replace(targets, op, recorder: Recorder | None = None,
                origin: Origin | None = None) -> str | None:
    new_children = [c for c in op if isinstance(c.tag, str)]
    for t in targets:
        if _is_attr(t):
            parent = t.getparent()
            if parent is None:
                return "attribute target has no owning element"
            parent.set(t.attrname, op.text or "")
            if recorder is not None:
                recorder.attr_set(parent, t.attrname,
                                  Origin(origin.source, "replace-attr", origin.line))
        elif new_children:
            parent = t.getparent()
            if parent is None:
                # The target IS the document root. lxml cannot swap a root through
                # its parent, so mutate it in place — the ElementTree identity and
                # every caller's handle stay valid. The engine DOES apply these:
                # `<replace sel="//macros">` is the standard whole-file override
                # idiom (VRO alone ships 848 of them) and X4 logs no complaint,
                # while it does log every other patch failure. Before this, the op
                # was dropped with a bare `continue` yet still reported applied.
                if len(new_children) != 1:
                    return (f"replace on the document root needs exactly one payload "
                            f"element (a document has one root), got {len(new_children)}")
                nc = copy.deepcopy(new_children[0])
                tail = t.tail
                t.clear()
                t.tag = nc.tag
                t.text, t.tail = nc.text, tail
                for k, v in nc.attrib.items():
                    t.set(k, v)
                t.extend(list(nc))
                if recorder is not None:
                    # Semantically identical to a full-file override: all prior
                    # lineage is gone and this source becomes the default origin.
                    recorder.full_override(Origin(origin.source, "replace-root", origin.line))
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
    return None


def _do_add(targets, op, recorder: Recorder | None = None,
            origin: Origin | None = None) -> str | None:
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
            return "add type=\"@\" names no attribute"
        for t in targets:
            if _is_attr(t):
                return "cannot hang an attribute off an attribute"
            t.set(name, op.text or "")
            if recorder is not None and origin is not None:
                recorder.attr_set(t, name, Origin(origin.source, "add-attr", origin.line))
        return None

    for t in targets:
        if _is_attr(t):
            return "add cannot target an attribute"
        if pos == "prepend":
            for i, child in enumerate(new_children):
                new = copy.deepcopy(child)
                t.insert(i, new)
                _record(new)
        elif pos in {"before", "after"}:
            parent = t.getparent()
            if parent is None:
                return (f"add pos={pos!r} targets the document root, which has no "
                        "siblings")
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
    return None


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


def _nested_target(vpath: str, owned_dlc: set[str] | None = None) -> tuple[str, str] | None:
    """'extensions/<target>/<rel>' -> ('<target>', '<rel>'); else None.

    This is the cross-mod patch idiom: the path is owned by <target>, not by the
    base game. An UNPACKED `ego_dlc_*` is excluded — it lives under
    reference/extensions/ and is already ordinary base content.

    *owned_dlc* names the DLC that exist only packed in the live install (see
    `Config.packed_dlc_names`). Those have no reference/ copy, so their content
    has to be reached through their own root exactly like a packed mod's.
    """
    parts = vpath.split("/")
    if len(parts) < 3 or parts[0].lower() != "extensions":
        return None
    if parts[1].lower().startswith("ego_dlc_") and parts[1].lower() not in (owned_dlc or set()):
        return None
    return parts[1], "/".join(parts[2:])


def _build_owned(owner_name: str, rel: str, vpath: str,
                 overlay_dirs: list[Path],
                 recorder: Recorder | None,
                 owner_is_dlc: bool = False) -> MergeResult:
    """Merge a file OWNED by another mod: that mod supplies the base at *rel*,
    every other mod patches it at the nested *vpath*.

    *owner_is_dlc* marks a packed-only DLC owner, where a `<diff>` root IS the
    base. Every DLC ships `libraries/god.xml` as a diff, and for an UNPACKED DLC
    the ordinary reference-path branch already uses that diff as the base tree.
    Refusing it here purely because the DLC happens to be packed would make the
    same mod's same patch an ERROR for mini_01 and fine for split — a difference
    with no counterpart in the engine. (A third-party MOD's diff at *rel* is a
    different matter and still not a base: it is a patch, and the file it patches
    lives elsewhere.)"""
    sources: list[str] = []
    skipped: list[str] = []
    tree: etree._Element | None = None

    owner_dir = next((d for d in overlay_dirs if d.name.lower() == owner_name.lower()), None)
    if owner_dir is not None:
        oroot = overlay_root(owner_dir, rel, skipped)
        if oroot is not None and (owner_is_dlc or oroot.tag != "diff"):
            tree = oroot
            sources.append(f"{owner_dir.name}:owner")

    for odir in overlay_dirs:
        if odir is owner_dir:
            continue
        oroot = overlay_root(odir, vpath, skipped)
        if oroot is None:
            continue
        tree, mode = apply_overlay(tree, oroot, vpath, odir.name, recorder=recorder)
        if recorder is not None and mode != "full":
            recorder.file_chain.append(Origin(odir.name, mode))
        sources.append(f"{odir.name}:{mode}")

    # A nested patch's base legitimately comes from another MOD, so "from the game"
    # is only true for a packed-DLC owner. No caller keys the inert-bare-path check
    # off this branch (it requires a non-nested path), but leaving the field False
    # for a DLC owner would be a lie waiting for the next caller.
    return MergeResult(tree=tree, sources=sources, base_found=tree is not None,
                       base_from_game=owner_is_dlc and tree is not None,
                       skipped=skipped)


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
    skipped: list[str] = []

    # DLC, then the Tier-B installed set (load order), then any explicit extras
    # (e.g. the mod under test) last.
    dlc_layers = config.dlc_dirs()
    overlay_dirs = dlc_layers + list(config.overlays) + list(extra_overlays or [])

    # Cross-mod nesting: a file at  <mymod>/extensions/<target>/<rel>  patches
    # <target>'s OWN <rel>. The base therefore lives inside <target>, not in
    # reference/. Without this, every such patch reports "no base game file"
    # even though the engine applies it (proven: ship_variation_expansion_vro
    # patches ship_variation_expansion this way and its ops take effect).
    owner_rel = _nested_target(vpath, config.packed_dlc_names())
    if owner_rel is not None:
        owner_name, rel = owner_rel
        return _build_owned(owner_name, rel, vpath, overlay_dirs, recorder,
                            owner_is_dlc=owner_name.lower() in config.packed_dlc_names())

    base_path = config.reference / vpath
    tree: etree._Element | None = None
    base_found = base_path.is_file()
    # Which layers count as "the game has this file" — see MergeResult.base_from_game.
    game_dirs = {d.resolve() for d in dlc_layers}
    # The ENGINE always supplies a language tree at t/*.xml, so a diff there is
    # well-founded no matter who else ships the path — this keys off the PATH, never
    # off `tree is None`. Getting that wrong is not theoretical: the first cut set it
    # after the loop inside the tree-is-None branch, and any mod whose t/ file another
    # mod also ships (which fills `tree` first) was then reported as an inert
    # bare-path patch. 33 of the 101 installed mods ship a t/ diff — the single
    # largest false-positive class this distinction exists to avoid.
    is_text_file = vpath.startswith("t/") and vpath.endswith(".xml")
    from_game = base_found or is_text_file
    if base_found:
        tree = parse_file(base_path)
        sources.append("base")

    for odir in overlay_dirs:
        oroot = overlay_root(odir, vpath, skipped)
        if oroot is None:
            continue
        # The engine only loads a bare-path <diff> when the GAME supplies the file;
        # over another mod's file it never even opens it (proven from debug.txt's
        # per-file signature lines — same rel path, owner logged, nested patcher
        # logged with its op evaluated, bare-path patcher absent). Applying it
        # anyway put 14 attribute values in the effective tree that the engine
        # never sees. By this point `from_game` is FINAL for mod overlays:
        # reference/ and t/ are decided upfront and DLC layers always precede mods
        # in overlay_dirs, so the refusal is load-order-independent. DLC-shipped
        # diffs are exempt — the engine trusts its own content, and a DLC diff
        # with no base is already the diff(no-base!) case.
        if (oroot.tag == "diff" and not from_game
                and odir.resolve() not in game_dirs):
            sources.append(f"{odir.name}:diff(inert)")
            continue
        tree, mode = apply_overlay(tree, oroot, vpath, odir.name, recorder=recorder)
        if mode != "diff(no-base!)":
            base_found = base_found or mode in {"union", "full"}
            if mode in {"union", "full"} and odir.resolve() in game_dirs:
                from_game = True
        if recorder is not None and mode != "full":
            # full-override already appended to file_chain inside apply_overlay
            recorder.file_chain.append(Origin(odir.name, mode))
        sources.append(f"{odir.name}:{mode}")

    # Text files (t/0001.xml, t/0001-lNNN.xml) have no single base file in reference
    # — the engine overlays them onto the language tree. A mod's t-diff adds <page>s
    # to /language; synthesize an empty <language> root so /language-targeted ops
    # resolve (page/string collisions are covered separately by check_text).
    if tree is None and is_text_file:
        tree = etree.Element("language")
        sources.append("synthetic:language")

    return MergeResult(tree=tree, sources=sources,
                       base_found=base_found or tree is not None,
                       base_from_game=from_game, skipped=skipped)
