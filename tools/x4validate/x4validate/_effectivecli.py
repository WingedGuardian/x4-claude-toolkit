"""x4effective CLI: argument parsing and rendering for :mod:`x4validate._effective`.

Split out of `_effective.py` for F69. `_effective.py` is an `ENGINE_SOURCE`, so
the freshness fingerprint hashes its BYTES. That meant editing an error message
invalidated the effective store AND BaseX `x4eff` exactly as a merge-semantics
change would, while the stale banner asserted *"the SAME inputs would now merge
differently"*. MEASURED 2026-08-27: two edits in one session moved the hash, the
second a pure DOCSTRING (10 lines added, 0 executable).

The population is what was wrong, not the hash. Making the hash cleverer -- an
AST or token-level digest -- would move it to the UNSAFE side, where one missed
merge change reintroduces the 2026-08-13 defect that recorded vanilla engine
values as VRO's (140 of 194 rows, 72%). Nothing here can change a merged value.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from lxml import etree

from x4validate import __version__, _effective, _merge, _paths, _registry
from x4validate._provenance import Recorder
from x4validate._effective import (
    BUILDABLE_KINDS,
    LIBRARY_REGISTRIES,
    _ADVISORY,
    _connect,
    _count_line,
    active_mods,
    build,
    build_touch_map,
    effective_db,
    ordered_overlays,
    store_freshness,
    touchers_for,
)


def _winner_not_origin_note(vpath: str, chain_json: str | None, cfg=None) -> str | None:
    """Disclaimer for a chain that shows a WINNER and reads like an ORIGIN (F64).

    A root ``<replace sel="//macros">`` swaps the whole document, so base
    contributes NO chain entry -- and that is VRO's dominant idiom (848
    root-replaces, CLAUDE.md #10). A single-entry chain therefore reads as
    "this mod introduced this" when it usually means "this mod re-supplied what
    vanilla already had".

    PEER-MEASURED: of 35,423 single-op root-replace attributes, 23,182 (65.4%)
    also exist in vanilla with the chain hiding it; only 39 vpaths are genuinely
    mod-added. `bullet_arg_m_ion_01_mk1_macro` is the sharpest case -- vanilla 10,
    live 10, chain ``[vro]``: identical value, sole credit, no hint a base file
    exists. It cost a real design conclusion ("VRO added Kha'ak shield
    disruption" -- false).

    SCOPE IS EXISTENCE, NOT THE VANILLA VALUE, on purpose. Reporting the value
    would mean re-deriving the property flatten, and a second implementation of a
    normaliser is exactly what made an independent check of this very defect
    report 2.6% where the answer was 65.4%. `base_has` answers existence, handles
    the DLC-prefix trap, and is not a second door.

    Returns None -- deliberately silent -- when there is nothing to disclaim:
    a pure-base value, a chain that already names base, or a vpath base+DLC do
    not ship (those 39 are genuinely mod-added and must not be slandered as
    re-supplies). A note that fires on the common case trains you to ignore it.
    """
    if not vpath or not chain_json:
        return None
    try:
        chain = json.loads(chain_json)
    except (ValueError, TypeError):  # silent-ok: a malformed chain is a STORE defect,
        # surfaced by the build and by claims_audit; this is an advisory annotation and
        # must not invent a second error channel for it.
        return None
    if len(chain) != 1 or not chain[0] or chain[0][0] == "base":
        return None
    try:
        cfg = cfg if cfg is not None else _merge.Config()
        if not _effective.base_has(cfg, vpath):
            return None
    except Exception:  # silent-ok: no resolvable reference tree means the question
        # 'does base ship this?' is UNANSWERABLE here, and an absent advisory note is a
        # non-answer while a wrong one would be a false claim. The caller's real output
        # (the chain itself) is unaffected, so there is no work silently not done.
        return None
    return (f"    (base+DLC ALSO supply {vpath} -- this chain shows which source "
            f"WON, not which introduced the value)")


def _fmt_chain(chain_json: str | None) -> str:
    if not chain_json:
        return "base"
    return " → ".join(f"{s} {op}" + (f":{ln}" if ln else "")
                      for s, op, ln in json.loads(chain_json))


# --- CLI ----------------------------------------------------------------------

@_paths.refuses_unconfigured
def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.
    p = argparse.ArgumentParser(
        prog="x4effective",
        description="Browse the effective merged values of every X4 entity, with provenance.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("--db", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="(re)build the effective store")
    b.add_argument("--reference", default=str(_merge.REFERENCE))
    # Derived, never re-typed: this default was a hardcoded "ware,macro,job" and
    # adding a kind to BUILDABLE_KINDS silently did not build it. Two sources of
    # truth for one list is the same defect class as five copies of the DLC walk.
    b.add_argument("--kinds", default=",".join(BUILDABLE_KINDS))

    lsp = sub.add_parser("ls", help="list entities of a kind")
    lsp.add_argument("kind")
    lsp.add_argument("--class", dest="klass", default=None)
    lsp.add_argument("--filter", default=None, help="substring match on name")
    lsp.add_argument("--modified-only", action="store_true")
    lsp.add_argument("--limit", type=int, default=200)

    sh = sub.add_parser("show", help="all props + provenance for one entity")
    sh.add_argument("kind")
    sh.add_argument("name")

    at = sub.add_parser("attr", help="one prop across all entities of a class")
    at.add_argument("kind")
    at.add_argument("prop")
    at.add_argument("--class", dest="klass", default=None)
    at.add_argument("--sort", choices=["num", "name"], default="name")
    at.add_argument("--limit", type=int, default=200)

    ws = sub.add_parser("who-sets", help="provenance chain for an entity['s prop]")
    ws.add_argument("kind")
    ws.add_argument("name")
    ws.add_argument("prop", nargs="?")

    dm = sub.add_parser("diff-mod", help="every value a mod wins")
    dm.add_argument("folder")
    dm.add_argument("--limit", type=int, default=500)

    du = sub.add_parser("dump", help="live effective XML for ANY vpath (incl. md/, aiscripts/)")
    du.add_argument("vpath")
    du.add_argument("--reference", default=str(_merge.REFERENCE))
    du.add_argument("--chain", action="store_true", help="also print the file-level source chain")

    sq = sub.add_parser("sql", help="read-only SELECT against the store")
    sq.add_argument("query")

    sub.add_parser("coverage", help="what this store DOES and does not index "
                                    "(so a negative can carry its denominator)")

    args = p.parse_args(argv)
    db = Path(args.db) if args.db else _registry.require(
        effective_db(), "the effective-store location",
        "set X4_EFFECTIVE_DB or X4_MODS (or X4_REGISTRY), or pass --db")

    if args.cmd == "build":
        cfg = _merge.Config(reference=Path(args.reference))
        kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())
        try:
            build(cfg, db, kinds=kinds, progress=lambda s: print(f"  {s}", file=sys.stderr))
        except (ValueError, OSError) as exc:
            # A bad --kinds and a lost install race are both ordinary operator
            # errors with an actionable message; a traceback would bury it.
            print(f"x4effective build: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "dump":
        return _cmd_dump(args)

    con = _connect(db)
    # Printed on EVERY read command until the store is rebuilt. A stale store is
    # not an absence and not a non-answer -- it is an answer about a world that
    # has moved on, and these are the commands a modlist decision leans on.
    _stale = store_freshness(con)
    if not _stale.fresh:
        print(_stale.banner("the effective store"), file=sys.stderr)
        print("!! Rebuild:  uv run x4effective build", file=sys.stderr)

    if args.cmd == "ls":
        return _cmd_ls(con, args)
    if args.cmd == "show":
        return _cmd_show(con, args)
    if args.cmd == "attr":
        return _cmd_attr(con, args)
    if args.cmd == "who-sets":
        return _cmd_who_sets(con, args)
    if args.cmd == "diff-mod":
        return _cmd_diff_mod(con, args)
    if args.cmd == "sql":
        return _cmd_sql(con, args)
    if args.cmd == "coverage":
        return _cmd_coverage(con, args)
    return 2


def _known_kinds(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT kind FROM entities ORDER BY kind").fetchall()]


def _reject_unknown_kind(con, kind: str) -> bool:
    """True (and prints) if *kind* is not a stored kind.

    Without this an unknown kind reads as a confident empty answer: `ls ship`
    printed "0 ship(s)" — which looks like "this game has no ships" rather than
    "there is no such kind". Same false-negative shape as a validator reporting OK
    because it examined nothing.

    ⚠ The hint below is for a PARTIAL build. A full build now stores kind='ship'
    (MEASURED 2026-08-27: 514 entities), plus 'station' and 'module', so for those
    three this branch is unreachable — but `--kinds` can build a subset, which is
    exactly when the hint earns its place, so it stays. What had rotted was this
    docstring's claim that ships are stored ONLY as kind='macro': a ship's balance
    props do live on kind='macro' (hull.max: 1,973 values there, 0 on kind='ship'),
    but the kind itself exists, so the guard passes the name through and the
    unknown-PROP guard is what has to catch it.
    """
    kinds = _known_kinds(con)
    if kind in kinds:
        return False
    print(f"unknown kind {kind!r} — stored kinds are: {', '.join(kinds) or '(store is empty; run build)'}",
          file=sys.stderr)
    if kind in {"ship", "engine", "shield", "turret", "weapon", "station", "module"}:
        print(f"       ships/equipment are stored as kind 'macro' "
              f"(try: ls macro --filter {kind}) and as kind 'ware'", file=sys.stderr)
    return True


def _reject_unknown_prop(con, kind: str, prop: str) -> bool:
    """True (and prints) if no entity of *kind* carries *prop*.

    The companion to _reject_unknown_kind, and it was missing from the one command
    that needed it most. `attr` printed "0 value(s) for properties.hull.max" and
    exited 0 -- a confident zero over a key that cannot exist, which reads as "no
    mod sets this" rather than "you spelled it the way the store does not".

    The predictable wrong guess is the <properties> wrapper: for MACRO entities the
    store strips it (`hull.max`), because emitting both was F9. A parallel session
    hand-rolled a flatten that kept it, matched only the keys living OUTSIDE
    <properties>, and reported 2.6% where the truth was 65.4% -- plausible and
    self-consistent, so nothing looked wrong.

    The strip is NOT universal: MEASURED 6,842 rows keep a `properties.` prefix,
    all of them kind='mapdataset' (`properties.area.sunlight`), with 0 duplicate
    pairs. So the suggestion is looked up IN THE STORE rather than derived from a
    rule -- a blanket strip would be wrong for every one of those rows.
    """
    hit = con.execute("SELECT COUNT(*) FROM attrs a JOIN entities e ON e.id=a.entity_id "
                      "WHERE e.kind=? AND a.prop=?", (kind, prop)).fetchone()[0]
    if hit:
        return False
    total = con.execute("SELECT COUNT(DISTINCT a.prop) FROM attrs a "
                        "JOIN entities e ON e.id=a.entity_id WHERE e.kind=?",
                        (kind,)).fetchone()[0]
    print(f"no {kind} carries prop {prop!r} - that kind has {total} distinct prop(s)",
          file=sys.stderr)
    for alt in _prop_suggestions(con, kind, prop):
        n = con.execute("SELECT COUNT(*) FROM attrs a JOIN entities e ON e.id=a.entity_id "
                        "WHERE e.kind=? AND a.prop=?", (kind, alt)).fetchone()[0]
        print(f"       did you mean {alt!r}? ({n} value(s))", file=sys.stderr)
    # A prop can be real and the KIND can be real while the pair matches nothing:
    # `attr ship hull.max` is 0 rows because hull.max is a macro prop. Rejecting
    # without saying where it DOES live leaves the caller as stuck as the zero did.
    elsewhere = con.execute(
        "SELECT e.kind, COUNT(*) FROM attrs a JOIN entities e ON e.id=a.entity_id "
        "WHERE a.prop=? AND e.kind != ? GROUP BY e.kind ORDER BY 2 DESC LIMIT 3",
        (prop, kind)).fetchall()
    for row in elsewhere:
        print(f"       {prop!r} is carried by kind {row[0]!r} ({row[1]} value(s))",
              file=sys.stderr)
    return True


def _prop_suggestions(con, kind: str, prop: str, limit: int = 3) -> list[str]:
    """Stored props for *kind* a caller plausibly meant. Store-derived, never a rule."""
    out: list[str] = []
    cand = (prop[len("properties."):] if prop.startswith("properties.")
            else "properties." + prop)
    r = con.execute("SELECT 1 FROM attrs a JOIN entities e ON e.id=a.entity_id "
                    "WHERE e.kind=? AND a.prop=? LIMIT 1", (kind, cand)).fetchone()
    if r is not None:
        out.append(cand)
    # last-segment match catches the other half of the guesses (`max` for `hull.max`)
    tail = prop.rsplit(".", 1)[-1]
    for (p,) in con.execute(
            "SELECT DISTINCT a.prop FROM attrs a JOIN entities e ON e.id=a.entity_id "
            "WHERE e.kind=? AND (a.prop = ? OR a.prop LIKE ?) ORDER BY a.prop LIMIT ?",
            (kind, tail, "%." + tail, limit)):
        if p not in out:
            out.append(p)
    return out[:limit]


def _cmd_ls(con, args) -> int:
    if _reject_unknown_kind(con, args.kind):
        return 2
    q = "SELECT name, klass, origin, chain FROM entities WHERE kind=?"
    params: list = [args.kind]
    if args.klass:
        q += " AND klass=?"
        params.append(args.klass)
    if args.filter:
        q += " AND name LIKE ?"
        params.append(f"%{args.filter}%")
    if args.modified_only:
        q += " AND chain IS NOT NULL"
    total = con.execute(q.replace("SELECT name, klass, origin, chain", "SELECT count(*)"),
                        params).fetchone()[0]
    q += " ORDER BY name LIMIT ?"
    params.append(args.limit)
    rows = con.execute(q, params).fetchall()
    for r in rows:
        mod = "" if r["chain"] is None else f"  ← {r['origin']}"
        print(f"{r['name']:<44} {r['klass']:<16}{mod}")
    print(f"\n{_count_line(len(rows), total, f'{args.kind}(s)')}  ·  {_ADVISORY}")
    return 0


def scope_note() -> str:
    """What this store DOES and does NOT index, in one line.

    A query that misses must never read like "no mod changes this". MEASURED
    2026-08-12: 3,349 of 7,995 corpus macros are outside the store -- the galaxy
    map (~1,371: zones, sectors, clusters, highways) and characters/npc (~1,810)
    -- while balance-relevant classes are 99.0% covered. Neither number is
    guessable from a bare "not found".
    """
    return (f"scope: {len(LIBRARY_REGISTRIES)} registry kinds from libraries/*.xml "
            f"({', '.join(sorted(LIBRARY_REGISTRIES))}), plus macro and component "
            f"per-file from assets/**. "
            f"NOT indexed: galaxy-map macros (zone/sector/cluster/highway); character & npc "
            f"MACROS (distinct from the `character` registry, which IS indexed); the structured "
            f"library documents god/parameters/loadoutrules/camerasettings; a component's "
            f"geometry (source/layers — indexing it measured 148x the whole store); and Lua "
            f"(never analysed by any tool). "
            f"See docs/BLIND-SPOTS.md for the measured denominators.")


def _cmd_coverage(con, args) -> int:
    """Answer 'what can this tool NOT see?' as a command, not as archaeology.

    Mirrors BaseX's coverage-<db>.json: the point is that scope is queryable, so a
    negative can carry its denominator instead of being taken on trust.
    """
    meta = dict(con.execute("SELECT key, value FROM meta"))
    print("x4effective coverage")
    print(f"  store           : {meta.get('active_mods', '?')} active mods indexed")
    ents = con.execute("SELECT kind, count(*) FROM entities GROUP BY kind ORDER BY 2 DESC").fetchall()
    total = sum(r[1] for r in ents)
    print(f"  entities        : {total}")
    for kind, n in ents:
        print(f"      {kind:<12} {n}")
    print(f"  attributes      : "
          f"{con.execute('SELECT count(*) FROM attrs').fetchone()[0]}")
    origins = con.execute("SELECT count(DISTINCT origin) FROM entities").fetchone()[0]
    print(f"  distinct origins: {origins}")
    print()
    print(f"  {scope_note()}")
    return 0


def _cmd_show(con, args) -> int:
    ent = con.execute("SELECT * FROM entities WHERE kind=? AND name=?",
                      (args.kind, args.name)).fetchone()
    if ent is None:
        if _reject_unknown_kind(con, args.kind):
            return 2
        print(f"no {args.kind} named {args.name!r} in the store — this is NOT proof "
              f"that nothing defines or changes it.", file=sys.stderr)
        print(f"  {scope_note()}", file=sys.stderr)
        return 1
    print(f"{args.kind} {ent['name']}  (class={ent['klass']})  vpath={ent['vpath']}")
    print(f"  entity origin: {_fmt_chain(ent['chain'])}")
    rows = con.execute(
        "SELECT prop, value, origin, chain FROM attrs WHERE entity_id=? ORDER BY prop",
        (ent["id"],)).fetchall()
    for r in rows:
        prov = "" if r["chain"] is None else f"   [{_fmt_chain(r['chain'])}]"
        print(f"  {r['prop']:<32} = {r['value']}{prov}")
    print(f"\n{len(rows)} properties  ·  {_ADVISORY}")
    return 0


def _cmd_attr(con, args) -> int:
    # Both arguments can be individually plausible while the PAIR matches nothing.
    # Without these, `attr zzznotakind hull.max` printed "0 value(s)" and exited 0.
    if _reject_unknown_kind(con, args.kind):
        return 2
    if _reject_unknown_prop(con, args.kind, args.prop):
        return 1
    q = ("SELECT e.name, e.klass, a.value, a.value_num, a.origin, a.chain "
         "FROM attrs a JOIN entities e ON e.id=a.entity_id "
         "WHERE e.kind=? AND a.prop=?")
    params: list = [args.kind, args.prop]
    if args.klass:
        q += " AND e.klass=?"
        params.append(args.klass)
    total = con.execute(
        q.replace("SELECT e.name, e.klass, a.value, a.value_num, a.origin, a.chain",
                  "SELECT count(*)"), params).fetchone()[0]
    order = "a.value_num" if args.sort == "num" else "e.name"
    q += f" ORDER BY {order} LIMIT ?"
    params.append(args.limit)
    rows = con.execute(q, params).fetchall()
    for r in rows:
        mod = "" if r["chain"] is None else f"  ← {r['origin']}"
        print(f"{r['name']:<44} {r['value']:>14}{mod}")
    print(f"\n{_count_line(len(rows), total, f'value(s) for {args.prop}')}  ·  {_ADVISORY}")
    return 0


def _cmd_who_sets(con, args) -> int:
    ent = con.execute("SELECT * FROM entities WHERE kind=? AND name=?",
                      (args.kind, args.name)).fetchone()
    if ent is None:
        if _reject_unknown_kind(con, args.kind):
            return 2
        print(f"no {args.kind} named {args.name!r}", file=sys.stderr)
        return 1
    if args.prop:
        r = con.execute("SELECT chain FROM attrs WHERE entity_id=? AND prop=?",
                        (ent["id"], args.prop)).fetchone()
        if r is None:
            print(f"no prop {args.prop!r} on {args.name}", file=sys.stderr)
            return 1
        print(f"{args.name}.{args.prop}: {_fmt_chain(r['chain'])}")
        _note = _winner_not_origin_note(ent["vpath"], r["chain"])
        if _note:
            print(_note)
    else:
        print(f"{args.name} (entity): {_fmt_chain(ent['chain'])}")
        _note = _winner_not_origin_note(ent["vpath"], ent["chain"])
        if _note:
            print(_note)
    return 0


def _cmd_diff_mod(con, args) -> int:
    total = con.execute("SELECT COUNT(*) FROM attrs a JOIN entities e ON e.id=a.entity_id "
                        "WHERE a.origin=?", (args.folder,)).fetchone()[0]
    rows = con.execute(
        "SELECT e.kind, e.name, a.prop, a.value FROM attrs a "
        "JOIN entities e ON e.id=a.entity_id WHERE a.origin=? "
        "ORDER BY e.kind, e.name, a.prop LIMIT ?", (args.folder, args.limit)).fetchall()
    for r in rows:
        print(f"{r['kind']:<6} {r['name']:<40} {r['prop']:<28} = {r['value']}")
    # "N value(s) won by X" is the headline number a balance discussion turns on;
    # printing the LIMIT as if it were the total makes that number wrong, not
    # merely the list incomplete.
    print(f"\n{_count_line(len(rows), total, f'value(s) won by {args.folder}')}  ·  {_ADVISORY}")
    return 0


def _cmd_sql(con, args) -> int:
    q = args.query.strip()
    if not q.lower().startswith(("select", "with")):
        print("only SELECT/WITH queries allowed", file=sys.stderr)
        return 2
    try:
        rows = con.execute(q).fetchall()
    except sqlite3.Error as exc:
        print(f"sql error: {exc}", file=sys.stderr)
        return 1
    for r in rows:
        print("\t".join("" if v is None else str(v) for v in r))
    return 0


def _cmd_dump(args) -> int:
    cfg = _merge.Config(reference=Path(args.reference))
    mods = active_mods()
    ordered = ordered_overlays(mods)
    folder_to_path = {m["folder"]: p for m, p in ordered}
    touch = build_touch_map(ordered)
    ov = touchers_for(args.vpath, touch, folder_to_path)
    rec = Recorder()
    res = _merge.build_effective(args.vpath, cfg, extra_overlays=ov, recorder=rec)
    if res.tree is None:
        print(f"no effective content for {args.vpath}", file=sys.stderr)
        return 1
    if args.chain:
        print(f"<!-- sources: {', '.join(res.sources)} -->")
        if "base" not in res.sources and _effective.base_has(cfg, args.vpath):
            print(f"<!-- note: base+DLC ALSO supply {args.vpath}; "
                  f"sources show which WON, not which introduced it -->")
    print(etree.tostring(res.tree, pretty_print=True, encoding="unicode"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
