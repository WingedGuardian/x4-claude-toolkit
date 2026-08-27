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

from x4validate import __version__, _diff, _input, _paths, _scan, _threeway
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
    p.add_argument("--base", action="append", default=[],
                   help="COMMON ANCESTOR of OLD and NEW: makes this a THREE-WAY "
                        "diff separating the author's edits from upstream drift "
                        "(repeatable, merged in order)")
    args = p.parse_args(argv)

    # Without this, a mistyped NEW path reports every file as "removed" — i.e.
    # "the new version deleted your whole mod" — with exit 0.
    _input.require_mod_dir(Path(args.old), "OLD (baseline) mod folder")
    _input.require_mod_dir(Path(args.new), "NEW mod folder")
    for o in args.overlay:
        _input.require_mod_dir(Path(o), "--overlay dir")

    if args.base:
        for b in args.base:
            _input.require_mod_dir(Path(b), "--base (common ancestor) dir")
        return _three_way(args)

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


def _three_way(args) -> int:
    """Render a three-way classification. OLD = archived, NEW = current."""
    base = [Path(b) for b in args.base]
    r = _threeway.three_way(base if len(base) > 1 else base[0],
                            Path(args.old), Path(args.new))

    print(f"# three-way  base={r.base}")
    print(f"#   archived={Path(r.archived).name}   current={Path(r.current).name}")
    # Denominator FIRST. The headline of the case this was built for was
    # "124 of 135 documents verbatim", and a bare change list hides exactly that.
    print(f"  documents shared with the baseline : {r.documents_compared}")
    print(f"    the author edited                : {len(r.author_edited_docs)}")
    print(f"    VERBATIM (author touched nothing): {r.verbatim}")
    print(f"  attributes classified              : {r.attributes_classified}")
    print(f"    author edits ....... {len(r.author_edits)}")
    print(f"    upstream drift ..... {len(r.upstream_drift)}")
    print(f"    converged .......... {len(r.converged)}   (both sides, same change)")
    print(f"    BOTH-MOVED ......... {len(r.both_moved)}   <-- the decisions")

    # A rewritten vpath is a transforming step and says so. Reported BEFORE the
    # exclusions, because it is what moves a document out of them.
    if r.unwrapped:
        print()
        print(f"  UNWRAPPED ({len(r.unwrapped)}): nested `extensions/<baseline>/` prefixes "
              f"removed so the overlay joins the mod it patches:")
        for u in r.unwrapped[:args.top]:
            print(f"    {u}")
        if len(r.unwrapped) > args.top:
            print(f"    ... {len(r.unwrapped) - args.top} more (raise --top)")
    if r.key_collisions:
        print()
        print(f"  KEY COLLISIONS ({len(r.key_collisions)}): two paths collapsed onto one "
              f"join key; the first was kept and the other NOT compared:")
        for c in r.key_collisions[:args.top]:
            print(f"    {c}")

    # Everything excluded from the verdict is NAMED. A silent exclusion is the
    # narrowing step this toolkit refuses.
    if r.no_base:
        print()
        print(f"  NO BASELINE ({len(r.no_base)}): in the archive, absent from the base "
              f"- direction UNKNOWABLE, excluded from every bucket above")
        for v in r.no_base[:args.top]:
            print(f"    {v}")
        if len(r.no_base) > args.top:
            print(f"    ... {len(r.no_base) - args.top} more (raise --top)")
    if r.dropped_by_author:
        print()
        print(f"  NOT IN THE ARCHIVE ({len(r.dropped_by_author)}): in the base, absent "
              f"from the archive - excluded, and NOT reported as upstream drift")
        for v in r.dropped_by_author[:args.top]:
            print(f"    {v}")
        if len(r.dropped_by_author) > args.top:
            print(f"    ... {len(r.dropped_by_author) - args.top} more (raise --top)")
    if r.unreadable:
        print()
        print(f"  NOT COMPARED ({len(r.unreadable)}) - absent from every section above, "
              f"and NOT counted as unchanged:")
        for v in r.unreadable[:args.top]:
            print(f"    {v}")
    if r.node_level:
        print()
        print(f"  node-level changes ({len(r.node_level)}) - reported, not classified:")
        for v in r.node_level[:args.top]:
            print(f"    {v}")

    want = (args.file or "").lower()

    def _keep(rows):
        return [c for c in rows if not want or c.vpath.lower() == want
                or c.vpath.lower().endswith("/" + want.lstrip("/"))]

    if want:
        print()
        print(f"  --file {args.file}: the counts above are the WHOLE comparison; "
              f"only the listings below are filtered")

    _bm = _keep(r.both_moved)
    if _bm:
        print()
        print("  BOTH-MOVED - both sides changed these, to different values:")
        for c in _bm:
            print(f"    {c.vpath}")
            print(f"      {c.node}@{c.attr}:  base {c.base}  ->  archived {c.archived}"
                  f"  |  upstream {c.current}")

    if args.detail:
        for title, allrows in (("author edits", r.author_edits),
                               ("upstream drift", r.upstream_drift),
                               ("converged", r.converged)):
            rows = _keep(allrows)
            if not rows:
                continue
            print()
            print(f"  {title} ({len(rows)}):")
            for c in rows[:args.top]:
                print(f"    {c.vpath}  {c.node}@{c.attr}: {c.base} -> {c.value}")
            if len(rows) > args.top:
                print(f"    ... {len(rows) - args.top} more (raise --top)")

    if want and not any(_keep(rows) for rows in
                        (r.both_moved, r.author_edits, r.upstream_drift, r.converged)):
        print()
        print(f"  --file {args.file}: no classified attribute in that document. "
              f"That is an ABSENCE only if the file is in the comparison - check the "
              f"exclusion lists above.")

    # Exit 1 when there is a decision to make, 0 when the port is mechanical.
    return 1 if _keep(r.both_moved) else 0
