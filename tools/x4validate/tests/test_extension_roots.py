"""Two extensions roots (game-root `extensions\\` and the profile's), as the ENGINE treats them.

MEASURED 2026-09-26, load-order probe rounds 2 and 3 (`scripts/load-order-probe.py`):

  * the engine READS the profile's `extensions\\` -- its Extensions dialog lists those mods;
  * a profile-root mod's patches are APPLIED, and AFTER every game-root mod's: proof lines
    (a replace that can never match) logged in the order game a, game c, profile b, profile d,
    and the chain's one miss was the game-root mod reading a profile-root attribute;
  * a REQUIRED dependency does NOT resolve across roots, in either direction (both probes red
    in the dialog, neither in the log).

UNMEASURED, and disclosed rather than guessed: every round-3 probe loaded in the first pass,
so where a game-root mod that WAITS a pass for a dependency falls relative to profile-root
mods is not known. The model walks game root then profile root, in repeated passes.

BLIND-SPOTS F141. Hermetic: every install and profile lives under tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _loadorder, _registry


def _manifest(ext: Path, folder: str, deps: list[tuple[str, bool]] | None = None) -> Path:
    d = ext / folder
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'<dependency id="{i}"{" optional=" + chr(34) + "true" + chr(34) if opt else ""}/>'
        for i, opt in (deps or []))
    (d / "content.xml").write_text(
        f'<content id="{folder}" version="100" name="{folder}">{body}</content>',
        encoding="utf-8")
    return d


@pytest.fixture
def roots(tmp_path, monkeypatch):
    game, prof = tmp_path / "game" / "extensions", tmp_path / "profile" / "extensions"
    game.mkdir(parents=True)
    prof.mkdir(parents=True)
    pc = tmp_path / "profile_content.xml"
    pc.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    return game, prof


def test_scan_records_which_root_each_mod_came_from(roots):
    game, prof = roots
    _manifest(game, "g_mod")
    _manifest(prof, "p_mod")
    got = {m["folder"]: m["root_rank"] for m in _registry.scan_installed([game, prof])}
    assert got == {"g_mod": 0, "p_mod": 1}


def test_every_profile_root_mod_loads_after_every_game_root_mod(roots):
    # names interleave on purpose: one walk BY NAME would give a, b, c, d
    game, prof = roots
    for f in ("x_a", "x_c"):
        _manifest(game, f)
    for f in ("x_b", "x_d"):
        _manifest(prof, f)
    mods = _registry.mods("active", [game, prof])
    assert _loadorder.compute_load_order(mods) == ["x_a", "x_c", "x_b", "x_d"]


@pytest.mark.parametrize("dep_root", ["game", "profile"])
def test_a_required_dependency_does_not_cross_roots(roots, dep_root):
    game, prof = roots
    provider_root, dependent_root = (game, prof) if dep_root == "game" else (prof, game)
    _manifest(provider_root, "provider")
    _manifest(dependent_root, "needy", [("provider", False)])
    dropped: list[str] = []
    active = {m["folder"] for m in _registry.mods("active", [game, prof], dropped=dropped)}
    assert active == {"provider"}, "the engine refuses a cross-root required dependency"
    assert any("needy" in d for d in dropped), dropped


def test_TWIN_a_required_dependency_in_the_SAME_root_still_resolves(roots):
    game, prof = roots
    _manifest(prof, "provider")
    _manifest(prof, "needy", [("provider", False)])
    active = {m["folder"] for m in _registry.mods("active", [game, prof])}
    assert active == {"provider", "needy"}


def test_an_optional_cross_root_dependency_neither_blocks_nor_reorders(roots):
    game, prof = roots
    _manifest(prof, "p_first")
    _manifest(game, "z_game", [("p_first", True)])     # optional, other root
    mods = _registry.mods("active", [game, prof])
    assert {m["folder"] for m in mods} == {"p_first", "z_game"}
    assert _loadorder.compute_load_order(mods) == ["z_game", "p_first"]


def test_a_candidate_keeps_its_installed_copys_root(roots, tmp_path):
    game, prof = roots
    _manifest(prof, "p_mod")
    cand = _manifest(tmp_path / "dev", "p_mod")
    placed = _loadorder.place_candidate(_registry.mods("active", [game, prof]), cand)
    assert placed.entry["root_rank"] == 1


def test_a_new_candidate_is_modelled_in_the_GAME_root(roots, tmp_path):
    game, prof = roots
    _manifest(prof, "p_mod")
    cand = _manifest(tmp_path / "dev", "a_new")          # sorts first by name
    placed = _loadorder.place_candidate(_registry.mods("active", [game, prof]), cand)
    assert placed.entry["root_rank"] == 0
    assert _loadorder.compute_load_order(placed.mods) == ["a_new", "p_mod"]


def test_the_unmeasured_cross_root_pass_shape_is_disclosed(roots):
    # a game-root mod that waits a pass, WITH profile-root mods present: where it falls
    # relative to them was never measured, so the order says so
    game, prof = roots
    _manifest(game, "a_needs_z", [("z_dep", False)])
    _manifest(game, "z_dep")
    _manifest(prof, "p_mod")
    dropped: list[str] = []
    _loadorder.compute_load_order(_registry.mods("active", [game, prof]), dropped)
    assert any("UNMEASURED" in d and "root" in d for d in dropped), dropped


def test_TWIN_one_root_discloses_nothing_about_roots(roots):
    game, _prof = roots
    _manifest(game, "a_needs_z", [("z_dep", False)])
    _manifest(game, "z_dep")
    dropped: list[str] = []
    _loadorder.compute_load_order(_registry.mods("active", [game]), dropped)
    assert not any("root" in d for d in dropped), dropped
