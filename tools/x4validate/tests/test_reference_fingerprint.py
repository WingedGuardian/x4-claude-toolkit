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

import re
import time
from pathlib import Path

import pytest

from x4validate import _freshness

#: The toolkit repository root, four levels up from tests/.
REPO = Path(__file__).resolve().parents[3]


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


def test_the_load_order_axis_is_WATCHED_not_merely_documented():
    """★ RE-POINTED 2026-09-06, when the gap this used to pin was CLOSED.

    It was `test_the_load_order_gap_is_still_documented_rather_than_silent`, and it
    asserted that `_compat.py` stays OUT of ENGINE_SOURCES -- true then, and still
    true, but for a different reason. Leaving a test named "the gap is still
    documented" passing over a gap that no longer exists is the stale-guard shape this
    suite exists to catch, so it now pins the FIX instead of the hole.

    `compute_load_order` decides every collision winner (gotcha #13: the same macro
    reads 0 alphabetically and 200 in true load order), so editing it changes the
    merged answer for byte-identical inputs -- exactly what the ENGINE axis is for. It
    now lives in `_loadorder.py`, which is named in ENGINE_SOURCES and imports only
    `pathlib` and `lxml.etree`.

    `_compat.py` stays OUT, still correctly: it carries the x4compat CLI, and F69
    measured that a CLI-text or docstring edit there invalidates the store for a
    rebuild that cannot move one row.
    """
    assert "_loadorder.py" in _freshness.ENGINE_SOURCES, (
        "the module that decides load order is not watched by the engine axis, so a "
        "collision-winner change would read as FRESH")
    assert "_compat.py" not in _freshness.ENGINE_SOURCES, (
        "a CLI module in ENGINE_SOURCES makes a docstring edit invalidate the store "
        "(F69); the split exists precisely to avoid that")

    # the function is really THERE, not just the filename in a tuple
    from x4validate import _compat, _loadorder
    assert _compat.compute_load_order is _loadorder.compute_load_order, (
        "_compat re-exports the lifted function; if that stops being true, the six "
        "existing call sites and mutation_probe's source-string mutant break silently")
    src = (_freshness._PKG / "_freshness.py").read_text(encoding="utf-8")
    assert "compute_load_order" in src, (
        "the load-order axis lost its explanation at the constant; the next reader "
        "cannot tell a deliberate inclusion from an accidental one")


def test_every_engine_source_actually_exists():
    """A typo here would silently hash `<ABSENT>` forever and never move again."""
    missing = [n for n in _freshness.ENGINE_SOURCES
               if not (_freshness._PKG / n).is_file()]
    assert not missing, "ENGINE_SOURCES names files that do not exist: %s" % missing


def _tree(root):
    (root / "libraries" / "sub").mkdir(parents=True)
    (root / "assets" / "units" / "deep").mkdir(parents=True)
    (root / "libraries" / "wares.xml").write_text("x", encoding="utf-8")
    return root


def test_an_ADD_below_the_top_level_moves_the_survey(tmp_path):
    """The blindness the docstring did not name.

    It described one limit -- "an in-place edit to an existing file" -- while folding
    only the TOP level, so an ADD or DELETE at depth 3 moved nothing either. That is
    not an in-place edit, and essentially all reference content sits deeper than
    depth 2. MEASURED 2026-09-05: `libraries/sub/new.xml` appearing was invisible.
    """
    root = _tree(tmp_path / "ref")
    before = _freshness._reference_survey(root)
    (root / "libraries" / "sub" / "new.xml").write_text("n", encoding="utf-8")
    assert _freshness._reference_survey(root) != before, (
        "an added file at depth 3 must move the survey")


def test_a_DELETE_below_the_top_level_moves_the_survey(tmp_path):
    root = _tree(tmp_path / "ref")
    f = root / "libraries" / "sub" / "new.xml"
    f.write_text("n", encoding="utf-8")
    before = _freshness._reference_survey(root)
    f.unlink()
    assert _freshness._reference_survey(root) != before


def test_an_edit_to_the_MARKER_file_still_moves_the_survey(tmp_path):
    """A REGRESSION the move to a shape-print introduced and presented as a widening.

    The single-file survey watched `libraries/wares.xml`, so an in-place edit to it
    moved the OLD axis. The shape-print moved nothing for that case. One stat buys it
    back, and this pins it so the trade cannot be re-made silently.
    """
    root = _tree(tmp_path / "ref")
    before = _freshness._reference_survey(root)
    (root / "libraries" / "wares.xml").write_text("edited", encoding="utf-8")
    assert _freshness._reference_survey(root) != before


