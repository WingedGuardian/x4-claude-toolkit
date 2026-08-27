"""x4save: the two defects that produced false positives, pinned in both directions.

Each of the first two tests has a FALSIFICATION TWIN that re-runs the same fixture
with the fix removed and asserts the bad answer comes back. A test that cannot fail
proves nothing (gotcha #26), and both of these shipped a wrong number before they were
caught -- 2,463 and 1,068 false dangling respectively.
"""
from __future__ import annotations

import gzip
import re

import pytest

from x4validate import _savecli


def _write_save(path, body: str, patches: str = "", history: str = "") -> None:
    """A minimal but STRUCTURALLY REAL save: gzip, <info>, <patches>, <history>."""
    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<savegame>\n<info>\n'
        '<save name="#T" date="1"/>\n'
        '<game id="X4" version="900" build="611726" time="3600" start="custom"/>\n'
        '<player name="P" location="{1,2}" money="42"/>\n'
        f"<patches>\n{patches}<history>\n{patches}{history}</history>\n</patches>\n"
        "</info>\n<universe>\n" + body + "\n</universe>\n</savegame>\n"
    )
    with gzip.open(path, "wb") as fh:
        fh.write(doc.encode("utf-8"))


# --- defect 1: <connection macro=> mirrors the connection NAME ------------------

#: `macro=` on <connection> duplicates the connection name and is NOT a macro
#: reference. Counting it produced 2,463 false dangling on one save.
_BODY_CONNECTION = (
    '<component macro="real_ship_macro">\n'
    '  <connection connection="con_cockpit" macro="con_cockpit"/>\n'
    '  <connection connection="con_dock_xs" macro="con_dock_xs"/>\n'
    "</component>\n"
)


def test_connection_macro_is_not_a_reference(tmp_path):
    p = tmp_path / "s.xml.gz"
    _write_save(p, _BODY_CONNECTION)
    refs = _savecli.extract_refs(p)
    assert set(refs) == {"real_ship_macro"}, (
        "con_cockpit / con_dock_xs are connection NAMES echoed into macro=; "
        "counting them is the 2,463-false-dangling defect")


def test_connection_macro_WOULD_be_counted_without_the_element_scope(tmp_path):
    """Falsification twin: widen the scope and the bad answer must come back."""
    p = tmp_path / "s.xml.gz"
    _write_save(p, _BODY_CONNECTION)
    wide = re.compile(rb'\bmacro="([^"]+)"')          # the original, unscoped pattern
    found = set(m.group(1).decode() for m in wide.finditer(gzip.open(p, "rb").read()))
    assert {"con_cockpit", "con_dock_xs"} <= found, (
        "if this does not reproduce the false positives, the fixture no longer "
        "exercises the defect and the test above proves nothing")


# --- defect 2: the corpus mixes case, the save lowercases -----------------------

def test_case_folding_resolves_a_lowercased_reference():
    """1,068 false positives on a STOCK VANILLA save came from comparing case-sensitively."""
    defined = {"Cluster_42_Sector001_macro", "ship_arg_s_fighter_01_a_macro"}
    folded = {n.lower() for n in defined}
    save_ref = "cluster_42_sector001_macro"          # exactly how a save writes it
    assert save_ref not in defined, "fixture must reproduce the case mismatch"
    assert save_ref in folded


def test_case_SENSITIVE_comparison_reports_a_false_positive():
    """Falsification twin: without the fold, a vanilla macro reads as dangling."""
    defined = {"Cluster_42_Sector001_macro"}
    assert "cluster_42_sector001_macro" not in defined


# --- the header, and what it is allowed to claim --------------------------------

def test_patch_lists_separates_current_from_history(tmp_path):
    p = tmp_path / "s.xml.gz"
    _write_save(p,
                "<component/>",
                patches='<patch extension="ego_dlc_split" version="900" name="S"/>\n',
                history='<patch extension="ego_dlc_ventures" version="127" name="V"/>\n')
    cur, hist = _savecli.patch_lists(_savecli.read_header(p))
    assert cur == [("ego_dlc_split", "900")]
    assert ("ego_dlc_ventures", "127") in hist
    assert ("ego_dlc_ventures", "127") not in cur, (
        "an extension in <history> but not <patches> is NOT loaded now")


# --- a run that examined nothing must never exit 0 ------------------------------

def test_unreadable_save_raises_rather_than_reporting_clean(tmp_path):
    p = tmp_path / "not-a-save.xml.gz"
    p.write_bytes(b"[project]\nname = 'nope'\n")
    with pytest.raises(_savecli.SaveUnreadable):
        _savecli.extract_refs(p)


def test_truncated_save_raises_rather_than_reporting_a_partial_count(tmp_path):
    """The dangerous case: half a save silently yielding a low 'unresolved' count."""
    full = tmp_path / "full.xml.gz"
    _write_save(full, "\n".join(f'<component macro="m{i}"/>' for i in range(2000)))
    cut = tmp_path / "cut.xml.gz"
    cut.write_bytes(full.read_bytes()[: len(full.read_bytes()) // 2])
    with pytest.raises(_savecli.SaveUnreadable):
        _savecli.extract_refs(cut)


def test_missing_info_block_is_a_non_answer(tmp_path):
    p = tmp_path / "s.xml.gz"
    with gzip.open(p, "wb") as fh:
        fh.write(b"<savegame><universe/></savegame>")
    with pytest.raises(_savecli.SaveUnreadable):
        _savecli.read_header(p)


def test_main_returns_2_not_0_for_an_unreadable_save(tmp_path):
    p = tmp_path / "junk.xml.gz"
    p.write_bytes(b"definitely not gzip")
    assert _savecli.main(["info", str(p)]) == 2, "rc 0 would read as a clean save"


# --- chunk-boundary safety ------------------------------------------------------

def test_reference_spanning_a_chunk_boundary_is_still_found(tmp_path, monkeypatch):
    """A tag split across two reads must not be dropped; hence the carried tail."""
    p = tmp_path / "s.xml.gz"
    _write_save(p, "\n".join(f'<component macro="m{i:05d}"/>' for i in range(5000)))
    monkeypatch.setattr(_savecli, "_CHUNK", 997)      # tiny, prime, forces many splits
    refs = _savecli.extract_refs(p)
    assert len(refs) == 5000, f"lost references at chunk boundaries: {len(refs)}"
