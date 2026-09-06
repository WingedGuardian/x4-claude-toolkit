"""C10: an overlay that could not be READ must not leave the store saying 'base'.

`_merge.MergeResult.skipped` states its own contract: *"overlays that could not be
parsed and were left out of the tree. Without this channel a malformed overlay is
indistinguishable from an absent one, and the resulting tree looks complete when it
is not."* `_check.py` honours it in three places. `_effective._merge_one` returned
`(res.tree, rec)` and dropped it.

⚠ AND THE EXCEPTION HANDLER COULD NOT COVER FOR IT. `build` wraps each `_merge_one`
in `except etree.LxmlError`, which reads like a skip channel -- but `overlay_root`
catches `XMLSyntaxError` internally, so nothing ever escapes for an OVERLAY file.
That handler can only fire for the base file's own `parse_file`. The tests below
therefore go through a real malformed overlay, not a mocked raise: a mocked
exception would exercise the one path that already worked and prove nothing.
"""
from __future__ import annotations

import sqlite3

import pytest

from x4validate import _effective, _merge

REF_WARES = """<?xml version="1.0" encoding="utf-8"?>
<wares>
  <ware id="ore" name="Ore" price_average="100"/>
  <ware id="silicon" name="Silicon" price_average="200"/>
</wares>
"""

GOOD_DIFF = """<?xml version="1.0" encoding="utf-8"?>
<diff>
  <replace sel="//ware[@id='silicon']/@price_average">222</replace>
</diff>
"""

# The SAME op, with the closing tag removed. Byte-for-byte the good overlay
# otherwise, so the only variable between control and case is well-formedness.
BAD_DIFF = GOOD_DIFF.replace("</diff>", "")


def _mod(root, folder, body):
    d = root / "extensions" / folder
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "wares.xml").write_text(body, encoding="utf-8")
    (d / "content.xml").write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n'
        f'<content id="{folder}" name="{folder}" version="100" date="2026-01-01"/>\n',
        encoding="utf-8")
    return d


@pytest.fixture
def tree(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text(REF_WARES, encoding="utf-8")
    return tmp_path, ref


def _merged(tmp_path, ref, overlay_body):
    d = _mod(tmp_path, "zzz_over", overlay_body)
    cfg = _merge.Config(reference=ref, overlays=[d])
    return _merge.build_effective("libraries/wares.xml", cfg, extra_overlays=[d])


def test_the_CONTROL_reads_the_overlay_and_reports_NO_loss(tree):
    """Without this the case below could pass because the fixture never worked."""
    tmp_path, ref = tree
    res = _merged(tmp_path, ref, GOOD_DIFF)
    assert res.tree is not None
    assert res.tree.xpath("//ware[@id='silicon']/@price_average") == ["222"], (
        "the overlay did not apply, so this fixture proves nothing about dropping it")
    assert res.skipped == [], res.skipped


def test_a_MALFORMED_overlay_is_reported_through_the_skipped_channel(tree):
    """The merge layer was always right -- it recorded the loss. The defect was
    downstream, in the consumer that threw the record away."""
    tmp_path, ref = tree
    res = _merged(tmp_path, ref, BAD_DIFF)
    assert res.tree is not None, (
        "the base tree must still build -- a malformed overlay is a partial loss, "
        "not a total one, and that is exactly why it is easy to miss")
    assert res.tree.xpath("//ware[@id='silicon']/@price_average") == ["200"], (
        "precondition: the overlay must NOT have applied, or there is no loss to report")
    assert res.skipped, "the merge layer failed to record the dropped overlay"


def test_merge_one_HANDS_BACK_the_dropped_overlays(tree):
    """The unit under repair. It returned `(tree, rec)` and dropped `res.skipped`."""
    tmp_path, ref = tree
    d = _mod(tmp_path, "zzz_over", BAD_DIFF)
    cfg = _merge.Config(reference=ref, overlays=[d])
    out = _effective._merge_one("libraries/wares.xml", cfg, [d])
    assert len(out) == 3, (
        "_merge_one still returns a 2-tuple, so every caller is structurally unable "
        "to see the loss: %r" % (out,))
    _tree, _rec, dropped = out
    assert dropped, "the third element is empty; the channel is still being discarded"


def test_the_EXCEPTION_handler_can_NOT_see_a_malformed_overlay(tree):
    """★ Why the pre-existing `except etree.LxmlError` was not already covering this.

    This is the assumption that made the defect invisible for a year: the handler
    LOOKS like a skip channel. It is one -- for the base file only. `overlay_root`
    swallows `XMLSyntaxError` internally, so a malformed OVERLAY raises nothing and
    the handler never runs. Pinned as a test because it is the thing a reader (and
    a reviewer) gets wrong by inspection.
    """
    tmp_path, ref = tree
    d = _mod(tmp_path, "zzz_over", BAD_DIFF)
    cfg = _merge.Config(reference=ref, overlays=[d])
    # No pytest.raises: the point is that NOTHING is raised.
    tree_, _rec, dropped = _effective._merge_one("libraries/wares.xml", cfg, [d])
    assert tree_ is not None and dropped, (
        "if this ever starts raising, the exception path becomes reachable and the "
        "comment above it must be corrected rather than left as folklore")


def test_the_two_losses_are_COUNTED_SEPARATELY(tree):
    """`absent` and `present but wrong` are different defects and only one of them
    produces a confident wrong answer. Summing them would be its own narrowing."""
    sk = _effective._SkipCount()
    sk.add("a/b.xml", ValueError("boom"))
    sk.add_overlay("c/d.xml", ["ov/x.xml: malformed XML, overlay skipped"])
    sk.add_overlay("c/e.xml", ["ov/y.xml: malformed", "ov/z.xml: malformed"])
    assert sk.n == 1, sk.n
    assert sk.dropped == 3, sk.dropped
    assert len(sk.samples) == 1 and len(sk.dropped_samples) == 3


def test_the_STORE_records_the_dropped_count_so_it_outlives_the_build(tmp_path):
    """Build-time progress scrolls past and is gone; a store carrying silently-wrong
    origins outlives the run that made it. A reader must be able to ask the store."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text(REF_WARES, encoding="utf-8")
    db = tmp_path / "eff.sqlite"
    _effective._write_db(db, _merge.Config(reference=ref), [], [], {}, [], [],
                         dropped_overlays=2,
                         dropped_samples=["a.xml: malformed", "b.xml: malformed"])
    con = sqlite3.connect(str(db))
    try:
        got = dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()
    assert got["dropped_overlays"] == "2", got.get("dropped_overlays")
    assert "a.xml" in got["dropped_overlay_samples"], got.get("dropped_overlay_samples")


def test_a_CLEAN_build_records_ZERO_rather_than_omitting_the_key(tmp_path):
    """The twin. An ABSENT key is unreadable as 'none were dropped' -- it is
    indistinguishable from a store written before this key existed, which is the
    same absence-vs-non-answer conflation the key exists to end."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text(REF_WARES, encoding="utf-8")
    db = tmp_path / "eff.sqlite"
    _effective._write_db(db, _merge.Config(reference=ref), [], [], {}, [], [])
    con = sqlite3.connect(str(db))
    try:
        got = dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()
    assert got["dropped_overlays"] == "0", got
    assert got["dropped_overlay_samples"] == "[]", got
