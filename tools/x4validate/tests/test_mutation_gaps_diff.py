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
    """DN16: a comment is a segment boundary; the text after it is compared, so
    changing it is a change."""
    fd = _fd("<r><t>a<!--c-->b</t></r>", "<r><t>a<!--c-->z</t></r>")
    assert [(p, a) for p, a, _o, _n in fd.attr_changes] == [("/r/t", "text()")]


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
