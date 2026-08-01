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

Schema compilation is slow (~100s for md/aiscripts; 122s for `diplomacy.xsd`,
<=0.1s for the rest), so both layers are ON-DEMAND (the `--update` flag), never
the default/hook path.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

from . import _merge

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
# just slow — `diplomacy.xsd` costs 122s to compile (it pulls in the 40k-line
# common.xsd), against <=0.1s for every other schema measured 2026-07-29.
@lru_cache(maxsize=64)
def _compiled(xsd_path: str) -> etree.XMLSchema:
    # Parse from the schema's own dir so <xs:include schemaLocation="common.xsd"/>
    # resolves relative to it.
    return etree.XMLSchema(etree.parse(xsd_path))


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


def validate_file(path: Path, lib: Path) -> tuple[list[XsdFinding], str | None]:
    """(findings, skip_reason). Empty findings + no reason = valid."""
    try:
        doc = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        return [XsdFinding(str(path), exc.lineno or 0, f"XML parse error: {exc.msg}")], None
    root = doc.getroot()
    schema_path = _schema_for(root, root.get(_XSI), lib)
    if schema_path is None:
        return [], f"no bundled schema for root <{root.tag}>"
    try:
        schema = _compiled(str(schema_path))
    except etree.XMLSchemaParseError as exc:
        return [XsdFinding(str(path), 0, f"could not compile {schema_path.name}: {exc}")], None
    if schema.validate(doc):
        return [], None
    return [XsdFinding(str(path), e.line, e.message) for e in schema.error_log], None


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


def schema_of(root: etree._Element, lib: Path) -> tuple[Path | None, str | None]:
    """(schema_path, why_not) for a merged document root.

    Read off the MERGED root rather than a hardcoded file list: a full-file
    override may legitimately change (or drop) the declaration, and a list would
    silently rot against the next DLC. Returns (None, None) for the common,
    uninteresting case of a file that declares no schema at all — macros,
    components and `libraries/wares.xml` are all in that group.
    """
    declared = root.get(_XSI)
    if not declared:
        return None, None
    name = declared.replace("\\", "/").split("/")[-1]
    p = lib / name
    if not p.is_file():
        # Real, and it must not be silent: coreaddon.xsd / cutscenes.xsd /
        # shadergl.xsd are declared by vanilla content but not shipped in
        # reference/libraries.
        return None, f"declared schema '{name}' is not bundled in {lib}"
    return p, None


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


def validate_mod(mod_dir: Path, config: _merge.Config | None = None):
    """Validate all md/ + aiscripts/ files. Returns (findings, checked, skipped)."""
    config = config or _merge.Config()
    lib = config.reference / "libraries"
    findings: list[XsdFinding] = []
    checked = skipped = 0
    for sub in SCRIPT_DIRS:
        d = mod_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.xml")):
            fnds, reason = validate_file(f, lib)
            if reason:
                skipped += 1
            else:
                checked += 1
            findings.extend(fnds)
    return findings, checked, skipped
