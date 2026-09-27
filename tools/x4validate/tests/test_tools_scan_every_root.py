"""x4compat, x4stats and x4similar model "the set the engine loads" -- EVERY root of it.

v3.3.0 release review (lane roots), finding 5. All three scanned `[ext_dir]` only, and
`ext_dir` defaulted to the GAME root, so a profile-root mod (which the engine loads,
MEASURED 2026-09-26, F141) was silently absent while their help said "the set the
engine loads". REPRODUCED first on the reviewer's two-root fixture: `x4compat check
--json` reported mods_scanned 1, load_order ["moda"], 0 collisions, rc 0 -- while the
profile-root "modb" patches the same attribute.

The rule now: no --ext-dir = every configured root (as Tier B and x4effective do, via
`_registry`'s defaults); --ext-dir = that folder ONLY, and the output says so.

Hermetic: every root, the profile and the reference live under tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from x4validate import _compat, _effective, _merge, _registry


def _mod(ext: Path, folder: str, wares: str | None = None) -> Path:
    d = ext / folder
    (d / "libraries").mkdir(parents=True, exist_ok=True)
    (d / "content.xml").write_text(
        f'<content id="{folder}" version="1" name="{folder}"/>', encoding="utf-8")
    if wares is not None:
        (d / "libraries" / "wares.xml").write_text(wares, encoding="utf-8")
    return d


def _add_ware(wid: str) -> str:
    return (f'<diff><add sel="/wares"><ware id="{wid}" group="x" transport="container" '
            f'volume="1"><price min="1" average="2" max="3"/></ware></add></diff>')


SAME_ATTR = "<diff><replace sel=\"/wares/ware[@id='ore']/@volume\">4</replace></diff>"


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    game = tmp_path / "game" / "extensions"
    prof = tmp_path / "profile" / "extensions"
    game.mkdir(parents=True)
    prof.mkdir(parents=True)
    ref = tmp_path / "ref"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text(
        '<wares><ware id="ore" volume="10"><price min="1" average="2" max="3"/></ware>'
        '</wares>', encoding="utf-8")
    pc = tmp_path / "profile" / "content.xml"
    pc.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", pc)
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", game)
    monkeypatch.setattr(_registry, "PROFILE_EXTENSIONS", prof)
    monkeypatch.setattr(_registry, "WORKSHOP_CONTENT", None)
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    return game, prof, ref, _merge.Config(reference=ref, include_packed_dlc=False)


# ------------------------------------------------------------------------ x4compat

def test_x4compat_default_scans_the_profile_root_too(two_roots, capsys):
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda", SAME_ATTR)
    _mod(prof, "modb", SAME_ATTR)
    _compat.main(["check", "--json", "--reference", str(ref)])
    got = json.loads(capsys.readouterr().out)
    assert got["mods_scanned"] == 2 and got["load_order"] == ["moda", "modb"], got
    assert got["files_examined"] == 1, "the two mods share a file"


def test_x4compat_ext_dir_scans_ONLY_it_and_says_so(two_roots, capsys):
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda", SAME_ATTR)
    _mod(prof, "modb", SAME_ATTR)
    _compat.main(["check", "--ext-dir", str(game), "--reference", str(ref)])
    text = capsys.readouterr().out
    assert "x4compat: 1 mods" in text
    assert "ONLY" in text and str(game) in text, text


def test_TWIN_x4compat_default_does_not_claim_an_ext_dir_limit(two_roots, capsys):
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda", SAME_ATTR)
    _compat.main(["check", "--reference", str(ref)])
    assert "ONLY" not in capsys.readouterr().out


def test_x4compat_a_bare_candidate_name_resolves_in_the_profile_root(two_roots, capsys):
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda", SAME_ATTR)
    _mod(prof, "modb", SAME_ATTR)
    _compat.main(["check", "modb", "--json", "--reference", str(ref)])
    got = json.loads(capsys.readouterr().out)
    assert got["candidate_path"].endswith("modb"), got
    assert Path(got["candidate_path"]).parent == prof


def test_x4compat_renders_a_registry_level_note(two_roots, tmp_path, monkeypatch):
    # a note `mods()` makes (a Workshop-root mod present) is not one of the order's
    # records, so it must reach the report by the ModList channel
    game, prof, _ref, cfg = two_roots
    ws = tmp_path / "workshop"
    ws.mkdir()
    monkeypatch.setattr(_registry, "WORKSHOP_CONTENT", ws)
    _mod(game, "moda", SAME_ATTR)
    _mod(ws, "111", SAME_ATTR)
    text = _compat.render(_compat.analyze(None, config=cfg))
    assert "Workshop" in text and "UNMEASURED" in text, text


# ------------------------------------------------------------------------- x4stats

def test_x4stats_default_pool_includes_the_profile_root(two_roots):
    from x4validate import _stats
    game, prof, _ref, cfg = two_roots
    _mod(game, "moda", _add_ware("ware_a"))
    _mod(prof, "modb", _add_ware("ware_b"))
    pool, _tree = _stats.effective_wares(None, cfg)
    assert {"ware_a", "ware_b"} <= set(pool), sorted(pool)


def test_x4stats_ext_dir_scans_ONLY_it_and_says_so(two_roots, tmp_path, capsys):
    from x4validate import _stats
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda", _add_ware("ware_a"))
    _mod(prof, "modb", _add_ware("ware_b"))
    cand = _mod(tmp_path / "dev", "cand", _add_ware("ware_c"))
    _stats.main(["wares", str(cand), "--ext-dir", str(game), "--reference", str(ref)])
    got = capsys.readouterr()
    assert "ONLY" in got.err and str(game) in got.err, got.err


def test_TWIN_x4stats_default_does_not_claim_an_ext_dir_limit(two_roots, tmp_path, capsys):
    from x4validate import _stats
    game, _prof, ref, _cfg = two_roots
    _mod(game, "moda", _add_ware("ware_a"))
    cand = _mod(tmp_path / "dev", "cand", _add_ware("ware_c"))
    _stats.main(["wares", str(cand), "--reference", str(ref)])
    assert "ONLY" not in capsys.readouterr().err


# ----------------------------------------------------------------------- x4similar

def _spy_scans(monkeypatch) -> list:
    seen: list = []
    real = _registry.mods

    def spy(scope, dirs=None, *a, **k):
        seen.append((scope, dirs))
        return real(scope, dirs, *a, **k)

    monkeypatch.setattr(_registry, "mods", spy)
    return seen


def test_x4similar_default_reads_every_configured_root(two_roots, monkeypatch, capsys):
    from x4validate import _similarity
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda")
    _mod(prof, "modb")
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: [])
    seen = _spy_scans(monkeypatch)
    _similarity.main(["--reference", str(ref)])
    assert seen and all(dirs is None for _scope, dirs in seen), seen
    assert {s for s, _d in seen} == {"active", "installed"}
    assert "ONLY" not in capsys.readouterr().err


def test_x4similar_ext_dir_reads_ONLY_it_and_says_so(two_roots, monkeypatch, capsys):
    from x4validate import _similarity
    game, prof, ref, _cfg = two_roots
    _mod(game, "moda")
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: [])
    seen = _spy_scans(monkeypatch)
    _similarity.main(["--reference", str(ref), "--ext-dir", str(game)])
    assert seen and all(dirs == [game] for _scope, dirs in seen), seen
    err = capsys.readouterr().err
    assert "ONLY" in err and str(game) in err, err
