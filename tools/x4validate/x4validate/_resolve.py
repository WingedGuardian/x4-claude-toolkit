"""Resolve X4's macro/component/connection graph to real files on disk.

Powers two v1.1 checks:
  - file-existence: <component ref="X_macro"> -> index/macros.xml value -> macro
    file exists? -> macro's <component ref> -> index/components.xml -> file exists?
  - connection-validation: a <loadout> entry `path="../con_engine_01"` must match a
    <connection name="con_engine_01"> in the ship's component.

Index `value` is a path WITHOUT `.xml`, backslash-separated, relative to the
SOURCE ROOT that defined the entry (base/DLC entries -> reference root, since DLC
values carry the `extensions\\ego_dlc_x\\` prefix; mod entries -> the mod root).
Wildcard entries (`character_*`) are skipped — they're patterns, not files.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from . import _merge

MACRO_INDEX = "index/macros.xml"
COMPONENT_INDEX = "index/components.xml"


def _index_entries(root: etree._Element):
    for entry in root.xpath("//entry[@name]"):
        name = entry.get("name")
        value = entry.get("value")
        if not value or "*" in name:  # skip wildcard patterns
            continue
        yield name, value


def build_index(config: _merge.Config, extra_overlays, index_rel: str) -> dict[str, tuple[Path, str]]:
    """name -> (resolution_root, value). Later sources win (mod over base)."""
    index: dict[str, tuple[Path, str]] = {}
    # base + DLC: values are resolved relative to the reference root.
    for src in [config.reference] + config.dlc_dirs():
        f = src / index_rel
        if f.is_file():
            try:
                for name, value in _index_entries(_merge.parse_file(f)):
                    index[name] = (config.reference, value)
            except etree.XMLSyntaxError:
                pass
    # mod overlays: values are resolved relative to the mod root.
    for ov in extra_overlays or []:
        f = ov / index_rel
        if f.is_file():
            try:
                for name, value in _index_entries(_merge.parse_file(f)):
                    index[name] = (ov, value)
            except etree.XMLSyntaxError:
                pass
    return index


def resolve_path(root: Path, value: str) -> Path:
    return root / (value.replace("\\", "/").lstrip("/") + ".xml")


def file_present(index: dict[str, tuple[Path, str]], name: str) -> Path | None:
    """Resolved file path if the index has *name* and the file exists, else None."""
    if name not in index:
        return None
    p = resolve_path(*index[name])
    return p if p.is_file() else None


def macro_component_links(
    macro_name: str,
    macro_index: dict[str, tuple[Path, str]],
    component_index: dict[str, tuple[Path, str]],
) -> list[str]:
    """Walk macro->file->component->file; return human messages for broken links.

    Assumes *macro_name* IS registered (unregistered macros are caught upstream as
    dangling refs). Empty list = the whole chain resolves to real files."""
    out: list[str] = []
    if macro_name not in macro_index:
        return out  # not our job here; dangling-ref check covers unregistered
    macro_file = resolve_path(*macro_index[macro_name])
    if not macro_file.is_file():
        out.append(f"macro '{macro_name}' registered but file missing: {macro_file}")
        return out
    try:
        mroot = _merge.parse_file(macro_file)
    except etree.XMLSyntaxError as exc:
        out.append(f"macro '{macro_name}' file unparseable: {exc}")
        return out
    comps = mroot.xpath(f"//macro[@name={_xq(macro_name)}]/component/@ref")
    if not comps:
        return out  # some macros legitimately have no component
    comp_ref = comps[0]
    if comp_ref not in component_index:
        out.append(f"macro '{macro_name}' -> component '{comp_ref}' not registered in index/components.xml")
        return out
    comp_file = resolve_path(*component_index[comp_ref])
    if not comp_file.is_file():
        out.append(f"component '{comp_ref}' registered but file missing: {comp_file}")
    return out


def component_connections(component_file: Path) -> set[str]:
    try:
        root = _merge.parse_file(component_file)
    except etree.XMLSyntaxError:
        return set()
    return set(root.xpath("//connection/@name"))


def loadout_targets(loadout_el: etree._Element) -> list[tuple[str, int]]:
    """(connection_name, sourceline) for each loadout entry with a `path` attr."""
    out = []
    for el in loadout_el.xpath(".//*[@path]"):
        path = el.get("path", "")
        conn = path.rsplit("/", 1)[-1]  # strip leading ../ (or any prefix)
        if conn:
            out.append((conn, el.sourceline or 0))
    return out


def _xq(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"
