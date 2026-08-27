"""x4diff CLI: argument parsing and rendering for :mod:`x4validate._diff`.

Split out of `_diff.py` for F69. `_diff.py` is an `ENGINE_SOURCE`, so the
freshness fingerprint hashes its BYTES -- which meant editing a help string or a
summary line invalidated the effective store and BaseX `x4eff` exactly as a
merge-semantics change would, while the stale banner asserted "the SAME inputs
would now merge differently". Nothing that only formats output belongs on that
side of the line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from x4validate import __version__, _diff, _input, _paths, _scan
from x4validate._diff import FileDiff, ModDiff, diff_mods


def _fmt_summary(md: ModDiff) -> str:
    ch, ad, rm = md.changed(), md.added(), md.removed()
    lines = [f"# diff  {Path(md.old).name}  ->  {Path(md.new).name}",
             f"  changed files: {len(ch)}   added: {len(ad)}   removed: {len(rm)}",
             f"  total attr changes: {sum(f.weight for f in ch)}"]
    if md.unreadable:
        lines.append(f"  NOT COMPARED: {len(md.unreadable)} file(s) — see the list below; "
                     "they are absent from every section, not 'unchanged'")
    return "\n".join(lines)


@_paths.refuses_unconfigured
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
