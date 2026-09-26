"""Mutation-campaign gaps in `_modfiles.overlay_vpaths` (campaign 2, 2026-09-26).

Each test names the surviving mutant it was written to kill and was verified to FAIL
with it applied and PASS without it. Only the two DEPENDENCIES are stubbed -- the base
set (`_effective.base_vpaths`) and the packed catalog reader (`_cat.mod_vfs`); the
enumeration logic under test runs for real over real loose files.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _effective, _modfiles

BASE = {"libraries/wares.xml": "libraries/wares.xml",
        "libraries/ships.xml": "libraries/ships.xml",
        "md/Setup.xml": "md/Setup.xml"}


def _w(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("<diff/>", encoding="utf-8")


@pytest.fixture
def env(monkeypatch, tmp_path):
    base = {k.lower(): v for k, v in BASE.items()}
    monkeypatch.setattr(_effective, "base_vpaths", lambda config, pattern: dict(base))
    packed: dict[str, object] = {}

    def mod_vfs(d, packed_only=True):
        v = packed.get(Path(d).name, [])
        if isinstance(v, Exception):
            raise v
        return list(v)
    monkeypatch.setattr(_modfiles._cat, "mod_vfs", mod_vfs)
    return tmp_path, packed


def test_unreadable_catalog_is_recorded_and_loose_files_still_count(env):
    """MF4: a catalog that cannot be read narrows the enumeration -- it must be
    RECORDED in *failures*, while the overlay's loose files still count."""
    tmp, packed = env
    ov = tmp / "ov_a"
    _w(ov / "libraries/wares.xml")
    packed["ov_a"] = OSError("bad cat")
    failures: list[str] = []
    contested, _untouched, _base = _modfiles.overlay_vpaths(None, [ov], failures)
    assert "libraries/wares.xml" in contested
    assert len(failures) == 1 and failures[0].startswith("ov_a: catalog unreadable")


def test_contested_takes_the_BASE_trees_casing(env):
    """MF5: an overlay shipping 'Libraries/Wares.xml' contests the base's
    'libraries/wares.xml' -- one spelling on both sides, the base's."""
    tmp, _packed = env
    ov = tmp / "ov_a"
    _w(ov / "Libraries/Wares.xml")
    contested, untouched, _ = _modfiles.overlay_vpaths(None, [ov], [])
    assert "libraries/wares.xml" in contested
    assert "Libraries/Wares.xml" not in contested
    assert "libraries/wares.xml" not in untouched


def test_untouched_excludes_every_contested_base_file(env):
    """MF6: untouched = base MINUS contested, not the whole base."""
    tmp, _packed = env
    ov = tmp / "ov_a"
    _w(ov / "libraries/wares.xml")
    _contested, untouched, _ = _modfiles.overlay_vpaths(None, [ov], [])
    assert untouched == {"libraries/ships.xml", "md/Setup.xml"}


def test_packed_overlay_xml_is_contested_and_non_xml_is_not(env):
    """MF7 (packed members dropped) and MF8 (the .xml filter): a packed-only overlay's
    XML members are contested; its textures are not documents."""
    tmp, packed = env
    ov = tmp / "ov_packed"
    ov.mkdir()
    packed["ov_packed"] = ["libraries/ships.xml", "assets/tex/foo.dds", "md/New.XML"]
    contested, untouched, _ = _modfiles.overlay_vpaths(None, [ov], [])
    assert contested == {"libraries/ships.xml", "md/New.XML"}
    assert "libraries/ships.xml" not in untouched
