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

from x4validate import _cat, _merge, _registry, _scan
from x4validate import __version__

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


def _iter_source_files(base: Path, source: str, unreadable: list | None = None):
    """Yield (vpath, parse_root) for md/ + aiscripts/ under a loose directory.

    `under()` narrows the walk to those two subtrees, so pointing this at the
    reference root does not rglob the whole ~13k-file base game.
    """
    yield from _scan.iter_mod_xml(base, _scan.under(*_SCRIPT_DIRS), unreadable)


def _iter_mod_files(mod_dir: Path, unreadable: list | None = None):
    """Yield (vpath, root) for a mod's md/aiscripts — packed (via _cat) and loose."""
    yield from _scan.iter_mod_xml(mod_dir, _scan.under(*_SCRIPT_DIRS), unreadable)


def build_index(reference: Path, ext_dir: Path,
                unreadable: list | None = None) -> list[XrefRow]:
    """Index base + DLC + every installed mod's MD/aiscripts.

    *unreadable* collects files that would not parse. An index is the
    denominator behind every "nobody references X" answer this tool gives, so a
    file silently missing from it turns a negative into a guess.
    """
    rows: list[XrefRow] = []

    # Base game (reference root, excluding the DLC extensions subtree).
    for vpath, root in _iter_source_files(reference, "base", unreadable):
        _walk(root, "base", vpath, rows)
    # DLC.
    dlc_root = reference / "extensions"
    if dlc_root.is_dir():
        for dlc in sorted(p for p in dlc_root.iterdir()
                          if p.is_dir() and p.name.startswith("ego_dlc_")):
            for vpath, root in _iter_source_files(dlc, f"dlc:{dlc.name}", unreadable):
                _walk(root, f"dlc:{dlc.name}", vpath, rows)
    # Installed mods.
    if ext_dir.is_dir():
        for m in _registry.scan_installed([ext_dir]):
            for vpath, root in _iter_mod_files(Path(m["path"]), unreadable):
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
    return _registry.require(
        _registry.DEFAULT_REGISTRY, "the registry location",
        "set X4_MODS (or X4_REGISTRY), or pass --out/--index").parent / "md_xref.tsv"


def _fmt(r: XrefRow) -> str:
    loc = f"{r.source}:{r.file}:{r.line}"
    ctx = f" (in cue {r.cue})" if r.cue else ""
    tgt = f" -> {r.target}" if r.target else ""
    return f"  {loc}{ctx}{tgt}"


_KIND_CMD = {"action": "who-calls", "event": "who-listens", "cuedef": "cue", "signal": "cue"}


def _sidecar(tsv: Path) -> Path:
    """Where an index records the files it could NOT read."""
    return tsv.with_suffix(tsv.suffix + ".notindexed")


def _exclusions(tsv: Path | None) -> str:
    """Render the index's own exclusions, so a negative carries its denominator.

    "0 hits" is a lead; "0 hits over N rows with M named exclusions" is a
    finding. Same contract as `tools\\basex\\ask.py`, which refuses to render a
    zero-result without coverage. A negative that hides its blind spots is the
    most confidently wrong answer this tool can give.
    """
    if tsv is None or not _sidecar(tsv).is_file():
        return ""
    lines = [ln for ln in _sidecar(tsv).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return ""
    return (f" — EXCEPT {len(lines)} file(s) that would not parse and are not in the "
            f"index at all (see {_sidecar(tsv).name})")


def _hint_other_kinds(rows: list[XrefRow], name: str, asked_kind: str,
                      tsv: Path | None = None) -> None:
    """When a name isn't found in the asked-for kind, say whether it exists at all.

    `who-calls event_player_ejected` used to print exactly the same line as
    `who-calls definitely_not_a_real_thing` — yet the first name is in the index
    5 times as an EVENT. Two completely different states, one message, exit 0.
    (That was also the example CLAUDE.md advertises for this tool.) A name that
    exists under another kind is a wrong-command mistake; a name that exists
    nowhere is a real negative. They must never read the same.
    """
    from collections import Counter
    elsewhere = Counter(r.kind for r in rows if r.name == name and r.kind != asked_kind)
    if not elsewhere:
        print(f"  and '{name}' does not appear under ANY kind — "
              f"a real negative over {len(rows)} indexed rows{_exclusions(tsv)}.")
        return
    print(f"  BUT '{name}' IS in the index under other kind(s):")
    for kind, n in elsewhere.most_common():
        cmd = _KIND_CMD.get(kind)
        suffix = f"   -> try:  x4xref {cmd} {name}" if cmd else ""
        print(f"    {kind:8} {n:>5} occurrence(s){suffix}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.

    p = argparse.ArgumentParser(
        prog="x4xref",
        description="Cross-index of MD/aiscript actions, events, and cue edges.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
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
        ext = Path(args.ext_dir) if args.ext_dir else _registry.require(
        _registry.GAME_EXTENSIONS, "the game extensions dir",
        "set X4_GAME (or X4_EXTENSIONS), or pass --ext-dir")
        out = Path(args.out) if args.out else _default_tsv()
        unreadable: list = []
        rows = build_index(ref, ext, unreadable)
        write_tsv(rows, out)
        from collections import Counter
        by = Counter(r.kind for r in rows)
        print(f"indexed {len(rows)} rows -> {out}")
        print("  " + "  ".join(f"{k}={v}" for k, v in sorted(by.items())))
        if unreadable:
            # The index is the denominator behind every negative answer below.
            # A file missing from it must be named, not quietly absent.
            print(f"\n  NOT INDEXED — {len(unreadable)} file(s) would not parse; "
                  "any 'no references' answer excludes them:", file=sys.stderr)
            for u in unreadable:
                print(f"   - {u}", file=sys.stderr)
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
            _hint_other_kinds(rows, args.name, "cue", tsv)
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
        _hint_other_kinds(rows, args.name, args._kind, tsv)
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
