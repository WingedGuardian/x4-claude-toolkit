"""A mod `mods("active")` leaves out must be DISCLOSED by every caller that renders.

AUDIT-2026-09-24 final review item 2: `_active_filter` records each exclusion (a
REQUIRED dependency missing, disabled or cyclic) only when the caller passes
`dropped=`, and none of the 14 active-scope callers did -- so a mod leaving the
world model said nothing. The engine is right to skip it; the tool staying silent
about it is the defect. Each surfaced caller is driven here with one excluded mod
("needy", requiring an id nothing provides) and must NAME it with its reason.

Hermetic: tmp_path install, profile and reference only.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from x4validate import _check, _compat, _effective, _merge, _registry

BASEX = Path(__file__).resolve().parents[2] / "basex"


def _mod(parent: Path, folder: str, deps: tuple[str, ...] = ()) -> Path:
    d = parent / folder
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(f'<dependency id="{i}"/>' for i in deps)
    (d / "content.xml").write_text(
        f'<content id="{folder}" version="100" name="{folder}">{body}</content>',
        encoding="utf-8")
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    ext = tmp_path / "game" / "extensions"
    ext.mkdir(parents=True)
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(b"<wares/>")
    prof = tmp_path / "profile_content.xml"
    prof.write_text("<content/>", encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    monkeypatch.setattr(_registry, "default_installed_dirs", lambda: [ext])
    monkeypatch.setattr(_registry, "_reference_dlc_dirs", lambda config=None: [])
    _mod(ext, "AAA")
    _mod(ext, "needy", deps=("nothing_provides_this",))
    return ext, tmp_path, _merge.Config(reference=ref)


def _names_needy(text: str) -> bool:
    return "needy" in text and "nothing_provides_this" in text


def test_tier_b_discloses_the_excluded_mod_as_NOT_CHECKED(env):
    ext, tmp, _cfg = env
    cand = _mod(tmp / "dev", "cand")
    rep = _check.Report()
    tb = _check.tier_b_trees(cand, rep)
    assert "needy" not in [p.name for p in tb.final]
    hits = [s for s in rep.skipped if _names_needy(f"{s.what} {s.why}")]
    assert hits, rep.skipped
    assert not any(s.degraded for s in hits), "the engine's own exclusion is not a degraded run"
    assert any(_names_needy(n) for n in tb.notes), tb.notes


def test_tier_b_twin_says_nothing_when_nothing_is_excluded(env):
    ext, tmp, _cfg = env
    (ext / "needy" / "content.xml").write_text(
        '<content id="needy" version="100" name="needy"/>', encoding="utf-8")
    rep = _check.Report()
    _check.tier_b_trees(_mod(tmp / "dev", "cand"), rep)
    assert not [s for s in rep.skipped if "NOT LOADED" in s.why + s.what], rep.skipped


def test_x4compat_discloses_the_excluded_mod(env):
    ext, _tmp, cfg = env
    rep = _compat.analyze(ext, config=cfg)
    assert "needy" not in rep.load_order
    assert any(_names_needy(f"{s.what} {s.why}") for s in rep.skipped), rep.skipped
    assert _names_needy(_compat.render(rep))


def test_x4effective_build_discloses_the_excluded_mod(env):
    ext, tmp, cfg = env
    said: list[str] = []
    _effective.build(cfg, tmp / "eff.sqlite", dirs=[ext], kinds=("ware",),
                     progress=said.append)
    assert any(_names_needy(s) for s in said), said


def test_basex_build_effective_discloses_the_excluded_mod(env, capsys):
    ext, _tmp, cfg = env
    spec = importlib.util.spec_from_file_location("basex_build_effective_excl",
                                                  BASEX / "build-effective.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    overlays = mod.installed_in_load_order(cfg)
    assert [p.name for p in overlays] == ["AAA"]
    assert _names_needy(capsys.readouterr().err)
