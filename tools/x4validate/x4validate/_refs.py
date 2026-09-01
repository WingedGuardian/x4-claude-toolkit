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
    """All @ware references as (id, sourceline).

    Deliberately UNFILTERED — script expressions are excluded by the consumer
    (`find_dangling`), which counts what it drops. Filtering here would make the
    exclusion invisible to every caller.
    """
    if tree is None:
        return []
    out = []
    for el in tree.xpath("//*[@ware]"):
        out.append((el.get("ware"), el.sourceline or 0))
    return out


#: Characters that only ever appear in a script EXPRESSION, never in a ware id.
#: In `md/` and `aiscripts/` the @ware attribute holds an expression rather than
#: an id — `$tradeware` (a variable), `ware.energycells` (a lookup) — and the
#: same forms turn up outside those directories too (a mod's own `backups/`), so
#: this keys on the value SHAPE rather than the file path.
_EXPRESSION_CHARS = ("$", ".", "@", "{", "[", "(", " ", "'", '"')


def is_script_expression(value: str | None) -> bool:
    """True when *value* is an MD/aiscript expression rather than a ware id.

    MEASURED over the 114 installed mods: this skips 183 of the 236 unresolved
    @ware references (md/ 170 of 172, aiscripts/ 7 of 7, plus expression forms in
    scratch directories) and matches **0 of 2,462** effective ware ids and **0 of
    1,980** vanilla ids. That denominator is the point — a filter that could
    match a real id would convert a false POSITIVE into a false NEGATIVE, which
    is strictly worse because nothing would ever surface it again.
    """
    if not value:
        return True
    return any(c in value for c in _EXPRESSION_CHARS)


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
    macro_def_set: set[str] | None = None,
    where: str = "",
    expressions: list[str] | None = None,
) -> list[DanglingRef]:
    """References present in *introduced_tree* that resolve to no definition.

    *macro_def_set* is None when the effective macro index could not be built —
    the macro check is then skipped, and the caller must have reported that skip.
    An EMPTY set is a different thing: an index that genuinely registers no
    macros, under which every `<component ref>` really is dangling. Gating these
    two on truthiness (as this did until 2026-07-27) collapsed them, so an
    unreadable index silently switched the whole check off and the run read OK.

    *expressions* collects the @ware values skipped as script expressions. That
    skip NARROWS the data, so it announces what it dropped instead of dropping it
    silently — the caller reports the count.
    """
    out: list[DanglingRef] = []
    if introduced_tree is None:
        return out
    for wid, line in ware_refs(introduced_tree):
        if is_script_expression(wid):
            if expressions is not None:
                expressions.append(wid)
            continue
        if wid not in ware_def_set:
            out.append(DanglingRef("ware", wid, where, line))
    # <container ref> was unchecked until 2026-08-01 — a new ware pointing at a
    # nonexistent pickup macro passed while its ware and text refs were both caught.
    # Both elements name entries in the SAME index/macros.xml, and in vanilla
    # libraries/wares.xml they are the only two that carry @ref: 734 component +
    # 183 container, all 917 of which resolve. So this cannot flood.
    for el in introduced_tree.xpath("//component[@ref] | //container[@ref]"):
        ref = el.get("ref")
        if macro_def_set is not None and ref not in macro_def_set:
            out.append(DanglingRef("macro", ref, where, el.sourceline or 0))
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
    #: The analogue named by --like does not exist in the effective wares tree.
    #: Without this flag its footprint is all-False, nothing can be "missing",
    #: and the run reports "matches the footprint of <X>" — a vacuous pass over
    #: an empty comparison set, and the most misleading output the tool had.
    analogue_missing: bool = False
    #: The entity under test does not exist either (usually a typo in --entity,
    #: or a mod that never actually adds the ware it claims to).
    entity_missing: bool = False


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
                  macro_def_set: set[str] | None) -> dict[str, bool]:
    if elem is None:
        return dict.fromkeys(ALL_KINDS, False)
    name_ok = any((p, t) in text_def_set for p, t in text_refs_in(elem.get("name")))
    desc_ok = any((p, t) in text_def_set for p, t in text_refs_in(elem.get("description")))
    comp = elem.find("component")
    # "component" present AND its macro resolves. macro_def_set is None only when
    # the index could not be built (reported as a degraded skip) — then we check
    # presence alone. An empty set still means "no macro is registered", so the
    # ref genuinely does not resolve; testing truthiness here conflated the two
    # and let an unreadable index silently pass the component kind.
    comp_ok = comp is not None and (macro_def_set is None or comp.get("ref") in macro_def_set)
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
    macro_def_set: set[str] | None = None,
) -> CompletenessReport:
    """Report footprint kinds the analogue has but the new entity lacks.

    Handles ware / ship / module — all are <ware> entries that differ only in
    which footprint kinds the vanilla analogue exhibits.

    A nonexistent analogue is flagged rather than silently compared against:
    its footprint would be all-False, so nothing is ever "missing" and the
    result reads as a clean pass.
    """
    analogue_el = _ware_element(wares_tree, analogue_id)
    new_el = _ware_element(wares_tree, new_id)
    analogue_kinds = _entity_kinds(analogue_el, text_def_set, macro_def_set)
    new_kinds = _entity_kinds(new_el, text_def_set, macro_def_set)
    checked = sorted(analogue_kinds)
    missing = [k for k in checked if analogue_kinds[k] and not new_kinds[k]]
    return CompletenessReport(new_id, analogue_id, checked, missing,
                              analogue_missing=analogue_el is None,
                              entity_missing=new_el is None)


