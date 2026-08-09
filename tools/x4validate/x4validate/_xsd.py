r"""Validate mod XML against the game's BUNDLED schemas. Two layers.

**1. Script files, as written** (`validate_mod`) — the 9.0 migration backbone:
missing now-required attributes (the `space=` family) and removed/unknown actions
are caught deterministically against `reference\libraries\{md,aiscripts}.xsd`
(which `<xs:include common.xsd>`).

**2. Data files, as MERGED** (`errors_against` + `introduced`) — 42 vanilla files
under `libraries/` declare a schema in `xsi:noNamespaceSchemaLocation`, and mods
ship them as `<diff>`. Validating the patch is meaningless; validating the
effective merged tree is not, and it catches a class nothing else here can see: a
diff that leaves the DOCUMENT structurally broken. Measured case — a mod that
`<remove>`s `<production>` orphans the `<limits>` sibling 30 times over.

The catch, and the reason layer 2 is DIFFERENTIAL: **Egosoft's own base+DLC data
fails Egosoft's own bundled schemas** (66 errors across 6 files, measured
2026-07-29 — same stricter-than-the-engine gap already known for `md.xsd`). So
only the delta between baseline and baseline+mod is attributable to the mod. See
`introduced`.

Schema compilation is slow (98.5s md, 122s aiscripts/diplomacy; <=0.1s for the
rest — the driver is the recursive `actions` content model, NOT file size), so
both layers are ON-DEMAND (the `--update` flag), never the default/hook path.

**Layer 1 has a FAST path** (`required_attr_table` / `required_attr_findings`):
the gating class alone — `attribute X is required but missing` — is a flat fact
per element and needs no automaton, so it is extracted by plain parsing in
~0.05s and runs ALWAYS. `gates/xsd_fast_parity.py` proves it equals libxml2 on
that class corpus-wide.
"""

from __future__ import annotations

import re
import sys
import time

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

from . import _cat, _merge

_XSI = "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"
ROOT_TO_SCHEMA = {"mdscript": "md.xsd", "aiscript": "aiscripts.xsd"}
SCRIPT_DIRS = ("md", "aiscripts")

#: Not eligible for the effective-tree check. `md/` and `aiscripts/` are already
#: covered file-by-file by validate_mod(); `t/` has no single base file (the merge
#: synthesizes an empty <language> root), so a "merged" t-file is not a document
#: the engine ever validates.
EFFECTIVE_SKIP_PREFIXES = ("md/", "aiscripts/", "t/")


@dataclass
class XsdFinding:
    file: str
    line: int
    message: str


# 64, not 8: the effective-tree check touches one schema per patched data file and
# the corpus reaches 20+ distinct schemas in a single run. An evicted entry is not
# just slow — `diplomacy.xsd` costs 122s to compile, against <=0.1s for every
# other schema measured 2026-07-29.
#
# ⚠ CORRECTED 2026-08-09: the cost is NOT "they include the 40k-line common.xsd".
# Measured: XMLSchema(common.xsd) = 0.03s at 1660 KB, md.xsd = 98.55s at 190 KB,
# aiscripts.xsd = 122.15s at 151 KB. Size is not the driver — libxml2 is building
# a content-model automaton for the RECURSIVE `actions` group (referenced 10x in
# md.xsd; MD actions nest inside do_if/do_all). Anything that deepens a recursive
# content model is expensive; adding elements to a flat schema is not.
#: Schemas whose compile costs minutes, not milliseconds (measured 2026-07-29:
#: md/aiscripts ~100s, diplomacy 122s; every other bundled schema <=0.1s).
_SLOW_SCHEMAS = {"md.xsd", "aiscripts.xsd", "diplomacy.xsd"}


