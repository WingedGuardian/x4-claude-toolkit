"""Mutation-campaign gaps in `_resolve`, lane K (2026-09-26). Each test names the surviving
mutant it was written to kill and was verified to FAIL with it applied and PASS without."""
from __future__ import annotations

from lxml import etree

from x4validate import _resolve


def _entries(xml: str):
    return list(_resolve._index_entries(etree.fromstring(xml)))


def test_wildcard_index_entry_is_skipped():
    """R1: `character_*` is a pattern, not a file -- it is never yielded."""
    assert _entries('<index><entry name="character_*" value="a\\b"/>'
                    '<entry name="m" value="a\\m"/></index>') == [("m", "a\\m")]


def test_index_entry_with_empty_value_is_skipped():
    """R2: an entry naming no file (value="") is never yielded."""
    assert _entries('<index><entry name="e" value=""/>'
                    '<entry name="m" value="a\\m"/></index>') == [("m", "a\\m")]


def test_own_prefix_is_stripped_from_a_THREE_segment_value():
    """R3: `extensions\\<own>\\<file>` is the shortest prefixed value; it resolves to
    <file> inside the mod root."""
    assert _resolve._strip_mod_index_prefix("extensions\\mymod\\m", "mymod") == "m"


def test_own_prefix_strip_is_case_insensitive_on_EXTENSIONS():
    """R4: the engine's folder lookup is case-insensitive, `Extensions\\` included."""
    assert _resolve._strip_mod_index_prefix("Extensions\\mymod\\a\\m", "mymod") == "a/m"


def test_unregistered_component_is_reported_as_unregistered(tmp_path):
    """R8: a macro whose <component ref> is absent from index/components.xml is reported
    as NOT REGISTERED -- not looked up as though it were."""
    (tmp_path / "m.xml").write_text(
        '<macros><macro name="m1"><component ref="c1"/></macro></macros>', encoding="utf-8")
    out = _resolve.macro_component_links("m1", {"m1": (tmp_path, "m")}, {})
    assert len(out) == 1
    assert "not registered" in out[0]


def test_loadout_parent_and_self_paths_are_not_connection_names():
    """R9: path=".." / "." address the ship root, not a named connection."""
    el = etree.fromstring('<loadout><a path=".."/><b path="."/><c path="../con_x"/></loadout>')
    assert [c for c, _line in _resolve.loadout_targets(el)] == ["con_x"]


def test_xq_quotes_a_value_containing_an_apostrophe():
    """R10: a name containing `'` must still be a valid, matching XPath literal."""
    root = etree.fromstring("<r><m n=\"it's\"/></r>")
    assert len(root.xpath(f"//m[@n={_resolve._xq(chr(105) + 't' + chr(39) + 's')}]")) == 1