@dataclass
class UnobtainableRef:
    ref: str
    line: int
    wares: list[str]


def deprecated_only_macros(wares_tree) -> dict[str, list[str]]:
    """macro name -> the deprecated wares supplying it, when EVERY supplier is deprecated.

    "Obtainable" is a four-part question -- defined, indexed, supplied by a ware, and
    that ware not deprecated. This answers only the LAST part, and the scope is a
    measurement, not a preference.

    MEASURED 2026-08-28 over the effective tree, 125 active mods:

        indexed macros 5559 -> live 1575 (28.3%) | deprecated 39 (0.7%) | no ware 3945 (71.0%)

    The proposal that prompted this was "flag macros with NO ware", generalised from a
    1-in-5 figure measured on missiles alone. Corpus-wide it is **71%**, and it is the
    normal state: `bullet` is 170 of 170 (weapons reference bullets; nobody sells them),
    scenery/story macros 89.5%, `storage` 80.6%, `dock` 78.3%. A check firing on 3,945
    correctly-by-design macros would train everyone to ignore the channel it shares with
    real findings. That half needs a per-class expectation model and is deliberately
    absent here.

    ``all(deprecated)``, not ``any``: a macro still sold by one live ware is obtainable.
    MEASURED: **0** such macros exist today, so only a synthetic test can hold that
    clause honest -- which is why one exists.
    """
    if wares_tree is None:
        return {}
    supplied: dict[str, list[tuple[str, bool]]] = {}
    for ware in wares_tree.xpath("//ware"):
        deprecated = "deprecated" in (ware.get("tags") or "").split()
        for ref in ware.xpath("component/@ref"):
            supplied.setdefault(ref, []).append((ware.get("id"), deprecated))
    return {macro: [w for w, _ in suppliers]
            for macro, suppliers in supplied.items()
            if suppliers and all(dep for _w, dep in suppliers)}


def unobtainable_refs(root, dead: dict[str, list[str]]) -> list[UnobtainableRef]:
    """Attribute values that EXACTLY equal a macro no live ware supplies.

    Whole-value equality, never a substring: `dead_macro_mk2` is a different macro,
    and prose mentioning a name is not a reference. An exact match against a small
    known set cannot invent a finding the way a pattern can.
    """
    if root is None or not dead:
        return []
    out: list[UnobtainableRef] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for value in el.attrib.values():
            wares = dead.get(value)
            if wares:
                out.append(UnobtainableRef(value, el.sourceline or 0, list(wares)))
    return out