@lru_cache(maxsize=64)
def _compiled(xsd_path: str) -> etree.XMLSchema:
    # Announce the wait BEFORE it happens. md.xsd costs ~98.5s and aiscripts.xsd
    # ~122s; until 2026-08-09 that happened in
    # total silence, so `--update` on a mod with one script file looked hung for
    # two minutes. Measured then: `arck_job_registry` 2.8s -> 112s and
    # `battle_repair_support` 2.4s -> 121s, purely because those mods are PACKED
    # and had previously been checked against NO schema at all — the old speed was
    # the bug, not the new cost. Same remedy as the O(n^2) case: the silence was
    # what needed fixing.
    name = Path(xsd_path).name
    if name.lower() in _SLOW_SCHEMAS:
        # Only the ones that actually cost minutes — announcing a 0.0s compile
        # would be noise, and noise is how a real warning stops being read.
        print(f"  [xsd] compiling {name} — one-off, ~100s; cached for the rest of "
              f"this run", file=sys.stderr, flush=True)
    t0 = time.perf_counter()
    schema = etree.XMLSchema(etree.parse(xsd_path))
    elapsed = time.perf_counter() - t0
    if elapsed >= 5.0:
        print(f"  [xsd] {name} compiled in {elapsed:.1f}s", file=sys.stderr, flush=True)
    return schema


XSD_NS = "{http://www.w3.org/2001/XMLSchema}"


def _own_children(node):
    """Children of *node*, NOT descending into a nested `xs:element` declaration.

    Load-bearing. A plain `node.iter()` walks into child element declarations and
    would attribute THEIR required attributes to the parent — inventing
    requirements, i.e. false gating ERRORs, which is the one outcome this whole
    path must never produce.
    """
    for child in node:
        if not isinstance(child.tag, str):
            continue
        yield child
        if child.tag != XSD_NS + "element":
            yield from _own_children(child)


def _required_here(node, groups, types, seen: frozenset) -> set[str]:
    """Required attribute names contributed by *node*'s own definition.

    Follows `xs:attributeGroup ref=` and `xs:extension base=` to their named
    definitions (cycle-guarded via *seen*). Skipping the `base=` hop would only
    UNDER-report, never over-report — but `gates/xsd_fast_parity.py` requires
    exact equality with the compiled schema, so it is resolved.
    """
    out: set[str] = set()
    for child in _own_children(node):
        tag = child.tag
        if tag == XSD_NS + "attribute":
            if child.get("use") == "required" and child.get("name"):
                out.add(child.get("name"))
        elif tag == XSD_NS + "attributeGroup":
            ref = child.get("ref")
            if ref and ref not in seen and ref in groups:
                out |= _required_here(groups[ref], groups, types, seen | {ref})
        elif tag in (XSD_NS + "extension", XSD_NS + "restriction"):
            base = child.get("base")
            if base and base not in seen and base in types:
                out |= _required_here(types[base], groups, types, seen | {base})
    return out


def _schema_closure(path: Path, seen: set[str] | None = None) -> list:
    """A schema's parsed root plus every root it `xs:include`/`xs:import`s.

    Scoping matters, and getting it wrong is not theoretical. A table built from a
    FIXED trio (common/md/aiscripts) reported `<replace sel=...>` in a `<diff>`
    as missing `string`/`with` — because `common.xsd` happens to declare an
    unrelated `replace`. The document actually declares `diff.xsd`, where
    `replace` requires neither, and libxml2 validates against THAT. So the table
    must follow the same closure libxml2 does: the declared schema and its
    includes, nothing else.
    """
    seen = seen if seen is not None else set()
    key = str(path).lower()
    if key in seen or not path.is_file():
        return []
    seen.add(key)
    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return []  # silent-ok: an unparseable schema contributes no rules; the
        # parity gate compares against the compiled schema and fails loudly if
        # that ever costs a real finding.
    out = [root]
    for inc in root.iter(XSD_NS + "include", XSD_NS + "import"):
        loc = inc.get("schemaLocation")
        if loc:
            out.extend(_schema_closure(path.parent / loc, seen))
    return out


