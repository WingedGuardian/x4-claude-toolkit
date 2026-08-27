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
import fnmatch
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath

from lxml import etree

from x4validate import _cat, _compat, _merge, _mutation, _paths, _registry, _freshness, _resolve, _scan
from x4validate._provenance import BASE, Origin, Recorder
from x4validate import __version__


def effective_db() -> Path | None:
    """Where the effective store lives, or None when nothing is configured.

    Resolved on CALL and through `_paths` — the ONE door. This used to be
    `os.environ.get("X4_EFFECTIVE_DB")` evaluated at IMPORT time into a module
    constant that is also an argparse default, which had two consequences:
    a value in `.claude/x4-paths.env` was invisible, and `gates/_env.py` — which
    resolved the same variable through `_paths` — could disagree with this module
    about which store was configured. Two doors to one question is the shape that
    produced F30; it does not get to exist twice.
    """
    p = _paths.path_value("X4_EFFECTIVE_DB")
    if p is not None:
        return p
    reg = _registry.DEFAULT_REGISTRY
    return (reg.parent / "effective.sqlite") if reg else None


#: Backwards-compatible module constant. Prefer `effective_db()`: this is a
#: snapshot taken at import, so it cannot see configuration set afterwards.
DB_PATH: Path | None = effective_db()

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
    return _registry.mods("active", dirs)


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


def _under_assets(low: str) -> bool:
    """True when *low* is an ``assets/`` path of the game root or of a DLC.

    Deliberately exact rather than ``"assets/" in low``: the substring form also
    matches ``libraries/assets/...``, and a filter that is *nearly* the old walk
    is precisely how a documented scope quietly turns into a different one.
    """
    if low.startswith("assets/"):
        return True
    parts = low.split("/")
    return len(parts) >= 3 and parts[0] == "extensions" and parts[2] == "assets"


@lru_cache(maxsize=16)
def _base_vpaths_cached(reference: Path, dlc: tuple[Path, ...],
                        packed: frozenset[str], pattern: str) -> dict[str, str]:
    """Memoized core of :func:`base_vpaths`.

    MEASURED 2026-08-22: one call is **1.72 s** (rglob over 9,138 loose files plus
    two catalog reads), and the inputs cannot change inside a run. Uncached, every
    caller that loops over mods repaid it -- `check_variant_consistency` alone
    spent ~25-35 s per corpus sweep re-deriving a byte-identical answer.

    Keyed on the CONFIG-DERIVED inputs rather than on the Config object, which is
    not hashable. Callers that monkeypatch `_cat.mod_vfs` under a fixed reference
    path must call `base_vpaths.cache_clear()`; every current test uses a unique
    tmp_path, so the key already distinguishes them.
    """
    out: dict[str, str] = {}
    for f in reference.rglob(pattern):  # reference-scope-ok: THE sanctioned walk; packed pass below
        if f.is_file():
            v = f.relative_to(reference).as_posix()
            out[v.lower()] = v
    for src in dlc:
        if src.name.lower() not in packed:
            continue
        for entry in _cat.mod_vfs(src, packed_only=True):  # packed-ok: loose pass is above
            rel = entry.replace("\\", "/")
            if not fnmatch.fnmatch(rel.rsplit("/", 1)[-1].lower(), pattern.lower()):
                continue
            v = f"extensions/{src.name}/{rel}"
            out[v.lower()] = v
    return out


