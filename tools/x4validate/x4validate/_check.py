"""Orchestration: run the three checks against a mod folder and collect findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from lxml import etree

from . import (_cat, _compat, _debuglog, _exprlint, _merge, _migration, _refs,
               _registry, _resolve, _xref, _xsd)

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


def collect_text_defs(config: _merge.Config, extra_overlays=None) -> set[tuple[str, str]]:
    """Union (page,t) definitions from every t-file across base + DLC + overlays.

    Works for full <language> files and <diff> files alike (text_defs scans
    //page[@id]//t[@id] regardless of root). t-files are purely additive, so a
    plain union is faithful here."""
    defs: set[tuple[str, str]] = set()
    sources = ([config.reference] + config.dlc_dirs()
               + list(config.overlays) + list(extra_overlays or []))
    for src in sources:
        for rel in TEXT_FILES:
            f = src / rel
            if f.is_file():
                try:
                    defs |= _refs.text_defs(_merge.parse_file(f))
                except etree.XMLSyntaxError:
                    pass
    return defs


def collect_macro_defs(config: _merge.Config, extra_overlays=None) -> set[str]:
    """Registered macro names from the EFFECTIVE index/macros.xml.

    Built through build_effective rather than by unioning each directory's file,
    because an extension may ship index/macros.xml as a <diff> containing
    <remove> ops — and may ship it packed inside a .cat. A naive per-directory
    union sees neither, so it reports a macro as defined when the effective index
    no longer contains it. (Real case: xspvro removes
    turret_xen_m_beam_02_mk1_macro without re-adding it, orphaning a vanilla
    macro that six other mods reference.)
    """
    try:
        merged = _merge.build_effective(MACRO_INDEX, config, extra_overlays=extra_overlays)
    except (etree.LxmlError, OSError):
        return set()
    if merged.tree is None:
        return set()
    return _refs.macro_names(merged.tree)


def _mod_identity(mod_dir: Path) -> tuple[str, str]:
    """(folder name, content.xml id) for the mod under test; id may be ''."""
    folder = mod_dir.resolve().name
    mod_id = ""
    cx = mod_dir / "content.xml"
    if cx.is_file():
        try:
            mod_id = _merge.parse_file(cx).get("id") or ""
        except etree.XMLSyntaxError:
            pass
    return folder, mod_id


def tier_b_overlays(mod_dir: Path) -> tuple[tuple[Path, ...], list[str]]:
    """Installed extension roots that load BEFORE the mod under test — the tree its
    `sel=` selectors actually see.

    Returns (overlay_dirs, notes). This is what makes a cross-mod patch
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

    KNOWN LIMITATION: reference checks (does this ware/macro id exist?) are a
    *runtime* question and would ideally use the FINAL tree (all overlays), not this
    patch-time one. They currently share this tree, so a ware added only by a
    later-loading mod can read as unresolved. Measured impact on the dev mods at the
    time of the change: none. Split the two trees if that ever produces a false alarm.

    The mod under test is excluded by BOTH folder name and content.xml id, since
    a dev folder is usually also deployed under extensions\\ and would otherwise
    be merged in twice (its own ops pre-applied, masking real misses).

    Load order here is the community-reported convention (alphabetical,
    dependencies first) — advisory, not engine-verified.
    """
    notes: list[str] = []
    try:
        mods = _registry.scan_installed()
    except OSError as exc:
        return (), [f"Tier B: could not scan installed mods ({exc}); fell back to base+DLC only"]
    if not mods:
        return (), ["Tier B: no installed extensions found; fell back to base+DLC only"]

    folder, mod_id = _mod_identity(mod_dir)
    by_folder = {m["folder"]: m for m in mods}
    order = _compat.compute_load_order(mods)

    dirs: list[Path] = []
    skipped = ""
    placed = False
    for name in order:
        m = by_folder.get(name)
        if m is None:
            continue
        if m["folder"] == folder or (mod_id and m["id"] == mod_id):
            skipped, placed = m["folder"], True
            break  # everything after this loads LATER — not visible to our selectors
        p = Path(m["path"])
        if p.is_dir():
            dirs.append(p)

    if placed:
        notes.append(
            f"Tier B: merged {len(dirs)} extension(s) that load BEFORE this mod "
            f"(of {len(order)} installed) — the tree its selectors actually see")
        notes.append(f"Tier B: excluded the mod under test's installed copy '{skipped}' "
                     "and everything loading after it")
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
    return tuple(dirs), notes


@dataclass
class Finding:
    severity: str   # "error" | "warn" | "info"
    category: str   # "sel" | "ref" | "completeness" | "path"
    message: str
    vpath: str = ""
    line: int = 0


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))


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



def iter_mod_xml_roots(mod_dir: Path):
    """Yield (virtual_path, root) for every XML file owned by a mod.

    Loose files win over packed catalog members, matching the engine and
    _merge.overlay_root. This lets static checks see packed-only mods without
    duplicating catalog parsing in each check.
    """
    yielded: set[str] = set()
    for path in sorted(mod_dir.rglob("*.xml")):
        if not path.is_file():
            continue
        try:
            root = _merge.parse_file(path)
        except etree.XMLSyntaxError:
            continue
        vpath = path.relative_to(mod_dir).as_posix()
        yielded.add(vpath.lower())
        yield vpath, root

    for vpath, member in sorted(_cat.mod_vfs(mod_dir).items()):
        if not vpath.lower().endswith(".xml") or vpath.lower() in yielded:
            continue
        try:
            root = _merge.parse_bytes(_cat.read_member(member))
        except (OSError, etree.XMLSyntaxError):
            continue
        yield vpath, root


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


def _installed_folders() -> set[str]:
    """Lowercased folder names of every installed extension (empty if unscannable)."""
    try:
        return {m["folder"].lower() for m in _registry.scan_installed()}
    except OSError:
        return set()


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
    nested = _merge._nested_target(vpath)
    if nested is not None and nested[0].lower() not in _installed_folders():
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


def check_sel_resolution(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Flag any non-silent op whose sel= matches nothing in the merged base+DLC tree."""
    checked = 0
    seen_skips: set[str] = set()
    for vpath, diff_root in iter_diff_files(mod_dir):
        checked += 1
        merged = _merge.build_effective(vpath, config)
        # An overlay we could not parse was left out of this tree — say so, because
        # every verdict below is computed against an incomplete tree.
        for msg in merged.skipped:
            if msg not in seen_skips:
                seen_skips.add(msg)
                report.add("warn", "skipped", f"tree may be incomplete: {msg}", vpath)
        if merged.tree is None:
            report.add(*_no_base_finding(vpath, config), vpath)
            continue
        _check_ops(diff_root, merged.tree, vpath, report)
    if checked == 0:
        # A mod with no readable <diff> file was silently reported "OK" until
        # 2026-07-26, which is how packed mods passed while the engine rejected
        # their ops. Nothing examined is a SKIP, never a pass.
        report.add("warn", "skipped",
                   "no <diff> file could be read from this mod — nothing was "
                   "sel-checked. If the mod ships a .cat/.dat, its catalog could not "
                   "be opened; if it ships loose XML, check the folder layout", "")


def check_sel_resolution_one(file_path: Path, mod_dir: Path,
                             config: _merge.Config, report: Report) -> None:
    """Fast path: sel-resolution for ONE edited file (the auto-validate hook)."""
    try:
        root = _merge.parse_file(file_path)
    except etree.XMLSyntaxError as exc:
        report.add("error", "sel", f"unparseable XML: {exc}", str(file_path))
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
    text_def_set = collect_text_defs(config, mod_overlay)
    macro_def_set = collect_macro_defs(config, mod_overlay)
    report.notes.append(
        f"reference defs: {len(ware_def_set)} wares, {len(text_def_set)} text strings, "
        f"{len(macro_def_set)} macros")

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
    macro_index = _resolve.build_index(config, mod_overlay, _resolve.MACRO_INDEX)
    component_index = _resolve.build_index(config, mod_overlay, _resolve.COMPONENT_INDEX)
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
    existing = collect_text_defs(config)  # base + DLC only (NOT the mod)
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
    macro_index = _resolve.build_index(config, mod_overlay, _resolve.MACRO_INDEX)
    component_index = _resolve.build_index(config, mod_overlay, _resolve.COMPONENT_INDEX)
    conn_cache: dict[str, set[str] | None] = {}

    def conns_for_component(comp_ref: str | None) -> set[str] | None:
        if not comp_ref:
            return None
        if comp_ref not in conn_cache:
            cf = _resolve.file_present(component_index, comp_ref)
            conn_cache[comp_ref] = _resolve.component_connections(cf) if cf else None
        return conn_cache[comp_ref]

    def component_of_macro(macro_name: str) -> str | None:
        mf = _resolve.file_present(macro_index, macro_name)
        if mf is None:
            return None
        try:
            mr = _merge.parse_file(mf)
        except etree.XMLSyntaxError:
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
    text_def_set = collect_text_defs(config, mod_overlay)
    macro_def_set = collect_macro_defs(config, mod_overlay)
    rep = _refs.ware_completeness(eid, lid, wares.tree, text_def_set, macro_def_set)
    report.notes.append(f"completeness checked kinds: {', '.join(rep.checked)}")
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
    for m in _migration.scan_mod(mod_dir):
        report.add("warn", "migration", f"{m.note}  [{m.snippet}]", _relpath(m.file, mod_dir), m.line)


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
        report.add("info", "xsd-strict", f.message, _relpath(f.file, mod_dir), f.line)


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
    if tier == "b" and not config.overlays:
        overlays, notes = tier_b_overlays(mod_dir)
        config = replace(config, overlays=overlays)
        report.notes.extend(notes)
    if only_file is not None:
        # Fast path for the per-edit hook: sel-resolution for one file only.
        check_sel_resolution_one(Path(only_file), mod_dir, config, report)
        return report
    check_sel_resolution(mod_dir, config, report)
    check_references(mod_dir, config, report)
    check_file_existence(mod_dir, config, report)
    check_connections(mod_dir, config, report)
    check_page_collisions(mod_dir, config, report)
    check_text_sanity(mod_dir, config, report)
    check_identity_values(mod_dir, config, report)
    check_engine_connection_tags(mod_dir, config, report)
    check_variant_consistency(mod_dir, config, report)
    check_exprlint(mod_dir, config, report)  # cheap, always-on: expression-grammar heuristic
    if entity and like:
        check_completeness(mod_dir, config, report, entity, like)
    if debug is not None:  # authoritative: fold the engine's own errors for this mod (gates)
        check_debug_correlation(mod_dir, config, report, debug)
    if update:  # mechanical-port extras (9.0 migration): runtime heuristic + XSD (slow, last)
        check_migration(mod_dir, config, report)
        check_xsd(mod_dir, config, report)
    return report
