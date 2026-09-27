"""Tier B: a nested patch whose ACTIVE target mod loads AFTER the mod under test.

v3.3.0 release review (lane roots).

Finding 6. `extensions/<T>/<rel>` patches mod T's own file. When T is active but loads
AFTER the candidate, T is (correctly) not in the patch-time tree -- and the path fell
through to "no base game file (path mismatch? this patch can never apply)", an ERROR
that is the wrong diagnosis: the path is right, the ORDER is what is in question, and
whether the engine applies a nested patch to a later-loading mod is UNMEASURED. It is
now a WARN naming T, saying so, and advising an optional <dependency> on T (which
places T first). A truly absent file keeps the path ERROR -- one twin per clause:
T loads later but does not ship the file; T loads earlier and does not ship it.

Finding 7. The Tier B note said "(of M installed)" while M counted the ACTIVE set.

The `else` branch after the placement walk ("assumed to load LAST") is UNREACHABLE:
`place_candidate` always puts the candidate's entry in the set, and
`compute_load_order` returns every folder it is given, so the walk always meets it.
The invariant is pinned below and the dead branch is removed.

Hermetic: one tmp_path install (the game root), profile and reference.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _check, _loadorder, _merge, _registry


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


BASE = "<r><a v='1'/></r>"
PATCH = "<diff><replace sel=\"/r/a/@v\">2</replace></diff>"


@pytest.fixture
def install(tmp_path, monkeypatch):
    ext = tmp_path / "game" / "extensions"
    ref = tmp_path / "ref"
    _w(ref / "libraries" / "wares.xml", "<wares/>")
    _w(ref / "index" / "macros.xml", "<index/>")
    _w(ref / "index" / "components.xml", "<index/>")
    _w(ref / "t" / "0001-l044.xml", "<language/>")
    for folder, rel in (("aaa_base", "libraries/aaa_only.xml"),
                        ("zzz_later", "libraries/later_only.xml")):
        _w(ext / folder / "content.xml", f'<content id="{folder}" version="1" name="x"/>')
        _w(ext / folder / rel, BASE)
    pc = tmp_path / "content.xml"
    _w(pc, "<content/>")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", ext)
    monkeypatch.setattr(_registry, "PROFILE_EXTENSIONS", None)
    monkeypatch.setattr(_registry, "WORKSHOP_CONTENT", None)
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    return ext, tmp_path, _merge.Config(reference=ref, include_packed_dlc=False)


def _cand(tmp: Path, *nested: str, deps: str = "") -> Path:
    cand = tmp / "dev" / "cand"
    _w(cand / "content.xml", f'<content id="cand" version="1" name="c">{deps}</content>')
    for vpath in nested:
        _w(cand / vpath, PATCH)
    return cand


def _findings(cand: Path, cfg: _merge.Config, vpath: str):
    rep = _check.validate(cand, cfg, tier="b", sel_only=True)
    return [f for f in rep.findings if f.vpath == vpath], rep


LATER = "extensions/zzz_later/libraries/later_only.xml"
EARLIER = "extensions/aaa_base/libraries/aaa_only.xml"


def test_a_nested_patch_on_a_LATER_loading_active_mod_is_a_WARN_naming_it(install):
    _ext, tmp, cfg = install
    got, _rep = _findings(_cand(tmp, LATER), cfg, LATER)
    assert len(got) == 1, got
    f = got[0]
    assert f.severity == "warn", f
    assert "path mismatch" not in f.message, f.message
    assert "zzz_later" in f.message and "AFTER" in f.message, f.message
    assert "UNMEASURED" in f.message and "dependency" in f.message, f.message


def test_TWIN_the_same_patch_on_an_EARLIER_mod_resolves(install):
    _ext, tmp, cfg = install
    got, _rep = _findings(_cand(tmp, EARLIER), cfg, EARLIER)
    assert got == [], got


def test_TWIN_a_later_mod_that_does_NOT_ship_the_file_is_still_a_path_ERROR(install):
    _ext, tmp, cfg = install
    vpath = "extensions/zzz_later/libraries/not_there.xml"
    got, _rep = _findings(_cand(tmp, vpath), cfg, vpath)
    assert [f.severity for f in got] == ["error"], got
    assert "path mismatch" in got[0].message


def test_TWIN_an_earlier_mod_that_does_NOT_ship_the_file_is_still_a_path_ERROR(install):
    _ext, tmp, cfg = install
    vpath = "extensions/aaa_base/libraries/not_there.xml"
    got, _rep = _findings(_cand(tmp, vpath), cfg, vpath)
    assert [f.severity for f in got] == ["error"], got
    assert "path mismatch" in got[0].message


def test_TWIN_an_optional_dependency_on_the_target_resolves_it(install):
    # the advice the WARN gives, taken: T is placed first, the patch evaluates
    _ext, tmp, cfg = install
    cand = _cand(tmp, LATER, deps='<dependency id="zzz_later" optional="true"/>')
    got, _rep = _findings(cand, cfg, LATER)
    assert got == [], got


def test_TWIN_tier_A_keeps_its_own_verdict(install):
    # no runtime tree under Tier A: nothing says T loads later, so no load-order WARN
    _ext, tmp, cfg = install
    rep = _check.validate(_cand(tmp, LATER), cfg, tier="a", sel_only=True)
    assert not any("AFTER" in f.message for f in rep.findings), rep.findings


# ------------------------------------------------------------------- finding 7

def test_the_tier_b_note_counts_what_it_says(install):
    ext, tmp, cfg = install
    _w(ext / "off_mod" / "content.xml",
       '<content id="off_mod" version="1" name="x" enabled="0"/>')   # installed, inactive
    t = _check.tier_b_trees(_cand(tmp), _check.Report())
    note = next(n for n in t.notes if "load BEFORE this mod" in n)
    # 2 other ACTIVE mods (aaa_base, zzz_later); 3 installed
    assert "of 2 other active" in note, note


# ---------------------------------------------------------- the dead else-branch

@pytest.mark.parametrize("case", ["not_installed", "same_folder", "same_id",
                                  "case_different_folder", "no_manifest"])
def test_the_placed_candidate_is_ALWAYS_in_the_computed_order(install, case):
    ext, tmp, _cfg = install
    mods = _registry.mods("active")
    if case == "not_installed":
        cand = _cand(tmp)
    elif case == "same_folder":
        cand = tmp / "dev" / "zzz_later"
        _w(cand / "content.xml", '<content id="zzz_later" version="2" name="x"/>')
    elif case == "same_id":
        cand = tmp / "dev" / "renamed"
        _w(cand / "content.xml", '<content id="aaa_base" version="2" name="x"/>')
    elif case == "case_different_folder":
        cand = tmp / "dev" / "ZZZ_LATER"
        _w(cand / "content.xml", '<content id="other" version="2" name="x"/>')
    else:
        cand = tmp / "dev" / "bare"
        cand.mkdir(parents=True)
    placed = _loadorder.place_candidate(mods, cand)
    order = _loadorder.compute_load_order(placed.mods)
    assert order.count(placed.entry["folder"]) == 1, (order, placed.entry)
    by_folder = {m["folder"]: m for m in placed.mods}
    assert by_folder[placed.entry["folder"]] is placed.entry


def test_no_tier_b_note_claims_the_mod_is_assumed_to_load_LAST(install):
    _ext, tmp, _cfg = install
    t = _check.tier_b_trees(_cand(tmp), _check.Report())
    assert not any("assumed to load" in n for n in t.notes), t.notes
