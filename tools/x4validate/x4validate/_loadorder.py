"""Load order: which mod folder the engine reads first.

WHY THIS MODULE EXISTS, AND IT IS NOT TIDINESS. `compute_load_order` decides which
mod wins every collision -- CLAUDE.md gotcha #13 measures the same macro reading 0
alphabetically and 200 in true load order -- so editing it changes the merged answer
for byte-identical inputs. That is exactly what `_freshness`'s ENGINE axis exists to
detect, and it could not: the function lived in `_compat.py`, which also carries the
`x4compat` CLI, and `tests/test_engine_sources_carry_no_cli.py` (F69) measured the
cost of naming a CLI module there -- a CLI-text change and a DOCSTRING change each
invalidated the effective store and BaseX `x4eff` for rebuilds that could not change
one row. A hash that cries wolf trains you to ignore the banner.

F69's own remedy, quoted at the constant it guards: *"make the POPULATION right, not
the hash clever -- lift `compute_load_order` into a CLI-free module and name THAT."*
This is that module. It imports `pathlib` and `lxml.etree` and nothing else, so it
carries no argparse, no entry point and no `print`, and satisfies all four of F69's
checks by construction rather than by exemption.

`_compat` re-exports both names, so every existing caller and
`gates/mutation_probe.py`'s source-string mutant are unaffected.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree


def mod_deps(mod_path: Path, dropped: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (mod_id, [dependency_ids]) from a mod's content.xml.

    Ids only, optional and required alike -- for LOAD ORDER both kinds place the
    dependency first. Whether a dependency is REQUIRED decides whether the mod loads
    at all; that question is :func:`mod_dependencies`'.

    A manifest that will not parse yields ZERO dependencies, and dependencies are
    what force a mod to load EARLIER -- so silently swallowing the failure changes
    the computed load order, which decides every collision winner. Report it through
    *dropped* (same convention as `_registry.scan_installed`, which already handles
    this case correctly). MEASURED 2026-08-12: 0 of 122 installed manifests are
    malformed, so this is a latent defect -- the cost is zero today and unbounded
    the day it isn't.
    """
    mod_id, deps = mod_dependencies(mod_path, dropped)
    return mod_id, [d for d, _optional in deps]


def mod_dependencies(mod_path: Path, dropped: list[str] | None = None
                     ) -> tuple[str, list[tuple[str, bool]]]:
    """Return (mod_id, [(dependency_id, optional)]) from a mod's content.xml.

    `optional="true"` (or "1", any case) marks an optional dependency. A
    `<dependency>` with no `id` names only a GAME VERSION and is not a mod
    dependency, so it is not returned. Failure handling as :func:`mod_deps`.
    """
    cx = mod_path / "content.xml"
    if not cx.is_file():
        if dropped is not None:
            dropped.append(f"{mod_path.name}: no content.xml -- assuming no dependencies")
        return mod_path.name, []
    try:
        root = etree.parse(str(cx)).getroot()
    except etree.XMLSyntaxError as exc:
        if dropped is not None:
            dropped.append(f"{mod_path.name}: content.xml will not parse ({exc}) -- "
                           "load-order position from its folder name alone")
        return mod_path.name, []
    mod_id = root.get("id") or mod_path.name
    deps = [(d.get("id"),
             str(d.get("optional", "")).strip().lower() in ("true", "1"))
            for d in root.findall(".//dependency") if d.get("id")]
    return mod_id, deps


#: The extensions-root KINDS between which a dependency is MEASURED not to resolve
#: (2026-09-26, probe rounds 2-3, BLIND-SPOTS F141: game <-> profile, both directions).
#: Nothing about any other root was measured -- the Steam Workshop root in particular --
#: so a root of any other kind keeps the pre-F141 model (dependencies resolve across it)
#: and `_registry.mods` DISCLOSES that as unmeasured. `root_kind` comes from
#: `_registry.scan_installed`; an entry without one is modelled in the game root.
ISOLATED_ROOT_KINDS = frozenset({"game", "profile"})


def crosses_isolated_roots(kind_a: str, kind_b: str) -> bool:
    """True when a dependency between roots of these kinds is MEASURED to not resolve."""
    return (kind_a != kind_b and kind_a in ISOLATED_ROOT_KINDS
            and kind_b in ISOLATED_ROOT_KINDS)


def root_kind(m: dict) -> str:
    """A mod entry's extensions-root kind; no field = the game root, where mods deploy."""
    return m.get("root_kind") or "game"