def base_vpaths(config: _merge.Config, pattern: str = "*.xml") -> dict[str, str]:
    r"""lower(vpath) -> vpath for EVERY base+DLC file matching *pattern*, WHOLE tree.

    THE single enumeration of "what the game itself ships". vpaths are game-root
    relative and a DLC keeps its ``extensions/ego_dlc_x/`` prefix, which is the
    spelling ``_merge._nested_target`` already expects.

    Loose THEN packed, and that ordering is the whole point. Six of the eight DLC
    are unpacked under ``reference\``; the two mini-DLC (Hyperion, Envoy) are
    NEVER unpacked and live only in ``ext_*.cat``. A plain ``reference.rglob``
    therefore cannot see them, and every hand-rolled copy of that walk has lost
    them silently:

      _input.py . _migration.py . _effective.py . _xref.py . _similarity.py .
      stage.py . build-effective.py   -- SEVEN occurrences, MEASURED.

    The last one (2026-08-22) cost BaseX ``x4eff`` **119 of 142 mini-DLC
    documents (84%)**, and the coverage check that gates negative claims over
    that index reported COMPLETE throughout, because a vpath never attempted
    cannot appear in a failure list. See docs/BLIND-SPOTS.md F34 and F35.

    Prose did not stop occurrences two through seven -- ``tests/test_no_loose_only_reference_walk.py``
    is the part that is expected to.
    """
    # Returns the CACHED dict; callers must not mutate it. `reference_vpaths`
    # builds a new dict, and every other caller only reads.
    return _base_vpaths_cached(config.reference, tuple(config.dlc_dirs()),
                               frozenset(config.packed_dlc_names()), pattern)


def reference_vpaths(config: _merge.Config, pattern: str) -> dict[str, str]:
    """base+DLC files matching *pattern*, RESTRICTED TO ``assets/``.

    The restriction is F3's documented scope decision -- galaxy-map macros
    (``maps/xu_ep2_universe/*``) and character macros
    (``libraries/character_macros.xml``) are out of scope for the store, not
    missing from it. MEASURED 2026-08-22 on the two mini-DLC: of 72 macro names,
    **40 are in scope and 35 sit in those two excluded classes**.

    It is written as an explicit FILTER over :func:`base_vpaths` rather than as a
    walk that happens to start at ``assets/``, so the scope is a decision someone
    can find and change -- and so there is exactly one enumeration underneath.
    Set-equality with the pre-refactor walk is pinned by
    ``tests/test_prop_depth.py``.
    """
    return {low: v for low, v in base_vpaths(config, pattern).items() if _under_assets(low)}


#: Test hook: drop the memo when a fixture changes what a fixed path resolves to.
base_vpaths.cache_clear = _base_vpaths_cached.cache_clear  # type: ignore[attr-defined]


def base_has(config: _merge.Config, vpath: str, owner: str | None = None) -> bool:
    r"""Does base+DLC ship *vpath*? Handles the DLC prefix so callers need not.

    THE TRAP THIS EXISTS TO REMOVE. :func:`base_vpaths` keys base-game files
    BARE (``libraries/wares.xml``) but keeps a DLC's ``extensions/ego_dlc_x/``
    prefix, because that is the spelling ``_merge._nested_target`` expects. Both
    spellings are correct; what is not correct is a caller that knows only one.

    MEASURED 2026-08-25: an audit looked up 58 DLC targets with the prefix
    STRIPPED and reported **all 58 GONE** when every one of them exists. Nothing
    was wrong with the data or with `base_vpaths`; the lookup asked the wrong
    question and got a confident, uniform, entirely false answer -- the shape
    CLAUDE.md #22 is about.

    No shipped call site had this bug (all three ITERATE the mapping rather than
    look up a key), so this is PREVENTIVE. It is worth the twelve lines because
    the failure mode is a wall of false negatives that looks like a real finding,
    and because ad-hoc analysis scripts are written far more often than call
    sites are.

    *owner*, when given, is a DLC folder name (``ego_dlc_terran``) to try as a
    prefix as well -- so a caller holding a vpath relative to a DLC root can ask
    about it without hand-assembling the prefix.
    """
    low = str(vpath).replace("\\", "/").lstrip("/").lower()
    # Keyed to THIS vpath's suffix, never "*": the enumeration is memoized per
    # pattern, and a bare "*" would walk the whole 60 GB base+DLC tree and cache
    # it -- paying a tree walk to answer one membership question.
    suffix = PurePosixPath(low).suffix
    known = base_vpaths(config, f"*{suffix}" if suffix else "*")
    if low in known:
        return True
    # A caller may hold either spelling; try the other rather than judge them.
    if low.startswith("extensions/"):
        tail = low.split("/", 2)
        if len(tail) == 3 and tail[2] in known:
            return True
    if owner and f"extensions/{owner.lower()}/{low}" in known:
        return True
    return any(k.endswith("/" + low) and k.startswith("extensions/") for k in known)


