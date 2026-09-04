r"""A `sel=` that is not a node-set must be a FINDING, never a crash or a wrong count.

`tree.xpath(sel)` returns a list for a node selector, but a float / bool / string for
an expression -- `count(//ware)`, `true()`, `string(//ware/@id)`. The code went straight
to `len(targets)`, which produced two different failures from one cause:

    <replace sel="count(//ware)">3</replace>   TypeError: object of type 'float'
                                               has no len()  -- a raw traceback at rc 1,
                                               the SAME rc as "your mod has errors",
                                               and `--json` emitted 0 bytes
    <replace sel="string(//ware/@id)">x</replace>
                                               "sel matched 18 nodes" -- 18 is the
                                               LENGTH OF THE STRING. No crash, a
                                               confident wrong number, which is worse

Both are malformed patches: X4's `sel` selects nodes. The tool's job is to say so.
"""

from __future__ import annotations

from lxml import etree

from x4validate import _merge

BASE = b"""<wares>
  <ware id="ore" volume="10"/>
  <ware id="ice" volume="20"/>
</wares>"""

SCALARS = [
    ('<replace sel="count(//ware)">3</replace>', "float"),
    ('<replace sel="true()">x</replace>', "bool"),
    ('<remove sel="count(//ware)"/>', "float"),
    ('<add sel="boolean(//ware)"><x/></add>', "bool"),
    ('<replace sel="string(//ware/@id)">x</replace>', "string"),
    ('<replace sel="name(//ware)">x</replace>', "string"),
]


def _apply(op_xml):
    tree = etree.fromstring(BASE)
    diff = etree.fromstring(("<diff>%s</diff>" % op_xml).encode())
    return _merge.apply_diff(tree, diff)


def test_a_scalar_sel_is_reported_not_raised():
    for op_xml, kind in SCALARS:
        applied = _apply(op_xml)                      # must not raise
        assert len(applied) == 1, op_xml
        a = applied[0]
        assert not a.ok, "%s (%s) was reported as applied" % (op_xml, kind)
        assert "node" in a.detail.lower(), (
            "the reason must say the selector is not a node-set; got %r" % a.detail)


def test_the_reason_never_reports_a_node_COUNT_for_a_string():
    """`len("ore")` is 3 and `len(name(//ware))` is 4. Reporting either as a node
    count is a confident wrong number, which is worse than the crash beside it."""
    applied = _apply('<replace sel="string(//ware/@id)">x</replace>')
    assert "matched 18 nodes" not in applied[0].detail
    assert "nodes" not in applied[0].detail or "node-set" in applied[0].detail


def test_a_REAL_node_selector_is_untouched():
    """The control: without it, returning an error for everything would pass above."""
    tree = etree.fromstring(BASE)
    diff = etree.fromstring(
        b'<diff><replace sel="//ware[@id=\'ore\']/@volume">99</replace></diff>')
    applied = _merge.apply_diff(tree, diff)
    assert applied[0].ok, applied[0].detail
    assert tree.xpath("//ware[@id='ore']/@volume") == ["99"]


def test_an_empty_node_set_still_reports_matched_nothing():
    """A scalar and an empty node-set are different findings and must stay so."""
    applied = _apply('<replace sel="//ware[@id=\'nope\']">x</replace>')
    assert not applied[0].ok
    assert "matched nothing" in applied[0].detail


def test_a_falsey_scalar_is_still_a_scalar_finding():
    """`count(//nope)` is 0.0 and `false()` is False -- both falsey, so the old
    `if not targets` branch swallowed them as 'matched nothing'. They are malformed
    selectors, not empty ones."""
    for op_xml in ('<replace sel="count(//nope)">x</replace>',
                   '<replace sel="false()">x</replace>'):
        applied = _apply(op_xml)
        assert not applied[0].ok
        assert "node" in applied[0].detail.lower(), applied[0].detail
        assert "matched nothing" not in applied[0].detail, (
            "a malformed selector was reported as an empty match: " + op_xml)