@lru_cache(maxsize=32)
def required_attr_table(schema_path_str: str) -> dict[str, tuple[str, ...]]:
    """`{element_name: (required attribute names, ...)}` — WITHOUT compiling.

    Why this exists: compiling `md.xsd` costs 98.5s and `aiscripts.xsd` 122s, and
    the result is not picklable so it cannot be cached between runs. Measured
    2026-08-09, the cost is NOT "they include the 40k-line common.xsd" — that
    compiles in 0.03s — it is libxml2 building a content-model automaton for the
    recursive `actions` group. But the one class the KB calls the *only reliable
    9.0 migration signal*, `"attribute X is required but missing"`, needs no
    automaton at all: it is a flat fact per element. Extracting it by plain
    parsing takes ~0.03s.

    **Ambiguity is resolved conservatively by INTERSECTION.** 25 element names are
    declared with different required sets in different contexts (`ware` requires
    nothing in one place and `ware` in another). Taking the intersection means an
    ambiguous name can only ever under-report. Over-reporting here would be a
    false ERROR on a working mod — the exact defect class this codebase has spent
    the most effort removing.
    """
    roots = _schema_closure(Path(schema_path_str))
    groups, types = {}, {}
    for r in roots:
        for g in r.iter(XSD_NS + "attributeGroup"):
            if g.get("name"):
                groups[g.get("name")] = g
        for t in r.iter(XSD_NS + "complexType"):
            if t.get("name"):
                types[t.get("name")] = t

    per_name: dict[str, list[set[str]]] = {}
    for r in roots:
        for el in r.iter(XSD_NS + "element"):
            name = el.get("name")
            if not name:
                continue
            req = _required_here(el, groups, types, frozenset())
            ref_type = el.get("type")
            if ref_type and ref_type in types:
                req |= _required_here(types[ref_type], groups, types, frozenset({ref_type}))
            per_name.setdefault(name, []).append(req)

    table: dict[str, tuple[str, ...]] = {}
    for name, sets in per_name.items():
        common = set.intersection(*sets) if sets else set()
        if common:
            table[name] = tuple(sorted(common))
    return table


def required_attr_findings(root: etree._Element, display: str,
                           lib: Path) -> list[XsdFinding]:
    """`required but missing` findings for one parsed script, via the fast table.

    The message is byte-identical to what libxml2 emits for the same defect, so
    the two paths de-duplicate cleanly and `gates/xsd_fast_parity.py` can compare
    them as sets.
    """
    # A <diff> is a PATCH, never a script "as written", and its payload is not the
    # diff schema's business — libxml2 treats what sits inside <add>/<replace> as
    # lax and rules on none of it. Two parity failures came from ignoring that,
    # and they looked different enough to seem unrelated:
    #   226 false positives when NO schema resolved for the diff, so the fixed
    #       common/md/aiscripts table matched its `<replace sel=...>` ops; then
    #    10 more once the table was correctly scoped and `diff.xsd` DID resolve,
    #       applying diff.xsd's `replace` (which requires `sel`) to PAYLOAD
    #       `<replace string= with=/>` elements that legitimately have none.
    # Same wrong premise both times: that a diff document is ours to rule on.
    if root.tag == "diff":
        return []
    # Otherwise mirror the compiled path exactly: no schema, no verdict.
    schema_path = _schema_for(root, root.get(_XSI), lib)
    if schema_path is None:
        return []
    table = required_attr_table(str(schema_path))
    out: list[XsdFinding] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in table.get(el.tag, ()):
            if el.get(attr) is None:
                out.append(XsdFinding(
                    display, el.sourceline or 0,
                    f"Element '{el.tag}': The attribute '{attr}' is required but missing."))
    return out


def ambiguous_element_names(schema_path_str: str) -> int:
    """How many element names carry conflicting required sets (disclosure only)."""
    roots = _schema_closure(Path(schema_path_str))
    groups, types = {}, {}
    for r in roots:
        for g in r.iter(XSD_NS + "attributeGroup"):
            if g.get("name"):
                groups[g.get("name")] = g
        for t in r.iter(XSD_NS + "complexType"):
            if t.get("name"):
                types[t.get("name")] = t
    per: dict[str, set[frozenset]] = {}
    for r in roots:
        for el in r.iter(XSD_NS + "element"):
            if el.get("name"):
                per.setdefault(el.get("name"), set()).add(
                    frozenset(_required_here(el, groups, types, frozenset())))
    return sum(1 for v in per.values() if len(v) > 1)


def _schema_for(root: etree._Element, declared: str | None, lib: Path) -> Path | None:
    """Pick the bundled schema: prefer the file's declared one, else by root tag."""
    candidates = []
    if declared:
        candidates.append(declared.replace("\\", "/").split("/")[-1])
    if root.tag in ROOT_TO_SCHEMA:
        candidates.append(ROOT_TO_SCHEMA[root.tag])
    for name in candidates:
        p = lib / name
        if p.is_file():
            return p
    return None


