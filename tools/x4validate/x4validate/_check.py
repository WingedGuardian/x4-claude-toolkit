"""Orchestration: run the three checks against a mod folder and collect findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from . import _merge, _migration, _refs, _resolve, _xsd

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


def collect_text_defs(config: _merge.Config, extra_overlays=None) -> set[tuple[str, str]]:
    """Union (page,t) definitions from every t-file across base + DLC + overlays.

    Works for full <language> files and <diff> files alike (text_defs scans
    //page[@id]//t[@id] regardless of root)."""
    defs: set[tuple[str, str]] = set()
    sources = [config.reference] + config.dlc_dirs() + list(extra_overlays or [])
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
    """Union registered macro names from index/macros.xml across base+DLC+overlays."""
    names: set[str] = set()
    sources = [config.reference] + config.dlc_dirs() + list(extra_overlays or [])
    for src in sources:
        f = src / MACRO_INDEX
        if f.is_file():
            try:
                names |= _refs.macro_names(_merge.parse_file(f))
            except etree.XMLSyntaxError:
                pass
    return names


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
    """Yield (virtual_path, file_path, diff_root) for every <diff> file in the mod."""
    for path in sorted(mod_dir.rglob("*.xml")):
        if not path.is_file():
            continue
        try:
            root = _merge.parse_file(path)
        except etree.XMLSyntaxError:
            continue
        if root.tag != "diff":
            continue
        vpath = path.relative_to(mod_dir).as_posix()
        yield vpath, path, root


def _check_ops(diff_root, tree, vpath: str, report: Report) -> None:
    """Evaluate every diff op's sel= against *tree*; flag non-matches."""
    for op in diff_root:
        if not isinstance(op.tag, str) or op.tag not in _merge._OPS:
            continue
        sel = op.get("sel", "")
        line = op.sourceline or 0
        silent = _merge._truthy(op.get("silent"))
        try:
            hits = tree.xpath(sel)
        except etree.XPathEvalError as exc:
            report.add("error", "sel", f"<{op.tag}> invalid sel= ({exc})", vpath, line)
            continue
        if not hits:
            sev = "warn" if silent else "error"
            report.add(sev, "sel",
                       f"<{op.tag}> sel matched nothing: {sel}"
                       + (" (silent)" if silent else ""), vpath, line)


def check_sel_resolution(mod_dir: Path, config: _merge.Config, report: Report) -> None:
    """Flag any non-silent op whose sel= matches nothing in the merged base+DLC tree."""
    for vpath, _path, diff_root in iter_diff_files(mod_dir):
        merged = _merge.build_effective(vpath, config)
        if merged.tree is None:
            report.add("error", "path", f"no base game file for '{vpath}' "
                       "(path mismatch? this patch can never apply)", vpath)
            continue
        _check_ops(diff_root, merged.tree, vpath, report)


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

    for vpath, _path, diff_root in iter_diff_files(mod_dir):
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
    for vpath, _path, diff_root in iter_diff_files(mod_dir):
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
    for vpath, _path, diff_root in iter_diff_files(mod_dir):
        added: set[tuple[str, str]] = set()
        for holder in _added_subtrees(diff_root):
            added |= _refs.text_defs(holder)
        for page, t in sorted(added & existing):
            report.add("warn", "text",
                       f"text {{{page},{t}}} already defined in base/DLC — your add clobbers it", vpath)


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

    for path in sorted(mod_dir.rglob("*.xml")):
        if not path.is_file():
            continue
        try:
            root = _merge.parse_file(path)
        except etree.XMLSyntaxError:
            continue
        vpath = path.relative_to(mod_dir).as_posix()
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
) -> Report:
    config = config or _merge.Config()
    report = Report()
    if not reference_ready(config, report):
        return report  # empty/missing reference -> a clean run would be a false 'OK'
    if only_file is not None:
        # Fast path for the per-edit hook: sel-resolution for one file only.
        check_sel_resolution_one(Path(only_file), mod_dir, config, report)
        return report
    check_sel_resolution(mod_dir, config, report)
    check_references(mod_dir, config, report)
    check_file_existence(mod_dir, config, report)
    check_connections(mod_dir, config, report)
    check_page_collisions(mod_dir, config, report)
    check_variant_consistency(mod_dir, config, report)
    if entity and like:
        check_completeness(mod_dir, config, report, entity, like)
    if update:  # mechanical-port extras (9.0 migration): runtime heuristic + XSD (slow, last)
        check_migration(mod_dir, config, report)
        check_xsd(mod_dir, config, report)
    return report
