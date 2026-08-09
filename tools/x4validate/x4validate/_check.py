"""Orchestration: run the three checks against a mod folder and collect findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from lxml import etree

from . import (_cat, _compat, _debuglog, _exprlint, _merge, _migration, _refs,
               _registry, _resolve, _scan, _xref, _xsd)

# A ship variant macro file: <base>_<a|b|c|...>_macro.xml
VARIANT_RE = re.compile(r"^(?P<base>.+)_(?P<v>[a-z0-9])_macro\.xml$")

# Localisation: X4 UNIONS pages across every t-file (base + DLC + mods), and
# strings may be defined either in the language-neutral 0001.xml or the
# English 0001-l044.xml. So text defs must be unioned across all sources, not
# read from one overridable path.
TEXT_FILES = ("t/0001.xml", "t/0001-l044.xml")
WARES_FILE = "libraries/wares.xml"
# index/macros.xml is additively UNIONED across extensions (like t-files), not
# overridden — each extension registers its own macro->file mappings.
MACRO_INDEX = "index/macros.xml"
RACES_FILE = "libraries/races.xml"
FACTIONS_FILE = "libraries/factions.xml"
#: A mod's manifest, not payload. It is XML that `iter_mod_xml_roots` yields, so any
#: "does this mod ship content?" count must exclude it — otherwise a folder holding
#: nothing but content.xml looks like it has one payload file.
MANIFEST = "content.xml"


def collect_text_defs(config: _merge.Config, extra_overlays=None,
                      report: Report | None = None) -> set[tuple[str, str]]:
    """Union (page,t) definitions from every t-file across base + DLC + overlays.

    Works for full <language> files and <diff> files alike (text_defs scans
    //page[@id]//t[@id] regardless of root). t-files are purely additive, so a
    plain union is faithful here.

    **PACKED t-files count** (fixed 2026-07-27). This used to test `f.is_file()`
    only, so a mod shipping its strings inside ext_01.cat contributed nothing —
    the same blind spot that made iter_diff_files report packed mods as clean.
    Measured on the live modlist: **977 strings exist only in packed t-files**
    (vro 425, ship_variation_expansion 108, xenon_backup 102, ...). Every one was
    a potential false "introduced text reference does not resolve", and Tier B —
    where you patch another mod and quote its strings — is exactly where it bites.

    A t-file that fails to parse is REPORTED, not swallowed: a shrunken def set
    turns into false unresolved-reference errors downstream, and silently
    dropping it is indistinguishable from the string genuinely not existing.
    """
    defs: set[tuple[str, str]] = set()
    sources = ([config.reference] + config.dlc_dirs()
               + list(config.overlays) + list(extra_overlays or []))
    for src in sources:
        for rel in TEXT_FILES:
            f = src / rel
            try:
                if f.is_file():
                    defs |= _refs.text_defs(_merge.parse_file(f))
                    continue
                data = _cat.read_path(src, rel)  # packed: ext_01.cat/.dat
                if data is not None:
                    defs |= _refs.text_defs(_merge.parse_bytes(data))
            except (etree.XMLSyntaxError, OSError) as exc:
                if report is not None:
                    report.skip("text-reference checks",
                                f"{src.name}/{rel}: unreadable, its strings are missing "
                                f"from the definition set ({exc})")
    return defs


def collect_macro_defs(config: _merge.Config, extra_overlays=None,
                       report: Report | None = None) -> set[str] | None:
    """Registered macro names from the EFFECTIVE index/macros.xml, or None.

    Built through build_effective rather than by unioning each directory's file,
    because an extension may ship index/macros.xml as a <diff> containing
    <remove> ops — and may ship it packed inside a .cat. A naive per-directory
    union sees neither, so it reports a macro as defined when the effective index
    no longer contains it. (Real case: xspvro removes
    turret_xen_m_beam_02_mk1_macro without re-adding it, orphaning a vanilla
    macro that six other mods reference.)

    Returns **None** when the index could not be built — never an empty set.
    Both `_refs` consumers gate on this value, and they used to do so by
    truthiness: an empty set silently disabled *every* macro-reference check and
    made ware completeness's `component` field pass unconditionally. "Could not
    read the index" and "the index defines no macros" must not be the same value.
    """
    def _fail(why: str) -> None:
        if report is not None:
            report.skip("macro-reference checks", f"{MACRO_INDEX}: {why}", degraded=True)

    try:
        merged = _merge.build_effective(MACRO_INDEX, config, extra_overlays=extra_overlays)
    except (etree.LxmlError, OSError) as exc:
        _fail(f"could not build the effective macro index ({exc})")
        return None
    if merged.tree is None:
        _fail("no effective macro index (missing from base+DLC and every overlay)")
        return None
    for s in merged.skipped:
        if report is not None:
            report.skip("macro index overlay", s)
    return _refs.macro_names(merged.tree)


def _mod_identity(mod_dir: Path, report: Report | None = None) -> tuple[str, str]:
    """(folder name, content.xml id) for the mod under test; id may be ''.

    An empty id is not free: Tier B excludes the mod's own installed copy by
    folder name AND by id, so losing the id means a mod deployed under a
    different folder name gets merged in as if it were a third-party overlay —
    the mod validated against itself.
    """
    folder = mod_dir.resolve().name
    mod_id = ""
    cx = mod_dir / "content.xml"
    if cx.is_file():
        try:
            mod_id = _merge.parse_file(cx).get("id") or ""
        except etree.XMLSyntaxError as exc:
            if report is not None:
                report.skip("mod identity",
                            f"content.xml will not parse ({exc}) — this mod's own installed "
                            "copy can only be excluded by folder name, not by id")
    return folder, mod_id


@dataclass
class TierB:
    """The two trees a cross-mod check needs. They are NOT interchangeable.

    `patch_time` is truncated at the mod's own load-order position — the tree that
    exists at the moment the engine applies this mod's diffs. `final` is every
    installed extension — the tree that exists once loading is done, which is what
    a *runtime* lookup (does macro X resolve? does ware Y exist?) actually sees.

    Using one for the other's job is wrong in both directions, and `X4CapturableXenonXL`
    demonstrates both at once (measured 2026-07-28 — see `tier_b_overlays`).
    """
    patch_time: tuple[Path, ...] = ()
    final: tuple[Path, ...] = ()
    notes: list[str] = field(default_factory=list)


def tier_b_overlays(mod_dir: Path,
                    report: Report | None = None) -> tuple[tuple[Path, ...], list[str]]:
    """The PATCH-TIME tree only, as `(overlay_dirs, notes)`.

    Thin wrapper over `tier_b_trees` for callers that genuinely only care about the
    tree a `sel=` sees (the diff oracle, ad-hoc scripts). Anything validating a mod
    should use `tier_b_trees` and honour BOTH trees.
    """
    t = tier_b_trees(mod_dir, report)
    return t.patch_time, t.notes


def tier_b_trees(mod_dir: Path, report: Report | None = None) -> TierB:
    """Both installed-extension trees for the mod under test — see `TierB`.

    `patch_time` holds the roots that load BEFORE the mod, which is the tree its
    `sel=` selectors actually see. This is what makes a cross-mod patch
    checkable: Tier A (base+DLC) cannot see a node another mod adds, nor notice
    one another mod removed, so both directions produce false results —
    a false 'sel matched nothing' for the former, a false 'OK' for the latter.

    **Truncated at the mod's own load-order position (fixed 2026-07-26).** Merging
    *every* other mod builds a tree that never exists at the moment this mod is
    patched: a node some LATER mod adds is already present, so an op that the
    engine skips looks fine to us. Measured against the engine's own debug.txt for
    `cpsdo_faction` (192 rejected ops):

        overlays = all others (old)  -> 165 agree, 27 FALSE OK, 3 false alarm
        overlays = those before (new)-> 192 agree,  0 FALSE OK, 3 false alarm

    All 27 were `//wares/ware[@id='ishield_cpsdo_*']/owner/@faction`: `cpsdo_vro`
    *adds* those wares and loads AFTER `cpsdo_faction`, which patches them — neither
    declares a dependency on the other, so the engine runs the patch first and skips
    it. A real upstream bug our optimistic tree was hiding.

    **The two trees ARE now split (2026-07-28).** The limitation this docstring used
    to describe as theoretical was confirmed against the engine, so reference /
    file-existence / connection checks run on `TierB.final` while `sel=` resolution
    keeps this patch-time tree. `X4CapturableXenonXL` (load position 79) proves both
    directions at once, which is why one tree cannot serve both:

      - patch-time is RIGHT for `sel=`: its three `<remove sel="…connection_cockpit">`
        ops match the vanilla node at position 79. Against the final tree they read as
        'sel matched nothing' — 3 false alarms — because `xspvro` (position 92)
        replaces that macro file wholesale.
      - final is RIGHT for references: `xspvro` re-points `ship_xen_xl_carrier_01_a_macro`
        at component `ship_pla_xl_battleship`, which has 243 connections and lacks
        `connection_shieldgen_external03` (vanilla `ship_xen_xl_carrier_01` HAS it).
        The mod's `libraries/loadouts.xml:44` still asks for it, so at runtime the
        loadout is broken — a REAL defect the patch-time tree cannot see, and which
        the deployed copy therefore reported as 0 errors.

    Not engine-logged: a loadout mismatch only surfaces when the ship is instantiated,
    and the reference log is a load-time capture. The chain is verified statically
    instead (load order 79 < 92; both mods ship the macro file, so the later wins).

    The mod under test is excluded by BOTH folder name and content.xml id, since
    a dev folder is usually also deployed under extensions\\ and would otherwise
    be merged in twice (its own ops pre-applied, masking real misses).

    Load order here is the community-reported convention (alphabetical,
    dependencies first) — advisory, not engine-verified.
    """
    notes: list[str] = []

    def _fallback(why: str) -> TierB:
        """Tier B was asked for and could not be built.

        The fallback tree is base+DLC — i.e. Tier A — which cannot see anything
        another mod adds or removes. A cross-mod patch validated against it is
        not validated at all. This used to emit a note and exit 0, so a gate or
        CI step read the run as a pass; it is now a degraded skip, which the CLI
        turns into a non-zero exit.
        """
        if report is not None:
            report.skip("Tier B cross-mod validation",
                        f"{why}; fell back to base+DLC (Tier A) — cross-mod selectors "
                        "cannot resolve against that tree", degraded=True)
        return TierB((), (), [f"Tier B: {why}; fell back to base+DLC only"])

    try:
        mods = _registry.scan_installed()
    except OSError as exc:
        return _fallback(f"could not scan installed mods ({exc})")
    if not mods:
        return _fallback("no installed extensions found")

    folder, mod_id = _mod_identity(mod_dir, report)
    by_folder = {m["folder"]: m for m in mods}
    order = _compat.compute_load_order(mods)

    dirs: list[Path] = []       # patch-time: up to the mod's own position
    final_dirs: list[Path] = []  # runtime: every other installed extension
    skipped = ""
    placed = False
    for name in order:
        m = by_folder.get(name)
        if m is None:
            continue
        if m["folder"] == folder or (mod_id and m["id"] == mod_id):
            # The mod under test is excluded from BOTH trees — merging its own copy
            # would pre-apply its ops and mask exactly the misses we look for.
            skipped, placed = m["folder"], True
            continue  # keep walking: later mods are invisible to selectors, but REAL at runtime
        p = Path(m["path"])
        if p.is_dir():
            final_dirs.append(p)
            if not placed:  # everything after the mod loads LATER — not visible to our selectors
                dirs.append(p)

    if placed:
        notes.append(
            f"Tier B: merged {len(dirs)} extension(s) that load BEFORE this mod "
            f"(of {len(order)} installed) — the tree its selectors actually see")
        notes.append(f"Tier B: excluded the mod under test's installed copy '{skipped}' "
                     "and everything loading after it")
        if len(final_dirs) > len(dirs):
            notes.append(
                f"Tier B: reference/connection checks additionally see the {len(final_dirs) - len(dirs)} "
                "extension(s) loading AFTER it — those are invisible to selectors but real at runtime")
    else:
        # Not installed (dev-only): we cannot place it, so assume it loads last —
        # the optimistic tree. Say so, because that is exactly the FALSE-OK shape.
        notes.append(
            f"Tier B: merged all {len(dirs)} installed extension(s) — this mod is NOT "
            "installed, so its load-order position is unknown and it is assumed to load "
            "LAST. Ops targeting nodes added by a mod that really loads later would be "
            "reported OK here but SKIPPED by the engine; deploy it to place it exactly")
    notes.append("Tier B: load order is the community-reported convention "
                 "(dependencies first, then alphabetical) — advisory, not engine-verified")
    return TierB(tuple(dirs), tuple(final_dirs), notes)


@dataclass
class Finding:
    severity: str   # "error" | "warn" | "info"
    category: str   # "sel" | "ref" | "completeness" | "path"
    message: str
    vpath: str = ""
    line: int = 0


@dataclass
class Skipped:
    """A piece of work the validator could NOT do.

    Every false-pass this tool has ever shipped had the same shape: a helper hit
    an unreadable file, returned a falsy sentinel (`set()` / `[]` / `None`), and
    the caller could not tell "found nothing" from "could not look". With no
    channel to say *"I did not check this"*, silence rendered as OK.

    *degraded* = the skip disabled an ENTIRE check, so a clean run is not
    evidence of correctness and the CLI exits non-zero. A partial skip (one
    unreadable file among many) is reported but does not gate.
    """
    what: str       # which check / input was affected
    why: str        # the concrete reason, including the exception text
    degraded: bool = False


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Work that was NOT done. See the Skipped docstring — this is the channel
    #: whose absence caused every "nothing examined rendered as OK" defect.
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def degraded(self) -> list[Skipped]:
        """Skips that disabled a whole check — the run cannot be trusted as a pass."""
        return [s for s in self.skipped if s.degraded]

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    def skip(self, what: str, why: str, degraded: bool = False) -> None:
        self.skipped.append(Skipped(what, why, degraded))


def iter_diff_files(mod_dir: Path):
    """Yield (virtual_path, diff_root) for every <diff> file in the mod.

    Delegates to iter_mod_xml_roots so PACKED mods are covered too. Until
    2026-07-26 this walked mod_dir.rglob("*.xml") directly, which finds nothing in
    a mod shipped as ext_01.cat/.dat — so sel-resolution, the tool's core check,
    silently examined ZERO ops and the run printed "OK: no issues found". That is a
    whole-mod false pass: `moreroomsforships` reported clean while the engine was
    rejecting 6 of its ops. 9 of the 10 mods with cardinality failures in the
    reference log are packed, so this blind spot covered most of the real damage.
    """
    for vpath, root in iter_mod_xml_roots(mod_dir):
        if root.tag == "diff":
            yield vpath, root



def iter_mod_xml_roots(mod_dir: Path, predicate=None):
    """Yield (virtual_path, root) for every XML file owned by a mod.

    Thin wrapper over `_scan.iter_mod_xml` — loose wins over packed, matching
    the engine. Files that will not parse are skipped here and reported ONCE by
    `check_readability`, rather than at each of this function's eight call sites.
    """
    yield from _scan.iter_mod_xml(mod_dir, predicate)


#: Directory segments whose contents the engine never loads — a mod's own
#: scratch space. A malformed file in one of these is untidy, not broken.
#: Measured over 100 installed mods: 10 of the 12 unparseable files live here
#: (all in VRO's tmp/, backup/ and md_debug/), so without this split the check
#: would be 83% noise.
SCRATCH_DIRS = frozenset({"tmp", "backup", "backups", "old", "unused", "md_debug", ".git"})


def check_readability(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Report every XML file in the mod that will not parse.

    Until 2026-07-28 these vanished: `iter_mod_xml_roots` ended both its branches
    in a bare `except XMLSyntaxError: continue`. Neither nearby guard covered it —
    `MergeResult.skipped` is a different code path (overlay-tree parses), and the
    "checked == 0" warning only fires at *zero*, so five good diffs plus one
    malformed printed nothing at all.

    A file at a real content path is also a `warn`: the engine's parser is no more
    forgiving than lxml, so it cannot load that file either. Confirmed live on two
    installed mods — `cpsdo_faction/t/0001-l088.xml` (stray `</t>`, drops a whole
    Traditional-Chinese page) and `xspvro/assets/units/size_xl/xen_shell.xml`
    (`<offset>`/`<lights>` mis-nested, drops a component).
    """
    # No manifest = not an extension. X4 discovers mods by content.xml, so a folder
    # without one is never loaded and every verdict below it is about a file the
    # engine will not read. Reporting that clean is a false pass about the whole run,
    # so it gates. Packed mods keep content.xml LOOSE (it is read before the catalog),
    # so this is safe for them too.
    if not (mod_dir / MANIFEST).is_file():
        report.skip("this folder as an extension",
                    f"no {MANIFEST} — X4 discovers extensions by their manifest, so it "
                    "would never load this folder at all", degraded=True)

    unreadable: list[_scan.Unreadable] = []
    for _ in _scan.iter_mod_xml(mod_dir, unreadable=unreadable):
        pass
    for u in unreadable:
        segments = {s.lower() for s in u.vpath.split("/")[:-1]}
        scratch = bool(segments & SCRATCH_DIRS)
        report.skip("this file was not examined at all",
                    f"{u.vpath}: will not parse ({u.why})")
        if not scratch:
            report.add("warn", "parse",
                       f"file will not parse, so the engine cannot load it either: {u.why}",
                       u.vpath)


def _check_ops(diff_root, tree, vpath: str, report: Report) -> None:
    """Evaluate every diff op's sel= against *tree*; flag non-matches.

    Mirrors _merge.apply_diff's gate order exactly: if= is evaluated FIRST, and a
    falsy guard skips the op — so its sel= is never reached and must not be
    reported as a failure. An if=-guarded op that matches nothing is a *designed*
    no-op (the idiom for targeting content from a mod that may not be installed),
    not an error.
    """
    for op in diff_root:
        if not isinstance(op.tag, str) or op.tag not in _merge._OPS:
            continue
        sel = op.get("sel", "")
        line = op.sourceline or 0
        silent = _merge._truthy(op.get("silent"))

        cond = op.get("if")
        if cond:
            try:
                gate_open = bool(tree.xpath(cond))
            except etree.XPathEvalError as exc:
                report.add("error", "sel", f"<{op.tag}> invalid if= ({exc})", vpath, line)
                continue
            if not gate_open:
                report.add("info", "sel",
                           f"<{op.tag}> skipped: if= is false ({cond}) — "
                           "guarded no-op, sel= not evaluated", vpath, line)
                continue

        try:
            hits = tree.xpath(sel)
        except etree.XPathEvalError as exc:
            report.add("error", "sel", f"<{op.tag}> invalid sel= ({exc})", vpath, line)
            continue
        if not hits:
            # A guard that IS open but whose sel still misses is a real problem:
            # the author asserted the target should exist.
            sev = "warn" if silent else "error"
            report.add(sev, "sel",
                       f"<{op.tag}> sel matched nothing: {sel}"
                       + (" (silent)" if silent else "")
                       + (f" [if= passed: {cond}]" if cond else ""), vpath, line)
        elif len(hits) > 1:
            # The OTHER silent no-op: X4 requires sel to match exactly one node
            # (RFC 5261). On multiple matches it logs "Multiple matching nodes ...
            # Skipping node" and applies NOTHING — the patch looks fine but does
            # nothing. Disambiguate with a predicate.
            report.add("error", "sel",
                       f"<{op.tag}> sel matched {len(hits)} nodes (must match exactly 1 "
                       f"— the engine SKIPS ambiguous ops, so this silently does nothing): {sel}",
                       vpath, line)


def _installed_folders() -> set[str] | None:
    """Lowercased folder names of every installed extension, or None if unscannable.

    None, not `set()`: an empty set means "no mods are installed", which reads as
    a definite fact about the world. The caller must be able to tell that apart
    from "the extensions directory could not be listed".
    """
    try:
        return {m["folder"].lower() for m in _registry.scan_installed()}
    except OSError:
        # silent-ok: None is this function's whole contract (see docstring) —
        # distinct from set(). _path_verdict branches on it and reports
        # "unverifiable" rather than silently excusing the patch.
        return None


def _no_base_finding(vpath: str, config: _merge.Config) -> tuple[str, str, str]:
    """(severity, category, message) for a file whose base tree could not be built.

    A NESTED cross-mod patch — `extensions/<target>/<rel>` — whose <target> is not
    installed is a DESIGNED no-op, not an error: compatibility-patch mods ship
    patches for dozens of optional targets and you only have some. The engine simply
    never loads that file. Treating it as an error is the same mistake as flagging an
    `if=`-guarded op whose guard is false, and it is loud: enabling packed-mod input
    made `moreroomsforships` report 76 errors, of which 72 were absent targets.

    `extensions/ego_dlc_*/...` is a SEPARATE case, because `_nested_target` treats
    `ego_dlc_*` as ordinary base content living in `reference/extensions/` — which is
    only true for DLC that were actually unpacked there. Real case: `ego_dlc_mini_01`
    (Hyperion Pack) and `ego_dlc_mini_02` (Envoy Pack) are genuinely INSTALLED and
    PACKED in the live game (`extensions/ego_dlc_mini_01/ext_01.cat`), but `reference/`
    was only ever unpacked for the 6 DLC named in CLAUDE.md — these two are simply
    missing from it. So this is not "target not installed" (it is), and not "path
    mismatch" (the file may genuinely exist) — it is "cannot verify with the reference
    we have". Reporting it as ERROR asserts non-existence we cannot actually back up.

    Target installed but no base found is still a real error — that is a genuine
    path mismatch or a file the target does not actually ship.
    """
    nested = _merge._nested_target(vpath, config.packed_dlc_names())
    if nested is not None:
        installed = _installed_folders()
        if installed is None:
            # Could not list the extensions dir. Downgrading to "not installed"
            # would silently excuse a genuine path mismatch; saying so is the
            # only honest option.
            return ("info", "unverifiable",
                    f"patch targets extension '{nested[0]}', but the installed extension "
                    "set could not be listed — cannot tell an inactive patch from a broken path")
        # A packed-only DLC is owned like a mod (so it lands here) but is NOT in
        # scan_installed, which filters ego_dlc_* out. Calling it "not installed"
        # would be flatly false.
        if nested[0].lower() not in installed | config.packed_dlc_names():
            return ("info", "inactive",
                    f"patch targets extension '{nested[0]}', which is not installed — "
                    "the engine never loads this file (designed no-op, not an error)")
    parts = vpath.split("/")
    if len(parts) > 1 and parts[0] == "extensions" and parts[1].lower().startswith("ego_dlc_"):
        dlc = parts[1]
        known = {d.name.lower() for d in config.dlc_dirs()}
        if dlc.lower() not in known:
            return ("info", "unverifiable",
                    f"targets DLC '{dlc}', which is installed but was never unpacked into "
                    "reference/ — cannot verify this path exists (not a confirmed error)")
    return ("error", "path",
            f"no base game file for '{vpath}' (path mismatch? this patch can never apply)")


def _inert_bare_path_finding(vpath: str, merged: _merge.MergeResult) -> tuple[str, str, str]:
    """(severity, category, message) for a <diff> the engine never loads at all.

    A patch aimed at ANOTHER MOD's file must live at `extensions/<owner>/<rel>` inside
    your mod. At the BARE mirrored path it is inert: the engine only consults
    reference/ + DLC for that path, finds the file is not base-game content, and never
    opens the file. Nothing is logged, no op is rejected, and the mod loads clean — the
    quietest failure in X4 modding.

    Proven 2026-08-01 from a two-run debug.txt, on ONE identical rel path under
    `assets/units/size_s/macros/`, with three mods involved: the file's OWNER is
    logged; a second mod's NESTED patch (`extensions/<owner>/<rel>`) of it is logged
    AND has its op evaluated (`[=ERROR=] No matching node ... @makerrace`); a third
    mod's BARE-path patch of the same path is absent from both runs — even though
    that mod is loaded, its own base-game-path files being logged three times.
    Same path, same load, three mods, two logged and one not.

    Why this needs its own finding rather than falling out of the existing
    `_no_base_finding`: under Tier B an installed mod's full file satisfies `base_found`
    (`_merge.build_effective`'s `base_found or mode in {union, full}`), so `merged.tree`
    is non-None and the Tier A error is silently CURED by installing more mods. Measured
    on the live 101-mod install: Tier A reports these 7 files, Tier B reports 0 errors and
    exits 0 — a false OK, in the tier the convention tells you to use for cross-mod work.
    """
    # Only union/full contributors SUPPLY the file; a `diff` contributor is another
    # mod patching it, exactly as this mod is. Listing patchers as suppliers would
    # send the reader to move their file under a mod that does not own it — the
    # wrong-reason failure that stops the next person checking.
    suppliers = [s.rsplit(":", 1)[0] for s in merged.sources
                 if s.rsplit(":", 1)[-1] in {"union", "full", "owner"}]
    owner = suppliers[0] if suppliers else "<owner>"
    who = ", ".join(suppliers) if suppliers else "another mod, not the base game"
    return ("error", "path",
            f"'{vpath}' is not a base game file — it is supplied by {who}. "
            f"A patch over another MOD's file must live at "
            f"'extensions/{owner}/{vpath}' inside your mod; at this bare path "
            f"the engine never loads it (silent no-op, no log line, no rejected op)")


#: Ops in ONE file beyond which validation gets visibly slow. Applying a diff is
#: O(n^2) in ops-per-file — every op re-evaluates its selector against a tree the
#: previous ops just grew — so cost rises ~3.5x each time the count doubles
#: (measured 2026-08-08). That is inherent to "N ops x a full-tree evaluation",
#: not a defect to optimize away: an op cannot reuse a match the op before it
#: invalidated. The threshold is ~3x the largest file in a real ~120-mod install
#: (1,443 ops, about 0.03s), so normal content never trips it and nobody is left
#: staring at an apparent hang with no explanation.
_LARGE_OP_COUNT = 5000


def _warn_if_pathologically_large(diff_root, vpath: str, report: Report) -> None:
    n = sum(1 for op in diff_root if isinstance(op.tag, str))
    if n >= _LARGE_OP_COUNT:
        report.add("info", "path",
                   f"{n} ops in one file — validation is O(n^2) in ops-per-file, so "
                   f"this file alone may take a while (typical mods ship under 1,500)",
                   vpath)


def check_sel_resolution(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Flag any non-silent op whose sel= matches nothing in the merged base+DLC tree."""
    checked = 0
    seen_skips: set[str] = set()
    for vpath, diff_root in iter_diff_files(mod_dir):
        checked += 1
        _warn_if_pathologically_large(diff_root, vpath, report)
        merged = _merge.build_effective(vpath, config)
        # An overlay we could not parse was left out of this tree, so every verdict
        # below is computed against an incomplete tree. That disables the check's
        # premise, not one file — the Skipped docstring's definition of degraded.
        for msg in merged.skipped:
            if msg not in seen_skips:
                seen_skips.add(msg)
                report.skip(f"sel-resolution against a complete tree ({vpath})",
                            f"an overlay could not be parsed, so the comparison tree is "
                            f"incomplete: {msg}", degraded=True)
        if merged.tree is None:
            report.add(*_no_base_finding(vpath, config), vpath)
            continue
        if (not merged.base_from_game
                and _merge._nested_target(vpath, config.packed_dlc_names()) is None):
            # Some mod supplies this file, but the GAME does not — so a bare-path diff
            # over it is inert. Deliberately `continue` without _check_ops: its verdict
            # on a file the engine never opens is noise, and "sel resolves fine" on a
            # dead patch is exactly the false reassurance this finding exists to kill.
            report.add(*_inert_bare_path_finding(vpath, merged), vpath)
            continue
        _check_ops(diff_root, merged.tree, vpath, report)

    # Always state the denominator. "OK: no issues found" over 14 files and over 1
    # file printed identically until 2026-08-01, for the tool's PRIMARY check.
    payload = [v for v, _ in iter_mod_xml_roots(mod_dir) if v.lower() != MANIFEST]
    report.notes.append(
        f"sel-resolution: {checked} diff file(s) checked "
        f"across {len(payload)} payload XML file(s)")

    if checked:
        return
    # Nothing was sel-checked. That has three causes with three different verdicts,
    # and until 2026-08-01 all three produced one warning asserting the third —
    # via report.add("warn", "skipped", ...), which LOOKS like the skip channel but
    # creates a Finding, so report.degraded stayed empty and the CLI exited 0.
    #
    # Measured over the 102 installed mods before this was written: 16 additive-only,
    # 1 asset-only (XTex: 0 XML but 4695 catalog members), 0 unreadable. Marking all
    # of them degraded would have been a second half-fix — 17 false exit-3s.
    if payload:
        report.notes.append(
            "sel-resolution: this mod is additive-only — it ships payload XML but no "
            "<diff>, so there are no selectors to resolve (not a problem)")
    elif _cat.is_packed(mod_dir):
        # Packed with no XML is normal for a texture/shader mod, but only if the
        # catalog actually OPENED. XTex is the live example: 0 XML members, 4695
        # total. An empty vfs means the .cat/.dat could not be read.
        if _cat.mod_vfs(mod_dir, xml_only=False):
            report.notes.append(
                "sel-resolution: this mod is packed and ships no XML (assets only) — "
                "there is nothing for the selector check to examine")
        else:
            report.skip("sel-resolution", "this mod is packed but not one catalog member "
                        "could be read — the .cat/.dat could not be opened", degraded=True)
    elif any(p.is_file() and p.name.lower() != MANIFEST for p in mod_dir.rglob("*")):
        report.notes.append(
            "sel-resolution: this mod ships loose assets but no XML — there is nothing "
            "for the selector check to examine")
    else:
        # Nothing but a manifest. Not an extension the engine can do anything with,
        # and reporting it clean is the same false pass this branch exists to end.
        report.skip("sel-resolution", "this folder contains nothing but content.xml — "
                    "no payload of any kind was found to check", degraded=True)


def check_sel_resolution_one(file_path: Path, mod_dir: Path,
                             config: _merge.Config, report: Report) -> None:
    """Fast path: sel-resolution for ONE edited file (the auto-validate hook)."""
    try:
        root = _merge.parse_file(file_path)
    except etree.XMLSyntaxError as exc:
        report.add("error", "sel", f"unparseable XML: {exc}", str(file_path))
        return
    except OSError as exc:
        # Missing/unreadable file. lxml raises OSError here, not XMLSyntaxError,
        # so the narrower catch above let a plain typo escape as a traceback.
        report.add("error", "path", f"cannot read file: {exc}", str(file_path))
        return
    if root.tag != "diff":
        return
    try:
        vpath = file_path.relative_to(mod_dir).as_posix()
    except ValueError:
        vpath = file_path.name
    merged = _merge.build_effective(vpath, config)
    if merged.tree is None:
        report.add("error", "path", f"no base game file for '{vpath}'", vpath)
        return
    _check_ops(root, merged.tree, vpath, report)


def _added_subtrees(diff_root: etree._Element):
    """Wrap each <add>'s children in a throwaway root so refs can be scanned."""
    for op in diff_root:
        if isinstance(op.tag, str) and op.tag == "add":
            holder = etree.Element("_added")
            for child in op:
                if isinstance(child.tag, str):
                    holder.append(child)  # move into holder; fine, diff_root is discarded
            yield holder


def check_references(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Flag references the mod *introduces* that resolve to no definition."""
    mod_overlay = [mod_dir]
    wares_merged = _merge.build_effective(WARES_FILE, config, extra_overlays=mod_overlay)
    ware_def_set = _refs.ware_defs(wares_merged.tree)
    text_def_set = collect_text_defs(config, mod_overlay, report)
    macro_def_set = collect_macro_defs(config, mod_overlay, report)
    report.notes.append(
        f"reference defs: {len(ware_def_set)} wares, {len(text_def_set)} text strings, "
        + (f"{len(macro_def_set)} macros" if macro_def_set is not None
           else "macros NOT CHECKED (index unreadable)"))

    for vpath, diff_root in iter_diff_files(mod_dir):
        for holder in _added_subtrees(diff_root):
            for d in _refs.find_dangling(holder, ware_def_set, text_def_set, macro_def_set, where=vpath):
                report.add("error", "ref",
                           f"introduced {d.kind} reference does not resolve: {d.ref}", vpath, d.line)


def check_file_existence(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """For each <component ref="X_macro"> the mod introduces, verify the whole
    chain resolves to real files: macro registered -> macro file -> its component
    -> component file."""
    mod_overlay = [mod_dir]
    macro_index = _resolve.build_index(config, mod_overlay, _resolve.MACRO_INDEX, report)
    component_index = _resolve.build_index(config, mod_overlay, _resolve.COMPONENT_INDEX, report)
    seen: set[str] = set()
    for vpath, diff_root in iter_diff_files(mod_dir):
        for holder in _added_subtrees(diff_root):
            for comp in holder.xpath("//component[@ref]"):
                macro = comp.get("ref")
                if macro in seen:
                    continue
                seen.add(macro)
                for msg in _resolve.macro_component_links(macro, macro_index, component_index):
                    report.add("error", "file", msg, vpath, comp.sourceline or 0)


def check_page_collisions(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Warn when the mod's added {page,t} pairs already exist in base/DLC (silent clobber)."""
    existing = collect_text_defs(config, report=report)  # base + DLC only (NOT the mod)
    for vpath, diff_root in iter_diff_files(mod_dir):
        added: set[tuple[str, str]] = set()
        for holder in _added_subtrees(diff_root):
            added |= _refs.text_defs(holder)
        for page, t in sorted(added & existing):
            report.add("warn", "text",
                       f"text {{{page},{t}}} already defined in base/DLC — your add clobbers it", vpath)



def check_text_sanity(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Warn on literal newlines inside text DB entries.

    X4 imports multiline <t> values but logs TextDB converter errors for them.
    Treat this as cleanup-worthy log noise rather than a gating loader failure.
    """
    for vpath, root in iter_mod_xml_roots(mod_dir):
        if not vpath.lower().startswith("t/"):
            continue
        for page in root.xpath("//page[@id]"):
            pid = page.get("id")
            for t in page.xpath(".//t[@id]"):
                text = "".join(t.itertext())
                if "\n" in text or "\r" in text:
                    report.add("warn", "text",
                               f"text {{{pid},{t.get('id')}}} contains a literal newline; "
                               "X4 logs this during TextDB import", vpath, t.sourceline or 0)


def _race_defs(config: _merge.Config, extra_overlays=None) -> set[str]:
    races = _merge.build_effective(RACES_FILE, config, extra_overlays=list(extra_overlays or []))
    if races.tree is None:
        return set()
    return set(races.tree.xpath("//race/@id"))


def check_identity_values(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Gate on identification makerrace values that are not real races.

    Factions such as 'loanshark' are valid in owner/job contexts but invalid
    as makerrace values; the engine reports these as race-list import errors.
    """
    races = _race_defs(config, [mod_dir])
    if not races:
        report.add("warn", "identity", f"could not resolve race definitions from {RACES_FILE}")
        return
    for vpath, root in iter_mod_xml_roots(mod_dir):
        for ident in root.xpath("//identification[@makerrace]"):
            race = ident.get("makerrace")
            if race and race not in races:
                report.add("error", "identity",
                           f"identification makerrace='{race}' is not a valid race id",
                           vpath, ident.sourceline or 0)


def _tag_set(value: str | None) -> frozenset[str]:
    return frozenset((value or "").split())


def check_engine_connection_tags(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Gate on non-identical engine compatibility tags within one component."""
    for vpath, root in iter_mod_xml_roots(mod_dir):
        if not vpath.lower().startswith("assets/"):
            continue
        for comp in root.xpath("//component[@name]"):
            engines: list[tuple[str, frozenset[str], int]] = []
            for conn in comp.xpath(".//connection[@name][@tags]"):
                tags = _tag_set(conn.get("tags"))
                if "engine" in tags:
                    engines.append((conn.get("name"), tags, conn.sourceline or 0))
            if len(engines) < 2:
                continue
            by_tags: dict[frozenset[str], list[str]] = {}
            for name, tags, _line in engines:
                by_tags.setdefault(tags, []).append(name)
            if len(by_tags) <= 1:
                continue
            detail = "; ".join(
                f"{','.join(names)}=[{' '.join(sorted(tags))}]"
                for tags, names in sorted(by_tags.items(), key=lambda item: sorted(item[1])[0])
            )
            report.add("error", "connection",
                       f"component '{comp.get('name')}' has non-identical engine connection tags: {detail}",
                       vpath, engines[0][2])


def check_connections(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Verify every <loadout> `path` resolves to a <connection> on the ship's component.

    Catches the engine/weapon/shield re-attach failure mode (loadout points at a
    connection the mesh doesn't have). Skips silently when the component can't be
    resolved (avoids false positives)."""
    mod_overlay = [mod_dir]
    macro_index = _resolve.build_index(config, mod_overlay, _resolve.MACRO_INDEX, report)
    component_index = _resolve.build_index(config, mod_overlay, _resolve.COMPONENT_INDEX, report)
    conn_cache: dict[str, set[str] | None] = {}

    def conns_for_component(comp_ref: str | None) -> set[str] | None:
        if not comp_ref:
            return None
        if comp_ref not in conn_cache:
            cf = _resolve.read_indexed(component_index, comp_ref)
            conns = _resolve.connections_of(cf.data) if cf else None
            if cf and conns is None:
                report.skip("connection checks",
                            f"component '{comp_ref}' ({cf.display.name}): unreadable, its loadout "
                            "targets were not verified")
            conn_cache[comp_ref] = conns
        return conn_cache[comp_ref]

    def component_of_macro(macro_name: str) -> str | None:
        mf = _resolve.read_indexed(macro_index, macro_name)
        if mf is None:
            return None
        try:
            mr = _merge.parse_bytes(mf.data)
        except etree.XMLSyntaxError as exc:
            report.skip("connection checks",
                        f"macro '{macro_name}' ({mf.display.name}): will not parse ({exc}), "
                        "its loadout targets were not verified")
            return None
        refs = mr.xpath(f"//macro[@name={_resolve._xq(macro_name)}]/component/@ref")
        return refs[0] if refs else None

    def check_loadout(lo, comp_ref, vpath, label):
        conns = conns_for_component(comp_ref)
        if conns is None:
            return
        for conn_name, line in _resolve.loadout_targets(lo):
            if conn_name not in conns:
                report.add("error", "connection",
                           f"loadout {label} references connection '{conn_name}' "
                           f"not on component '{comp_ref}'", vpath, line)

    for vpath, root in iter_mod_xml_roots(mod_dir):
        # Inline loadouts: <macro ...><loadouts>... (component ref in the same macro)
        for macro in root.xpath("//macro[.//loadout]"):
            crefs = macro.xpath("./component/@ref")
            comp_ref = crefs[0] if crefs else None
            for lo in macro.xpath(".//loadout"):
                check_loadout(lo, comp_ref, vpath, f"in {macro.get('name')}")
        # Centralized loadouts.xml: <loadout macro="M">
        for lo in root.xpath("//loadout[@macro]"):
            check_loadout(lo, component_of_macro(lo.get("macro")), vpath, f"for {lo.get('macro')}")


def check_variant_consistency(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Warn when the mod patches one ship variant macro but not its base siblings
    (per-variant props like hull/cargo/loadout won't change for the untouched ones)."""
    for path in sorted(mod_dir.rglob("*.xml")):
        if not path.is_file():
            continue
        m = VARIANT_RE.match(path.name)
        if not m:
            continue
        vpath = path.relative_to(mod_dir).as_posix()
        vdir = vpath.rsplit("/", 1)[0] if "/" in vpath else ""
        ref_dir = config.reference / vdir
        if not ref_dir.is_dir():
            continue
        siblings = sorted(p.name for p in ref_dir.glob(f"{m.group('base')}_*_macro.xml"))
        if len(siblings) < 2:
            continue
        untouched = [s for s in siblings if s != path.name and not (mod_dir / vdir / s).exists()]
        if untouched:
            report.add("warn", "variant",
                       f"patched '{path.name}' but not sibling variant(s) {', '.join(untouched)} "
                       "— per-variant props (hull/cargo/loadout) won't change for them", vpath)


def check_completeness(
    mod_dir: Path, config: _merge.Config, report: Report, entity: str, like: str
) -> None:
    """entity/like are 'ware:<id>' specs (v1 supports the ware type)."""
    etype, _, eid = entity.partition(":")
    ltype, _, lid = like.partition(":")
    # ware / ship / module are all <ware> entries; the analogue defines the footprint.
    entity_types = {"ware", "ship", "module"}
    if etype not in entity_types or ltype not in entity_types:
        report.add("info", "completeness",
                   f"completeness supports {sorted(entity_types)}; got '{etype}'/'{ltype}'")
        return
    mod_overlay = [mod_dir]
    wares = _merge.build_effective(WARES_FILE, config, extra_overlays=mod_overlay)
    text_def_set = collect_text_defs(config, mod_overlay, report)
    macro_def_set = collect_macro_defs(config, mod_overlay, report)
    rep = _refs.ware_completeness(eid, lid, wares.tree, text_def_set, macro_def_set)
    report.notes.append(f"completeness checked kinds: {', '.join(rep.checked)}")

    # A nonexistent --like analogue makes every comparison vacuous: its footprint
    # is all-False, so `missing` is empty and the old code cheerfully reported
    # "matches the footprint". Bail before that, and say which id was not found.
    if rep.analogue_missing:
        report.add("error", "completeness",
                   f"analogue '{lid}' does not exist in the effective wares tree — "
                   "nothing to compare against, so this check did not run "
                   "(check the --like id, or whether the mod defining it is installed)")
        report.skip("completeness", f"--like analogue '{lid}' not found", degraded=True)
        return
    if rep.entity_missing:
        report.add("error", "completeness",
                   f"entity '{eid}' does not exist in the effective wares tree — "
                   "the mod does not define it (check the --entity id)")
        return
    if not rep.missing:
        report.add("info", "completeness", f"ware '{eid}' matches the footprint of '{lid}'")
    for kind in rep.missing:
        report.add("error", "completeness",
                   f"ware '{eid}' is missing '{kind}' that analogue '{lid}' has")


def _relpath(abs_file: str, mod_dir: Path) -> str:
    try:
        return Path(abs_file).relative_to(mod_dir).as_posix()
    except ValueError:
        return abs_file


def check_migration(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Runtime-only 9.0 breakages (dead APIs / deprecated Lua) the XSD can't catch."""
    unreadable: list[str] = []
    for m in _migration.scan_mod(mod_dir, unreadable):
        report.add("warn", "migration", f"{m.note}  [{m.snippet}]", _relpath(m.file, mod_dir), m.line)
    for u in unreadable:
        report.skip("9.0 migration scan", f"{u} — not scanned for dead APIs")


def check_exprlint(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Heuristic lint of the script-expression grammar inside attribute VALUES —
    the layer XSD is blind to (it validates structure, treats values as opaque
    strings). ADVISORY only (warn/info, never gating): a regex heuristic flags for
    review; the authoritative gate is the --debug debug.txt correlation."""
    for f in _exprlint.scan_mod(mod_dir):
        report.add(f.severity, "exprlint", f"{f.note}  [{f.snippet}]", f.vpath, f.line)


def _script_name_map(mod_dir: Path) -> dict[str, str]:
    """name -> vpath for the mod's own mdscript/aiscript files (their root
    `name=` attribute). Resolves debug.txt runtime errors (which name a SCRIPT,
    not a file) back to a file."""
    out: dict[str, str] = {}
    for vpath, root in _xref._iter_mod_files(mod_dir):
        if isinstance(root.tag, str) and root.tag in ("mdscript", "aiscript"):
            name = root.get("name")
            if name:
                out[name] = vpath
    return out


def _mod_ids(mod_dir: Path) -> set[str]:
    """Identity tokens this mod owns in an extensions\\<folder> path: its dev
    folder name plus its content.xml id (they can differ)."""
    ids = {mod_dir.name.lower()}
    cx = mod_dir / "content.xml"
    if cx.is_file():
        try:
            mid = _merge.parse_file(cx).get("id")
            if mid:
                ids.add(mid.lower())
        except (etree.XMLSyntaxError, OSError):
            # silent-ok: the folder name (already in `ids`) is the identity that
            # matters for an extensions/<folder> path; the content.xml id is a
            # bonus alias. _mod_identity reports the same unreadable file.
            pass
    return ids


def check_debug_correlation(mod_dir: Path, config: _merge.Config, report: Report,
                            debug_path: str | Path) -> None:
    """Fold the ENGINE's own [=ERROR=] lines for THIS mod into the report — the
    authoritative layer static checks can't provide. Engine errors GATE (exit 1);
    engine warnings advise. Staleness caveat: pass a debug.txt captured AFTER the
    latest edits — a gate on a stale log is a false failure."""
    entries = _debuglog.parse_debug(debug_path)
    if not entries:
        report.notes.append(f"debug: no [=ERROR=] lines parsed from '{debug_path}' "
                            "(clean log, or wrong path / pre-load capture)")
        return
    ids = _mod_ids(mod_dir)
    names = _script_name_map(mod_dir)
    matched = 0
    diffops = 0
    for e in entries:
        if e.ident_kind == "path":
            if e.folder.lower() not in ids:
                continue
            # Shapes E/F name the patch file WITHOUT its extension — resolve it back
            # to the real file so the finding points somewhere openable.
            vpath = e.vpath
            for cand in _debuglog.xml_candidates(e.vpath):
                if (mod_dir / cand).is_file():
                    vpath = cand
                    break
        else:  # "script" — resolve name -> file via the mod's own scripts
            vpath = names.get(e.script_name)
            if vpath is None:
                continue
        matched += 1
        if e.cardinality:
            diffops += 1
        report.add(e.severity, "debug", f"(engine) {e.message}", vpath, e.line)
    report.notes.append(
        f"debug: {matched} engine finding(s) matched this mod from '{debug_path}' "
        f"(of {len(entries)} total in the log)"
        + (f"; {diffops} are diff-op cardinality failures — the engine SKIPPED those "
           "ops, so those patches silently did nothing" if diffops else "")
        + ("" if matched else " — clean load for this mod, or a stale/other-mod log"))


def check_xsd(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Validate MD/aiscript files against the bundled schemas (the 9.0 migration
    backbone). SLOW (~100s schema warmup) — only via --update, never the default.

    CATEGORIZE, don't gate: `md.xsd` is STRICTER than the actual engine (it rejects
    lowercase script/cue names and extra-but-tolerated attributes that working mods
    use). Evidence-based gating:
      GATE (error)    = 'required but missing' (loader enforces required attrs) AND
                        'element not expected' (an action not in the engine's schema
                        -> likely removed/renamed; safer to flag for review than miss).
      ADVISORY (info) = 'attribute not allowed' + name-pattern facets + key cascades
                        (the *evidenced* engine-tolerance noise from real mods).
    NOTE: nothing is hidden — advisories are still reported; categorization only sets
    severity + exit code. Authority on what truly breaks = the Migration Map + in-game test."""
    findings, checked, skipped = _xsd.validate_mod(mod_dir, config)

    def _gates(msg: str) -> bool:
        return "is required but missing" in msg or "is not expected" in msg

    high = [f for f in findings if _gates(f.message)]
    low = [f for f in findings if not _gates(f.message)]
    report.notes.append(
        f"XSD: {checked} validated — {len(high)} gating breakage(s) "
        f"(required-attr / removed-element), {len(low)} schema-strict "
        f"advisor{'y' if len(low) == 1 else 'ies'} (md.xsd stricter than the engine)")
    for f in high:
        report.add("error", "xsd", f.message, _relpath(f.file, mod_dir), f.line)
    for f in low:
        # F7's dead-attr class gets its OWN CATEGORY here but stays INFO — never
        # promote it to error on the MD side. Deliberate asymmetry with
        # check_effective_schema: MD attributes can be spawn-time engine features
        # that neither debug.txt nor a static pass can settle (the four
        # kuertee_atd attributes, audit F8, deliberately left unresolved by the
        # user). The distinct category makes the class queryable without gating
        # a working released mod on an unsettleable question.
        cat = ("xsd-unknown-attr"
               if _xsd.dead_attr(f.message, config) else "xsd-strict")
        report.add("info", cat, f.message, _relpath(f.file, mod_dir), f.line)


def _faction_defs(config: _merge.Config, extra_overlays=None) -> set[str]:
    f = _merge.build_effective(FACTIONS_FILE, config, extra_overlays=list(extra_overlays or []))
    if f.tree is None:
        return set()
    return set(f.tree.xpath("//faction/@id"))


def _schema_gates(msg: str) -> bool:
    """Same evidence-based split `check_xsd` uses, applied to merged data files.

    GATE on structural breakage — a missing required attribute or an element the
    content model does not admit. Those are what a bad diff produces, and the
    measured examples are all real (an orphaned `<limits>`, a `<filter>` placed
    under `<sound>` when every one of vanilla's 309 sits under `<effects>`).

    ADVISORY for attribute-not-allowed, facet failures and key-constraint
    cascades: these are where the bundled XSDs lag the engine. Nothing is hidden
    either way — this only sets severity and the exit code.
    """
    return "is required but missing" in msg or "is not expected" in msg


def check_effective_schema(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Schema-validate the EFFECTIVE merged tree for every data file the mod patches.

    Differential: baseline (everything but this mod) vs baseline+mod, and only the
    delta is reported. `_xsd.introduced` documents why that is mandatory rather
    than merely tidy.

    Under Tier B the baseline already contains the other installed mods, so their
    damage is subtracted out too and what remains is this mod's own contribution.
    """
    lib = config.reference / "libraries"
    defs: dict[str, set[str]] = {}
    checked = suppressed = 0
    #: Counted rather than silently `continue`d, so the note can say WHY nothing was
    #: validated. `new_files` is the known gap: a file the mod introduces has no base
    #: to difference against, so it gets no schema check at all.
    new_files = no_schema = 0
    seen: set[str] = set()

    for vpath, _root in iter_mod_xml_roots(mod_dir):
        v = vpath.replace("\\", "/")
        if v.lower() in seen or not _xsd.eligible(v):
            continue
        seen.add(v.lower())

        base = _merge.build_effective(v, config)
        if base.tree is None:
            new_files += 1  # brand-new file: nothing to difference against
            continue
        schema_path, why_not = _xsd.schema_of(base.tree, lib, v)
        if why_not:
            report.skip(f"schema check for {v}", why_not)
            continue
        if schema_path is None:
            no_schema += 1  # macros, components, wares.xml — not a finding
            continue

        before, why_not = _xsd.errors_against(base.tree, schema_path)
        merged = _merge.build_effective(v, config, extra_overlays=[mod_dir])
        if why_not or merged.tree is None:
            report.skip(f"schema check for {v}",
                        why_not or "the merged tree could not be built")
            continue
        after, why_not = _xsd.errors_against(merged.tree, schema_path)
        if why_not or before is None or after is None:
            report.skip(f"schema check for {v}", why_not or "the schema could not be applied")
            continue
        checked += 1

        for msg in _xsd.introduced(before, after):
            if not defs:  # built once, and only if something actually needs it
                defs = {"race": _race_defs(config, [mod_dir]),
                        "faction": _faction_defs(config, [mod_dir])}
            if _xsd.open_lookup_ok(msg, defs):
                suppressed += 1
                continue
            # Severity ladder (audit F7+F14, measured 2026-08-02 before written:
            # exactly 15 findings move INFO->ERROR across 3 mods, each verified
            # individually real — see gates/schema_sweep.py's re-measurement table).
            # The "md.xsd is stricter than the engine" excuse only covers what the
            # engine demonstrably tolerates; a value defined NOWHERE (enum-undefined)
            # or an (element, attribute) pair vanilla never uses (dead-attr) has
            # nothing to lag, so those gate.
            if _schema_gates(msg):
                sev, cat = "error", "schema"
            elif _xsd.enum_undefined(msg, defs):
                sev, cat = "error", "schema-enum-undefined"
            elif _xsd.dead_attr(msg, config):
                sev, cat = "error", "schema-dead-attr"
            else:
                sev, cat = "info", "schema-strict"
            report.add(sev, cat,
                       f"{msg} (introduced by this mod into the merged {v})", v, 0)

    # Unconditional, exactly like check_xsd's note 40 lines above. Guarding this on
    # `if checked:` meant a mod where nothing was validated printed NO schema line at
    # all, so "we validated 0 files" and "we did not run" looked identical — measured
    # on atd_ejection_router, which produced a bare "OK: no issues found".
    detail = ""
    if not checked and (new_files or no_schema):
        why = []
        if new_files:
            why.append(f"{new_files} brand-new (no base to difference against)")
        if no_schema:
            why.append(f"{no_schema} declaring no schema")
        detail = " — " + ", ".join(why)
    report.notes.append(
        f"effective-schema: {checked} merged data file(s) validated against their declared "
        f"schema, differenced against the same tree without this mod{detail}"
        + (f"; {suppressed} enumeration failure(s) suppressed as mod-defined races/factions"
           if suppressed else ""))


def check_packed_dlc_available(config: _merge.Config, report: Report) -> None:
    r"""Report when DLC that exist only PACKED cannot be reached.

    `reference/` holds only the DLC that were unpacked; the mini-DLC
    (`ego_dlc_mini_01` Hyperion Pack, `ego_dlc_mini_02` Envoy Pack) never were, so
    `dlc_dirs()` reaches them through the live game install instead. When the game
    root is not configured that silently drops from **8 DLC to 6** (measured
    2026-07-29) and `packed_dlc_names()` returns empty — every patch against
    Hyperion/Envoy content then falls back to "installed but never unpacked — cannot
    verify", which reads as *does not apply to me* rather than *I could not look*.

    This is the same shape B2 fixed one level down: B2 taught `dlc_dirs()` to SEE the
    packed DLC but gave it no channel for "I couldn't". Not `degraded` — most mods
    touch no mini-DLC content, so this is a partial skip, not a failed run.
    """
    if not config.include_packed_dlc or config.reference != _merge.REFERENCE:
        return  # deliberately isolated (hermetic run / foreign --reference)
    game_ext = _merge.GAME_ROOT / "extensions"
    if game_ext.is_dir():
        return
    report.skip("packed-DLC content",
                f"the live game install is not reachable at '{_merge.GAME_ROOT}', so DLC that "
                "were never unpacked into reference/ (the Hyperion and Envoy mini-DLC) are NOT "
                "in the tree. Patches targeting their content cannot be verified. Set $X4_GAME "
                "(see .claude/x4-paths.env) or run `x4validate --paths` to see what resolved")


def reference_ready(config: _merge.Config, report: Report) -> bool:
    """Guard: the reference tree must actually be loaded.

    Without it EVERY check degrades to a meaningless pass -- a sel matches
    nothing because there is nothing there, refs dangle against an empty
    catalog, completeness has no analogue. The tool's whole reason to exist
    (catch the silent no-op) would itself silently no-op and report 'OK'.
    So fail loud and non-zero instead of falsely passing.

    `libraries/wares.xml` is always present in the base game, so if it cannot
    be resolved the reference tree is missing or empty.
    """
    ref = config.reference
    if not ref.is_dir():
        report.add("error", "reference",
                   f"reference tree not found at '{ref}' -- unpack the base game first "
                   "($X4_REFERENCE / --reference). Validation is meaningless without it.",
                   str(ref))
        return False
    if _merge.build_effective(WARES_FILE, config).tree is None:
        report.add("error", "reference",
                   f"reference tree at '{ref}' is empty or incomplete "
                   f"(base '{WARES_FILE}' not found) -- re-unpack the base game; "
                   "results are meaningless without a real reference tree.",
                   str(ref))
        return False
    return True


def validate(
    mod_dir: Path,
    config: _merge.Config | None = None,
    entity: str | None = None,
    like: str | None = None,
    only_file: str | Path | None = None,
    update: bool = False,
    debug: str | Path | None = None,
    tier: str = "a",
) -> Report:
    config = config or _merge.Config()
    report = Report()
    if not reference_ready(config, report):
        return report  # empty/missing reference -> a clean run would be a false 'OK'
    check_packed_dlc_available(config, report)
    if tier == "b" and not config.overlays:
        trees = tier_b_trees(mod_dir, report)
        config = replace(config, overlays=trees.patch_time, final_overlays=trees.final)
        report.notes.extend(trees.notes)
    if only_file is not None:
        # Fast path for the per-edit hook: sel-resolution for one file only.
        check_sel_resolution_one(Path(only_file), mod_dir, config, report)
        return report
    check_readability(mod_dir, config, report)  # first: names what every other check will miss
    # PATCH-TIME tree: a selector only sees what has loaded by this mod's turn.
    check_sel_resolution(mod_dir, config, report)
    # RUNTIME tree: "does this id resolve?" is answered after every extension loads,
    # so these must also see mods that load LATER. Same tree under Tier A — see
    # Config.for_runtime. Getting this backwards costs a real finding in each
    # direction; `tier_b_trees` documents the measured case.
    runtime = config.for_runtime()
    check_references(mod_dir, runtime, report)
    check_file_existence(mod_dir, runtime, report)
    check_connections(mod_dir, runtime, report)
    check_page_collisions(mod_dir, config, report)
    check_text_sanity(mod_dir, config, report)
    check_identity_values(mod_dir, config, report)
    check_engine_connection_tags(mod_dir, config, report)
    check_variant_consistency(mod_dir, config, report)
    check_exprlint(mod_dir, config, report)  # cheap, always-on: expression-grammar heuristic
    if entity and like:
        check_completeness(mod_dir, runtime, report, entity, like)  # runtime: needs macro defs
    if debug is not None:  # authoritative: fold the engine's own errors for this mod (gates)
        check_debug_correlation(mod_dir, config, report, debug)
    if update:  # mechanical-port extras (9.0 migration): runtime heuristic + XSD (slow, last)
        check_migration(mod_dir, config, report)
        check_xsd(mod_dir, config, report)          # script files, as written
        check_effective_schema(mod_dir, config, report)  # data files, as merged
    return report