def _validate_doc(doc, display: str, lib: Path) -> tuple[list[XsdFinding], str | None]:
    """Schema-check one parsed document. Shared by the loose and packed readers
    so the two can never drift into checking different things."""
    root = doc.getroot()
    schema_path = _schema_for(root, root.get(_XSI), lib)
    if schema_path is None:
        return [], f"no bundled schema for root <{root.tag}>"
    try:
        schema = _compiled(str(schema_path))
    except etree.XMLSchemaParseError as exc:
        return [XsdFinding(display, 0, f"could not compile {schema_path.name}: {exc}")], None
    if schema.validate(doc):
        return [], None
    return [XsdFinding(display, e.line, e.message) for e in schema.error_log], None


def validate_file(path: Path, lib: Path) -> tuple[list[XsdFinding], str | None]:
    """(findings, skip_reason). Empty findings + no reason = valid."""
    try:
        doc = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        return [XsdFinding(str(path), exc.lineno or 0, f"XML parse error: {exc.msg}")], None
    return _validate_doc(doc, str(path), lib)


def validate_bytes(data: bytes, display: str, lib: Path) -> tuple[list[XsdFinding], str | None]:
    """Schema-check a script file read out of a mod's `.cat` catalog."""
    try:
        doc = etree.ElementTree(etree.fromstring(data))
    except etree.XMLSyntaxError as exc:
        return [XsdFinding(display, exc.lineno or 0, f"XML parse error: {exc.msg}")], None
    return _validate_doc(doc, display, lib)


def eligible(vpath: str) -> bool:
    r"""Can this virtual path be schema-checked as an effective merged document?

    The `extensions/<target>/` strip is load-bearing, not tidiness. A cross-mod
    patch lives at `<mymod>/extensions/<target>/md/foo.xml`, which does not START
    with `md/` — so a plain prefix test let 5 MD scripts through the exclusion
    (measured 2026-07-29: 4 from `vro`, 1 from `kuertee_emergent_missions`). They
    were then validated against `md.xsd`, which is both already covered by
    `validate_mod` and documented as stricter than the engine. Match the path
    SEGMENT after the nesting is removed.
    """
    v = vpath.replace("\\", "/").lstrip("/").lower()
    if v.startswith("extensions/"):
        parts = v.split("/", 2)
        if len(parts) == 3:
            v = parts[2]
    return v.endswith(".xml") and not v.startswith(EFFECTIVE_SKIP_PREFIXES)


def schema_of(root: etree._Element, lib: Path,
              vpath: str = "") -> tuple[Path | None, str | None]:
    """(schema_path, why_not) for a merged document root.

    Read off the MERGED root rather than a hardcoded file list: a full-file
    override may legitimately change (or drop) the declaration, and a list would
    silently rot against the next DLC. Returns (None, None) for the common,
    uninteresting case of a file that declares no schema at all — macros,
    components and `libraries/wares.xml` are all in that group.

    `xsi:noNamespaceSchemaLocation` is a path **relative to the document**, and
    vanilla uses it that way — `libraries/factions.xml` says `factions.xsd`,
    `cutscenes/*.xml` says `cutscenes.xsd`, and a mod's root `ui.xml` says
    `../../ui/core/addon.xsd`, climbing out of `extensions/<mod>/` to the game
    root. Until 2026-08-01 this took only the BASENAME and looked only in
    `reference/libraries`, so 31 documents were skipped as "not bundled" when the
    schema was bundled — a false statement, which is the worse half: a wrong
    reason is what stops the next person checking.

    Resolving against *vpath* is layer-aware for free. A DLC document carries its
    own `extensions/ego_dlc_*/` prefix, so `cutscenes.xsd` lands in that DLC's
    copy rather than whichever of the six the filesystem happened to yield first.
    """
    declared = root.get(_XSI)
    if not declared:
        return None, None
    rel = declared.replace("\\", "/").lstrip("/")
    name = rel.split("/")[-1]
    reference = lib.parent

    for cand in _schema_candidates(rel, name, vpath, reference, lib):
        if cand.is_file():
            return cand, None
    return None, (f"declared schema '{rel}' could not be resolved relative to "
                  f"'{vpath or name}' or found in {lib}")


