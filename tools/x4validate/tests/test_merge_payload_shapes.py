"""The boundaries the AUDIT-2026-09-24 MG-1/MG-2/MG-5 fixes chose, pinned so they cannot drift.

MEASURED before choosing, over every installed mod (loose + packed, 4,683 XML files):
  * 88 `<add>` ops carry NO payload at all and 2 carry only comments. The engine adds
    nothing for them, and reporting them as failures would have filed ~90 false findings
    overnight -- so they stay APPLIED no-ops.
  * 6 carry bare TEXT (an RFC 5261 text-node add); these are now modelled, where they
    used to change nothing while reporting success.
  * 0 selectors use `text()`; those are REFUSED with a reason, never guessed.
"""
from __future__ import annotations

import pytest
from lxml import etree

from x4validate import _merge


def _apply(base: str, diff: str):
    tree = _merge.parse_bytes(base.encode("utf-8"))
    ops = _merge.apply_diff(tree, _merge.parse_bytes(diff.encode("utf-8")))
    return etree.tostring(tree), ops


def test_an_empty_add_is_an_applied_no_op_not_a_failure():
    out, ops = _apply("<r><a/></r>", '<diff><add sel="//a"/></diff>')
    assert ops[0].ok and out == b"<r><a/></r>"


def test_a_comment_only_add_is_an_applied_no_op_not_a_failure():
    out, ops = _apply("<r><a/></r>", '<diff><add sel="//a"><!-- off --></add></diff>')
    assert ops[0].ok and out == b"<r><a/></r>"


@pytest.mark.parametrize("pos,want", [
    ("", b"<r><a>x<k/>T</a></r>"),          # append: after the last child
    ("prepend", b"<r><a>Tx<k/></a></r>"),
    ("after", b"<r><a>x<k/></a>T</r>"),
    ("before", b"<r>T<a>x<k/></a></r>"),
])
def test_a_text_add_lands_where_an_element_would(pos, want):
    attr = f' pos="{pos}"' if pos else ""
    out, ops = _apply("<r><a>x<k/></a></r>", f'<diff><add sel="//a"{attr}>T</add></diff>')
    assert ops[0].ok, ops[0].detail
    assert out == want


def test_a_text_selector_is_refused_with_a_reason():
    out, ops = _apply("<r><a>x</a></r>", '<diff><replace sel="//a/text()">y</replace></diff>')
    assert not ops[0].ok and "text node" in ops[0].detail
    assert out == b"<r><a>x</a></r>"


def test_a_comment_target_still_applies():
    """Comments are elements to lxml; DLC patches anchor on them (pos=after a comment)."""
    out, ops = _apply("<r><!--c--><a/></r>", '<diff><remove sel="//comment()"/></diff>')
    assert ops[0].ok and out == b"<r><a/></r>"
