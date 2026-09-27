"""Mutation-campaign gaps in `_diff` (x4diff) keying, text and stacking (campaign 2,
2026-09-26). Each test names the surviving mutant it was written to kill and was
verified to FAIL with it applied and PASS without it."""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from x4validate import _diff


def _fd(old: str, new: str):
    return _diff.diff_file(etree.fromstring(old), etree.fromstring(new), "x.xml")


def test_two_duplicates_of_one_key_are_told_apart():
    """D1r: exactly TWO siblings sharing a key still need positional suffixes; without
    them they collapse onto one path and an edit to the first vanishes."""
    fd = _fd('<r><x a="1"/><x a="2"/></r>', '<r><x a="9"/><x a="2"/></r>')
    assert fd.attr_changes == [("/r/x#0", "a", "1", "9")]


def test_same_payload_ops_are_keyed_by_sel_not_position():
    """DN9: ops installing the same payload under different `sel`s are told apart by
    `sel`; positional keys would re-key untouched ops when one is inserted first."""
    op = '<add sel="{}"><ware id="x"/></add>'
    old = "<diff>" + op.format("/a") + op.format("/b") + "</diff>"
    new = "<diff>" + op.format("/c") + op.format("/a") + op.format("/b") + "</diff>"
    fd = _fd(old, new)
    assert fd.attr_changes == [] and fd.nodes_removed == []
    assert "/diff/add[ware@id=x][@sel=/c]" in fd.nodes_added


def test_op_without_payload_identity_is_keyed_by_sel():
    """DN15: a <remove> has no payload, so its identity is its `sel`; removing one of
    two such ops must read as exactly that op removed."""
    fd = _fd('<diff><remove sel="/a"/><remove sel="/b"/></diff>',
             '<diff><remove sel="/b"/></diff>')
    assert fd.nodes_removed == ["/diff/remove[@sel=/a]"]
    assert fd.nodes_added == [] and fd.attr_changes == []


def test_payload_key_reads_only_the_FIRST_payload_element():
    """DN8: the op's payload identity is its FIRST element child's; a first child
    without identity means 'key by sel', not 'search further children'."""
    op = etree.fromstring('<add sel="/r"><foo/><ware id="x"/></add>')
    assert _diff._op_key(op) == "add[@sel=/r]"


def test_text_after_a_comment_is_its_own_segment():
    """DN16, corrected by finding 8 (release-review v3.3.0): a comment is NO LONGER
    a segment boundary (its tail folds into the text already running, so "a" +
    "b" around it reads as one segment "ab"), but the text is still compared as
    ordinary content either way -- "ab" -> "az" is still a change."""
    fd = _fd("<r><t>a<!--c-->b</t></r>", "<r><t>a<!--c-->z</t></r>")
    assert [(p, a) for p, a, _o, _n in fd.attr_changes] == [("/r/t", "text()")]


def test_inserting_a_comment_before_unchanged_text_is_NOT_a_phantom_change():
    """Finding 8: a comment WAS a segment boundary, so inserting one before
    unchanged text split "5" into a leading empty segment plus "5" -- a phantom
    text() change ("5" -> " <SEP> 5") with the segment separator itself now inside
    the reported value, purely from the comment's presence. No content changed."""
    fd = _fd("<r><t>5</t></r>", "<r><t><!--c-->5</t></r>")
    assert fd.attr_changes == [], fd.attr_changes


def test_a_PI_before_unchanged_text_is_also_NOT_a_phantom_change():
    """Twin: a processing instruction is the other non-str-tag shape `_text_value`
    must treat the same way as a comment."""
    fd = _fd("<r><t>5</t></r>", "<r><t><?pi data?>5</t></r>")
    assert fd.attr_changes == [], fd.attr_changes


def test_a_comment_inserted_between_two_REAL_elements_is_still_invisible():
    """Twin: a comment between two ordinary child elements must fold into
    whichever segment it sits in, never manufacture an extra one of its own."""
    fd = _fd("<r><t><a/>x<b/></t></r>", "<r><t><a/>x<!--c--><b/></t></r>")
    assert fd.attr_changes == [], fd.attr_changes


def test_a_later_full_document_supersedes_a_diff_only_baseline(tmp_path: Path):
    """DN3: in a stack whose first supplier is a <diff>, a later layer's FULL document
    supersedes the patch set (there is no base for the patches to apply to)."""
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    for d, body in ((d1, '<diff><add sel="/wares"><ware id="a"/></add></diff>'),
                    (d2, '<wares><ware id="b"/></wares>')):
        (d / "libraries").mkdir(parents=True)
        (d / "libraries/wares.xml").write_text(body, encoding="utf-8")
    tree = _diff.read_merged([d1, d2], "libraries/wares.xml")
    assert tree is not None and tree.tag == "wares"
    assert [w.get("id") for w in tree] == ["b"]


# --- finding 7: _norm must not conflate Unicode whitespace with ASCII formatting ------
#
# str.split() (Python's own notion of whitespace) treats NBSP (U+00A0) and other
# Unicode spaces exactly like an ASCII space, and always strips both ends -- so an
# NBSP-for-space edit, or a leading/trailing-space edit on an otherwise single-line
# value, read as VERBATIM. The pretty-print flood case _norm exists for is real
# multi-line indentation, and must still collapse to nothing.

def test_norm_preserves_NBSP_as_distinct_from_a_regular_space():
    assert _diff._norm("5 ") != _diff._norm("5 ")
    assert _diff._norm("5　") != _diff._norm("5 ")   # ideographic space, U+3000


def test_norm_preserves_a_leading_or_trailing_space_on_single_line_text():
    assert _diff._norm(" 5") != _diff._norm("5")
    assert _diff._norm("5 ") != _diff._norm("5")


def test_norm_still_floods_nothing_on_a_MULTILINE_reindent():
    """Twin: the case _norm exists for -- real pretty-print whitespace around a
    multi-line segment (newlines, indentation) is still fully collapsed, exactly as
    test_REINDENTING_a_document_is_not_an_edit (test_threeway.py) exercises
    end-to-end."""
    assert _diff._norm("  Same\n    ") == _diff._norm("Same") == "Same"


def test_an_NBSP_for_space_edit_is_reported_not_verbatim():
    fd = _fd("<r><t>a b</t></r>", "<r><t>a b</t></r>")
    assert [(p, a) for p, a, _o, _n in fd.attr_changes] == [("/r/t", "text()")]


def test_a_leading_space_edit_on_single_line_text_is_reported_not_verbatim():
    fd = _fd("<r><t> keep</t></r>", "<r><t>keep</t></r>")
    assert [(p, a) for p, a, _o, _n in fd.attr_changes] == [("/r/t", "text()")]
