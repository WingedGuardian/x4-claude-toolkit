"""`mods("active")` must load exactly what the ENGINE loads -- cases a-h.

MEASURED 2026-09-26 by the in-game load-order probe (`scripts/load-order-probe.py`,
23 throwaway mods launched to the main menu; a probe the engine loaded is
signature-checked in `debug.txt`, one it did not load never appears):

  a. manifest enabled="0" + profile enabled="true"  -> LOADED (the profile decides;
     the manifest is only the default when the profile has no entry)
  b. profile entry with NO `enabled` attribute       -> LOADED
  c. manifest enabled="0", no profile entry          -> NOT loaded
  d. REQUIRED dependency on an id nothing provides   -> NOT loaded (DLC count as providers)
  e. OPTIONAL dependency missing                     -> loaded
  f. required dependency on a mod that is installed but NOT loaded -> NOT loaded (fixpoint)
  g. dependency cycle                                -> NEITHER loads
  h. two folders with one manifest id                -> BOTH load

Every exclusion by d/f/g must be RECORDED in `dropped` with its reason, never silent.
Hermetic: every install and profile lives under tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _freshness, _loadorder, _registry


def _manifest(ext: Path, folder: str, mod_id: str | None = None, enabled: str | None = None,
              deps: list[tuple[str, bool]] | None = None) -> Path:
    d = ext / folder
    d.mkdir(parents=True, exist_ok=True)
    attrs = f'id="{mod_id or folder}" version="100" name="{folder}"'
    if enabled is not None:
        attrs += f' enabled="{enabled}"'
    body = "".join(
        f'<dependency id="{i}"{" optional=" + chr(34) + "true" + chr(34) if opt else ""}/>'
        for i, opt in (deps or []))
    (d / "content.xml").write_text(f"<content {attrs}>{body}</content>", encoding="utf-8")
    return d


@pytest.fixture
def world(tmp_path, monkeypatch):
    ext = tmp_path / "extensions"
    ext.mkdir()
    prof = tmp_path / "profile_content.xml"
    prof.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    # hermetic: the machine's reference/packed DLC must not act as providers here
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])

    def profile(entries: str) -> None:
        prof.write_text(f"<content>{entries}</content>", encoding="utf-8")

    def active(dropped: list[str] | None = None) -> set[str]:
        return {m["folder"] for m in _registry.mods("active", [ext], dropped=dropped)}

    return ext, profile, active


def test_a_the_profile_overrides_a_manifest_that_disables(world):
    ext, profile, active = world
    _manifest(ext, "m", enabled="0")
    profile('<extension id="m" enabled="true"/>')
    assert active() == {"m"}


def test_a_twin_the_profile_still_disables_a_manifest_enabled_mod(world):
    ext, profile, active = world
    _manifest(ext, "m")
    profile('<extension id="m" enabled="false"/>')
    assert active() == set()


def test_b_a_profile_entry_without_enabled_counts_as_enabled(world):
    ext, profile, active = world
    _manifest(ext, "m", enabled="0")
    profile('<extension id="m"/>')
    assert active() == {"m"}
    assert _registry.ingest_content_xml(_registry.PROFILE_CONTENT) == [("m", True)]


def test_b_the_freshness_reader_agrees(tmp_path):
    prof = tmp_path / "c.xml"
    prof.write_text('<content><extension id="m"/><extension id="n" enabled="false"/>'
                    '</content>', encoding="utf-8")
    assert _freshness._profile_decisions(prof) == {"m": True, "n": False}


def test_c_manifest_disabled_and_no_profile_entry_is_not_loaded(world):
    ext, profile, active = world
    _manifest(ext, "m", enabled="0")
    _manifest(ext, "other")
    assert active() == {"other"}


def test_d_a_missing_REQUIRED_dependency_excludes_the_mod_and_says_why(world):
    ext, profile, active = world
    _manifest(ext, "needy", deps=[("not_installed_anywhere", False)])
    _manifest(ext, "fine")
    dropped: list[str] = []
    assert active(dropped) == {"fine"}
    assert any("needy" in d and "not_installed_anywhere" in d for d in dropped), dropped


def test_d_an_installed_DLC_satisfies_a_required_dependency(world):
    ext, profile, active = world
    _manifest(ext, "ego_dlc_boron")
    _manifest(ext, "needs_dlc", deps=[("ego_dlc_boron", False)])
    dropped: list[str] = []
    assert active(dropped) == {"needs_dlc"}, dropped
    assert dropped == []


def test_d_a_version_only_dependency_is_a_game_requirement_not_a_mod(world):
    ext, profile, active = world
    d = ext / "vonly"
    d.mkdir()
    (d / "content.xml").write_text(
        '<content id="vonly" version="1"><dependency version="700"/></content>',
        encoding="utf-8")
    assert active() == {"vonly"}


def test_e_a_missing_OPTIONAL_dependency_does_not_exclude(world):
    ext, profile, active = world
    _manifest(ext, "opt", deps=[("not_installed_anywhere", True)])
    dropped: list[str] = []
    assert active(dropped) == {"opt"}
    assert dropped == []


def test_f_a_dependency_on_a_DISABLED_mod_excludes_to_a_fixpoint(world):
    ext, profile, active = world
    _manifest(ext, "base")
    _manifest(ext, "mid", deps=[("base", False)])
    _manifest(ext, "top", deps=[("mid", False)])
    _manifest(ext, "free")
    profile('<extension id="base" enabled="false"/>')
    dropped: list[str] = []
    assert active(dropped) == {"free"}
    assert any("mid" in d and "base" in d for d in dropped), dropped
    assert any(d.startswith("top") and "mid" in d for d in dropped), dropped


def test_g_a_dependency_cycle_loads_neither(world):
    ext, profile, active = world
    _manifest(ext, "cyc_a", deps=[("cyc_b", False)])
    _manifest(ext, "cyc_b", deps=[("cyc_a", False)])
    _manifest(ext, "free")
    dropped: list[str] = []
    assert active(dropped) == {"free"}
    assert sum("cycle" in d for d in dropped) == 2, dropped


def test_h_two_folders_with_one_id_BOTH_load(world):
    ext, profile, active = world
    _manifest(ext, "dup_one", mod_id="same")
    _manifest(ext, "dup_two", mod_id="same")
    _manifest(ext, "user", deps=[("same", False)])
    assert active() == {"dup_one", "dup_two", "user"}


def test_installed_scope_applies_none_of_it(world):
    ext, profile, active = world
    _manifest(ext, "needy", deps=[("nothere", False)])
    _manifest(ext, "off", enabled="0")
    assert {m["folder"] for m in _registry.mods("installed", [ext])} == {"needy", "off"}


def test_mod_dependencies_reports_optional_and_mod_deps_is_unchanged(tmp_path):
    d = _manifest(tmp_path, "m", deps=[("a", False), ("b", True)])
    assert _loadorder.mod_dependencies(d) == ("m", [("a", False), ("b", True)])
    assert _loadorder.mod_deps(d) == ("m", ["a", "b"])


def test_a_the_freshness_fingerprint_sees_the_profile_enable_a_manifest_disabled_mod(tmp_path):
    """Rule a makes "no profile entry" and "profile enabled=true" DIFFERENT worlds for a
    manifest-disabled mod (not loaded vs loaded), so the content axis must move between
    them. With the bit defaulting to True for an absent entry, both hashed identically."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    ext = tmp_path / "extensions"
    _manifest(ext, "m", enabled="0")
    prof = tmp_path / "c.xml"
    prof.write_text("<content/>", encoding="utf-8")
    before = _freshness.hash_content(ref, [ext], profile=prof)
    prof.write_text('<content><extension id="m" enabled="true"/></content>', encoding="utf-8")
    assert _freshness.hash_content(ref, [ext], profile=prof) != before


