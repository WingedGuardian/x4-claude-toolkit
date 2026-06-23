"""Reproduce X4's *effective* XML for a virtual path: base + DLC (+ mods).

Per-overlay strategy is decided by the overlay's ROOT ELEMENT, not its folder:
  - root <diff>      -> apply add/replace/remove ops (honoring pos/if/silent)
  - any other root   -> full-file override (e.g. index/macros.xml, DLC t-files)
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# --- Workspace defaults (overridable via Config / --reference / $X4_REFERENCE) ---
# Keep this injectable: no hardcoded user path should be the only way to point at
# the reference tree (community-release portability).
REFERENCE = Path(os.environ.get(
    "X4_REFERENCE", "reference"))
_PARSER = etree.XMLParser(remove_blank_text=False, recover=False, resolve_entities=False)


@dataclass
class Config:
    reference: Path = REFERENCE

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


@dataclass
class MergeResult:
    tree: etree._Element | None
    sources: list[str] = field(default_factory=list)  # which overlays contributed
    base_found: bool = False


def parse_file(path: Path) -> etree._Element:
    return etree.parse(str(path), _PARSER).getroot()


def _truthy(val: str | None) -> bool:
    return str(val).lower() in {"true", "1", "yes"}


# --- Diff application ---------------------------------------------------------

_OPS = {"add", "replace", "remove"}


def apply_diff(tree: etree._Element, diff_root: etree._Element) -> list[AppliedOp]:
    """Apply every op in *diff_root* to *tree* in document order. Mutates tree."""
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

        if op.tag == "remove":
            _do_remove(targets)
        elif op.tag == "replace":
            _do_replace(targets, op)
        elif op.tag == "add":
            _do_add(targets, op)
        applied.append(AppliedOp(op.tag, sel, line, True, f"{len(targets)} target(s)", silent))
    return applied


def _is_attr(node) -> bool:
    return getattr(node, "is_attribute", False)


def _do_remove(targets) -> None:
    for t in targets:
        if _is_attr(t):
            parent = t.getparent()
            if parent is not None:
                parent.attrib.pop(t.attrname, None)
        else:
            parent = t.getparent()
            if parent is not None:
                parent.remove(t)


def _do_replace(targets, op) -> None:
    new_children = [c for c in op if isinstance(c.tag, str)]
    for t in targets:
        if _is_attr(t):
            parent = t.getparent()
            if parent is not None:
                parent.set(t.attrname, op.text or "")
        elif new_children:
            parent = t.getparent()
            if parent is None:
                continue
            idx = parent.index(t)
            parent.remove(t)
            for off, child in enumerate(new_children):
                parent.insert(idx + off, copy.deepcopy(child))
        else:
            # Replace element's inner text/content.
            t.text = op.text
            for c in list(t):
                t.remove(c)


def _do_add(targets, op) -> None:
    pos = op.get("pos", "")
    new_children = [c for c in op if isinstance(c.tag, str)]
    for t in targets:
        if _is_attr(t):
            continue  # add cannot target an attribute
        if pos == "prepend":
            for i, child in enumerate(new_children):
                t.insert(i, copy.deepcopy(child))
        elif pos in {"before", "after"}:
            parent = t.getparent()
            if parent is None:
                continue
            idx = parent.index(t) + (1 if pos == "after" else 0)
            for off, child in enumerate(new_children):
                parent.insert(idx + off, copy.deepcopy(child))
        else:  # append (default)
            for child in new_children:
                t.append(copy.deepcopy(child))


# --- Effective-tree assembly --------------------------------------------------


def build_effective(
    virtual_path: str,
    config: Config | None = None,
    extra_overlays: list[Path] | None = None,
) -> MergeResult:
    """Build the effective tree for *virtual_path* = base + DLC + extra_overlays.

    *extra_overlays* are extension ROOT dirs (e.g. a mod under test, or Tier-B
    enabled mods) applied in the given order, after all DLC.
    """
    config = config or Config()
    vpath = virtual_path.replace("\\", "/").lstrip("/")
    sources: list[str] = []

    base_path = config.reference / vpath
    tree: etree._Element | None = None
    base_found = base_path.is_file()
    if base_found:
        tree = parse_file(base_path)
        sources.append("base")

    overlay_dirs = config.dlc_dirs() + list(extra_overlays or [])
    for odir in overlay_dirs:
        f = odir / vpath
        if not f.is_file():
            continue
        oroot = parse_file(f)
        if oroot.tag == "diff":
            if tree is None:
                # Diff with no base — record but cannot apply.
                sources.append(f"{odir.name}:diff(no-base!)")
                continue
            apply_diff(tree, oroot)
            sources.append(f"{odir.name}:diff")
        else:
            tree = oroot  # full-file override
            base_found = True
            sources.append(f"{odir.name}:full")

    return MergeResult(tree=tree, sources=sources, base_found=base_found or tree is not None)
