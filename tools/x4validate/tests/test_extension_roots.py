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
    # The roots are CONFIGURED as the game and profile roots: which rule applies is
    # decided by the root's KIND (`_registry.scan_installed` compares the scanned folder
    # to the configured roots), never by its position in the list.
    game, prof = tmp_path / "game" / "extensions", tmp_path / "profile" / "extensions"
    ws = tmp_path / "workshop" / "content" / "392160"
    for d in (game, prof, ws):
        d.mkdir(parents=True)
    pc = tmp_path / "profile_content.xml"
    pc.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", game)
    monkeypatch.setattr(_registry, "PROFILE_EXTENSIONS", prof)
    monkeypatch.setattr(_registry, "WORKSHOP_CONTENT", ws)
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


# ------------------------------------------------------------------------------------
# v3.3.0 release review (lane roots). The F141 isolation was applied to EVERY root by
# position, the Steam Workshop root included -- and nothing about the Workshop root was
# measured. Only game <-> profile is measured; everything else keeps the v3.2.0 model
# (dependencies resolve) and is DISCLOSED as unmeasured.
# ------------------------------------------------------------------------------------

def _ws(game: Path) -> Path:
    return game.parents[1] / "workshop" / "content" / "392160"


def _ws_manifest(ws: Path, num: str, deps: list[tuple[str, bool]] | None = None) -> Path:
    d = ws / num
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'<dependency id="{i}"{" optional=" + chr(34) + "true" + chr(34) if opt else ""}/>'
        for i, opt in (deps or []))
    (d / "content.xml").write_text(
        f'<content id="ws_{num}" version="100" name="w{num}">{body}</content>',
        encoding="utf-8")
    return d


def _id_manifest(ext: Path, folder: str, mod_id: str) -> None:
    d = ext / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.xml").write_text(
        f'<content id="{mod_id}" version="1" name="{folder}"/>', encoding="utf-8")


def test_scan_records_each_roots_KIND(roots):
    game, prof = roots
    ws = _ws(game)
    _manifest(game, "g_mod")
    _manifest(prof, "p_mod")
    _ws_manifest(ws, "111")
    got = {m["folder"]: m["root_kind"] for m in _registry.scan_installed([game, prof, ws])}
    assert got == {"g_mod": "game", "p_mod": "profile", "111": "workshop"}


@pytest.mark.parametrize("dependent", ["game", "profile"])
def test_a_required_dependency_on_a_WORKSHOP_mod_resolves(roots, dependent):
    # e.g. a Nexus mod requiring a Workshop-installed API. Unmeasured, so the v3.2.0
    # model stands: it LOADS. Before this fix: "NOT LOADED by the engine", as fact.
    game, prof = roots
    ws = _ws(game)
    _ws_manifest(ws, "111")
    _manifest(game if dependent == "game" else prof, "needs_ws", [("ws_111", False)])
    got = _registry.mods("active", [game, prof, ws])
    assert {m["folder"] for m in got} == {"111", "needs_ws"}, got.dropped
    assert not got.dropped


@pytest.mark.parametrize("provider", ["game", "profile"])
def test_a_WORKSHOP_mod_requiring_a_game_or_profile_mod_resolves(roots, provider):
    game, prof = roots
    ws = _ws(game)
    _manifest(game if provider == "game" else prof, "prov")
    _ws_manifest(ws, "111", [("prov", False)])
    got = _registry.mods("active", [game, prof, ws])
    assert {m["folder"] for m in got} == {"111", "prov"}, got.dropped


def test_an_optional_edge_to_a_WORKSHOP_mod_still_orders(roots):
    # a game-root patch with an OPTIONAL dependency on a Workshop mod: the edge was
    # silently dropped, so the patch was modelled as loading BEFORE what it patches
    game, prof = roots
    ws = _ws(game)
    _ws_manifest(ws, "111")
    _manifest(game, "b_patch", [("ws_111", True)])
    order = _loadorder.compute_load_order(_registry.mods("active", [game, prof, ws]))
    assert order.index("111") < order.index("b_patch"), order


def test_a_WORKSHOP_mod_present_is_disclosed_as_UNMEASURED(roots):
    game, prof = roots
    ws = _ws(game)
    _manifest(game, "g_mod")
    _ws_manifest(ws, "111")
    got = _registry.mods("active", [game, prof, ws])
    assert any("Workshop" in n and "UNMEASURED" in n for n in got.notes), got.notes
    note = _registry.dropped_note(got)
    assert note and "Workshop" in note and "UNMEASURED" in note, note
    assert _registry.left_out(got) == {}, "a disclosure is not an exclusion"


def test_TWIN_no_workshop_mod_no_workshop_disclosure(roots):
    game, prof = roots
    ws = _ws(game)                               # configured and scanned, but empty
    _manifest(game, "g_mod")
    got = _registry.mods("active", [game, prof, ws])
    assert got.notes == [] and _registry.dropped_note(got) is None


def test_the_rule_follows_the_KIND_not_the_position(roots, monkeypatch):
    # profile root unconfigured: the Workshop root is now SECOND in the default list,
    # where the profile root usually sits. Position-keyed isolation refused this.
    game, _prof = roots
    ws = _ws(game)
    monkeypatch.setattr(_registry, "PROFILE_EXTENSIONS", None)
    _ws_manifest(ws, "111")
    _manifest(game, "needs_ws", [("ws_111", False)])
    got = _registry.mods("active")
    assert {m["folder"] for m in got} == {"111", "needs_ws"}, got.dropped


