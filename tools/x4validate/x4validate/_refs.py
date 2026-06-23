"""Cross-file reference graph, dangling-reference detection, and completeness.

v1 reference types (the catalog is data-driven so it extends without new code):
  - ware ids        : <ware id> defs  <->  @ware refs
  - text refs       : {page,t}        <->  <page id><t id> in t/*-l044.xml
Completeness models a changed entity's footprint on a vanilla analogue and
reports which expected pieces are missing ("did I forget a spot?").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

# {page,t} or {page, t} with optional spaces.
TEXT_REF = re.compile(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}")


# --- Reference collection -----------------------------------------------------


def ware_defs(tree: etree._Element | None) -> set[str]:
    return set(tree.xpath("//ware/@id")) if tree is not None else set()


def ware_refs(tree: etree._Element | None) -> list[tuple[str, int]]:
    """All @ware references as (id, sourceline)."""
    if tree is None:
        return []
    out = []
    for el in tree.xpath("//*[@ware]"):
        out.append((el.get("ware"), el.sourceline or 0))
    return out


def text_defs(tree: etree._Element | None) -> set[tuple[str, str]]:
    """Set of (page_id, t_id) defined in a t/*-l044.xml language tree."""
    if tree is None:
        return set()
    out = set()
    for page in tree.xpath("//page[@id]"):
        pid = page.get("id")
        for t in page.xpath(".//t[@id]"):
            out.add((pid, t.get("id")))
    return out


def text_refs_in(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return []
    return [(m.group(1), m.group(2)) for m in TEXT_REF.finditer(value)]


def macro_names(tree: etree._Element | None) -> set[str]:
    """Macro names registered in an index/macros.xml (<entry name=...>).

    Works for full <index> files and <diff> overlays alike."""
    return set(tree.xpath("//entry/@name")) if tree is not None else set()


# --- Dangling-reference check -------------------------------------------------


@dataclass
class DanglingRef:
    kind: str
    ref: str
    where: str
    line: int


def find_dangling(
    introduced_tree: etree._Element | None,
    ware_def_set: set[str],
    text_def_set: set[tuple[str, str]],
    macro_def_set: set[str] = frozenset(),
    where: str = "",
) -> list[DanglingRef]:
    """References present in *introduced_tree* that resolve to no definition."""
    out: list[DanglingRef] = []
    if introduced_tree is None:
        return out
    for wid, line in ware_refs(introduced_tree):
        if wid not in ware_def_set:
            out.append(DanglingRef("ware", wid, where, line))
    for comp in introduced_tree.xpath("//component[@ref]"):
        ref = comp.get("ref")
        if macro_def_set and ref not in macro_def_set:
            out.append(DanglingRef("macro", ref, where, comp.sourceline or 0))
    for el in introduced_tree.iter():
        if not isinstance(el.tag, str):
            continue
        for attr_val in list(el.attrib.values()) + ([el.text] if el.text else []):
            for page, t in text_refs_in(attr_val):
                if (page, t) not in text_def_set:
                    out.append(DanglingRef("text", f"{{{page},{t}}}", where, el.sourceline or 0))
    return out


# --- Completeness (vanilla-analogue footprint diff) ---------------------------


@dataclass
class CompletenessReport:
    entity: str
    analogue: str
    checked: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _ware_element(tree: etree._Element | None, ware_id: str):
    if tree is None:
        return None
    found = tree.xpath(f"//ware[@id={_xq(ware_id)}]")
    return found[0] if found else None


def _xq(value: str) -> str:
    """Quote a value for an XPath literal, handling embedded quotes."""
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


# Unified footprint "kinds" for any ware-like entity (ware / ship / module).
# The vanilla analogue decides which kinds matter: a raw ware (ore) has no
# component/owner, so those are never flagged; a ship/module has them all.
ALL_KINDS = ("definition", "name_string", "description_string", "price",
             "production", "component", "owner", "restriction")


def _entity_kinds(elem, text_def_set: set[tuple[str, str]],
                  macro_def_set: set[str]) -> dict[str, bool]:
    if elem is None:
        return dict.fromkeys(ALL_KINDS, False)
    name_ok = any((p, t) in text_def_set for p, t in text_refs_in(elem.get("name")))
    desc_ok = any((p, t) in text_def_set for p, t in text_refs_in(elem.get("description")))
    comp = elem.find("component")
    # "component" present AND its macro resolves (when we have an index to check).
    comp_ok = comp is not None and (not macro_def_set or comp.get("ref") in macro_def_set)
    return {
        "definition": True,
        "name_string": name_ok,
        "description_string": desc_ok,
        "price": bool(elem.xpath("./price")),
        "production": bool(elem.xpath("./production")),
        "component": comp_ok,
        "owner": bool(elem.xpath("./owner")),
        "restriction": bool(elem.xpath("./restriction")),
    }


def ware_completeness(
    new_id: str,
    analogue_id: str,
    wares_tree: etree._Element | None,
    text_def_set: set[tuple[str, str]],
    macro_def_set: set[str] = frozenset(),
) -> CompletenessReport:
    """Report footprint kinds the analogue has but the new entity lacks.

    Handles ware / ship / module — all are <ware> entries that differ only in
    which footprint kinds the vanilla analogue exhibits."""
    analogue_kinds = _entity_kinds(_ware_element(wares_tree, analogue_id), text_def_set, macro_def_set)
    new_kinds = _entity_kinds(_ware_element(wares_tree, new_id), text_def_set, macro_def_set)
    checked = sorted(analogue_kinds)
    missing = [k for k in checked if analogue_kinds[k] and not new_kinds[k]]
    return CompletenessReport(new_id, analogue_id, checked, missing)
