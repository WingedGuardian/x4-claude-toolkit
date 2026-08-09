r"""x4diff: semantic XML diff between two versions of a mod (pristine vs edited).

Isolates a user's personal edits from author content by comparing two mod trees
node/attribute-wise (not textually). Handles packed (cat/dat) and loose on either
side via _merge.overlay_root. Powers the personal-edit recovery: pristine -> edited
= your edit-set; edited -> newer-upstream = what the author has since changed.

Change model per common file: element identity = its tag-path with id/name/ref
disambiguation; report added / removed / changed attributes and added/removed nodes.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _compat, _merge, _input, _scan
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
            tree = oroot if oroot.tag != "diff" else None
            if oroot.tag == "diff":
                continue
        else:
            tree, _ = _merge.apply_overlay(tree, oroot, vpath, d.name)
    return tree


def merged_vpaths(dirs: list[Path]) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in dirs:
        out.update(mod_xml_vpaths(d))
    return out


def _node_key(el: etree._Element) -> str:
    """Stable-ish identity: tag plus a disambiguating id/name/ref/macro attr."""
    for a in ("name", "id", "ref", "macro", "method", "ware", "class"):
        v = el.get(a)
        if v is not None:
            return f"{el.tag}[@{a}={v}]"
    return el.tag


def _index(root: etree._Element) -> dict[str, dict[str, str]]:
    """Canonical path -> {attr: value} for every element in the tree.

    Sibling duplicates with identical keys get a positional suffix so they stay
    distinct."""
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
            out[path] = dict(child.attrib)
            walk(child, path)

    out["/" + _node_key(root)] = dict(root.attrib)
    walk(root, "/" + _node_key(root))
    return out


@dataclass
class FileDiff:
    vpath: str
    status: str                       # added | removed | changed
    attr_changes: list[tuple[str, str, str, str]] = field(default_factory=list)  # path, attr, old, new
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


def _fmt_summary(md: ModDiff) -> str:
    ch, ad, rm = md.changed(), md.added(), md.removed()
    lines = [f"# diff  {Path(md.old).name}  ->  {Path(md.new).name}",
             f"  changed files: {len(ch)}   added: {len(ad)}   removed: {len(rm)}",
             f"  total attr changes: {sum(f.weight for f in ch)}"]
    if md.unreadable:
        lines.append(f"  NOT COMPARED: {len(md.unreadable)} file(s) — see the list below; "
                     "they are absent from every section, not 'unchanged'")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.
    p = argparse.ArgumentParser(prog="x4diff",
                                description="Semantic XML diff between two mod versions.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("old", help="pristine/older mod dir (baseline)")
    p.add_argument("new", help="edited/newer mod dir")
    p.add_argument("--overlay", action="append", default=[],
                   help="extra baseline dir merged onto OLD (repeatable; e.g. a VRO submod)")
    p.add_argument("--detail", action="store_true", help="list every attr change")
    p.add_argument("--file", help="detail one vpath only")
    p.add_argument("--top", type=int, default=30, help="show N heaviest changed files")
    args = p.parse_args(argv)

    # Without this, a mistyped NEW path reports every file as "removed" — i.e.
    # "the new version deleted your whole mod" — with exit 0.
    _input.require_mod_dir(Path(args.old), "OLD (baseline) mod folder")
    _input.require_mod_dir(Path(args.new), "NEW mod folder")
    for o in args.overlay:
        _input.require_mod_dir(Path(o), "--overlay dir")

    baseline = [Path(args.old)] + [Path(o) for o in args.overlay]
    md = diff_mods(baseline, Path(args.new))
    print(_fmt_summary(md))

    if args.file:
        fd = next((f for f in md.files if f.vpath.lower() == args.file.lower()), None)
        if fd is None:
            print(f"  {args.file}: no differences"); return 0
        _print_file(fd)
        return 0

    # Every one of these lists is truncated by --top. A bare list reads as
    # complete, and "removed files" reading as complete is the worst of the three
    # — it says the new version DELETED content it may simply not have listed.
    def _section(title: str, items: list, mark: str, detail: bool = False) -> None:
        shown = items[:args.top] if args.top else items
        print(f"\n## {title}: {_scan.count_line(len(shown), len(items), 'file(s)', '--top')}")
        for f in shown:
            suffix = f"  ({f.weight} changes)" if detail else ""
            print(f"  {mark} {f.vpath}{suffix}")
            if detail and args.detail:
                _print_file(f, indent="      ")

    _section("added files (present only in NEW)",
             sorted(md.added(), key=lambda x: x.vpath), "+")
    _section("removed files (present only in OLD)",
             sorted(md.removed(), key=lambda x: x.vpath), "-")
    _section("changed files (heaviest first)",
             sorted(md.changed(), key=lambda x: -x.weight), "~", detail=True)
    if md.unreadable:
        print(f"\n## NOT COMPARED ({len(md.unreadable)}):")
        for u in md.unreadable:
            print(f"  ? {u}")
    return 0


def _print_file(fd: FileDiff, indent: str = "  ") -> None:
    for path, attr, ov, nv in fd.attr_changes:
        print(f"{indent}{path} @{attr}: {ov} -> {nv}")
    for path in fd.nodes_added:
        print(f"{indent}+ {path}")
    for path in fd.nodes_removed:
        print(f"{indent}- {path}")


if __name__ == "__main__":
    raise SystemExit(main())
