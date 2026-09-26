"""Mutation-campaign gaps in `_loadorder.compute_load_order` (campaign 2, 2026-09-26).

Every test here was written against a NAMED surviving mutant and verified to FAIL with
that mutant applied and PASS without it. The mutant id is in each docstring, so a later
campaign can map a kill back to its test.

These pin the behaviour the module's docstring STATES, for an "installed"-scope caller
(`_registry.mods("active")` already removes cycles and missing required deps, so the
cycle and duplicate branches below are the safety net the docstring describes).
"""
from __future__ import annotations

from pathlib import Path

from x4validate import _loadorder


def _mods(tmp_path: Path, spec: list[tuple[str, str, list[str]]]) -> list[dict]:
    """spec: [(folder, manifest id, [dependency ids])], in registry order."""
    out = []
    for folder, mod_id, deps in spec:
        d = tmp_path / folder
        d.mkdir(exist_ok=True)
        dep_xml = "".join(f'<dependency id="{x}"/>' for x in deps)
        (d / "content.xml").write_text(
            f'<content id="{mod_id}" version="100">{dep_xml}</content>', encoding="utf-8")
        out.append({"folder": folder, "path": str(d)})
    return out


def _order(tmp_path, spec, dropped=None):
    return _loadorder.compute_load_order(_mods(tmp_path, spec), dropped)


def test_dependency_loaded_earlier_in_the_same_pass_places_the_dependent_in_that_pass(tmp_path):
    """LN1: x's dependency a loads earlier in pass 1, so x loads in pass 1 -- BEFORE z,
    which sorts after x. A rule that only sees mods loaded in PREVIOUS passes defers x
    to pass 2 and puts z first. (The existing LO-1 case a,b,x cannot tell the two
    apart: x is last in the walk either way.)"""
    assert _order(tmp_path, [("a", "a", []), ("x", "x", ["a"]), ("z", "z", [])]) \
        == ["a", "x", "z"]


def test_self_dependency_does_not_hold_a_mod_back(tmp_path):
    """LN2/L3: a manifest naming its OWN id is not a dependency edge. Treated as one,
    the mod waits on itself forever, falls into the cycle fallback, and moves after
    every other mod -- with a spurious 'dependency cycle' record."""
    dropped: list[str] = []
    assert _order(tmp_path, [("a", "a", ["a"]), ("b", "b", [])], dropped) == ["a", "b"]
    assert dropped == []


def test_duplicate_id_dependency_resolves_to_the_LATER_folder_and_is_recorded(tmp_path):
    """LN11/L7: two folders claim id 'dup'; per the recorded message 'the later one wins
    the id', so b's dependency resolves to zz_late (registry order), and b waits for it.
    First-wins would resolve it to aa_early and load b before zz_late."""
    dropped: list[str] = []
    order = _order(tmp_path, [("aa_early", "dup", []), ("zz_late", "dup", []),
                              ("b", "b", ["dup"])], dropped)
    assert order == ["aa_early", "zz_late", "b"]
    assert len(dropped) == 1
    assert "'dup'" in dropped[0] and "'aa_early'" in dropped[0] and "'zz_late'" in dropped[0]


def test_cycle_is_recorded_and_falls_back_to_the_folder_sort_order(tmp_path):
    """LN8/L8 (record) and L9r (fallback order): a <-> b is a cycle. The rest follow
    the SORT order (a before b), not its reverse, and the assumption is recorded."""
    dropped: list[str] = []
    order = _order(tmp_path, [("b", "b", ["a"]), ("a", "a", ["b"]), ("c", "c", [])],
                   dropped)
    assert order == ["c", "a", "b"]
    assert len(dropped) == 1 and "dependency cycle among 2 mod(s) (a, b)" in dropped[0]


def test_repeated_folder_is_recorded_once_and_is_not_an_id_clash(tmp_path):
    """LN9/L10 (the duplicate-folder record) and L12 (a folder repeated with its own
    id is NOT two folders claiming one id -- the clash record needs the folders to
    DIFFER). Exactly one record, and it is the duplicate-folder one."""
    mods = _mods(tmp_path, [("a", "a", []), ("b", "b", [])])
    mods.append(dict(mods[0]))
    dropped: list[str] = []
    order = _loadorder.compute_load_order(mods, dropped)
    assert order == ["a", "b"]
    assert len(dropped) == 1 and "appears more than once" in dropped[0]


def test_sort_key_is_per_character_not_whole_string_upper():
    """LN5: `str.upper()` turns a sharp s into 'SS' and changes the order; the
    docstring's contract is PER CHARACTER. (Which one the ENGINE uses for non-ASCII
    names is the probe's question -- this pins the implementation's stated contract.)"""
    names = ["straße", "strassf"]
    assert sorted(names, key=_loadorder.sort_key) == ["strassf", "straße"]
