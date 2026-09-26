r"""The load-order oracle gate, and the engine rule it holds `compute_load_order` to.

Two halves:

* The GATE's own logic (`parse_sequences`, `score`, the refusal paths) -- pinned so the
  instrument can go red and can refuse. A gate that could only print PASS would be
  decoration (CLAUDE.md #26).
* LO-1 (AUDIT-2026-09-24): the ENGINE's order, MEASURED on a real 125-mod install --
  372 file classes / 5,134 ordered pairs across two launches two weeks apart, 0
  inverted by this rule, 685 inverted by the pre-fix code:
    - folders walked in case-insensitive UPPERCASE order (`_` sorts AFTER letters,
      a space before `_`);
    - repeated passes; in each pass every mod whose INSTALLED dependencies are already
      loaded -- including ones loaded earlier in the SAME pass -- loads.
  Those cases are xfail(strict) until the fix lands, so the fix is forced to prove
  itself and the marker cannot be forgotten.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
import load_order_oracle as g  # noqa: E402

from x4validate import _loadorder  # noqa: E402

BS = "\\"


def _line(folder: str, rel: str) -> str:
    return ("[FileIO ] 0.00 File I/O: Failed to verify the file signature for file "
            f"'.{BS}extensions{BS}{folder}{BS}{rel.replace('/', BS)}' (error: 14)\n")


# --------------------------------------------------------------------------- parse
def test_parse_keeps_first_check_order_per_class():
    lines = [_line("b_mod", "libraries/wares.xml"), _line("a_mod", "libraries/wares.xml"),
             _line("b_mod", "libraries/wares.xml"),        # a repeat check is not a new position
             _line("a_mod", "t/0001.xml"), "unrelated line\n"]
    seqs = g.parse_sequences(lines)
    assert seqs == {"libraries/wares.xml": ["b_mod", "a_mod"], "t/0001.xml": ["a_mod"]}


def test_parse_lowercases_and_keeps_nested_remainder_separate():
    lines = [_line("Ship AI Core", "libraries/wares.xml"),
             _line("patcher", "extensions/vro/libraries/wares.xml")]
    seqs = g.parse_sequences(lines)
    assert seqs["libraries/wares.xml"] == ["ship ai core"]
    assert seqs["extensions/vro/libraries/wares.xml"] == ["patcher"]


# --------------------------------------------------------------------------- score
def test_score_agreeing_order_has_no_inversions():
    s = g.score(["a", "b", "c"], {"x.xml": ["a", "b", "c"]})
    assert (s.classes, s.pairs, s.inversions) == (1, 3, 0)


def test_score_counts_every_inverted_pair_exactly():
    s = g.score(["c", "b", "a"], {"x.xml": ["a", "b", "c"]})
    assert (s.pairs, s.inversions) == (3, 3)
    assert s.bad[0][0] == "x.xml"


def test_score_ignores_single_mod_classes_and_tracks_unknown_folders():
    s = g.score(["a", "b"], {"one.xml": ["a"], "two.xml": ["a", "ghost", "b"]})
    assert s.classes == 1 and s.pairs == 1          # 'ghost' is not compared...
    assert s.unknown_folders == {"ghost"}           # ...but it is counted, never dropped


def test_score_with_nothing_comparable_has_zero_classes():
    """main() turns this into rc 2 -- an empty comparison is never a PASS."""
    assert g.score(["a"], {"x.xml": ["a"]}).classes == 0


def test_main_refuses_without_a_log(monkeypatch):
    monkeypatch.setattr(g, "_log_path", lambda: None)
    assert g.main() == 2


# --------------------------------------------------------------------------- LO-1
def _mods(tmp_path: Path, spec: dict[str, list[str]]) -> list[dict]:
    """spec: {folder: [dependency ids]}; each mod's id is its folder name lowercased."""
    out = []
    for folder, deps in spec.items():
        d = tmp_path / folder
        d.mkdir()
        dep_xml = "".join(f'<dependency id="{x}"/>' for x in deps)
        (d / "content.xml").write_text(
            f'<content id="{folder.lower()}" version="100">{dep_xml}</content>',
            encoding="utf-8")
        out.append({"folder": folder, "path": str(d)})
    return out


def _order(tmp_path, spec):
    return _loadorder.compute_load_order(_mods(tmp_path, spec))


def test_LO1_folder_names_compare_case_insensitively(tmp_path):
    assert _order(tmp_path, {"Zeta": [], "alpha": []}) == ["alpha", "Zeta"]


def test_LO1_underscore_sorts_after_letters(tmp_path):
    assert _order(tmp_path, {"s_combat": [], "station": []}) == ["station", "s_combat"]


def test_LO1_space_sorts_before_underscore(tmp_path):
    """Both rules agree here -- the control that the case above is not an artefact."""
    assert _order(tmp_path, {"ship_v": [], "ship ai": []}) == ["ship ai", "ship_v"]


def test_LO1_unmet_dependency_waits_for_the_next_pass(tmp_path):
    # pass 1: a skipped (c not loaded yet), b, c, d  -- pass 2: a
    assert _order(tmp_path, {"a": ["c"], "b": [], "c": [], "d": []}) == ["b", "c", "d", "a"]


def test_LO1_dependency_loaded_earlier_in_the_same_pass_counts(tmp_path):
    """Refutes the 'defer every dependent to the next pass' variant (33/72 on the log):
    x's dependency a loaded earlier in THIS pass, so x loads in this pass too."""
    assert _order(tmp_path, {"a": [], "b": [], "x": ["a"]}) == ["a", "b", "x"]


def test_LO1_uninstalled_dependency_does_not_hold_a_mod_back(tmp_path):
    """34 of 125 real mods declare dependencies that are not mods here (mostly DLC ids);
    the MEASURED order places them as if those were satisfied. Missing REQUIRED
    dependencies are an open question for the probe (LO-3), not asserted here."""
    assert _order(tmp_path, {"a": ["ego_dlc_boron"], "b": []}) == ["a", "b"]