def case_only_note(folder: str, wanted: str, actual: str) -> str:
    """THE record for a dependency id that matches an installed id only ignoring case.

    Whether the engine compares dependency ids case-sensitively is UNMEASURED. Excluding
    the mod on a spelling difference would assert a behaviour nobody observed, so the
    model treats the dependency as SATISFIED (and as a load-order edge) and says so.
    One implementation, so `_registry` and this module record the SAME string and a
    shared channel keeps one copy."""
    return (f"{folder}: dependency {wanted!r} matches the installed id {actual!r} only "
            "ignoring case; modelled as SATISFIED and as a load-order edge -- whether the "
            "engine matches dependency ids case-sensitively is UNMEASURED")


def _record(msg: str, mods, dropped: list[str] | None) -> None:
    """Send one load-order record to *dropped* and to the mod list's own channel.

    A `_registry.ModList` carries ``.notes``; a record appended there reaches every
    caller that renders `_registry.model_note`, whether or not it passed *dropped*
    (the release review found the records reached x4compat only). Duck-typed on
    purpose: this module imports nothing from `_registry`. Deduplicated on the list,
    because one mod list is often ordered more than once in a run."""
    if dropped is not None:
        dropped.append(msg)
    notes = getattr(mods, "notes", None)
    if notes is not None and msg not in notes:
        notes.append(msg)


