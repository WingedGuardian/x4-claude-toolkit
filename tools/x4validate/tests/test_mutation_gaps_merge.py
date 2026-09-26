"""Mutation-campaign gaps in `_merge` op application (campaign 2, 2026-09-26): MG-5 tail
placement and MG-2 text-node adds. Each test names the surviving mutant it was written
to kill and was verified to FAIL with it applied and PASS without it."""
from __future__ import annotations

from lxml import etree

from x4validate import _merge


def _apply(base: str, diff: str):
    tree = etree.fromstring(base)
    applied = _merge.apply_diff(tree, etree.fromstring(diff))
    return etree.tostring(tree, encoding="unicode"), applied


def test_removed_nodes_tail_joins_the_PREVIOUS_siblings_tail():
    """MG2b: with a previous sibling, the removed node's tail goes to THAT sibling's
    tail -- after it, where it was -- not to the parent's leading text."""
    out, applied = _apply("<r><a/>A<b/>B<c/></r>", '<diff><remove sel="/r/b"/></diff>')
    assert applied[0].ok
    assert out == "<r><a/>AB<c/></r>"


def test_replaced_nodes_tail_follows_the_LAST_payload_element():
    """MG3b: a multi-element <replace> puts the replaced node's tail after the LAST
    inserted element, not between the payload elements."""
    out, applied = _apply("<r><a/>T<z/></r>",
                          '<diff><replace sel="/r/a"><x/><y/></replace></diff>')
    assert applied[0].ok
    assert out == "<r><x/><y/>T<z/></r>"


def test_text_add_beside_the_document_root_is_refused():
    """MG12: a text-only <add pos="after"> on the ROOT has no sibling position; it
    must be reported NOT applied, never silently written to the root's tail."""
    out, applied = _apply("<r><a/></r>", '<diff><add sel="/r" pos="after">tail</add></diff>')
    assert not applied[0].ok
    assert "document root" in applied[0].detail
    assert out == "<r><a/></r>"


def test_whitespace_only_add_payload_adds_nothing():
    """MG5b: a pretty-printed empty <add> (whitespace, no elements) is an applied
    no-op -- the whitespace is formatting, not a text node to insert."""
    out, applied = _apply("<r><a/></r>", '<diff><add sel="/r">\n    \n  </add></diff>')
    assert applied[0].ok
    assert out == "<r><a/></r>"
