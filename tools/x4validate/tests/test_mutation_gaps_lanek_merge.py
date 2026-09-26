"""Mutation-campaign gaps in `_merge`, lane K (2026-09-26). Each test names the surviving
mutant it was written to kill and was verified to FAIL with it applied and PASS without."""
from __future__ import annotations

from lxml import etree

from x4validate import _merge


def _apply(base: str, diff: str):
    tree = etree.fromstring(base)
    applied = _merge.apply_diff(tree, etree.fromstring(diff))
    return etree.tostring(tree, encoding="unicode"), applied


def test_type_attribute_on_a_REPLACE_is_not_refused_as_an_unsupported_add():
    """M5: the unsupported-`type=` refusal is scoped to <add>. A <replace> carrying a
    stray type= must still apply, not be reported as an unmodelled add type."""
    out, applied = _apply("<r><a/></r>",
                          '<diff><replace sel="/r/a" type="ns"><b/></replace></diff>')
    assert applied[0].ok, applied[0].detail
    assert out == "<r><b/></r>"


def test_prepend_of_several_elements_keeps_payload_order():
    """M8: pos="prepend" with two payload elements inserts them at 0 and 1, so the
    payload's own order survives -- not reversed by inserting each at 0."""
    out, applied = _apply("<r><z/></r>",
                          '<diff><add sel="/r" pos="prepend"><x/><y/></add></diff>')
    assert applied[0].ok
    assert out == "<r><x/><y/><z/></r>"


def test_additive_dir_full_file_with_a_DIFFERENT_root_is_a_full_override_not_a_union():
    """M12: the union branch requires the overlay root to match the base root. A
    full file at libraries/ whose root tag differs is a full override."""
    base = etree.fromstring('<wares><ware id="a"/></wares>')
    over = etree.fromstring('<macros><macro name="m"/></macros>')
    tree, mode = _merge.apply_overlay(base, over, "libraries/wares.xml", "m")
    assert mode == "full"
    assert tree.tag == "macros"


def test_silent_1_is_truthy():
    """M16: silent="1" (a real corpus spelling) marks the op silent, like "true"."""
    _out, applied = _apply("<r/>", '<diff><remove sel="/r/nope" silent="1"/></diff>')
    assert not applied[0].ok
    assert applied[0].silent is True


def test_two_segment_extensions_path_is_not_a_nested_target():
    """M17: `extensions/<file>` has no <rel> part, so it is a plain path -- it must not
    be read as a cross-mod patch owned by an extension named after the FILE."""
    assert _merge._nested_target("extensions/foo.xml") is None


def test_text_replace_drops_the_targets_child_elements():
    """M18: a text-only <replace> replaces the node's whole content: its children go,
    not just its leading text."""
    out, applied = _apply("<r><a>old<b/><c/></a></r>",
                          '<diff><replace sel="/r/a">new</replace></diff>')
    assert applied[0].ok
    assert out == "<r><a>new</a></r>"