def compute_load_order(mods: list[dict], dropped: list[str] | None = None) -> list[str]:
    """Order mod FOLDERS as the X4 engine loads them. MEASURED, not assumed.

    THE RULE (AUDIT-2026-09-24 LO-1, measured on the engine's own debug.txt):

      1. Folders are walked in case-insensitive UPPERCASE order -- `_` sorts AFTER the
         letters (it is 0x5F, above 'Z'), a space before `_`. Lowercase order is WRONG
         (it would put `s_combat` before `station`).
      2. Repeated passes over that order. In each pass every mod whose INSTALLED
         dependencies have ALREADY loaded -- including ones loaded earlier in the SAME
         pass -- loads. A mod whose dependency sorts after it therefore waits for the
         next pass; it is NOT placed right after that dependency.
      3. A dependency on an id that is not an installed mod (a DLC, or an OPTIONAL
         dependency you do not have) does not hold the mod back here. Whether the mod
         loads AT ALL is not this function's question: `_registry.mods("active")`
         already excludes a mod whose REQUIRED dependency is missing, disabled or
         cyclic (MEASURED 2026-09-26, the load-order probe), and records why.

    Evidence: the "Failed to verify the file signature" sequence for every file path two
    or more mods ship. Fitted on the t-file class (72 extensions, 72/72 exact), then
    scored on 372 classes / 5,134 ordered pairs across two launches two weeks apart:
    0 inverted. The previous algorithm -- an ASCII sort with Kahn placement, the
    community convention X4_Customizer also implements -- inverted 685 of them.
    `gates/load_order_oracle.py` re-checks this against every new log.

    MEASURED 2026-09-26 by the in-game load-order probe (scripts/load-order-probe.py):
    a missing REQUIRED dependency and a dependency CYCLE both mean the mod does not
    load, and two folders sharing an id BOTH load. So an "active"-scope caller never
    reaches the cycle branch below -- `_registry.mods("active")` has already removed
    the cycle. It stays as a SAFETY NET for "installed"-scope callers (modelling a mod
    before it is switched on): there the rest follow the sort order and the
    assumption is RECORDED. A duplicate id is RECORDED too -- never silently resolved.

    *mods* are entries from `_registry.mods(...)`. Pass *dropped* to receive every
    manifest or shape that made the order an assumption rather than a measurement.
    When *mods* is a `_registry.ModList` the same records are ALSO appended (once
    each) to its ``.notes``, so every caller that renders `_registry.model_note`
    discloses them without passing *dropped* -- before this, only x4compat did.
    """
    folders = [m["folder"] for m in mods]
    # EXTENSIONS ROOTS (MEASURED 2026-09-26, probe rounds 2-3; BLIND-SPOTS F141): every
    # game-root mod applies before every profile-root mod, and a dependency does not
    # cross between THOSE TWO roots. `root_rank` (position of the configured root, the
    # walk order) and `root_kind` (game / profile / workshop / custom -- which rule
    # applies) come from `_registry.scan_installed`; an entry without them (a candidate
    # placed from a dev folder, a test fixture) is modelled in the GAME root, where mods
    # are deployed. Only game <-> profile edges are cut: nothing about the Workshop root
    # (or an unconfigured one) was measured, so its edges are kept, as before F141.
    rank_of = {m["folder"]: m.get("root_rank", 0) for m in mods}
    kind_of = {m["folder"]: root_kind(m) for m in mods}
    # A REPEATED FOLDER COLLAPSES SILENTLY, AND IT TAKES THE MOD WITH IT.
    # `incoming` below is keyed by folder, so two entries with the same folder
    # become ONE node: the mod disappears from the load order, from the effective
    # tree built over it, and from every provenance answer -- nothing raised,
    # nothing recorded. Reachable by the profile-vs-game-root mistake CLAUDE.md
    # warns about, where one folder exists under two configured roots.
    #
    # MEASURED 2026-09-08 on this install: 3 configured roots, 133 folders, ZERO
    # names in more than one root, ZERO duplicates in the computed order, ZERO mods
    # lost. Verified reachable anyway: three mods, two sharing a folder, produce an
    # order of length TWO. So this RECORDS rather than restructures -- it costs
    # nothing today, and changing behaviour during close-out is how earlier rounds
    # introduced defects. What it must never do again is happen with no channel.
    _seen_folder: set[str] = set()
    id_to_folder: dict[str, str] = {}
    deps_by_folder: dict[str, list[str]] = {}
    for m in mods:
        if m["folder"] in _seen_folder:
            _record(
                "%s: folder appears more than once in the mod set, so one entry "
                "collapses onto the other and vanishes from the load order, the "
                "effective tree and every provenance answer" % m["folder"], mods, dropped)
        _seen_folder.add(m["folder"])
        _parse: list[str] = []
        mod_id, deps = mod_deps(Path(m["path"]), _parse)
        for msg in _parse:
            _record(msg, mods, dropped)
        # `mod_id` truthy FIRST: `mod_deps` returns "" for a mod with no
        # content.xml, and an ABSENT id is not a claimed one. Without this the
        # record fires for every second manifest-less mod -- caught by the twin,
        # which recorded a clash between two folders that share nothing.
        _clash = (mod_id
                  and mod_id in id_to_folder
                  and id_to_folder[mod_id] != m["folder"])
        if _clash:
            _record(
                "manifest id %r is claimed by both %r and %r; the later one wins "
                "the id, so a dependency naming it resolves to only one of them"
                % (mod_id, id_to_folder[mod_id], m["folder"]), mods, dropped)
        id_to_folder[mod_id] = m["folder"]
        deps_by_folder[m["folder"]] = deps

    # Edges: dep_folder -> folder (dependency loads first). Ignore uninstalled deps.
    # An id that matches only IGNORING CASE is an edge too, and recorded (engine
    # behaviour UNMEASURED; see `case_only_note`).
    id_by_lower: dict[str, str] = {}
    for mod_id in id_to_folder:
        id_by_lower.setdefault(mod_id.lower(), mod_id)
    incoming: dict[str, set[str]] = {f: set() for f in folders}
    for folder, dep_ids in deps_by_folder.items():
        for dep_id in dep_ids:
            dep_folder = id_to_folder.get(dep_id)
            if dep_folder is None:
                actual = id_by_lower.get(dep_id.lower())
                if actual is not None:
                    dep_folder = id_to_folder[actual]
                    if dep_folder != folder:
                        _record(case_only_note(folder, dep_id, actual), mods, dropped)
            if (dep_folder and dep_folder != folder
                    and not crosses_isolated_roots(kind_of[dep_folder], kind_of[folder])):
                incoming[folder].add(dep_folder)

    walk = sorted(dict.fromkeys(folders), key=lambda f: (rank_of[f], sort_key(f)))
    ordered: list[str] = []
    resolved: set[str] = set()
    passes = 0                          # completed passes before the current one
    last_rank = max(rank_of.values(), default=0)
    _noted_roots = False
    while len(ordered) < len(walk):
        loaded_this_pass = False
        for f in walk:
            if f in resolved or not incoming[f] <= resolved:
                continue
            if passes > 0 and rank_of[f] < last_rank and not _noted_roots:
                # UNMEASURED: round 3's probes all loaded in the FIRST pass, so whether a
                # game-root mod that WAITS a pass falls before or after the profile-root
                # mods is not known. The model keeps one walk (game root, then profile
                # root) in repeated passes; say so rather than let it read as measured.
                _record(
                    "%s: loads in a later dependency pass while mods in another extensions "
                    "root are present; its position relative to that root's mods is "
                    "UNMEASURED (the model walks game root, then profile root, in repeated "
                    "passes)" % f, mods, dropped)
                _noted_roots = True
            ordered.append(f)
            resolved.add(f)                  # visible to mods LATER in this same pass
            loaded_this_pass = True
        passes += 1
        if not loaded_this_pass:
            # A pass that loads nothing: the rest wait on each other (a cycle). The
            # ENGINE loads none of them (MEASURED 2026-09-26, load-order probe), and
            # mods("active") has already dropped them; reaching here means an
            # "installed"-scope caller. The rest follow the sort order and the
            # assumption is RECORDED -- it can change a collision winner.
            rest = [f for f in walk if f not in resolved]
            _record(
                "dependency cycle among %d mod(s) (%s); their load order falls back "
                "to the folder sort order, an UNMEASURED assumption that can change "
                "which mod wins a collision" % (len(rest), ", ".join(rest[:5])),
                mods, dropped)
            ordered.extend(rest)
            break
    return ordered


