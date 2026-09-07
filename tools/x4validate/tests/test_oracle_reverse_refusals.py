"""The reverse oracle's PASS branch was reachable with our own side unexamined.

`disagree_a` is `missing_ids & found_ids` and `disagree_b` is `parts & known`. If the
effective t/ tree or the component index fails to build, both sets are empty BY
CONSTRUCTION -- so the gate printed "We agree with the engine on every checkable
complaint in this log" and returned 0 over a comparison it never made. The engine
named the misses; we examined nothing; the two "agreed".

The existing refusal covered the OTHER empty input (a log with no complaints), which
is why this one looked handled. Gotcha #26: ask what would concretely have made it go
red -- here, nothing that could actually have occurred.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))

LOG_BOTH = (
    "[General] GetText(pageid=1001, textid=42) TextID not found!\n"
    "[=ERROR=] Cannot find referenced part template XML file from index 'part_x'\n"
)


def _drive(monkeypatch, tmp_path, log_text, trees):
    """Run main() against a synthetic log and a synthetic effective tree.

    `trees` maps vpath -> XML string, or -> None for "could not be built"."""
    import oracle_reverse as orev
    log = tmp_path / "debug.txt"
    log.write_text(log_text, encoding="utf-8")
    monkeypatch.setattr(orev, "log_path", lambda: log)
    monkeypatch.setattr(
        orev, "effective",
        lambda vpath: (etree.fromstring(trees[vpath].encode("utf-8"))
                       if trees.get(vpath) else None))
    return orev.main()


T_WITH_PAGE = '<language id="44"><page id="1001"><t id="9">x</t></page></language>'
IDX_WITH_ENTRY = '<index><entry name="something_else" value="v"/></index>'


def test_a_t_tree_that_could_not_be_built_is_a_NON_ANSWER(monkeypatch, tmp_path):
    """Pre-fix: rc 0, "We agree with the engine on every checkable complaint"."""
    rc = _drive(monkeypatch, tmp_path, LOG_BOTH,
                {"index/components.xml": IDX_WITH_ENTRY})
    assert rc == 2


def test_an_EMPTY_component_index_is_a_NON_ANSWER(monkeypatch, tmp_path):
    """An index that parses to zero entries can never contain the engine's miss,
    so `parts & known` is empty by construction rather than by measurement."""
    rc = _drive(monkeypatch, tmp_path, LOG_BOTH,
                {"t/0001-l044.xml": T_WITH_PAGE, "index/components.xml": "<index/>"})
    assert rc == 2


def test_a_t_tree_with_ZERO_pages_is_a_NON_ANSWER(monkeypatch, tmp_path):
    """Built, but empty. `scanned` alone would have called this examined."""
    rc = _drive(monkeypatch, tmp_path, LOG_BOTH,
                {"t/0001-l044.xml": '<language id="44"/>',
                 "index/components.xml": IDX_WITH_ENTRY})
    assert rc == 2


def test_BOTH_SIDES_EXAMINED_and_agreeing_is_still_rc0(monkeypatch, tmp_path):
    """The twin that makes the three above mean something: with a real tree that
    genuinely does NOT resolve the engine's complaints, agreement is a measurement
    and must still pass."""
    rc = _drive(monkeypatch, tmp_path, LOG_BOTH,
                {"t/0001-l044.xml": T_WITH_PAGE,        # page 1001 exists, t 42 does not
                 "index/components.xml": IDX_WITH_ENTRY})
    assert rc == 0


def test_a_REAL_disagreement_still_fails(monkeypatch, tmp_path):
    """The other twin: the gate must still be able to find something."""
    rc = _drive(monkeypatch, tmp_path, LOG_BOTH,
                {"t/0001-l044.xml":
                     '<language id="44"><page id="1001"><t id="42">x</t></page></language>',
                 "index/components.xml": IDX_WITH_ENTRY})
    assert rc == 1


def test_a_log_with_no_checkable_complaint_is_still_a_NON_ANSWER(monkeypatch, tmp_path):
    """The pre-existing refusal must survive the new one being added in front of it."""
    rc = _drive(monkeypatch, tmp_path, "nothing checkable here\n",
                {"t/0001-l044.xml": T_WITH_PAGE, "index/components.xml": IDX_WITH_ENTRY})
    assert rc == 2
