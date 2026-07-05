r"""x4xref: a cross-index of MD / aiscript actions, events, and cue edges.

Behavioral mod interactions (two mods reacting to the same event, one disabling an
engine feature another relies on) are invisible to a file/node collision check and
painful to trace by grep: the decisive tokens often share no keywords with the
concept (ATD suppresses ejection via ``set_emergency_eject_active`` +
``set_object_min_hull`` — neither contains "eject" or "death"). This index answers
the three questions that actually matter for interaction analysis in one lookup:

- ``who-calls <action>``  — every place an MD/aiscript action element appears
- ``who-listens <event>`` — every cue whose condition fires on an ``event_*``
- ``cue <name>``          — where a cue is defined, signalled, and cancelled

built over base + DLC + every installed mod (packed or loose). Structural containers,
control flow (``do_*``/``check_*``), and variable/debug plumbing are excluded so the
index stays about behavior, not bookkeeping.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from x4validate import _cat, _merge, _registry

# Excluded from the `action` index: structural containers, control flow, and
# variable/debug plumbing whose element TAG carries no behavioral meaning (the
# interesting part, if any, is an attribute we index separately or not at all).
_SKIP_TAGS = frozenset({
    "actions", "conditions", "cues", "library", "params", "param",
    "do_if", "do_else", "do_elseif", "do_all", "do_while", "do_for_each",
    "check_all", "check_any", "check_value", "check_age",
    "set_value", "remove_value", "append_to_list", "insert_in_list", "remove_from_list",
    "debug_text", "run_actions", "include_actions", "patch", "delay", "aiscript", "mdscript",
})
# Cue-edge actions: their `cue=` attribute names the target cue.
_CUE_EDGE_TAGS = frozenset({
    "signal_cue", "signal_cue_instantly", "cancel_cue", "reset_cue",
    "enable_cue", "disable_cue", "complete_cue",
})
_SCRIPT_DIRS = ("md/", "aiscripts/")


@dataclass(frozen=True)
class XrefRow:
    kind: str     # event | signal | cuedef | action
    name: str     # event tag / action tag / cue name
    source: str   # base | dlc:<name> | <mod folder>
    file: str     # virtual path
    cue: str      # enclosing cue (MD) or aiscript name
    line: int
    target: str = ""  # signal -> cue=; event -> object=/by= if present


def _walk(root: etree._Element, source: str, vpath: str, out: list[XrefRow]) -> None:
    """DFS the tree, emitting rows, carrying the nearest enclosing cue/script name."""
    script_name = root.get("name", "") if root.tag in ("mdscript", "aiscript") else ""

    def rec(el: etree._Element, cue: str) -> None:
        tag = el.tag
        if not isinstance(tag, str):
            return
        here_cue = cue
        if tag == "cue" and el.get("name"):
            here_cue = el.get("name")
            out.append(XrefRow("cuedef", here_cue, source, vpath, cue, el.sourceline or 0))
        elif tag.startswith("event_"):
            target = el.get("object") or el.get("by") or el.get("cue") or ""
            out.append(XrefRow("event", tag, source, vpath, cue, el.sourceline or 0, target))
        elif tag in _CUE_EDGE_TAGS:
            out.append(XrefRow("signal", tag, source, vpath, cue, el.sourceline or 0,
                               el.get("cue", "")))
        elif tag not in _SKIP_TAGS:
            out.append(XrefRow("action", tag, source, vpath, cue, el.sourceline or 0))
        for child in el:
            rec(child, here_cue)

    rec(root, script_name)


def _iter_source_files(base: Path, source: str):
    """Yield (vpath, parse_root) for md/ + aiscripts/ under a loose directory."""
    for sub in _SCRIPT_DIRS:
        d = base / sub.rstrip("/")
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.xml")):
            if not f.is_file():
                continue
            try:
                root = etree.parse(str(f), _merge._PARSER).getroot()
            except etree.XMLSyntaxError:
                continue
            yield f"{sub}{f.relative_to(d).as_posix()}", root


def _iter_mod_files(mod_dir: Path):
    """Yield (vpath, root) for a mod's md/aiscripts — packed (via _cat) and loose."""
    seen: set[str] = set()
    for f in sorted(mod_dir.rglob("*.xml")):
        if not f.is_file():
            continue
        vpath = f.relative_to(mod_dir).as_posix()
        if vpath.lower().startswith(_SCRIPT_DIRS):
            seen.add(vpath.lower())
            try:
                yield vpath, etree.parse(str(f), _merge._PARSER).getroot()
            except etree.XMLSyntaxError:
                continue
    for vpath, member in _cat.mod_vfs(mod_dir).items():
        if vpath.lower().startswith(_SCRIPT_DIRS) and vpath.lower() not in seen:
            try:
                yield vpath, _merge.parse_bytes(_cat.read_member(member))
            except etree.XMLSyntaxError:
                continue


def build_index(reference: Path, ext_dir: Path) -> list[XrefRow]:
    """Index base + DLC + every installed mod's MD/aiscripts."""
    rows: list[XrefRow] = []

    # Base game (reference root, excluding the DLC extensions subtree).
    for vpath, root in _iter_source_files(reference, "base"):
        _walk(root, "base", vpath, rows)
    # DLC.
    dlc_root = reference / "extensions"
    if dlc_root.is_dir():
        for dlc in sorted(p for p in dlc_root.iterdir()
                          if p.is_dir() and p.name.startswith("ego_dlc_")):
            for vpath, root in _iter_source_files(dlc, f"dlc:{dlc.name}"):
                _walk(root, f"dlc:{dlc.name}", vpath, rows)
    # Installed mods.
    if ext_dir.is_dir():
        for m in _registry.scan_installed([ext_dir]):
            for vpath, root in _iter_mod_files(Path(m["path"])):
                _walk(root, m["folder"], vpath, rows)
    return rows