def sort_key(folder: str) -> str:
    """The engine's folder order: case-insensitive, compared in UPPERCASE.

    Per CHARACTER, not `str.upper()` on the whole name: `str.upper()` maps a sharp s to
    'SS' and so changes the key's length and order. The engine keeps ß as one character
    (as NTFS's own directory order does): MEASURED 2026-09-26 by the load-order probe's
    non-ASCII case, a folder with ß loads AFTER one with sz. On ASCII names the two agree.
    """
    return "".join(c.upper() if len(c.upper()) == 1 else c for c in folder)


@dataclass
class Placement:
    """Where the mod under test sits in the tree -- see :func:`place_candidate`."""
    #: the mod set with the candidate IN it (as `entry`) and its installed copy OUT
    mods: list
    #: the candidate's entry: {"folder": position key, "id", "path": the candidate}
    entry: dict
    #: installed entries that are the same mod (same folder or id), left out
    excluded: list


def place_candidate(mods: list[dict], candidate: Path, cand_id: str | None = None,
                    dropped: list[str] | None = None) -> Placement:
    """Place the mod under test in *mods* -- THE one rule Tier B, x4compat and x4stats
    share (AUDIT-2026-09-24 final review; each used to hand-roll its own).

      * POSITION KEY: when the candidate matches an entry of *mods* by folder name or
        manifest id (both CASE-INSENSITIVE), that INSTALLED copy's folder name -- the
        name the engine walks; else the candidate's own folder name.
      * DEPENDENCIES: the CANDIDATE's manifest (the entry's `path` is the candidate),
        because it is the version under test; the installed manifest may be older.
      * Every matching installed entry is EXCLUDED, so the mod is never counted twice
        or merged as a third party into its own tree.

    *cand_id* skips re-reading the manifest when the caller already has it.
    """
    candidate = Path(candidate)
    own_folder = candidate.resolve().name
    if cand_id is None:
        cand_id = (mod_dependencies(candidate, dropped)[0]
                   if (candidate / "content.xml").is_file() else "")
    low_folder, low_id = own_folder.lower(), (cand_id or "").lower()
    by_folder = [m for m in mods if m["folder"].lower() == low_folder]
    by_id = [m for m in mods if low_id and str(m.get("id", "")).lower() == low_id]
    match = (by_folder or by_id or [None])[0]
    excluded = [m for m in mods if m in by_folder or m in by_id]
    # ROOT: the installed copy's extensions root (it is the slot being replaced); a mod
    # not installed anywhere is modelled in the GAME root (rank 0), where mods deploy.
    entry = {"folder": match["folder"] if match is not None else own_folder,
             "id": cand_id or own_folder, "path": str(candidate),
             "root_rank": match.get("root_rank", 0) if match is not None else 0,
             "root_kind": root_kind(match) if match is not None else "game"}
    kept = [m for m in mods if not any(m is x for x in excluded)]
    placed = kept + [entry]
    if hasattr(mods, "notes") and hasattr(mods, "dropped"):
        # A `_registry.ModList` in, a ModList out, SHARING its channels: a record the
        # later `compute_load_order` makes over the placed set lands on the list the
        # caller already discloses from (release review, finding 3).
        placed = type(mods)(placed)
        placed.dropped, placed.notes = mods.dropped, mods.notes
    return Placement(mods=placed, entry=entry, excluded=excluded)

