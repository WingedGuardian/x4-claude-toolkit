"""`scripts/deploy-mod.py` -- the guarded deploy of a mod this toolkit SHIPS.

WHY. The obvious deploy is `rm -rf "$EXT/$m" && cp -r "$SRC/$m" "$EXT/"`: one empty shell
variable away from deleting the wrong tree inside the game installation, and it destroys
the destination BEFORE the copy. The workspace had a guarded script for this, but it lived
in a private tree with personal paths and a personal mod list, so the public repo -- which
ships the helper mod -- had no safe way to install it at all.

One test per guard, each built so that ONLY that guard can refuse it.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "deploy-mod.py"


def _mod():
    spec = importlib.util.spec_from_file_location("deploy_mod", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _manifest(mod_id: str) -> str:
    return f'<?xml version="1.0" encoding="utf-8"?>\n<content id="{mod_id}" name="x" version="1"/>\n'


def _shipped(tmp_path, name="helper", mod_id="helper_id", files=None):
    src = tmp_path / "mods" / name
    (src / "ui").mkdir(parents=True)
    (src / "content.xml").write_text(_manifest(mod_id), encoding="utf-8")
    for rel, body in (files or {"ui/a.lua": "print(1)\n"}).items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(body.encode("utf-8"))
    ext = tmp_path / "game" / "extensions"
    ext.mkdir(parents=True)
    return tmp_path / "mods", ext


def test_a_DRY_RUN_writes_nothing(tmp_path):
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    assert d.deploy("helper", apply=False, src_root=src_root, ext_root=ext, out=lambda s: None)
    assert not (ext / "helper").exists()


def test_APPLY_copies_every_file_and_re_reads_them_byte_identical(tmp_path):
    d = _mod()
    src_root, ext = _shipped(tmp_path, files={"ui/a.lua": "print(1)\n", "ui.xml": "<x/>\n"})
    assert d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)
    for rel in ("content.xml", "ui/a.lua", "ui.xml"):
        assert (ext / "helper" / rel).read_bytes() == (src_root / "helper" / rel).read_bytes()


def test_a_copy_that_does_not_READ_BACK_identical_is_a_failure_not_a_success(tmp_path, monkeypatch):
    """'N copied' is the writer's intention; the re-read is the file's state."""
    d = _mod()
    src_root, ext = _shipped(tmp_path, files={"ui/a.lua": "print(1)\n" * 50})

    def short_copy(a, b):
        pathlib.Path(b).write_bytes(pathlib.Path(a).read_bytes()[:10])

    monkeypatch.setattr(d.shutil, "copy2", short_copy)
    assert d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None) is False


def test_REFUSES_a_mod_this_repo_does_not_ship(tmp_path):
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    with pytest.raises(d.Refused, match="does not ship"):
        d.deploy("someone_elses_mod", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)


def test_REFUSES_a_destination_carrying_a_DIFFERENT_manifest_id(tmp_path):
    """Folder name is not identity: the manifest id is the real 'same mod' test."""
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    (ext / "helper").mkdir()
    (ext / "helper" / "content.xml").write_text(_manifest("another_mod"), encoding="utf-8")
    with pytest.raises(d.Refused, match="manifest id"):
        d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)
    assert (ext / "helper" / "content.xml").read_text(encoding="utf-8") == _manifest("another_mod")


def test_REFUSES_a_destination_folder_with_NO_manifest(tmp_path):
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    (ext / "helper").mkdir()
    (ext / "helper" / "keep.txt").write_text("not ours", encoding="utf-8")
    with pytest.raises(d.Refused, match="no content.xml"):
        d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)
    assert (ext / "helper" / "keep.txt").is_file()


def test_REFUSES_an_extensions_root_inside_the_PROFILE(tmp_path, monkeypatch):
    """Dependencies resolve only within ONE extensions root, so a profile deploy makes
    every dependency read as MISSING."""
    d = _mod()
    src_root, _ = _shipped(tmp_path)
    profile = tmp_path / "Documents" / "Egosoft" / "X4" / "123"
    prof_ext = profile / "extensions"
    prof_ext.mkdir(parents=True)
    monkeypatch.setattr(d._paths, "profile", lambda: profile)
    with pytest.raises(d.Refused, match="profile"):
        d.deploy("helper", apply=True, src_root=src_root, ext_root=prof_ext, out=lambda s: None)


def test_an_ORPHAN_is_deleted_one_named_FILE_at_a_time(tmp_path):
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    assert d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)
    (ext / "helper" / "ui" / "stale.lua").write_text("old\n", encoding="utf-8")
    assert d.deploy("helper", apply=True, src_root=src_root, ext_root=ext, out=lambda s: None)
    assert not (ext / "helper" / "ui" / "stale.lua").exists()
    assert (ext / "helper" / "ui" / "a.lua").is_file()


def test_the_output_NAMES_the_source_tree_it_deployed_from(tmp_path):
    """Two checkouts once forked with nothing saying which one a tool was standing in."""
    d = _mod()
    src_root, ext = _shipped(tmp_path)
    lines = []
    d.deploy("helper", apply=False, src_root=src_root, ext_root=ext, out=lines.append)
    assert any(str(src_root / "helper") in s for s in lines), lines


def test_main_is_rc_2_when_no_game_extensions_folder_is_configured(monkeypatch, capsys):
    d = _mod()
    monkeypatch.setattr(d._paths, "game_extensions", lambda: None)
    assert d.main(["x4_toolkit_helper"]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_main_lists_what_it_can_deploy_when_given_nothing(capsys):
    d = _mod()
    assert d.main([]) == 2
    assert "x4_toolkit_helper" in capsys.readouterr().out