def test_the_depth_limit_is_STATED_not_implied(tmp_path):
    """The control, and the honest half. Depth 4 is still blind -- chosen, because
    folding depth 3 costs 0.441 s against 0.018 s (MEASURED on the real 510,711-file
    tree) and this runs on every query. If someone deepens it, this test should be
    updated deliberately, not discovered by a slowdown."""
    root = _tree(tmp_path / "ref")
    before = _freshness._reference_survey(root)
    (root / "assets" / "units" / "deep" / "ship.xml").write_text("s", encoding="utf-8")
    assert _freshness._reference_survey(root) == before, (
        "depth 4 is documented as blind; if this now moves, update _SURVEY_DEPTH's "
        "note and the docstring rather than leaving them describing the old shape")


def test_CLAUDE_md_lists_exactly_the_ENGINE_SOURCES_the_module_derives():
    """The freshness cell in the SHIPPED CLAUDE.md has been wrong TWICE, the same
    way, inside the sentence that says "derive that list from the module, never
    retype it".

    2026-08-29 it said 5 and omitted `_effective` / `_registry` -- and a comparison
    hand-typed from it came out clean either way, i.e. a check whose result was
    independent of its input. 2026-09-07 it said 7 and omitted `_loadorder`, which
    F69's remedy had lifted out of `_compat` during that very arc: the change that
    made the doc stale was one of ours, and it shipped.

    Prose cannot be tested, so this tests the prose against the module. That is the
    only thing that stops a third occurrence -- an instruction not to retype a list
    does not stop anyone retyping it, and both corrections were written BY someone
    who had just read that instruction.
    """
    from x4validate import _freshness
    doc = REPO / "CLAUDE.md"
    if not doc.is_file():
        pytest.skip("no CLAUDE.md beside the toolkit (not the shipped layout)")
    rows = [l for l in doc.read_text(encoding="utf-8").splitlines()
            if "_freshness.ENGINE_SOURCES" in l]
    assert len(rows) == 1, "expected exactly one freshness cell, got %d" % len(rows)
    cell = rows[0]

    derived = {n[:-3] for n in _freshness.ENGINE_SOURCES}
    # Only the parenthesised roster, not the whole cell: the prose deliberately names
    # modules it got WRONG in the past, and those must not read as current members.
    m = re.search(r"as of \d{4}-\d{2}-\d{2}:([^)]*)\)", cell)
    assert m, "the cell must carry a dated `as of <date>: <list>)` roster"
    listed = set(re.findall(r"`(_[a-z_]+)`", m.group(1)))
    assert listed == derived, (
        "CLAUDE.md's freshness roster disagrees with _freshness.ENGINE_SOURCES.\n"
        "  only in the doc   : %s\n  only in the module: %s"
        % (sorted(listed - derived), sorted(derived - listed)))

    m2 = re.search(r"\(\*\*(\d+)\*\* as of", cell)
    assert m2 and int(m2.group(1)) == len(derived), (
        "the cell's COUNT must equal the module's %d" % len(derived))


def test_the_survey_is_DETERMINISTIC_over_an_unchanged_tree(tmp_path):
    """A freshness axis that moves without the world moving reports a spurious STALE.

    MEASURED 2026-09-07: with the directory mtime folded in, two surveys taken back to
    back with NO filesystem change between them differed **1 time in 400** on a freshly
    built tree. It surfaced as `test_the_depth_limit_is_STATED_not_implied` failing 1 of
    2 COLD runs — on the leg that GATES the release, which would have reddened a release
    for a reason that has nothing to do with it.

    The directory mtime was the only value in the fold that could move without the tree
    moving, and it is redundant: a directory's mtime changes when a child is added,
    removed or renamed, all of which also change `len(kids)` or the name list, and it
    does NOT change for a child's in-place edit. Measured over 400 trees, removing it
    left add@3, del@3 and edit@1 detection at 400/400 while instability went 1 -> 0.

    30 iterations here rather than 400: enough to catch a regression that reintroduces a
    per-call unstable value (which would fire at ~7% over 30), cheap enough to run every
    time. The 400-tree measurement lives in the commit and at the fold.
    """
    root = _tree(tmp_path / "ref")
    first = _freshness._reference_survey(root)
    for i in range(30):
        assert _freshness._reference_survey(root) == first, (
            "the survey moved on iteration %d with NO filesystem change — the content "
            "axis can now report a spurious STALE" % i)


def test_removing_the_directory_mtime_did_not_cost_DETECTION(tmp_path):
    """The twin, and the reason the removal is safe rather than merely quieter. Each
    of the three change classes the survey exists to catch must still move it."""
    root = _tree(tmp_path / "ref")

    base = _freshness._reference_survey(root)
    added = root / "libraries" / "sub" / "new.xml"
    added.write_text("n", encoding="utf-8")
    assert _freshness._reference_survey(root) != base, "an ADD at depth 3 must move it"

    base = _freshness._reference_survey(root)
    added.unlink()
    assert _freshness._reference_survey(root) != base, "a DELETE at depth 3 must move it"

    import os
    base = _freshness._reference_survey(root)
    os.utime(root / "libraries" / "wares.xml", (1, 1))
    assert _freshness._reference_survey(root) != base, (
        "an in-place edit to a depth-2 FILE must still move it — file mtimes are kept")
