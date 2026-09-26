r"""x4diff: semantic XML diff between two versions of a mod (pristine vs edited).

Isolates a user's personal edits from author content by comparing two mod trees
node/attribute-wise (not textually). Handles packed (cat/dat) and loose on either
side via _merge.overlay_root. Powers the personal-edit recovery: pristine -> edited
= your edit-set; edited -> newer-upstream = what the author has since changed.

Change model per common file: element identity = its tag-path with id/name/ref
disambiguation; report added / removed / changed attributes and added/removed nodes.

Element TEXT is compared too, as the reserved pseudo-attribute ``text()`` (an XML
attribute name cannot contain parentheses, so it can never collide with a real
one). ~48% of installed-mod ops carry their value in text --
``<replace sel=".../@min">999</replace>``, a t-file ``<t id="1">...</t>`` -- and
comparing attributes alone read a 5 -> 999 edit as "changed files: 0"
(AUDIT-2026-09-24 DF-1). Whitespace-only text (pretty-print indentation) is not
content and is not keyed; real text is compared with its leading/trailing
whitespace stripped, so re-indenting a document changes nothing while any change
to the words does. Non-whitespace TAIL text of child elements (mixed content)
is folded into the parent's value, so it is not silently outside the comparison.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _paths, _compat, _merge, _input, _scan
from x4validate import __version__


def mod_xml_vpaths(mod_dir: Path) -> dict[str, str]:
    """lower(vpath) -> real vpath for a mod's XML (packed + loose). content.xml dropped."""
    return _compat._mod_xml_paths(mod_dir)


def read_vpath(mod_dir: Path, vpath: str) -> etree._Element | None:
    try:
        return _merge.overlay_root(mod_dir, vpath)
    except etree.LxmlError:
        # silent-ok: None is this function's documented "could not read" sentinel
        # and every caller branches on it (diff_mods records it in
        # ModDiff.unreadable). Absent != unreadable is preserved by the caller.
        return None


def read_merged(dirs: list[Path], vpath: str,
                unreadable: list[str] | None = None) -> etree._Element | None:
    """Effective root for *vpath* after applying *dirs* in order (later wins).

    Lets the baseline be a stack (e.g. pristine core + pristine VRO submod), so a
    diff isolates ONLY the user's edits on top of the official merged content."""
    tree: etree._Element | None = None
    for d in dirs:
        try:
            oroot = _merge.overlay_root(d, vpath)
        except etree.LxmlError as exc:
            if unreadable is not None:
                unreadable.append(f"{d.name}/{vpath}: {exc}")
            continue
        if oroot is None:
            continue
        if tree is None:
            # The first layer that supplies the document IS the baseline, whatever
            # its shape. A `<diff>` here used to be discarded, so a stack whose
            # first supplier patches the file (the normal shape for a mod: its own
            # files are diffs against vanilla) returned None and the caller
            # reported "the OLD copy would not parse" about a well-formed file
            # (AUDIT-2026-09-24 DF-2). The single-layer path (`read_vpath`)
            # already compares a diff document as a diff document; this matches it.
            tree = oroot
        elif tree.tag == "diff":
            # No layer supplied a base document, so the baseline so far is a
            # PATCH SET. A further diff layer extends it -- ops apply in load
            # order, which is document order here -- and a full document from a
            # later layer supersedes the patches (there is no base in this stack
            # for them to have applied to).
            if oroot.tag == "diff":
                tree.extend(copy.deepcopy(op) for op in oroot)
            else:
                tree = oroot
        else:
            tree, _ = _merge.apply_overlay(tree, oroot, vpath, d.name)
    return tree


