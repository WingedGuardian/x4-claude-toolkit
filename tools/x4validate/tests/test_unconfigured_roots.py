"""An UNCONFIGURED extensions root is not a root.

The v3.3.0 cold-clone verification (no X4 installed, every root None) caught
`x4xref who-calls` raising TypeError: `index_roots(None)` returned `[None]`, and the
freshness stamp then called `Path(None)`. Every CLI that stamps freshness was one
unconfigured root away from the same crash. These run on ANY machine: the roots are
forced to None here rather than relying on the machine being cold.
"""
from __future__ import annotations

from pathlib import Path

from x4validate import _freshness, _registry, _xref


def test_index_roots_never_contains_None(monkeypatch):
    monkeypatch.setattr(_registry, "default_installed_dirs", lambda: [])
    assert _xref.index_roots(None) == []


def test_TWIN_index_roots_keeps_a_configured_root(monkeypatch, tmp_path):
    monkeypatch.setattr(_registry, "default_installed_dirs", lambda: [])
    assert _xref.index_roots(tmp_path) == [tmp_path]


def test_as_dirs_skips_an_unconfigured_entry(tmp_path):
    assert _freshness._as_dirs([None, tmp_path, None]) == [tmp_path]


def test_TWIN_as_dirs_still_takes_one_root_or_none(tmp_path):
    assert _freshness._as_dirs(tmp_path) == [Path(tmp_path)]
    assert _freshness._as_dirs(None) == []


def test_who_calls_with_no_install_does_not_crash(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", None)
    monkeypatch.setattr(_registry, "default_installed_dirs", lambda: [])
    tsv = tmp_path / "idx.tsv"
    tsv.write_text("kind\tname\tfile\tline\tcontext\n", encoding="utf-8")
    rc = _xref.main(["who-calls", "some_cue", "--tsv", str(tsv)])
    assert rc in (0, 1, 2, 3), rc                      # an answer or a refusal, never a crash
