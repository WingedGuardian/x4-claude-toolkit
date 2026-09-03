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
    for p in sorted(MODS.glob("*/ui/*.lua")):
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
