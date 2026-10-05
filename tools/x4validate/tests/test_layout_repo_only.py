"""`_layout.require_repo` -- the one door for a test that needs repo-only content (R2-B1).

Each clause of "skip iff installed layout AND content absent" has its own twin, so neither
clause can be dropped without a test going red (CLAUDE.md #26)."""
from __future__ import annotations

import pytest

import _layout


def _installed(tmp_path):
    (tmp_path / "tools").mkdir()                 # an install: no agent/
    return tmp_path


def _checkout(tmp_path):
    (tmp_path / "agent").mkdir()
    return tmp_path


def test_installed_layout_and_ABSENT_content_SKIPS_with_a_counted_named_reason(tmp_path):
    root = _installed(tmp_path)
    with pytest.raises(pytest.skip.Exception) as e:
        _layout.require_repo("agent/rules/codex-rules.yaml", why="the rule rows", root=root)
    msg = str(e.value)
    assert _layout.REASON in msg and "agent/rules/codex-rules.yaml" in msg and "rule rows" in msg


def test_TWIN_a_CHECKOUT_missing_the_same_file_does_NOT_skip(tmp_path):
    """A checkout that lost a source file is broken, not installed: the test must run (and fail)."""
    _layout.require_repo("agent/rules/codex-rules.yaml", root=_checkout(tmp_path))


def test_TWIN_an_installed_layout_WITH_the_content_does_NOT_skip(tmp_path):
    root = _installed(tmp_path)
    (root / "docs").mkdir()
    _layout.require_repo("docs", root=root)


def test_installed_layout_is_keyed_on_the_agent_source_dir(tmp_path):
    assert _layout.installed_layout(_installed(tmp_path)) is True
    assert _layout.installed_layout(_checkout(tmp_path)) is False


# --- configured is not present (R2-B1) ---------------------------------------------------

def _paths_pointing_at(monkeypatch, reg, ext, ref):
    from x4validate import _paths
    monkeypatch.setattr(_paths, "registry", lambda: reg)
    monkeypatch.setattr(_paths, "game_extensions", lambda: ext)
    monkeypatch.setattr(_paths, "reference", lambda: ref)


def test_a_CONFIGURED_root_that_does_not_exist_is_unresolvable(tmp_path, monkeypatch):
    """A fresh install configures every root before the user unpacks or runs anything; a gate
    then exits 2 on a missing folder, which import_gate re-raised as an ERROR (MEASURED: 12 in
    an installed toolkit). It is the no-X4-yet case, so it SKIPS like the unconfigured one."""
    import conftest
    (tmp_path / "ext").mkdir()
    (tmp_path / "ref").mkdir()
    (tmp_path / "reg.json").write_text("{}", encoding="utf-8")
    _paths_pointing_at(monkeypatch, tmp_path / "reg.json", tmp_path / "ext", tmp_path / "nope")
    assert conftest._environment_is_unresolvable() is True
    _paths_pointing_at(monkeypatch, tmp_path / "nope.json", tmp_path / "ext", tmp_path / "ref")
    assert conftest._environment_is_unresolvable() is True
    _paths_pointing_at(monkeypatch, tmp_path / "reg.json", tmp_path / "nope", tmp_path / "ref")
    assert conftest._environment_is_unresolvable() is True


def test_TWIN_every_configured_root_present_is_resolvable(tmp_path, monkeypatch):
    import conftest
    (tmp_path / "ext").mkdir()
    (tmp_path / "ref").mkdir()
    (tmp_path / "reg.json").write_text("{}", encoding="utf-8")
    _paths_pointing_at(monkeypatch, tmp_path / "reg.json", tmp_path / "ext", tmp_path / "ref")
    assert conftest._environment_is_unresolvable() is False


def test_reference_unpacked_needs_the_wares_library_not_just_a_folder(tmp_path, monkeypatch):
    from x4validate import _paths
    monkeypatch.setattr(_paths, "reference", lambda: tmp_path)
    assert _layout.reference_unpacked() is False                 # configured, empty
    (tmp_path / "libraries").mkdir()
    (tmp_path / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    assert _layout.reference_unpacked() is True                  # twin
    monkeypatch.setattr(_paths, "reference", lambda: None)
    assert _layout.reference_unpacked() is False                 # unconfigured