# --- TSV persistence + queries ------------------------------------------------

_HEADER = ["kind", "name", "source", "file", "cue", "line", "target"]


def write_tsv(rows: list[XrefRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(_HEADER)
        for r in rows:
            w.writerow([r.kind, r.name, r.source, r.file, r.cue, r.line, r.target])
    return path


def read_tsv(path: Path) -> list[XrefRow]:
    rows: list[XrefRow] = []
    with open(path, encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)  # header
        for row in r:
            if len(row) == 7:
                rows.append(XrefRow(row[0], row[1], row[2], row[3], row[4],
                                    int(row[5] or 0), row[6]))
    return rows


def query(rows: list[XrefRow], kind: str, name: str) -> list[XrefRow]:
    name_l = name.lower()
    return [r for r in rows if r.kind == kind and r.name.lower() == name_l]


def cue_edges(rows: list[XrefRow], cue_name: str) -> dict[str, list[XrefRow]]:
    """All rows referencing a cue by short name (defs, signals, cancels).

    A ``cue="md.Script.Cue"`` reference is matched on its final ``.Cue`` segment,
    since signals within a script use the short name and cross-script refs qualify it.
    """
    short = cue_name.rsplit(".", 1)[-1].lower()
    out: dict[str, list[XrefRow]] = defaultdict(list)
    for r in rows:
        if r.kind == "cuedef" and r.name.lower() == short:
            out["defined"].append(r)
        elif r.kind == "signal" and r.target.rsplit(".", 1)[-1].lower() == short:
            out[r.name].append(r)
    return dict(out)


# --- CLI ----------------------------------------------------------------------

def _default_tsv() -> Path:
    return _registry.DEFAULT_REGISTRY.parent / "md_xref.tsv"


def _fmt(r: XrefRow) -> str:
    loc = f"{r.source}:{r.file}:{r.line}"
    ctx = f" (in cue {r.cue})" if r.cue else ""
    tgt = f" -> {r.target}" if r.target else ""
    return f"  {loc}{ctx}{tgt}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser(
        prog="x4xref",
        description="Cross-index of MD/aiscript actions, events, and cue edges.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build", help="(re)build the index over base+DLC+installed mods")
    pb.add_argument("--reference", help="unpacked base+DLC tree ($X4_REFERENCE)")
    pb.add_argument("--ext-dir", help="extensions dir (default: game-root from _registry)")
    pb.add_argument("--out", help="TSV output path (default: dev\\_registry\\md_xref.tsv)")

    for cmd, kind, help_ in [
        ("who-calls", "action", "list every place an action element appears"),
        ("who-listens", "event", "list every cue reacting to an event_* condition"),
    ]:
        q = sub.add_parser(cmd, help=help_)
        q.add_argument("name", help="the action/event name (e.g. set_object_min_hull)")
        q.add_argument("--tsv", help="index path (default: dev\\_registry\\md_xref.tsv)")
        q.add_argument("--limit", type=int, default=20,
                       help="max occurrences shown per source (0 = no cap)")
        q.set_defaults(_kind=kind)

    qc = sub.add_parser("cue", help="where a cue is defined, signalled, cancelled")
    qc.add_argument("name", help="cue name (short or md.Script.Cue)")
    qc.add_argument("--tsv")

    args = p.parse_args(argv)

    if args.cmd == "build":
        ref = Path(args.reference) if args.reference else _merge.Config().reference
        ext = Path(args.ext_dir) if args.ext_dir else _registry.GAME_EXTENSIONS
        out = Path(args.out) if args.out else _default_tsv()
        rows = build_index(ref, ext)
        write_tsv(rows, out)
        from collections import Counter
        by = Counter(r.kind for r in rows)
        print(f"indexed {len(rows)} rows -> {out}")
        print("  " + "  ".join(f"{k}={v}" for k, v in sorted(by.items())))
        return 0

    tsv = Path(args.tsv) if getattr(args, "tsv", None) else _default_tsv()
    if not tsv.is_file():
        print(f"index not found: {tsv}\nrun `x4xref build` first.", file=sys.stderr)
        return 2
    rows = read_tsv(tsv)

    if args.cmd == "cue":
        edges = cue_edges(rows, args.name)
        if not edges:
            print(f"no references to cue '{args.name}'")
            return 0
        for group in ("defined", *sorted(k for k in edges if k != "defined")):
            if group in edges:
                print(f"{group} ({len(edges[group])}):")
                for r in edges[group]:
                    print(_fmt(r))
        return 0

    hits = query(rows, args._kind, args.name)
    if not hits:
        print(f"no {args._kind} '{args.name}' found in the index.")
        return 0
    by_source: dict[str, list[XrefRow]] = defaultdict(list)
    for h in hits:
        by_source[h.source].append(h)
    print(f"{args._kind} '{args.name}': {len(hits)} occurrence(s) across "
          f"{len(by_source)} source(s)")
    cap = args.limit if args.limit and args.limit > 0 else None
    for src in sorted(by_source):
        group = by_source[src]
        print(f"[{src}]  ({len(group)})")
        for r in group[:cap] if cap else group:
            print(_fmt(r))
        if cap and len(group) > cap:
            print(f"  ... +{len(group) - cap} more (use --limit 0 to show all)")
    return 0
