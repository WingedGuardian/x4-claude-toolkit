"""x4validate/_surface.py -- the CLI/subcommand surface, asked of the programs.

WHY THIS MODULE IS SEPARATE FROM THE GATE THAT NEEDS IT. The enumeration lived in
`gates/toolkit_usage.py` while that gate lived in a separate dev repository, so a
gate here could not import it. Moving it verbatim would carry `_env.skip()` -- which
`raise SystemExit(2)`s -- into the shipped package. Gotcha #26 records what that
costs: every `gates/` module resolved paths at import, and a SystemExit during
pytest collection is an INTERNALERROR that aborts the whole session on a fresh
clone, while being invisible on a configured machine.

So the contract is: the LIBRARY raises a domain exception, the GATE decides the
exit code. These tests pin that split, because it is the only thing that
distinguishes this module from a copy-paste.
"""

from __future__ import annotations

import pytest

from x4validate import _surface


def test_a_missing_pyproject_raises_SurfaceUnavailable_and_never_SystemExit(tmp_path):
    """The whole reason this is not a verbatim move.

    A SystemExit here is fatal during collection on a fresh clone and silent on a
    configured one -- so it must be a catchable domain error instead.
    """
    with pytest.raises(_surface.SurfaceUnavailable):
        _surface.cli_roster(root=tmp_path)


def test_SurfaceUnavailable_is_not_a_SystemExit_subclass():
    """Belt and braces: a subclass would satisfy the test above while still
    aborting pytest collection."""
    assert not issubclass(_surface.SurfaceUnavailable, SystemExit)
    assert issubclass(_surface.SurfaceUnavailable, Exception)


def test_cli_roster_reads_the_console_scripts_from_pyproject(tmp_path):
    pj = tmp_path / "pyproject.toml"
    pj.write_text(
        '[project]\nname = "x"\n[project.scripts]\nbeta = "m:main"\nalpha = "m:main"\n',
        encoding="utf-8")
    assert _surface.cli_roster(root=tmp_path) == ["alpha", "beta"]


def test_an_empty_scripts_table_is_a_refusal_not_an_empty_answer(tmp_path):
    """A roster of zero would make every coverage check vacuously true."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.scripts]\n', encoding="utf-8")
    with pytest.raises(_surface.SurfaceUnavailable):
        _surface.cli_roster(root=tmp_path)


def test_a_subprocess_failure_is_a_refusal_not_a_single_command_cli(monkeypatch):
    """_run() folds an OSError into `out`; without a rc check that text has no
    {...} block and reads as 'single-command CLI'. A CLI with 10 subcommands
    would then count as fully routed with zero. Found by review."""
    import subprocess
    def boom(*a, **k):
        raise FileNotFoundError("uv not found")
    monkeypatch.setattr(subprocess, "run", boom)
    subs, note = _surface.subcommands("x4live")
    assert subs is None, (subs, note)
    assert "could not be run" in note


def test_the_real_roster_is_this_package(tmp_path):
    """Against the real tree, not a fixture -- the fixture cannot catch a wrong ROOT."""
    names = _surface.cli_roster()
    assert "x4validate" in names and "x4live" in names
    assert len(names) >= 10, names


def test_a_MALFORMED_pyproject_is_a_refusal_not_a_traceback(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project.scripts\nbroken = ", encoding="utf-8")
    with pytest.raises(_surface.SurfaceUnavailable):
        _surface.cli_roster(tmp_path)
