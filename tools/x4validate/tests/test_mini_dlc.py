"""B2 — DLC that exist only PACKED in the live install belong to the Tier A tree.

`reference/` holds only the DLC that were actually unpacked. The two mini-DLC
(`ego_dlc_mini_01` Hyperion Pack, `ego_dlc_mini_02` Envoy Pack) never were, so
every patch targeting their content reported "installed but never unpacked —
cannot verify". No unpack is needed: `_cat` reads their archives directly.

The trap, and why this file exists: making `dlc_dirs()` see them is NOT enough.
`extensions/<dlc>/<rel>` then resolves as a plain path under `reference/`, finds
nothing, and the honest INFO becomes a false `no base game file` ERROR — measured
across 4 installed mods before the owner-resolution half was added. Two halves,
or it is worse than before.

Hermeticity: these tests set an explicit reference and rely on
`include_packed_dlc` being scoped to the configured workspace reference, so they
never reach into the real game install.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from x4validate import _merge


def _write_cat(mod_dir, cat_name, members):
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cat.with_suffix(".dat").write_bytes(bytes(blob))


def _world(tmp_path, monkeypatch):
    """A reference with one UNPACKED dlc + a game root with one PACKED dlc."""
    ref = tmp_path / "reference"
    (ref / "extensions" / "ego_dlc_big" / "libraries").mkdir(parents=True)
    (ref / "extensions" / "ego_dlc_big" / "libraries" / "god.xml").write_text(
        "<diff/>", encoding="utf-8")
    game = tmp_path / "game"
    _write_cat(game / "extensions" / "ego_dlc_mini_01", "ext_01.cat", [
        ("libraries/god.xml", b"<diff><add sel='/god'/></diff>"),
        ("assets/units/size_l/ship_par_l.xml",
         b"<components><component name='ship_par_l'/></components>"),
    ])
    monkeypatch.setattr(_merge, "GAME_ROOT", game)
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    return _merge.Config(reference=ref)


def test_packed_only_dlc_joins_dlc_dirs(tmp_path, monkeypatch):
    cfg = _world(tmp_path, monkeypatch)
    names = [p.name for p in cfg.dlc_dirs()]
    assert names == ["ego_dlc_big", "ego_dlc_mini_01"]
    assert cfg.packed_dlc_names() == {"ego_dlc_mini_01"}


def test_an_unpacked_copy_always_wins(tmp_path, monkeypatch):
    """No double-counting: a DLC present in BOTH is taken from reference only."""
    cfg = _world(tmp_path, monkeypatch)
    _write_cat(tmp_path / "game" / "extensions" / "ego_dlc_big", "ext_01.cat",
               [("libraries/god.xml", b"<diff/>")])
    dirs = cfg.dlc_dirs()
    assert [p.name for p in dirs] == ["ego_dlc_big", "ego_dlc_mini_01"]
    assert dirs[0].parent.parent == cfg.reference


def test_opt_out_restores_reference_only(tmp_path, monkeypatch):
    cfg = _world(tmp_path, monkeypatch)
    assert [p.name for p in replace(cfg, include_packed_dlc=False).dlc_dirs()] == ["ego_dlc_big"]


def test_a_foreign_reference_is_not_supplemented(tmp_path, monkeypatch):
    """Only the CONFIGURED workspace reference is assumed to mirror this install."""
    cfg = _world(tmp_path, monkeypatch)
    other = tmp_path / "elsewhere"
    (other / "extensions" / "ego_dlc_big").mkdir(parents=True)
    assert [p.name for p in replace(cfg, reference=other).dlc_dirs()] == ["ego_dlc_big"]


def test_content_inside_a_packed_dlc_resolves_as_a_real_base(tmp_path, monkeypatch):
    """The half that stops B2 from manufacturing false errors."""
    cfg = _world(tmp_path, monkeypatch)
    res = _merge.build_effective(
        "extensions/ego_dlc_mini_01/assets/units/size_l/ship_par_l.xml", cfg)
    assert res.base_found and res.tree.tag == "components"
    assert res.sources == ["ego_dlc_mini_01:owner"]


def test_a_packed_dlc_diff_is_a_base_exactly_as_an_unpacked_one_is(tmp_path, monkeypatch):
    """Every DLC ships libraries/god.xml as a <diff>; both must behave alike.

    Asserts BOTH sides — if only the packed case were pinned, a change that broke
    the unpacked path would still pass.
    """
    cfg = _world(tmp_path, monkeypatch)
    packed = _merge.build_effective("extensions/ego_dlc_mini_01/libraries/god.xml", cfg)
    unpacked = _merge.build_effective("extensions/ego_dlc_big/libraries/god.xml", cfg)
    assert packed.base_found and unpacked.base_found
    assert packed.tree.tag == unpacked.tree.tag == "diff"


def test_a_genuinely_absent_path_is_still_not_found(tmp_path, monkeypatch):
    cfg = _world(tmp_path, monkeypatch)
    res = _merge.build_effective("extensions/ego_dlc_mini_01/libraries/nope.xml", cfg)
    assert not res.base_found


@pytest.mark.parametrize("ext, root, other", [
    pytest.param(r"D:\Games\X4\extensions", r"D:\Games\X4", r"E:\elsewhere",
                 id="windows-drive-path",
                 marks=pytest.mark.skipif(
                     os.name != "nt",
                     reason="a backslash drive path is ONE filename on POSIX, so "
                            "the parent of it is '.', not a game root")),
    pytest.param("/games/x4/extensions", "/games/x4", "/elsewhere",
                 id="posix-path"),
])
def test_game_root_follows_the_documented_extensions_env_var(
        monkeypatch, ext, root, other):
    """$X4_GAME_EXTENSIONS is the knob the toolkit documents and users set.

    A second independent $X4_GAME_ROOT would leave anyone who configured the
    documented one with packed-DLC support pointed at the wrong place — and it
    fails back to "cannot verify", so it reads as "does not apply to me".

    Parametrised over both path shapes because the DERIVATION being tested
    (root = parent of extensions) is platform-independent, while the literal is
    not: a Windows drive path is a single filename on a POSIX system, so the
    original test failed on Linux for a reason that said nothing about the code.
    """
    monkeypatch.delenv("X4_GAME_ROOT", raising=False)
    monkeypatch.setenv("X4_GAME_EXTENSIONS", ext)
    assert _merge._default_game_root() == Path(root)

    monkeypatch.setenv("X4_GAME_ROOT", other)
    assert _merge._default_game_root() == Path(other), \
        "an explicit X4_GAME_ROOT must still win"
