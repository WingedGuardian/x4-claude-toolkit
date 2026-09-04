r"""The content axis must represent the reference tree, not one file inside it.

`hash_content` folded in `(mtime, size)` of a SINGLE file -- `libraries/wares.xml` --
standing in for 510,711 files and 27 GB. Anything that changed a DLC macro, a script or
an index while leaving that one file alone moved nothing, so the effective store could
be reported fresh by BOTH axes while describing a world that had changed. That is worse
than a stale artifact: it is a stale artifact that reports success.

The limit is measured, not assumed. Costs on the real tree:

    stat every file   17.6 s      the only way to see an in-place content edit
    name-only walk     0.80 s     sees add / remove / rename, not edits
    this survey        0.001 s    sees top-level shape and the recorded build id

An in-place edit moves NO ancestor directory's mtime at any depth, so nothing cheap can
see it. That is tolerable only because `reference/` is policy-locked read-only behind
`.unpacked-and-locked`; the change that actually happens is a game patch plus a
re-unpack, which the build id catches exactly.
"""

from __future__ import annotations

import time

import pytest

from x4validate import _freshness


@pytest.fixture()
def ref(tmp_path):
    r = tmp_path / "reference"
    for sub in ("libraries", "assets/props", "index"):
        (r / sub).mkdir(parents=True)
    (r / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    (r / "assets" / "props" / "turret.xml").write_text("<macros/>", encoding="utf-8")
    (r / "index" / "macros.xml").write_text("<index/>", encoding="utf-8")
    return r


def test_the_survey_is_stable_when_nothing_changes(ref):
    """A fingerprint that drifts on its own makes everything permanently stale, which
    is a worse failure than one that is too still."""
    first = _freshness._reference_survey(ref)
    for _ in range(4):
        assert _freshness._reference_survey(ref) == first


def test_adding_or_removing_a_file_moves_it(ref):
    before = _freshness._reference_survey(ref)
    time.sleep(1.1)                       # mtime granularity is one second
    (ref / "index" / "newthing.xml").write_text("<x/>", encoding="utf-8")
    added = _freshness._reference_survey(ref)
    assert added != before, "an added file did not move the fingerprint"
    time.sleep(1.1)
    (ref / "index" / "newthing.xml").unlink()
    assert _freshness._reference_survey(ref) != added, "a removal did not move it"


def test_a_new_top_level_directory_moves_it(ref):
    """A DLC arriving or leaving is exactly this shape."""
    before = _freshness._reference_survey(ref)
    (ref / "extensions").mkdir()
    assert _freshness._reference_survey(ref) != before


def test_the_recorded_build_id_is_part_of_it(ref):
    """The realistic staleness: the game updated under a tree unpacked from an older
    build. `bin/unpack-reference.sh` records the build; a re-unpack changes it."""
    cfg = ref.parent / ".claude"
    cfg.mkdir()
    none = _freshness._reference_survey(ref)
    (cfg / ".reference-buildid").write_text("23524486", encoding="utf-8")
    old = _freshness._reference_survey(ref)
    (cfg / ".reference-buildid").write_text("23660954", encoding="utf-8")
    new = _freshness._reference_survey(ref)
    assert none != old != new and none != new, (
        "the recorded build id does not reach the fingerprint")


def test_an_absent_reference_is_named_not_silently_equal(tmp_path):
    """Two different missing trees must not hash the same as a real one."""
    got = _freshness._reference_survey(tmp_path / "nope")
    assert got == "ref:<ABSENT>"


def test_the_load_order_gap_is_still_documented_rather_than_silent():
    """`_compat.compute_load_order` decides every collision winner, so the engine axis
    cannot see a load-order change. Adding `_compat.py` to ENGINE_SOURCES was tried and
    WITHDRAWN: it carries the x4compat CLI, and F69 measured that a CLI-text or even a
    docstring edit in an engine source invalidates the store for a rebuild that cannot
    change one row. The remedy is to lift the function into a CLI-free module.

    This pins that the gap stays NAMED. If someone adds `_compat.py` without doing the
    split, test_engine_sources_carry_no_cli.py goes red and points here."""
    assert "_compat.py" not in _freshness.ENGINE_SOURCES
    src = (_freshness._PKG / "_freshness.py").read_text(encoding="utf-8")
    assert "compute_load_order" in src, (
        "the known load-order gap lost its explanation; a silent hole is worse than a "
        "documented one")


def test_every_engine_source_actually_exists():
    """A typo here would silently hash `<ABSENT>` forever and never move again."""
    missing = [n for n in _freshness.ENGINE_SOURCES
               if not (_freshness._PKG / n).is_file()]
    assert not missing, "ENGINE_SOURCES names files that do not exist: %s" % missing