# --- the DLC provider set is the REFERENCE/GAME DLC, not what the scanned dirs hold ---
# AUDIT final review item 1: with `--ext-dir <a folder that holds no ego_dlc_*>` every
# mod requiring a DLC was silently NOT LOADED, because the only providers counted were
# DLC folders found in the SCANNED dirs.

def test_d_a_reference_DLC_satisfies_a_dependency_the_scanned_dir_lacks(tmp_path, monkeypatch):
    from x4validate import _merge
    ext = tmp_path / "not_the_game" / "extensions"
    ext.mkdir(parents=True)
    prof = tmp_path / "profile_content.xml"
    prof.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    ref = tmp_path / "reference"
    (ref / "extensions" / "ego_dlc_boron").mkdir(parents=True)
    _manifest(ext, "needs_dlc", deps=[("ego_dlc_boron", False)])
    dropped: list[str] = []
    got = _registry.mods("active", [ext], dropped=dropped,
                         dlc_config=_merge.Config(reference=ref))
    assert {m["folder"] for m in got} == {"needs_dlc"}, dropped
    assert dropped == []


def test_d_twin_a_DLC_neither_scanned_nor_in_the_reference_still_excludes(tmp_path, monkeypatch):
    from x4validate import _merge
    ext = tmp_path / "extensions"
    ext.mkdir()
    prof = tmp_path / "profile_content.xml"
    prof.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    ref = tmp_path / "reference"
    (ref / "extensions" / "ego_dlc_split").mkdir(parents=True)
    _manifest(ext, "needs_dlc", deps=[("ego_dlc_boron", False)])
    dropped: list[str] = []
    got = _registry.mods("active", [ext], dropped=dropped,
                         dlc_config=_merge.Config(reference=ref))
    assert got == []
    assert any("ego_dlc_boron" in d for d in dropped), dropped


def test_d_the_profile_can_still_disable_a_reference_DLC(tmp_path, monkeypatch):
    from x4validate import _merge
    ext = tmp_path / "extensions"
    ext.mkdir()
    prof = tmp_path / "profile_content.xml"
    prof.write_text('<content><extension id="ego_dlc_boron" enabled="false"/></content>',
                    encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    ref = tmp_path / "reference"
    (ref / "extensions" / "ego_dlc_boron").mkdir(parents=True)
    _manifest(ext, "needs_dlc", deps=[("ego_dlc_boron", False)])
    got = _registry.mods("active", [ext], dlc_config=_merge.Config(reference=ref))
    assert got == []