def _schema_candidates(rel: str, name: str, vpath: str,
                       reference: Path, lib: Path):
    """Where a declared schema could live, best guess first.

    Kept separate so the ordering is testable without a filesystem full of XSDs.
    """
    v = vpath.replace("\\", "/").lstrip("/")
    if v:
        # 1. Relative to the document's own position in the reference tree. This
        #    is the engine's own rule and handles every vanilla form, DLC layers
        #    included.
        yield _resolve(reference / v, rel, reference)
        # 2. The same document seen as an EXTENSION file. A mod's ui.xml sits at
        #    extensions/<mod>/ui.xml, two levels below the game root, which is
        #    exactly what its "../../" is written to climb.
        yield _resolve(reference / "extensions" / "_mod_" / v, rel, reference)
    # 3. Legacy behaviour, and still correct for a bare name under libraries/.
    yield lib / name
    # 4. Unique basename anywhere in the tree. Needed because a declaration can
    #    be relative to where the author COPIED it from rather than where the file
    #    ended up: 30 mods ship ui.xml at their root declaring
    #    "../../core/coreaddon.xsd", which is written for vanilla's
    #    ui/addons/<x>/ layout and resolves nowhere from a mod root. The engine
    #    does not read this attribute at all, so those mods work — but we would
    #    lose the check. Only accepted when the name is UNAMBIGUOUS: cutscenes.xsd
    #    exists in six layers, and guessing between them is how a layer-aware fix
    #    would quietly become layer-blind again.
    found = _by_basename(reference).get(name.lower())
    if found is not None:
        yield found


@lru_cache(maxsize=8)
def _by_basename(reference: Path) -> dict[str, Path]:
    """{lowercased xsd filename: path} for names that occur EXACTLY ONCE."""
    seen: dict[str, Path | None] = {}
    for p in reference.rglob("*.xsd"):
        key = p.name.lower()
        seen[key] = None if key in seen else p  # None marks "ambiguous"
    return {k: v for k, v in seen.items() if v is not None}


def _resolve(doc_path: Path, rel: str, reference: Path) -> Path:
    """`rel` resolved against `doc_path`'s directory, clamped inside `reference`.

    The clamp matters: a declaration with enough `../` to escape the tree must
    not turn into a probe of the developer's filesystem.
    """
    target = (doc_path.parent / rel).resolve()
    try:
        target.relative_to(reference.resolve())
    except ValueError:
        return reference / "__outside_reference__"
    return target


def errors_against(root: etree._Element,
                   schema_path: Path) -> tuple[list[str] | None, str | None]:
    """Schema-validate a merged root. Returns (messages, why_not).

    `why_not` carries the compiler's own text rather than a bare None: "could not
    compile diplomacy.xsd" is not actionable, whereas the parse error names the
    construct. The caller turns it into a `report.skip`, so an unusable schema is
    visible work-not-done instead of a file that quietly looks clean.
    """
    try:
        schema = _compiled(str(schema_path))
    except etree.XMLSchemaParseError as exc:
        return None, f"'{schema_path.name}' would not compile: {exc}"
    schema.validate(etree.ElementTree(root))
    return [e.message for e in schema.error_log], None


def introduced(baseline: list[str], with_mod: list[str]) -> list[str]:
    """The messages the mod ADDED — the only ones it can be blamed for.

    This is why the check is differential rather than absolute. Measured
    2026-07-29: base+DLC alone yields **66** errors against its own bundled
    schemas (`libraries/modules.xml` 28, `jobs.xml` 27, `sound_library.xml` 4,
    `god.xml` 3, `effects.xml` 3, `gamestarts.xml` 1) — the same
    stricter-than-the-engine gap already documented for `md.xsd`. An absolute
    check would therefore open with 66 false positives on a mod that changed
    nothing. Differencing suppresses them BY CONSTRUCTION, not by a hand-tuned
    exclusion list that would rot at the next game patch.

    SET semantics, deliberately — a message text the baseline exhibits AT ALL is
    dropped, however many times the mod repeats it. Written first as a multiset
    ("credit the mod for its own copies") and the corpus sweep showed why that is
    wrong: it flagged `ebi_pirate_chaos_conflict` 31x and `vro` 15x purely for
    adding more entries in vanilla's own idiom (`<category>` with content;
    `amplitude` on `<low>`). Vanilla exhibiting a construct IS the evidence the
    engine tolerates it, so a mod reusing it cannot be the finding. 50 noise
    findings removed, and none of the four known-real defects moved — their
    message texts carry the offending value, so they never collide with a
    baseline message.
    """
    seen = set(baseline)
    return [m for m in with_mod if m not in seen]