def test_UNCONFIGURED_roots_keep_the_v320_model_and_say_so(tmp_path, monkeypatch):
    # two folders that are NOT the configured roots (a custom `dirs` list): their kind
    # is unknown, so nothing is isolated -- and, with mods in more than one of them,
    # the modelled cross-root behaviour is disclosed as unmeasured
    a, b = tmp_path / "a" / "extensions", tmp_path / "b" / "extensions"
    pc = tmp_path / "pc.xml"
    pc.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    for name in ("GAME_EXTENSIONS", "PROFILE_EXTENSIONS", "WORKSHOP_CONTENT"):
        monkeypatch.setattr(_registry, name, None)
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    _manifest(a, "prov")
    _manifest(b, "needy", [("prov", False)])
    got = _registry.mods("active", [a, b])
    assert {m["folder"] for m in got} == {"prov", "needy"}
    assert any("UNMEASURED" in n for n in got.notes), got.notes


def test_TWIN_one_unconfigured_root_alone_says_nothing(tmp_path, monkeypatch):
    a = tmp_path / "a" / "extensions"
    pc = tmp_path / "pc.xml"
    pc.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    _manifest(a, "prov")
    _manifest(a, "needy", [("prov", False)])
    got = _registry.mods("active", [a])
    assert {m["folder"] for m in got} == {"prov", "needy"} and got.notes == []


# --- dependency ids that differ only in CASE (engine behaviour UNMEASURED) ------------

def test_a_case_only_dependency_mismatch_is_SATISFIED_and_noted(roots):
    game, prof = roots
    _manifest(game, "provider")
    _manifest(game, "aaa_needy", [("Provider", False)])
    got = _registry.mods("active", [game, prof])
    assert {m["folder"] for m in got} == {"provider", "aaa_needy"}, got.dropped
    assert any("'Provider'" in n and "'provider'" in n and "UNMEASURED" in n
               for n in got.notes), got.notes
    # ...and it is a load-order edge: aaa_needy sorts first but waits for provider
    assert _loadorder.compute_load_order(got) == ["provider", "aaa_needy"]


def test_a_case_only_mismatch_orders_in_the_INSTALLED_scope_too(roots):
    game, prof = roots
    _manifest(game, "provider")
    _manifest(game, "aaa_needy", [("Provider", True)])
    dropped: list[str] = []
    order = _loadorder.compute_load_order(_registry.mods("installed", [game, prof]), dropped)
    assert order == ["provider", "aaa_needy"]
    assert any("UNMEASURED" in d and "'Provider'" in d for d in dropped), dropped


def test_TWIN_an_exact_case_match_carries_no_note(roots):
    game, prof = roots
    _manifest(game, "provider")
    _manifest(game, "aaa_needy", [("provider", False)])
    got = _registry.mods("active", [game, prof])
    assert {m["folder"] for m in got} == {"provider", "aaa_needy"} and got.notes == []


def test_TWIN_a_truly_missing_id_is_still_NOT_LOADED(roots):
    game, prof = roots
    _manifest(game, "provider")
    _manifest(game, "aaa_needy", [("Providerx", False)])
    got = _registry.mods("active", [game, prof])
    assert {m["folder"] for m in got} == {"provider"}
    assert "aaa_needy" in _registry.left_out(got)


def test_a_case_only_match_across_game_and_profile_is_still_refused(roots):
    # the case rule relaxes the SPELLING, never the measured cross-root refusal
    game, prof = roots
    _manifest(prof, "provider")
    _manifest(game, "aaa_needy", [("Provider", False)])
    got = _registry.mods("active", [game, prof])
    assert {m["folder"] for m in got} == {"provider"}
    assert "DIFFERENT extensions root" in _registry.left_out(got)["aaa_needy"]


# --- load-order records ride on the mod list they were computed from (finding 3) ----

def test_load_order_records_ride_on_the_ModList(roots):
    game, prof = roots
    _id_manifest(game, "b_one", "shared")
    _id_manifest(game, "d_two", "shared")
    got = _registry.mods("active", [game, prof])
    assert _registry.dropped_note(got) is None
    _loadorder.compute_load_order(got)
    _loadorder.compute_load_order(got)                  # twice: recorded ONCE
    clash = [n for n in got.notes if "claimed by both" in n]
    assert len(clash) == 1, got.notes
    assert "claimed by both" in (_registry.dropped_note(got) or "")
    assert _registry.left_out(got) == {}, "a load-order record is not an exclusion"


def test_a_placed_candidate_keeps_the_channel(roots, tmp_path):
    game, prof = roots
    _manifest(game, "p_mod")
    got = _registry.mods("active", [game, prof])
    placed = _loadorder.place_candidate(got, _manifest(tmp_path / "dev", "cand"))
    assert placed.mods.notes is got.notes and placed.mods.dropped is got.dropped


def test_TWIN_a_plain_list_still_works(roots):
    game, prof = roots
    _manifest(game, "p_mod")
    plain = list(_registry.mods("active", [game, prof]))
    assert _loadorder.compute_load_order(plain) == ["p_mod"]