def merged_vpaths(dirs: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in dirs:
        out.update(mod_xml_vpaths(d))
    return out


#: Identity attributes, most-discriminating FIRST. `id` leads because it is what
#: X4 keys entities on; `name` came first before AUDIT-2026-09-24 DF-3, and
#: vanilla `wares.xml` carries 101 wares in 49 duplicated-name groups (name is
#: often a t-file reference like "{20201,301}"), so the positional suffix those
#: groups needed made ONE inserted ware shift the key of every untouched sibling
#: and read as phantom attribute edits. `sel` identifies a diff op.
_KEY_ATTRS = ("id", "name", "ref", "macro", "sel", "method", "ware", "class")

#: Reserved pseudo-attribute carrying an element's text (see the module docstring).
TEXT_ATTR = "text()"


def _node_key(el: etree._Element) -> str:
    """Stable identity: tag plus the first discriminating attribute present.

    Only an element with NONE of `_KEY_ATTRS` falls back to a positional key
    (assigned by `_index`), as do genuine duplicates of one key."""
    for a in _KEY_ATTRS:
        v = el.get(a)
        if v is not None:
            return f"{el.tag}[@{a}={v}]"
    return el.tag


def _text_value(el: etree._Element) -> str | None:
    """The element's own text content, pretty-print whitespace removed.

    Returns None when the element carries no non-whitespace text, so indentation
    never becomes a key. Child TAIL text (mixed content) is included, because a
    change there is a change to this element's content."""
    parts = [el.text] + [c.tail for c in el]
    kept = [t.strip() for t in parts if t is not None and t.strip()]
    return " ".join(kept) if kept else None


def _values(el: etree._Element) -> dict[str, str]:
    """Attributes plus the `text()` pseudo-attribute when the element has text."""
    out = dict(el.attrib)
    txt = _text_value(el)
    if txt is not None:
        out[TEXT_ATTR] = txt
    return out


def _index(root: etree._Element) -> dict[str, dict[str, str]]:
    """Canonical path -> {attr: value} for every element in the tree.

    The value map includes the `text()` pseudo-attribute. Sibling duplicates with
    identical keys get a positional suffix so they stay distinct."""
    out: dict[str, dict[str, str]] = {}

    def walk(el, prefix):
        counts: dict[str, int] = {}
        for child in el:
            if not isinstance(child.tag, str):
                continue
            key = _node_key(child)
            counts[key] = counts.get(key, -1) + 1
        seen: dict[str, int] = {}
        for child in el:
            if not isinstance(child.tag, str):
                continue
            key = _node_key(child)
            if counts[key] > 0:
                seen[key] = seen.get(key, -1) + 1
                key = f"{key}#{seen[key]}"
            path = f"{prefix}/{key}"
            out[path] = _values(child)
            walk(child, path)

    out["/" + _node_key(root)] = _values(root)
    walk(root, "/" + _node_key(root))
    return out


@dataclass
class FileDiff:
    vpath: str
    status: str                       # added | removed | changed
    #: (path, attr, old, new); attr may be the `text()` pseudo-attribute.
    attr_changes: list[tuple[str, str, str, str]] = field(default_factory=list)
    nodes_added: list[str] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return len(self.attr_changes) + len(self.nodes_added) + len(self.nodes_removed)


def diff_file(old: etree._Element, new: etree._Element, vpath: str) -> FileDiff:
    fd = FileDiff(vpath, "changed")
    oi, ni = _index(old), _index(new)
    for path in ni.keys() - oi.keys():
        fd.nodes_added.append(path)
    for path in oi.keys() - ni.keys():
        fd.nodes_removed.append(path)
    for path in oi.keys() & ni.keys():
        oa, na = oi[path], ni[path]
        for attr in oa.keys() | na.keys():
            ov, nv = oa.get(attr), na.get(attr)
            if ov != nv:
                fd.attr_changes.append((path, attr, ov if ov is not None else "∅",
                                        nv if nv is not None else "∅"))
    return fd


@dataclass
class ModDiff:
    old: str
    new: str
    files: list[FileDiff] = field(default_factory=list)
    #: vpaths present on BOTH sides that could not be compared because one side
    #: would not parse. Without this they fell out of `files` entirely and read
    #: as UNCHANGED — the one verdict a diff must never invent.
    unreadable: list[str] = field(default_factory=list)

    def changed(self):
        return [f for f in self.files if f.status == "changed" and f.weight]

    def added(self):
        return [f for f in self.files if f.status == "added"]

    def removed(self):
        return [f for f in self.files if f.status == "removed"]


def diff_mods(old_dirs: Path | list[Path], new_dir: Path,
              ignore_suffixes: tuple[str, ...] = (".xsd",)) -> ModDiff:
    """Diff *new_dir* against a baseline of one or more *old_dirs* (merged in order)."""
    old_list = [old_dirs] if isinstance(old_dirs, Path) else list(old_dirs)
    md = ModDiff(" + ".join(d.name for d in old_list), str(new_dir))
    ov, nv = merged_vpaths(old_list), mod_xml_vpaths(new_dir)
    drop = lambda low: low.endswith(ignore_suffixes)
    for low in nv.keys() - ov.keys():
        if not drop(low):
            md.files.append(FileDiff(nv[low], "added"))
    for low in ov.keys() - nv.keys():
        if not drop(low):
            md.files.append(FileDiff(ov[low], "removed"))
    for low in ov.keys() & nv.keys():
        if drop(low):
            continue
        o = (read_merged(old_list, ov[low], md.unreadable) if len(old_list) > 1
             else read_vpath(old_list[0], ov[low]))
        n = read_vpath(new_dir, nv[low])
        if o is None or n is None:
            side = "OLD" if o is None else "NEW"
            md.unreadable.append(f"{nv[low]}: the {side} copy would not parse — "
                                 "not compared, and NOT counted as unchanged")
            continue
        fd = diff_file(o, n, nv[low])
        if fd.weight:
            md.files.append(fd)
    return md
