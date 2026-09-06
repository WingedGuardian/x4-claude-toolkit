"""The BUILD stamp must cover every shipped game-side lua, not just the primary one.

`mod_lua()` locates the primary file by globbing `*live_query.lua`. `mod_lua_files()`
exists because that glob is not the shipped SET: `engine_probe.lua` has the same
extension, runs automatically at load, and writes profile UI userdata -- and a change
to it shipped undetected because nothing stamped or checked it.

The mutation gate found that the fix reverts GREEN: with `mod_lua_files()` narrowed
back to the primary glob, no test noticed, and CI now gates on `--check`. So the
property is pinned here directly.

Pinned as "every lua carrying a BUILD line", derived from disk, rather than as a list
of two filenames -- a hard-coded pair would be a third copy of the same list, drifting
independently of the two it guards, which is the failure this file exists to prevent.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "tools" / "x4validate" / "scripts" / "stamp-mod-build.py"
MODS = ROOT / "mods"


def _stamp():
    if not SRC.is_file():
        pytest.skip(f"no {SRC.name} (dev-only script) -- NOT CHECKED")
    spec = importlib.util.spec_from_file_location("stamp_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shipped_lua_with_a_build_line() -> list[pathlib.Path]:
    """The denominator, from the repo rather than from the module under test.

    Asking the module for its own answer and then comparing it to itself is the
    shape of a check that cannot fail.
    """
    if not MODS.is_dir():
        return []
    out = []
    # THE WHOLE SHIPPED TREE, not the stamper's own glob. This used
    # `*/ui/*.lua` -- byte-identical to `mod_lua_files()` -- so the "independent"
    # denominator could only ever contain files the stamper already covered,
    # which is the shape this function's own docstring calls a check that cannot
    # fail. A lua ONE DIRECTORY DEEPER (`*/ui/lib/nested.lua`) carrying a stale
    # BUILD line was unstamped, absent from this expectation, and only PRINTED
    # by the stamper's announcement -- so `--check` exited 0 and both tests
    # passed over it.
    #
    # MEASURED 2026-09-06: 2 shipped .lua, 0 outside the narrow glob -- so
    # widening is free today and would not have been once a nested file existed.
    for p in sorted(q for q in MODS.glob("*/**/*.lua") if q.is_file()):
        if "local BUILD" in p.read_text(encoding="utf-8", errors="replace"):
            out.append(p)
    return out


def test_every_shipped_lua_carrying_a_BUILD_line_is_stamped():
    expected = _shipped_lua_with_a_build_line()
    if not expected:
        pytest.skip("no shipped mods/*/ui/*.lua in this checkout -- NOT CHECKED")
    got = {p.name for p in _stamp().mod_lua_files()}
    missing = {p.name for p in expected} - got
    assert not missing, (
        f"stamped {sorted(got)} but the repo ships {sorted(p.name for p in expected)}; "
        f"unstamped: {sorted(missing)}. A change to an unstamped file ships undetected "
        "-- that is the defect this exists for.")


def test_it_finds_MORE_than_the_primary_file():
    """The specific regression: `mod_lua()` globs `*live_query.lua`, and narrowing
    `mod_lua_files()` back to that glob is what reverted green."""
    expected = _shipped_lua_with_a_build_line()
    if len(expected) < 2:
        pytest.skip("this checkout ships fewer than two stamped lua files -- "
                    "the regression cannot be expressed here")
    got = _stamp().mod_lua_files()
    assert len(got) >= 2, (
        f"mod_lua_files() returned {len(got)} file(s) but the repo ships "
        f"{len(expected)}; it is back to the primary glob")
    assert any("live_query" not in p.name for p in got), (
        "every file returned is a live_query match -- mod_lua_files() has collapsed "
        "into mod_lua()")


def test_a_lua_ONE_DIRECTORY_DEEPER_is_in_the_expectation(tmp_path, monkeypatch):
    """The twin for the widened denominator, on a synthetic tree.

    The stamper covers `*/ui/*.lua`. A file at `*/ui/lib/*.lua` carrying a BUILD line
    is unstamped and unchecked; the stamper only PRINTS it as NOT COVERED and still
    exits 0. Before the widening this expectation used the stamper's own glob, so the
    nested file was absent from both sides and the disagreement could not be seen.

    Asserted as the SET DIFFERENCE, so it states the direction: the expectation must
    be a strict superset of the stamped glob whenever a nested file exists.
    """
    import test_stamp_covers_every_shipped_lua as m
    mods = tmp_path / "mods"
    (mods / "probe" / "ui" / "lib").mkdir(parents=True)
    (mods / "probe" / "ui" / "top.lua").write_text(
        'local BUILD = "aaaaaaaa"\n', encoding="utf-8")
    (mods / "probe" / "ui" / "lib" / "nested.lua").write_text(
        'local BUILD = "bbbbbbbb"\n', encoding="utf-8")
    monkeypatch.setattr(m, "MODS", mods)

    expected = {p.name for p in m._shipped_lua_with_a_build_line()}
    narrow = {p.name for p in mods.glob("*/ui/*.lua")}
    assert "nested.lua" in expected, (
        "a shipped lua one directory deeper is invisible to the expectation, so the "
        "stamper and its denominator agree by construction: %s" % sorted(expected))
    assert "nested.lua" not in narrow, (
        "precondition: the stamper's own glob must NOT see it, or this proves nothing")
    assert narrow < expected, (narrow, expected)


def test_the_expectation_does_not_invent_files_without_a_BUILD_line(tmp_path, monkeypatch):
    """The other twin. Widening the glob must not start demanding a stamp on every
    lua in the tree -- only those that actually carry a BUILD line, which is the
    stamper's own contract ("a shipped lua with no BUILD line is outside this gate
    entirely")."""
    import test_stamp_covers_every_shipped_lua as m
    mods = tmp_path / "mods"
    (mods / "probe" / "ui" / "lib").mkdir(parents=True)
    (mods / "probe" / "ui" / "top.lua").write_text(
        'local BUILD = "aaaaaaaa"\n', encoding="utf-8")
    (mods / "probe" / "ui" / "lib" / "helper.lua").write_text(
        "-- no build line here\nreturn {}\n", encoding="utf-8")
    monkeypatch.setattr(m, "MODS", mods)
    assert {p.name for p in m._shipped_lua_with_a_build_line()} == {"top.lua"}