#: Attributes whose XSD enumeration is a VANILLA FLOOR, not a closed set: mods add
#: races and factions, so the shipped list is incomplete by design. Measured
#: 2026-07-29 — `xenon_backup` uses race="tfdrones" and DEFINES it in its own
#: libraries/races.xml diff (3 false positives), while `cpsdo_faction` uses
#: race="central" which nothing anywhere defines (7 real). Same shape, opposite
#: answers: only the effective definition set can tell them apart.
OPEN_LOOKUPS = {"race": "race", "primaryrace": "race", "makerrace": "race",
                "faction": "faction", "owner": "faction", "primaryfaction": "faction"}

_RE_ENUM_FACET = re.compile(
    r"attribute '(?P<attr>[\w:-]+)': \[facet 'enumeration'\] "
    r"The value '(?P<value>[^']*)' is not an element of the set")


def open_lookup_ok(message: str, defs: dict[str, set[str]]) -> bool:
    """True when an enumeration failure names a value the modlist really defines.

    Suppresses ONLY that case. A value nothing defines still reports — that is the
    difference between "the XSD is behind the modlist" and "this is a typo".
    """
    m = _RE_ENUM_FACET.search(message)
    if m is None:
        return False
    kind = OPEN_LOOKUPS.get(m.group("attr").lower())
    return kind is not None and m.group("value") in defs.get(kind, set())


def enum_undefined(message: str, defs: dict[str, set[str]]) -> bool:
    """True when an enumeration failure names an open-lookup value that NOTHING
    defines — not the XSD's vanilla floor, not the effective modlist tree.

    This is audit F14: `open_lookup_ok` already computed the distinction (it
    correctly suppressed `xenon_backup`'s mod-defined race while reporting
    `cpsdo_faction`'s race='central'), but severity never consulted it — both
    landed as INFO with the excuse "the XSD lags the engine". For a value defined
    NOWHERE that excuse cannot apply: there is nothing to lag. Measured 2026-08-02:
    exactly 7 findings move, all `cpsdo_faction`'s race='central', the confirmed
    July upstream defect. Non-lookup enums are untouched — mods cannot extend
    those by defining something, so their failures keep the advisory treatment.
    """
    m = _RE_ENUM_FACET.search(message)
    if m is None:
        return False
    kind = OPEN_LOOKUPS.get(m.group("attr").lower())
    return kind is not None and m.group("value") not in defs.get(kind, set())


_RE_ATTR_NOT_ALLOWED = re.compile(
    r"Element '(?P<elem>[\w:-]+)', attribute '(?P<attr>[\w:-]+)': "
    r"The attribute '[\w:-]+' is not allowed")


def dead_attr_pair(message: str) -> tuple[str, str] | None:
    """('element', 'attribute') from an attribute-not-allowed message, else None."""
    m = _RE_ATTR_NOT_ALLOWED.search(message)
    if m is None:
        return None
    return (m.group("elem").lower(), m.group("attr").lower())


#: (element, attribute) pairs used anywhere in vanilla+DLC, keyed by reference
#: path. Built ONCE per process on first demand — a full corpus walk (~9k loose
#: files + the packed DLC) is far too slow per finding, and the pair vocabulary
#: is small enough to hold whole.
_VANILLA_PAIRS: dict[str, set[tuple[str, str]]] = {}


def vanilla_pair_exists(elem: str, attr: str, config: _merge.Config | None = None) -> bool:
    """Does vanilla+DLC use *attr* on *elem* ANYWHERE? Pair granularity is
    load-bearing, not pedantry (audit F7, measured 2026-08-02): `matchextension`
    has 140 base-game uses — every one on `<location>` — so a name-level lookup
    would excuse the real defect of writing it on `<category>`, where the engine
    ignores it. Includes the packed-only DLC via `dlc_dirs()`, because a
    loose-reference-only scan has a two-DLC blind spot.
    """
    config = config or _merge.Config()
    key = str(config.reference)
    pairs = _VANILLA_PAIRS.get(key)
    if pairs is None:
        from . import _scan
        pairs = set()
        roots = [config.reference] + [d for d in config.dlc_dirs()
                                      if not str(d).startswith(key)]
        for base in roots:
            for _vpath, root in _scan.iter_mod_xml(base, lambda v: True, None):
                for el in root.iter():
                    if not isinstance(el.tag, str):
                        continue
                    t = el.tag.lower()
                    for k in el.attrib:
                        pairs.add((t, k.lower()))
        _VANILLA_PAIRS[key] = pairs
    return (elem.lower(), attr.lower()) in pairs