def _defines_macro(folder_to_path: dict[str, Path], touchers: list[tuple[str, str]]) -> bool:
    """True if any toucher's copy of the file actually contains a <macro name=>.

    Cheap byte-level test on files the touch map already located — no XML parse,
    no extra directory walk.
    """
    unreadable = False
    for folder, real in touchers:
        base = folder_to_path.get(folder)
        if base is None:
            continue
        try:
            data = _cat.read_path(base, real)
        except OSError:
            # silent-ok: FAIL OPEN. This helper only decides whether to LOOK at a
            # file; "I could not read it" is not "it holds no macros". Admitting
            # it hands the file to the merge, which parses it for real and reports
            # any failure through `skipped` — so an unreadable file surfaces there
            # instead of vanishing here. Swallowing to `False` would be the exact
            # silent-narrowing defect this change exists to remove.
            unreadable = True
            continue
        if data and b"<macro" in data:
            return True
    return unreadable


def macro_vpaths(config: _merge.Config, touch: dict[str, list[tuple[str, str]]],
                 folder_to_path: dict[str, Path] | None = None) -> dict[str, str]:
    """All effective macro-file vpaths: reference/DLC + mod-provided.

    Admission is by FILENAME (`*_macro.xml`, the cheap fast path) and, when
    *folder_to_path* is supplied, additionally by CONTENT for other
    ``assets/**.xml``. VRO ships macro files that simply are not named
    `*_macro.xml` (`bullet_gen_turret_l_rotor`, `bullet_ter_m_graviton`) and the
    engine loads them — both are in the effective `index/macros.xml` — so a
    filename rule silently loses real, live weapon balance data.

    The ``assets/`` restriction is deliberate and stays: galaxy-map and character
    macros are documented out of scope (docs/BLIND-SPOTS.md F3), not a defect.
    """
    out = reference_vpaths(config, "*_macro.xml")
    for low, touchers in touch.items():
        if not touchers or "assets/" not in low or not low.endswith(".xml"):
            continue
        if low.endswith("_macro.xml"):
            out.setdefault(low, touchers[0][1])
        elif folder_to_path is not None and _defines_macro(folder_to_path, touchers):
            out.setdefault(low, touchers[0][1])
    return out


