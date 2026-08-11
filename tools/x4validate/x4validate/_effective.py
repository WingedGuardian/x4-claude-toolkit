r"""x4effective: the "xEdit for X4" — final effective values + per-attribute provenance.

Builds the effective merged tree of base + DLC + all ACTIVE mods (load order) and
extracts, for every entity (ware / macro / job), each attribute's final value AND
the chain of overlays that produced it (which mod won). Results land in a SQLite
store queried by the CLI, by Claude (`sql`), and by the HTML browser (_effhtml).

Design notes:
- Enumeration is by game-root vpath (= mod-relative path). A mod file at
  ``assets/foo_macro.xml`` maps to game vpath ``assets/foo_macro.xml``; a file at
  ``extensions/ego_dlc_x/...`` patches that DLC's vpath. build_effective already
  resolves both base-owned files (base from reference) and mod-owned files (first
  overlay full-overrides when reference has no base), so one call path serves both.
- ``touchers`` per vpath are precomputed once, so each merge is passed only the
  mods that actually carry the file (not all ~90) — same result, ~90x fewer stats.
- Provenance is advisory: load order = _compat.compute_load_order (community-standard
  topo sort, not engine-verified).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _cat, _compat, _merge, _registry, _scan
from x4validate._provenance import BASE, Origin, Recorder
from x4validate import __version__

# None when neither $X4_EFFECTIVE_DB nor a registry location is configured —
# resolved through _registry.require() at CLI time, never guessed at import time.
_env_db = os.environ.get("X4_EFFECTIVE_DB")
DB_PATH: Path | None = (Path(_env_db) if _env_db
                        else (_registry.DEFAULT_REGISTRY.parent / "effective.sqlite"
                              if _registry.DEFAULT_REGISTRY else None))

SCHEMA_VERSION = 1
_ADVISORY = ("winner reflects community-standard load order "
             "(alphabetical + dependency-first), not engine-verified")


def _count_line(shown: int, total: int, noun: str) -> str:
    """Footer count that NEVER hides truncation.

    `--limit` defaults to 200 and the footer used to print a bare "200 ware(s)"
    while the store holds 2,431 — so the capped number read as the total. A
    silent cap is the same class of lie as a silent skip: the output looks like
    an answer about everything when it is an answer about the first N.

    Lives in `_scan` now so `x4diff --top` shares one implementation; kept here
    as the module-local name every call site already uses.
    """
    return _scan.count_line(shown, total, noun)


# --- active mod set + load order ---------------------------------------------

def active_mods(dirs: list[Path] | None = None) -> list[dict]:
    """Installed ∩ manifest-enabled ∩ profile content.xml enabled.

    A mod id absent from the profile content.xml is treated as enabled
    (matches the registry's "absent = enabled" convention)."""
    installed = _registry.scan_installed(dirs)
    try:
        prof = dict(_registry.ingest_content_xml())
    except (OSError, etree.XMLSyntaxError):
        prof = {}
    return [m for m in installed
            if m["enabled"] and prof.get(m["id"], True)]


def ordered_overlays(mods: list[dict]) -> list[tuple[dict, Path]]:
    """(mod, path) pairs in engine load order."""
    order = _compat.compute_load_order(mods)
    by_folder = {m["folder"]: (m, Path(m["path"])) for m in mods}
    return [by_folder[f] for f in order if f in by_folder]


# --- vpath enumeration + touch map -------------------------------------------

def build_touch_map(ordered: list[tuple[dict, Path]]) -> dict[str, list[tuple[str, str]]]:
    """lower(LOGICAL vpath) -> [(mod_folder, real_vpath), ...] in load order.

    A mod-on-mod nested patch — a file at ``extensions/<owner>/<rel>`` where
    <owner> is an INSTALLED MOD folder — is registered under the owner's own
    ``<rel>``, because that is the one document the engine builds. Keying it by
    its literal path gave the same logical file two disconnected keys: the
    owner's entities never saw the patcher (wrong values, wrong provenance), and
    the patcher's key minted a phantom duplicate entity at a vpath the game does
    not have. DLC-nested paths (``extensions/ego_dlc_*``) are NOT rewritten —
    those are genuine game vpaths, and ego_dlc folders never appear in *ordered*.
    """
    folders = {mod["folder"].lower() for mod, _ in ordered}
    touch: dict[str, list[tuple[str, str]]] = {}
    for mod, path in ordered:
        for low, real in _compat._mod_xml_paths(path).items():
            parts = low.split("/")
            if (len(parts) >= 3 and parts[0] == "extensions"
                    and parts[1] in folders
                    and parts[1] != mod["folder"].lower()
                    # SINGLE-level nesting only. A double-nested file —
                    # extensions/<modA>/extensions/<dlc-or-mod>/<rel> — is a patch
                    # on another mod's PATCH FILE, and whether the engine applies
                    # that transitively is not engine-proven. Rewriting it onto the
                    # inner vpath double-applied ebi_m0_vro (it ships BOTH the
                    # direct DLC patch and the double-nested form) and flipped six
                    # entity origins. Unproven == keep the old behavior.
                    and parts[2] != "extensions"):
                low = "/".join(parts[2:])
            touch.setdefault(low, []).append((mod["folder"], real))
    return touch


def reference_vpaths(config: _merge.Config, pattern: str) -> dict[str, str]:
    """lower(vpath) -> vpath for reference base + DLC files matching *pattern*
    (rglob) under assets/. vpaths are game-root relative (DLC keeps its
    extensions/ego_dlc_x/ prefix)."""
    out: dict[str, str] = {}
    root = config.reference
    roots = [root] + config.dlc_dirs()
    for src in roots:
        adir = src / "assets"
        if not adir.is_dir():
            continue
        for f in adir.rglob(pattern):
            if f.is_file():
                v = f.relative_to(root).as_posix()
                out[v.lower()] = v
    return out


def macro_vpaths(config: _merge.Config, touch: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    """All effective macro-file vpaths: reference/DLC + mod-provided."""
    out = reference_vpaths(config, "*_macro.xml")
    for low, real in ((low, ts[0][1]) for low, ts in touch.items() if ts):
        if low.endswith("_macro.xml") and ("assets/" in low):
            out.setdefault(low, real)
    return out


def touchers_for(vpath: str, touch: dict[str, list[tuple[str, str]]],
                 folder_to_path: dict[str, Path]) -> list[Path]:
    return [folder_to_path[f] for f, _ in touch.get(vpath.lower(), []) if f in folder_to_path]


# --- entity model -------------------------------------------------------------

@dataclass
class Entity:
    kind: str
    name: str
    klass: str
    vpath: str
    origin: str
    chain: list[Origin]
    attrs: list[tuple[str, str, float | None, list[Origin]]] = field(default_factory=list)


def _num(val: str) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        # silent-ok: "this attribute is not numeric" is the ANSWER here, not a
        # failure to look. Callers keep the original string either way.
        return None


def _chain_json(chain: list[Origin], default: Origin) -> str | None:
    """JSON list of the chain; None when the value is pure default (base) — saves space."""
    if len(chain) == 1 and chain[0] == default:
        return None
    return json.dumps([[o.source, o.op, o.line] for o in chain])


def _child_ident(el: etree._Element) -> str | None:
    for a in ("id", "name", "method", "ware", "ref", "type"):
        v = el.get(a)
        if v is not None:
            return v
    return None


def flatten_with_prov(el: etree._Element, rec: Recorder,
                      child_scope: etree._Element | None = None,
                      ) -> list[tuple[str, str, float | None, list[Origin]]]:
    """Flatten *el*'s own attrs (``@attr``) + one level of children (``tag.attr``,
    or ``tag[ident].attr`` for disambiguated duplicates) to (prop, value, num, chain).

    *child_scope* limits which children are walked (e.g. a macro's <properties>);
    default = direct children of *el*."""
    rows: list[tuple[str, str, float | None, list[Origin]]] = []
    for attr, val in el.attrib.items():
        rows.append((f"@{attr}", val, _num(val), rec.attr_chain(el, attr)))
    scope = child_scope if child_scope is not None else el
    tag_counts: dict[str, int] = {}
    for child in scope:
        if isinstance(child.tag, str):
            tag_counts[child.tag] = tag_counts.get(child.tag, 0) + 1
    seen: dict[str, int] = {}
    for child in scope:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag
        if tag_counts[tag] > 1:
            ident = _child_ident(child)
            if ident is None:
                seen[tag] = seen.get(tag, -1) + 1
                ident = str(seen[tag])
            prefix = f"{tag}[{ident}]"
        else:
            prefix = tag
        for attr, val in child.attrib.items():
            rows.append((f"{prefix}.{attr}", val, _num(val), rec.attr_chain(child, attr)))
    return rows


def extract_macros(tree: etree._Element, vpath: str, rec: Recorder) -> list[Entity]:
    out: list[Entity] = []
    macros = tree.iter("macro") if tree.tag != "macro" else [tree]
    for m in macros:
        name = m.get("name")
        if not name:
            continue
        props = m.find("properties")
        rows = flatten_with_prov(m, rec)  # @name/@class + top-level (component, etc.)
        if props is not None:
            rows += flatten_with_prov(props, rec, child_scope=props)
        out.append(Entity("macro", name, m.get("class", ""), vpath,
                          rec.winner(m).source, rec.elem_chain(m), rows))
    return out


def _extract_registry(tree: etree._Element, kind: str, child_tag: str,
                      klass_attr: str, vpath: str, rec: Recorder) -> list[Entity]:
    out: list[Entity] = []
    for el in tree.findall(child_tag):
        name = el.get("id")
        if not name:
            continue
        out.append(Entity(kind, name, el.get(klass_attr, ""), vpath,
                          rec.winner(el).source, rec.elem_chain(el),
                          flatten_with_prov(el, rec)))
    return out


# --- build --------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE mods(folder TEXT PRIMARY KEY, mod_id TEXT, name TEXT, version TEXT,
                  rank INTEGER, enabled INTEGER, packed INTEGER);
CREATE TABLE entities(id INTEGER PRIMARY KEY, kind TEXT, name TEXT, klass TEXT,
                      vpath TEXT, origin TEXT, chain TEXT);
CREATE TABLE attrs(entity_id INTEGER REFERENCES entities(id), prop TEXT,
                   value TEXT, value_num REAL, origin TEXT, chain TEXT);
CREATE TABLE removed(vpath TEXT, node_path TEXT, source TEXT, op_line INTEGER);
CREATE INDEX idx_ent_kind_klass ON entities(kind, klass);
CREATE INDEX idx_ent_name ON entities(name);
CREATE INDEX idx_attr_entity ON attrs(entity_id);
CREATE INDEX idx_attr_prop ON attrs(prop);
CREATE INDEX idx_attr_origin ON attrs(origin);
"""


def _merge_one(vpath: str, config: _merge.Config,
               overlays: list[Path]) -> tuple[etree._Element | None, Recorder]:
    rec = Recorder()
    res = _merge.build_effective(vpath, config, extra_overlays=overlays, recorder=rec)
    return res.tree, rec


class _SkipCount:
    def __init__(self):
        self.n = 0
        self.samples: list[str] = []

    def add(self, vpath: str, exc: Exception):
        self.n += 1
        if len(self.samples) < 10:
            self.samples.append(f"{vpath}: {exc}")


#: The kinds `build` knows how to extract. Kept beside the extractors below so
#: adding one without listing it here fails loudly rather than silently.
BUILDABLE_KINDS = ("ware", "macro", "job")


def build(config: _merge.Config | None = None, db_path: Path | None = None,
          dirs: list[Path] | None = None, kinds: tuple[str, ...] = BUILDABLE_KINDS,
          progress=lambda s: None) -> Path:
    config = config or _merge.Config()
    # Reject an unknown kind instead of quietly building nothing. `--kinds
    # shieldgenerator` (a *klass*, not a kind) used to write an empty store and
    # exit 0, so every later query answered from an empty database with nothing
    # ever saying the name was wrong. The read side already refuses this — `ls`
    # prints "unknown kind ... stored kinds are: ..." — and the build side must
    # agree, because a false clean here poisons everything downstream.
    unknown = [k for k in kinds if k not in BUILDABLE_KINDS]
    if unknown:
        raise ValueError(
            f"unknown kind(s) {', '.join(sorted(unknown))} — buildable kinds are "
            f"{', '.join(sorted(BUILDABLE_KINDS))}. (Values like 'shieldgenerator' "
            "are entity CLASSES; filter those at query time, e.g. "
            "`x4effective attr macro <prop> --class shieldgenerator`.)"
        )
    db_path = db_path or _registry.require(
        DB_PATH, "the effective-store location",
        "set X4_EFFECTIVE_DB or X4_MODS (or X4_REGISTRY), or pass --db")
    mods = active_mods(dirs)
    ordered = ordered_overlays(mods)
    folder_to_path = {m["folder"]: p for m, p in ordered}
    overlay_paths = [p for _, p in ordered]
    order_rank = {m["folder"]: i for i, (m, _) in enumerate(ordered)}
    touch = build_touch_map(ordered)
    progress(f"active mods: {len(mods)}; load order computed")

    entities: list[Entity] = []
    removed: list[tuple[str, str, str, int]] = []
    skipped = _SkipCount()

    def collect_removed(vpath, rec):
        for path, o in rec.removed:
            removed.append((vpath, path, o.source, o.line))

    # library registries (single union-merged files)
    lib = {"ware": ("libraries/wares.xml", "ware", "group"),
           "job": ("libraries/jobs.xml", "job", "category")}
    for kind in kinds:
        if kind in lib:
            vpath, child, klass_attr = lib[kind]
            ov = touchers_for(vpath, touch, folder_to_path)
            try:
                tree, rec = _merge_one(vpath, config, ov)
            except etree.LxmlError as exc:
                skipped.add(vpath, exc)
                continue
            if tree is not None:
                entities += _extract_registry(tree, kind, child, klass_attr, vpath, rec)
                collect_removed(vpath, rec)
            progress(f"{kind}s: {sum(1 for e in entities if e.kind == kind)}")

    # macros (per-file)
    if "macro" in kinds:
        mvpaths = macro_vpaths(config, touch)
        progress(f"macro files to merge: {len(mvpaths)}")
        n = 0
        for low, vpath in sorted(mvpaths.items()):
            # Look up touchers by the map KEY, not the real path: for a nested
            # patch normalized onto its owner's rel, the real path no longer
            # equals the key, and a real-path lookup would silently hand the
            # merge an empty overlay list.
            ov = touchers_for(low, touch, folder_to_path)
            try:
                tree, rec = _merge_one(vpath, config, ov)
            except etree.LxmlError as exc:
                skipped.add(vpath, exc)
                n += 1
                continue
            if tree is not None:
                entities += extract_macros(tree, vpath, rec)
                if rec.removed:
                    collect_removed(vpath, rec)
            n += 1
            if n % 500 == 0:
                progress(f"  merged {n}/{len(mvpaths)} macro files, {len(entities)} entities")

    if skipped.n:
        progress(f"skipped {skipped.n} unparseable file(s); e.g. {skipped.samples[0]}")
    _write_db(db_path, config, mods, ordered, order_rank, entities, removed)
    progress(f"wrote {len(entities)} entities to {db_path}")
    return db_path


def _write_db(db_path, config, mods, ordered, order_rank, entities, removed):
    # PID-qualified: two concurrent builds used to pick the SAME `<db>.tmp`, so
    # they raced on os.replace and BOTH died with a raw PermissionError
    # (WinError 32). Build-then-atomically-replace already keeps the store safe
    # — the loser must simply lose quietly and leave a valid db behind.
    tmp = db_path.with_suffix(f"{db_path.suffix}.{os.getpid()}.tmp")
    if tmp.exists():
        tmp.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(tmp))
    try:
        con.executescript("PRAGMA journal_mode=MEMORY; PRAGMA synchronous=OFF;" + _SCHEMA)
        con.executemany("INSERT INTO meta VALUES(?,?)", [
            ("schema_version", str(SCHEMA_VERSION)),
            ("reference", str(config.reference)),
            ("active_mods", str(len(mods))),
            ("load_order", json.dumps([m["folder"] for m, _ in ordered])),
            ("advisory", _ADVISORY),
        ])
        con.executemany("INSERT INTO mods VALUES(?,?,?,?,?,?,?)", [
            (m["folder"], m["id"], m["name"], m["version"], order_rank[m["folder"]],
             int(m["enabled"]), int(_cat.is_packed(p))) for m, p in ordered])
        default = Origin(BASE, BASE)
        eid = 0
        ent_rows, attr_rows = [], []
        for e in entities:
            eid += 1
            ent_rows.append((eid, e.kind, e.name, e.klass, e.vpath, e.origin,
                             _chain_json(e.chain, default)))
            for prop, value, num, chain in e.attrs:
                attr_rows.append((eid, prop, value, num,
                                  chain[-1].source, _chain_json(chain, default)))
        con.executemany("INSERT INTO entities VALUES(?,?,?,?,?,?,?)", ent_rows)
        con.executemany("INSERT INTO attrs VALUES(?,?,?,?,?,?)", attr_rows)
        con.executemany("INSERT INTO removed VALUES(?,?,?,?)", removed)
        con.commit()
    finally:
        con.close()
    try:
        os.replace(tmp, db_path)
    except OSError as exc:
        # Windows refuses the replace while another process holds the target
        # (a concurrent build, or a reader with the store open). The store is
        # untouched and still valid, so say that plainly instead of unwinding a
        # traceback that reads like data loss.
        try:
            os.unlink(tmp)
        except OSError:
            pass  # silent-ok: best-effort cleanup of our own temp; the real error is raised below
        raise OSError(
            f"could not install the rebuilt store at {db_path}: {exc}. "
            "Another x4effective build or an open reader is holding it — "
            "the existing store is unchanged; retry once that finishes."
        ) from exc


# --- queries ------------------------------------------------------------------

def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise SystemExit(f"no store at {db_path} — run `x4effective build` first")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _fmt_chain(chain_json: str | None) -> str:
    if not chain_json:
        return "base"
    return " → ".join(f"{s} {op}" + (f":{ln}" if ln else "")
                      for s, op, ln in json.loads(chain_json))


# --- CLI ----------------------------------------------------------------------

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
    p.add_argument("--db", default=str(DB_PATH) if DB_PATH else None)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="(re)build the effective store")
    b.add_argument("--reference", default=str(_merge.REFERENCE))
    b.add_argument("--kinds", default="ware,macro,job")

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

    args = p.parse_args(argv)
    db = Path(args.db) if args.db else _registry.require(
        DB_PATH, "the effective-store location",
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
    return 2


def _known_kinds(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT kind FROM entities ORDER BY kind").fetchall()]


def _reject_unknown_kind(con, kind: str) -> bool:
    """True (and prints) if *kind* is not a stored kind.

    Without this an unknown kind reads as a confident empty answer: `ls ship`
    printed "0 ship(s)" — which looks like "this game has no ships" rather than
    "there is no such kind". Ships are stored as kind='macro' (and their wares as
    kind='ware'), so the natural guess is silently wrong. Same false-negative shape
    as a validator reporting OK because it examined nothing.
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


def _cmd_show(con, args) -> int:
    ent = con.execute("SELECT * FROM entities WHERE kind=? AND name=?",
                      (args.kind, args.name)).fetchone()
    if ent is None:
        if _reject_unknown_kind(con, args.kind):
            return 2
        print(f"no {args.kind} named {args.name!r}", file=sys.stderr)
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
    else:
        print(f"{args.name} (entity): {_fmt_chain(ent['chain'])}")
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
    print(etree.tostring(res.tree, pretty_print=True, encoding="unicode"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
