"""The stamper and the test suite must locate the SAME game-side mod lua.

Nothing pinned them, and the drift was real and silent: `scripts/stamp-mod-build.py`
searched only `dev/`, which does not exist in the public repo. There `mod_lua()`
returned None, `--check` printed "nothing to stamp" and exited **0**, and the staleness
gate passed by never running -- while the mod's BUILD line said `e1af07d7` and its
content hashed to `539c405e`.

A deployed-but-not-loaded mod is the precise failure the stamper exists to catch, and it
was blind to it in the only tree that ships. This test is cheap; that hole was not.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _stamp():
    spec = importlib.util.spec_from_file_location("stamp", SCRIPTS / "stamp-mod-build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _suite_lookup():
    """The test suite's own finder, imported without needing lupa."""
    root = pathlib.Path(__file__).resolve().parents[3]
    searched = []
    for name in ("mods", "dev"):
        d = root / name
        if not d.is_dir():
            continue
        searched.append(d)
        hits = sorted(d.glob("*/ui/*live_query.lua"))
        if hits:
            return hits[0], searched
    return None, searched


def test_the_stamper_and_the_suite_find_the_same_file():
    stamp = _stamp()
    mine, roots = _suite_lookup()
    if not roots:
        pytest.skip("no mods/ or dev/ root in this tree")
    # A root exists, so BOTH must find something. "Both returned None" is the state this
    # test exists to reject -- it is what a silent skip looked like from the outside.
    assert mine is not None, "the suite lookup found nothing under %s" % roots
    assert stamp.mod_lua() == mine, (
        "the stamper and the suite disagree on which lua ships:\n"
        "  stamper: %s\n  suite  : %s" % (stamp.mod_lua(), mine))


def test_the_stamper_searches_mods_before_dev():
    """Order matters: the public tree has mods/, the private one has both."""
    assert _stamp()._ROOTS_ORDER == ("mods", "dev")


def test_check_refuses_rather_than_returning_zero_when_a_root_is_empty(tmp_path, monkeypatch):
    """`--check` returning 0 on "nothing found" is a green over a check that never ran."""
    stamp = _stamp()
    monkeypatch.setattr(stamp, "roots", lambda: [tmp_path])   # exists, holds no mod
    monkeypatch.setattr(stamp, "mod_lua", lambda: None)
    assert stamp.main(["--check"]) == 2

    monkeypatch.setattr(stamp, "roots", lambda: [])           # nowhere to look at all
    assert stamp.main(["--check"]) == 0