def component_vpaths(config: _merge.Config, touch: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    """lower(vpath) -> vpath for every component file: all `assets/**.xml` that is
    not a `*_macro.xml`, from reference + DLC + mod-provided.

    **Not enumerated from `index/components.xml`.** That was the first design and
    it silently lost **487 of 3,959 components (12%), 34 of them vanilla** --
    `ship_xen_xl_mothership_01`, `engine_ter_s_01` and friends simply are not in
    the index. Which is precisely KNOWLEDGEBASE's "the index is NOT the definition
    set", written the same day and then relied on anyway.

    Excluding `*_macro.xml` is safe and measured: **0 files** anywhere define both
    a macro and a component, so the two enumerations cannot double-count.
    Components in `libraries/character_components.xml` stay out, consistent with
    character macros being out.
    """
    out: dict[str, str] = {}
    for low, real in reference_vpaths(config, "*.xml").items():
        if not low.endswith("_macro.xml"):
            out[low] = real
    for low, ts in touch.items():
        # `"assets/" IN low`, not startswith: a mod may ship content nested under
        # a DLC (`extensions/ego_dlc_timelines/assets/units/...`), and startswith
        # silently dropped 12 such components. `macro_vpaths` already uses the
        # substring form -- two enumerations of the same tree must agree.
        if (ts and "assets/" in low and low.endswith(".xml")
                and not low.endswith("_macro.xml")):
            out.setdefault(low, ts[0][1])
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


#: Recursion guard for `flatten_with_prov`. MEASURED 2026-08-12 over the whole
#: reference tree: the deepest <properties> subtree is 5 (character macros; ship
#: macros stop at 2), so 8 is headroom, not a limit anyone should hit. If it IS
#: hit the path is recorded in `truncated_props` and reported by the build --
#: never silently dropped, which is the defect class this whole change exists to
#: kill (see docs/BLIND-SPOTS.md).
MAX_PROP_DEPTH = 8

#: Property paths abandoned at MAX_PROP_DEPTH during the last build.
truncated_props: list[str] = []


def _walk_props(scope: etree._Element, rec: Recorder, prefix: str, depth: int,
                rows: list[tuple[str, str, float | None, list[Origin]]],
                no_recurse: frozenset | tuple = ()) -> None:
    """Append `<prefix><tag>[ident].attr` rows for *scope*'s children, recursively.

    The depth-1 key shape is byte-identical to the pre-2026-08-12 implementation
    (that is the golden-vector regression guard); deeper levels simply extend the
    same grammar with another dotted segment. Provenance is per-attribute at every
    depth: `Recorder.attr_chain` is keyed by (element, attr) and falls back to the
    nearest recorded ancestor, so a grandchild an overlay touched carries that
    overlay, and one it did not carries the inherited chain.
    """
    tag_counts: dict[str, int] = {}
    for child in scope:
        if isinstance(child.tag, str):
            tag_counts[child.tag] = tag_counts.get(child.tag, 0) + 1
    seen: dict[str, int] = {}
    #: (tag, ident) -> how many siblings have already claimed that exact bracket.
    #: F33: the bracket discriminator is NOT unique among siblings, so several
    #: collapsed onto one key and a `where prop=?` + `fetchone()` returned an
    #: arbitrary one of them. MEASURED on 582,107 attr rows: 627 duplicate
    #: (entity_id, prop) groups, 1,071 extra rows (0.18%), and 201 of those groups
    #: held genuinely DIFFERENT values under one key. Worst case:
    #: faction/player `licences.licence[generaluseequipment].factions` -- 8 rows,
    #: 8 distinct values.
    ident_seen: dict[tuple[str, str], int] = {}
    for child in scope:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag
        if tag_counts[tag] > 1:
            ident = _child_ident(child)
            if ident is None:
                # Zero-based positional index counting ONLY the ident-less
                # siblings -- preserved exactly from the original.
                seen[tag] = seen.get(tag, -1) + 1
                ident = str(seen[tag])
            # Disambiguate COLLISION-ONLY: the first claimant of a bracket keeps
            # the original key untouched, so 99.8% of rows are byte-identical and
            # the golden-vector guard still means something. Only the 2nd, 3rd...
            # gain `#1`, `#2` -- the same grammar `connection[name#n]` already
            # uses below, rather than a second invented one. Indexing EVERY key
            # positionally would have rewritten 358,415 rows (61.6%) to fix 0.18%.
            n = ident_seen.get((tag, ident), -1) + 1
            ident_seen[(tag, ident)] = n
            key = f"{tag}[{ident}]" if n == 0 else f"{tag}[{ident}#{n}]"
        else:
            key = tag
        full = f"{prefix}{key}"
        for attr, val in child.attrib.items():
            rows.append((f"{full}.{attr}", val, _num(val), rec.attr_chain(child, attr)))
        if len(child) and child not in no_recurse:
            if depth >= MAX_PROP_DEPTH:
                truncated_props.append(full)
                continue
            _walk_props(child, rec, f"{full}.", depth + 1, rows, no_recurse)


def flatten_with_prov(el: etree._Element, rec: Recorder,
                      child_scope: etree._Element | None = None,
                      no_recurse: frozenset | tuple = (),
                      ) -> list[tuple[str, str, float | None, list[Origin]]]:
    """Flatten *el*'s own attrs (``@attr``) + its children at EVERY depth
    (``tag.attr``, ``tag[ident].attr``, ``tag.child.attr``, ...) to
    (prop, value, num, chain).

    Until 2026-08-12 this walked exactly one level of children, which made the
    entire flight model invisible -- `physics/drag` (8 axes), `physics/inertia`,
    `jerk/*`, `steeringcurve/point` -- and dropped ware recipes
    (`production/primary/ware`). MEASURED over 339 vanilla ship macros: 4,094
    attribute occurrences indexed vs 9,197 invisible. The merged tree was always
    complete; only this projection was lossy.

    *child_scope* limits which children are walked (e.g. a macro's <properties>);
    default = direct children of *el*.

    *no_recurse* names child elements whose OWN attrs are still emitted but whose
    subtree is not descended into. `extract_macros` walks a macro twice — once for
    the macro itself and once scoped to <properties> — so without this the
    recursion re-emitted every property a second time under a `properties.` prefix
    (MEASURED: 67,333 duplicate rows, 23.1% of the store, before this guard)."""
    rows: list[tuple[str, str, float | None, list[Origin]]] = []
    for attr, val in el.attrib.items():
        rows.append((f"@{attr}", val, _num(val), rec.attr_chain(el, attr)))
    scope = child_scope if child_scope is not None else el
    _walk_props(scope, rec, "", 1, rows, no_recurse)
    return rows


def extract_macros(tree: etree._Element, vpath: str, rec: Recorder) -> list[Entity]:
    out: list[Entity] = []
    macros = tree.iter("macro") if tree.tag != "macro" else [tree]
    for m in macros:
        name = m.get("name")
        if not name:
            continue
        props = m.find("properties")
        # @name/@class + top-level (component, etc.). <properties> is walked by the
        # scoped call below, so exclude its subtree here or every property lands
        # twice (once as `x.y`, once as `properties.x.y`).
        rows = flatten_with_prov(m, rec, no_recurse=(props,) if props is not None else ())
        if props is not None:
            rows += flatten_with_prov(props, rec, child_scope=props)
        out.append(Entity("macro", name, m.get("class", ""), vpath,
                          rec.winner(m).source, rec.elem_chain(m), rows))
    return out


def extract_components(tree: etree._Element, vpath: str, rec: Recorder) -> list[Entity]:
    """Component identity + its connection SLOTS. Deliberately not the geometry.

    A component is what a macro's ``<connections><connection><macro ref=...>``
    points at: the slot a cockpit, turret, shield or engine actually occupies.
    Macro-side connections became visible on 2026-08-12 (0 -> 19,994 rows); this
    is the other half of that join, and together they answer "what is installed
    in this slot" without hand-parsing files.

    SCOPE: identity + ``connections/connection`` only. ``<layers>`` and
    ``<source>`` are 3D data -- MEASURED, flattening components wholesale yields
    **33,131,780 attribute rows, 148x the entire store**, so the naive design was
    not merely expensive but impossible. This one measures ~204k rows (+91%).
    Keyed by ``@name`` (components have no ``@id``).
    """
    out: list[Entity] = []
    for comp in tree.iter("component"):
        name = comp.get("name")
        if not name:
            continue
        rows: list[tuple[str, str, float | None, list[Origin]]] = []
        for attr, val in comp.attrib.items():
            rows.append((f"@{attr}", val, _num(val), rec.attr_chain(comp, attr)))
        conns = comp.find("connections")
        if conns is not None:
            seen: dict[str, int] = {}
            for conn in conns.findall("connection"):
                cname = conn.get("name")
                if cname is None:
                    continue
                # 11 of 5,011 components repeat a connection name. Two slots must
                # never collapse into one row -- that is the silent-narrowing
                # defect this whole effort exists to remove -- so a repeat takes
                # an explicit ordinal suffix rather than overwriting.
                n = seen.get(cname, 0)
                seen[cname] = n + 1
                key = f"connection[{cname}]" if n == 0 else f"connection[{cname}#{n}]"
                for attr, val in conn.attrib.items():
                    if attr == "name":
                        continue
                    rows.append((f"{key}.{attr}", val, _num(val),
                                 rec.attr_chain(conn, attr)))
        out.append(Entity("component", name, comp.get("class", ""), vpath,
                          rec.winner(comp).source, rec.elem_chain(comp), rows))
    return out


#: kind -> (vpath, child tag, class attr, KEY attr). Measured 2026-08-12 against
#: reference\: every entry verified 100% keyed on the attribute named here, every
#: registry verified to merge, and each is patched by 4-28 installed mods.
#: `god`, `parameters`, `loadoutrules` and `camerasettings` are deliberately absent
#: -- they are structured documents, not flat id-keyed registries, and need a
#: different entity model.
LIBRARY_REGISTRIES: dict[str, tuple[str, str, str, str]] = {
    "ware":        ("libraries/wares.xml", "ware", "group", "id"),
    "job":         ("libraries/jobs.xml", "job", "category", "id"),
    "ship":        ("libraries/ships.xml", "ship", "group", "id"),
    "shipgroup":   ("libraries/shipgroups.xml", "group", "tags", "name"),
    "loadout":     ("libraries/loadouts.xml", "loadout", "name", "id"),
    "station":     ("libraries/stations.xml", "station", "type", "id"),
    "stationgroup": ("libraries/stationgroups.xml", "group", "tags", "name"),
    "module":      ("libraries/modules.xml", "module", "group", "id"),
    # MEASURED 2026-08-21 over the EFFECTIVE tree (base + 8 DLC incl. both mini-DLC +
    # every installed mod): 146 groups, and every one is a bare <group name="...">
    # carrying no second attribute -- so there is no distinct class to record. Reusing
    # the key as the class follows the existing `mapdataset` row rather than inventing a
    # meaning. Added because the engine caught a bad <module group=> reference that
    # x4validate was structurally blind to (cpsdo_faction, 43 FactoryGenerator errors).
    "modulegroup": ("libraries/modulegroups.xml", "group", "name", "name"),
    "plan":        ("libraries/constructionplans.xml", "plan", "name", "id"),
    "basket":      ("libraries/baskets.xml", "basket", "name", "id"),
    "people":      ("libraries/people.xml", "people", "name", "id"),
    "mapdataset":  ("libraries/mapdefaults.xml", "dataset", "macro", "macro"),
    "sound":       ("libraries/sound_library.xml", "sound", "name", "id"),
    "icon":        ("libraries/icons.xml", "icon", "texture", "name"),
    "gfxeffect":   ("libraries/effects.xml", "effect", "type", "name"),
    "roomgroup":   ("libraries/roomgroups.xml", "group", "tags", "name"),
    "room":        ("libraries/rooms.xml", "room", "type", "id"),
    "character":   ("libraries/characters.xml", "character", "race", "id"),
    "region":      ("libraries/region_definitions.xml", "region", "density", "name"),
    "faction":     ("libraries/factions.xml", "faction", "primaryrace", "id"),
}


def _extract_registry(tree: etree._Element, kind: str, child_tag: str,
                      klass_attr: str, vpath: str, rec: Recorder,
                      key_attr: str = "id") -> list[Entity]:
    """Entities from a flat id-keyed registry file.

    *key_attr* exists because this used to hardcode ``el.get("id")`` and skip
    silently when absent. MEASURED: 7 of 18 registries key by ``@name`` and one by
    ``@macro``, so hardcoding would have indexed **zero entities while reporting
    success** for seven of them -- a confident empty answer downstream, with
    nothing anywhere saying the key was wrong.

    Raises when children exist but none are keyed, because that is a
    misconfiguration and not data. A file with no children at all is data, and
    returns empty quietly.
    """
    out: list[Entity] = []
    children = tree.findall(child_tag)
    for el in children:
        name = el.get(key_attr)
        if not name:
            continue
        out.append(Entity(kind, name, el.get(klass_attr, ""), vpath,
                          rec.winner(el).source, rec.elem_chain(el),
                          flatten_with_prov(el, rec)))
    if children and not out:
        raise ValueError(
            f"{kind}: {vpath} has {len(children)} <{child_tag}> element(s) but the "
            f"registry yielded no entities — @{key_attr!r} matches none of them. "
            f"Indexing nothing while reporting success is the defect this guard exists "
            f"to catch; fix the key attribute in LIBRARY_REGISTRIES.")
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
#: Derived, never re-typed: every flat registry, plus the two per-file kinds.
BUILDABLE_KINDS = tuple(LIBRARY_REGISTRIES) + ("macro", "component")


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
        effective_db(), "the effective-store location",
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
    for kind in kinds:
        if kind in LIBRARY_REGISTRIES:
            vpath, child, klass_attr, key_attr = LIBRARY_REGISTRIES[kind]
            ov = touchers_for(vpath, touch, folder_to_path)
            try:
                tree, rec = _merge_one(vpath, config, ov)
            except etree.LxmlError as exc:
                skipped.add(vpath, exc)
                continue
            if tree is not None:
                entities += _extract_registry(tree, kind, child, klass_attr, vpath,
                                              rec, key_attr=key_attr)
                collect_removed(vpath, rec)
            progress(f"{kind}s: {sum(1 for e in entities if e.kind == kind)}")

    # macros (per-file)
    if "macro" in kinds:
        mvpaths = macro_vpaths(config, touch, folder_to_path)
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

    # components (per-file, enumerated from index/components.xml)
    if "component" in kinds:
        cvpaths = component_vpaths(config, touch)
        progress(f"component files to merge: {len(cvpaths)}")
        n = 0
        for low, vpath in sorted(cvpaths.items()):
            ov = touchers_for(low, touch, folder_to_path)
            try:
                tree, rec = _merge_one(vpath, config, ov)
            except etree.LxmlError as exc:
                skipped.add(vpath, exc)
                n += 1
                continue
            if tree is not None:
                entities += extract_components(tree, vpath, rec)
                if rec.removed:
                    collect_removed(vpath, rec)
            n += 1
            if n % 1000 == 0:
                progress(f"  merged {n}/{len(cvpaths)} component files, "
                         f"{sum(1 for e in entities if e.kind == 'component')} components")
        progress(f"components: {sum(1 for e in entities if e.kind == 'component')}")

    if skipped.n:
        progress(f"skipped {skipped.n} unparseable file(s); e.g. {skipped.samples[0]}")
    if truncated_props:
        # Never silent: a truncated property subtree is exactly the "narrowed the
        # data and reported success" shape this build was fixed to stop doing.
        progress(f"WARNING: {len(truncated_props)} property subtree(s) hit the "
                 f"depth-{MAX_PROP_DEPTH} guard and were NOT indexed; "
                 f"e.g. {truncated_props[0]}. Raise MAX_PROP_DEPTH.")
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
        # WHEN this store was true, not just how much it holds. Without it the
        # store cannot tell a current answer from one about a superseded world —
        # the exact failure that let BaseX's x4eff serve pre-merge-fix values for
        # eleven days (140 of 194 engine thrust rows wrong).
        _mutation.refuse_if_mutating("build the effective store")
        _freshness.stamp_sqlite(con, _freshness.fingerprint(config, _ext_root(config)))
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

def _ext_root(config) -> Path | None:
    """The extensions directory this store was built over, or ``None`` when that
    cannot be established.

    Freshness is judged against the same world the build enumerated, so this asks
    `_paths` rather than guessing from `config.overlays` -- an empty overlay list
    would otherwise fingerprint "no mods" and read as fresh forever. That reason
    is why the original code existed and it still holds: UNKNOWN is the honest
    answer here, never an inferred root.

    RETURNS ``None`` WHEN THE CONFIG DESCRIBES A DIFFERENT WORLD (F63 symptom 2).
    This used to return `_registry.GAME_EXTENSIONS` unconditionally, behind an
    `except AttributeError` that can never fire -- the attribute EXISTS and its
    VALUE is None when nothing is configured. So a store built over throwaway test
    directories was stamped with a fingerprint describing the REAL installed game:
    an artifact claiming provenance it does not have.

    `fingerprint()` already models the three states this needs (F63 symptom 1):
    OMITTED raises (F46's guard -- a caller who forgot must not silently hash the
    current directory), explicit ``None`` records the content axis as UNKNOWN, and
    `compare()` refuses to call an UNKNOWN axis fresh.
    """
    real_ref = _paths.reference()
    cfg_ref = getattr(config, "reference", None)
    if real_ref is None or cfg_ref is None:
        return None
    if Path(cfg_ref) != Path(real_ref):
        return None
    return _paths.game_extensions()


def store_freshness(con, config=None):
    """Does this store still describe the installed world? (see `_freshness`)"""
    config = config or _merge.Config()
    return _freshness.compare(
        _freshness.read_sqlite(con),
        _freshness.fingerprint(config, _ext_root(config)),
        engine_dependent=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise SystemExit(f"no store at {db_path} — run `x4effective build` first")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


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
        if not base_has(cfg, vpath):
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
        if "base" not in res.sources and base_has(cfg, args.vpath):
            print(f"<!-- note: base+DLC ALSO supply {args.vpath}; "
                  f"sources show which WON, not which introduced it -->")
    print(etree.tostring(res.tree, pretty_print=True, encoding="unicode"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