def dead_attr(message: str, config: _merge.Config | None = None) -> bool:
    """True for an attribute-not-allowed failure whose (element, attribute) pair
    appears NOWHERE in vanilla+DLC — unknown to the schema AND absent from the
    engine's own content, so the "schema lags the engine" excuse cannot apply.
    Measured 2026-08-02: 8 findings move (3 `category/@matchextension` — a real
    attribute on the wrong element — and 5 `element/@forkmaterial`, invented by
    VRO and read by nothing).
    """
    pair = dead_attr_pair(message)
    if pair is None:
        return False
    return not vanilla_pair_exists(pair[0], pair[1], config)


_RE_ELEM_NOT_EXPECTED = re.compile(
    r"Element '(?P<elem>[\w:-]+)': This element is not expected\."
    r"\s*Expected is one of \((?P<expected>[^)]*)\)")

#: Child elements `md.xsd` fails to model but the ENGINE accepts. Keyed by
#: (child, frozenset(expected siblings)) — the expected-set identifies which
#: parent's content model the schema was evaluating, which the message itself
#: never names.
#:
#: The bar for an entry here is ENGINE EVIDENCE, not plausibility. `check_xsd`
#: gates "element not expected" on the deliberate reasoning that a removed or
#: renamed action is safer flagged than missed, so demoting one needs proof the
#: engine tolerates it — otherwise this list becomes a place to hide real breaks.
SCHEMA_ELEMENT_GAPS: dict[tuple[str, frozenset], str] = {
    ("ammunition", frozenset({"orientation", "position", "safepos", "rotation"})):
        "md.xsd does not model <ammunition> under <create_ship>, but the engine accepts it "
        "(verified 2026-08-09 against a live debug.txt: the engine parsed the same files to "
        "LINE granularity — expression warnings at specific lines — while raising no objection "
        "at any of the 9 <ammunition> sites; and common.xsd:11738 defines exactly this nested "
        "<ammunition><ammunition macro= exact=/></ammunition> shape)",
}


def schema_element_gap(message: str) -> str | None:
    """Why this element-not-expected finding is md.xsd incompleteness, else None."""
    m = _RE_ELEM_NOT_EXPECTED.search(message)
    if m is None:
        return None
    expected = frozenset(p.strip().lower() for p in m.group("expected").split(",") if p.strip())
    return SCHEMA_ELEMENT_GAPS.get((m.group("elem").lower(), expected))


def validate_mod(mod_dir: Path, config: _merge.Config | None = None):
    """Validate all md/ + aiscripts/ files, loose AND packed.

    The packed half is not a nicety. This walked only the loose tree until
    2026-08-09, so on a PACKED mod it validated zero files and `--update`
    reported no schema breakages at all — while the KB names
    "attribute X is required but missing" as *the only reliable 9.0 migration
    signal*. The most trustworthy check we have was silently off for the
    majority of installed mods.

    Returns (findings, checked, skipped).
    """
    config = config or _merge.Config()
    lib = config.reference / "libraries"
    findings: list[XsdFinding] = []
    checked = skipped = 0
    seen: set[str] = set()
    for sub in SCRIPT_DIRS:
        d = mod_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.xml")):
            seen.add(f.relative_to(mod_dir).as_posix().lower())
            fnds, reason = validate_file(f, lib)
            if reason:
                skipped += 1
            else:
                checked += 1
            findings.extend(fnds)

    # Catalog members under md/ or aiscripts/. Loose wins (engine ordering, and
    # the same contract `_scan` documents). Depth matches the loose `glob("*.xml")`
    # above — direct children only — so the two halves check the same population.
    prefixes = tuple(f"{s}/" for s in SCRIPT_DIRS)
    for vpath, member in sorted(_cat.mod_vfs(mod_dir).items()):
        low = vpath.lower()
        if not low.endswith(".xml") or low in seen or not low.startswith(prefixes):
            continue
        if low.count("/") != 1:
            continue
        try:
            data = _cat.read_member(member)
        except OSError as exc:
            skipped += 1
            findings.append(XsdFinding(vpath, 0, f"could not read from catalog: {exc}"))
            continue
        fnds, reason = validate_bytes(data, vpath, lib)
        if reason:
            skipped += 1
        else:
            checked += 1
        findings.extend(fnds)
    return findings, checked, skipped
