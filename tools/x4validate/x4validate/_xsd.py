"""Validate a mod's MD / aiscript XML against the game's BUNDLED schemas.

This is the 9.0 migration backbone: missing now-required attributes (the `space=`
family) and removed/unknown actions are caught deterministically by validating
against `reference\\libraries\\{md,aiscripts}.xsd` (which `<xs:include common.xsd>`).

Schema compilation is slow (~100s — md/aiscripts pull in the 40k-line common.xsd),
so this is an ON-DEMAND check (the `--update` flag), never the default/hook path.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

from . import _merge

_XSI = "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation"
ROOT_TO_SCHEMA = {"mdscript": "md.xsd", "aiscript": "aiscripts.xsd"}
SCRIPT_DIRS = ("md", "aiscripts")


@dataclass
class XsdFinding:
    file: str
    line: int
    message: str


@lru_cache(maxsize=8)
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
