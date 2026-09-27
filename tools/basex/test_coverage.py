"""Tests for coverage.py's denominator contract.

Run:  cd tools/basex && python -m pytest test_coverage.py -q

No BaseX and no JVM required -- `basex_query` is monkeypatched, because what is
under test is the denominator guard, not XQuery evaluation.

WHY THIS FILE EXISTS (Track 2 audit, 2026-09-06). coverage.py is the tool every
other tool asks for its denominator, and it had **no test file at all**. It
validated `--reference` / `--extensions` for NON-EMPTINESS and never for
EXISTENCE, so a path that was merely wrong -- a typo, a stale config, an
unmounted drive -- passed the check, `count_disk_xml` returned 0 for it because
`root.is_dir()` was False, and this published

    {"expected": {"total": 0}, "indexed": {"total": 0},
     "status": "complete", "supports_negative_claim": true}

which ask.py then rendered as `NEGATIVE CONFIRMED over 0 of 0 documents
(complete).` with exit 0 -- the bare zero the whole pipeline exists to refuse,
wearing the one sentence that means it was checked.

The refusal one line above the defect already said the rule out loud: *"Refusing
to guess: an empty root resolves to the CURRENT DIRECTORY, which would publish a
denominator measured over the wrong population."* A root that does not exist is
the same failure with a different spelling.
"""
from __future__ import annotations

import json

import pytest

import coverage


@pytest.fixture
def no_basex(monkeypatch):
    """Stand in for BaseX, reporting an index that holds nothing.

    This is what makes the pre-fix defect REACHABLE in a test: without it, a run
    with a bogus root reaches `basex_query`, fails to find a JVM, and returns 2 --
    the same exit code the fix produces, for an entirely different reason. A test
    that cannot tell those apart would have passed against the broken code.
    """
    monkeypatch.setattr(coverage, "basex_query",
                        lambda db, xq: "total=0\nbase=0\nmods=0\n")


def _run(tmp_path, no_basex, *, reference, extensions):
    out = tmp_path / "coverage-test.json"
    rc = coverage.main([
        "--db", "x4raw",
        "--stage", str(tmp_path / "stage"),
        "--manifest", str(tmp_path / "no-such-manifest.json"),
        "--reference", str(reference),
        "--extensions", str(extensions),
        "--out", str(out),
    ])
    return rc, out


def test_a_root_that_does_not_exist_is_REFUSED_not_counted_as_zero(tmp_path, no_basex):
    """The reported defect. A non-empty but nonexistent --reference must refuse."""
    real = tmp_path / "extensions"
    real.mkdir()
    (real / "a.xml").write_text("<a/>", encoding="utf-8")

    rc, out = _run(tmp_path, no_basex,
                   reference=tmp_path / "definitely-not-here", extensions=real)
    assert rc == 2, "a nonexistent root was measured instead of refused"
    assert not out.exists(), (
        "a coverage artifact was published over a population that was never looked at")


def test_the_same_holds_for_extensions(tmp_path, no_basex):
    """Both roots, separately: a guard that only covered one would pass the test
    above while leaving half the defect live."""
    real = tmp_path / "reference"
    real.mkdir()
    (real / "a.xml").write_text("<a/>", encoding="utf-8")

    rc, out = _run(tmp_path, no_basex,
                   reference=real, extensions=tmp_path / "definitely-not-here")
    assert rc == 2 and not out.exists()


def test_two_real_but_EMPTY_roots_do_not_license_a_negative_claim(tmp_path, no_basex):
    """The half an existence check alone does not close.

    Both roots exist, so the check above passes -- and both hold zero XML, so the
    expected total is still 0, the deficit is still 0, and the artifact would
    still say `supports_negative_claim: true` over nothing.
    """
    ref, ext = tmp_path / "reference", tmp_path / "extensions"
    ref.mkdir()
    ext.mkdir()
    rc, out = _run(tmp_path, no_basex, reference=ref, extensions=ext)
    assert rc == 2, "coverage was published over an empty population"
    assert not out.exists()


def test_a_REAL_population_still_publishes(tmp_path, no_basex, monkeypatch):
    """The falsification twin for all three above.

    A guard that refused everything would make them pass while deleting the
    feature. With two real roots holding real documents and an index that matches,
    coverage must still be published and still say it supports a negative claim.
    """
    ref, ext = tmp_path / "reference", tmp_path / "extensions"
    ref.mkdir()
    ext.mkdir()
    (ref / "a.xml").write_text("<a/>", encoding="utf-8")
    (ext / "b.xml").write_text("<b/>", encoding="utf-8")
    monkeypatch.setattr(coverage, "basex_query",
                        lambda db, xq: "total=2\nbase=1\nmods=1\n")

    rc, out = _run(tmp_path, no_basex, reference=ref, extensions=ext)
    assert rc == 0, "a complete, real population was refused"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["expected"]["total"] == 2
    assert data["supports_negative_claim"] is True


def test_an_EMPTY_root_argument_is_still_refused(tmp_path, no_basex):
    """The pre-existing F46 guard must survive this change -- it is the reason the
    existence check sits beside it rather than replacing it."""
    rc = coverage.main(["--db", "x4raw", "--reference", "", "--extensions", ""])
    assert rc == 2


# ------------------------------------------------------------------------------
# coverage_effective returns BEFORE main()'s two producing-side refusals, so the
# x4eff path could publish a negative licence over an empty index. Release
# reviewer B2, measured: enumeration succeeded while every merge failed.


def _manifest(tmp_path, documents_total):
    man = tmp_path / "eff-manifest.json"
    man.write_text(json.dumps({
        "counts": {"documents_total": documents_total},
        "enumeration": {"sources_configured": 2, "documents_enumerated": 5000,
                        "sources": {"reference": {"count": 5000, "read": "loose"}},
                        "sources_contributing_nothing": []},
        "failures": [], "merge_skips": [], "out": str(tmp_path)}), encoding="utf-8")
    return man


def test_a_zero_denominator_does_NOT_support_a_negative(tmp_path, monkeypatch):
    """0 produced, 0 indexed: the deltas reconcile, so nothing else objects. It used
    to print COVERAGE COMPLETE, write supports_negative_claim=true and exit 0 -- and
    build-effective.sh then stamped a freshness fingerprint on it."""
    monkeypatch.setattr(coverage, "basex_query", lambda *a, **k: "0")
    out = tmp_path / "coverage-x4eff.json"
    rc = coverage.coverage_effective("x4eff", _manifest(tmp_path, 0), out)
    assert rc != 0, "an empty index must not exit 0"
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["status"] == "empty"
    assert d["supports_negative_claim"] is False


def test_a_REAL_denominator_still_supports_a_negative(tmp_path, monkeypatch):
    """The twin: the refusal must be about ZERO, not about being cautious. A store
    that produced and indexed the same non-zero count is still complete."""
    monkeypatch.setattr(coverage, "basex_query", lambda *a, **k: "1234")
    out = tmp_path / "coverage-x4eff.json"
    rc = coverage.coverage_effective("x4eff", _manifest(tmp_path, 1234), out)
    assert rc == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["status"] == "complete"
    assert d["supports_negative_claim"] is True


# ------------------------------------------------------------------------------
# An UNREADABLE CATALOG is not one missing vpath (v3.3.0 release review, finding 3).
#
# `_modfiles.overlay_vpaths` records an overlay whose packed catalog cannot be read as ONE
# entry in `failures` -- "<mod>: catalog unreadable (...) -- only its LOOSE files were
# enumerated" -- and coverage_effective counted every `failures` entry as one "vpath with no
# effective tree": a LEGITIMATE absence it discloses and still licenses. MEASURED by the
# reviewer: status complete, supports_negative_claim true, and ask.py printed "NEGATIVE
# CONFIRMED over 10000 of 10000 documents ... 1 vpath(s) with no effective tree" while
# every packed member of that catalog -- a count nobody knows -- was never enumerated.
#
# That is F35's shape (a source the enumeration never reached is absent from the produced
# count, the failure list and the deficit alike), so it gets F35's verdict: unexplained.


def _real_catalog_failure(monkeypatch, tmp_path) -> str:
    """The failure string exactly as the build writes it -- produced by the real
    `_modfiles.overlay_vpaths` over a catalog reader that raises, never retyped here."""
    from x4validate import _effective, _modfiles
    monkeypatch.setattr(_effective, "base_vpaths", lambda config, pattern: {})
    def unreadable(d, packed_only=True):
        raise ValueError("bad cat")
    monkeypatch.setattr(_modfiles._cat, "mod_vfs", unreadable)
    ov = tmp_path / "somemod"
    ov.mkdir()
    failures: list[str] = []
    _modfiles.overlay_vpaths(None, [ov], failures)
    assert len(failures) == 1, failures
    return failures[0]


def _manifest_with(tmp_path, failures, **extra):
    man = tmp_path / "eff-manifest.json"
    man.write_text(json.dumps({
        "counts": {"documents_total": 1234},
        "enumeration": {"sources_configured": 2, "documents_enumerated": 5000,
                        "sources": {"reference": {"count": 5000, "read": "loose"}},
                        "sources_contributing_nothing": []},
        "failures": failures, "merge_skips": [], "out": str(tmp_path), **extra}),
        encoding="utf-8")
    return man


def test_an_UNREADABLE_CATALOG_does_not_support_a_negative(tmp_path, monkeypatch):
    fail = _real_catalog_failure(monkeypatch, tmp_path)
    monkeypatch.setattr(coverage, "basex_query", lambda *a, **k: "1234")
    out = tmp_path / "coverage-x4eff.json"
    rc = coverage.coverage_effective("x4eff", _manifest_with(tmp_path, [fail]), out)
    d = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 4 and d["status"] == "unexplained", d
    assert d["supports_negative_claim"] is False
    assert d["unreadable_catalogs"] == [fail]
    # it is not ALSO counted as a vpath without an effective tree: it is not one
    assert d["negative_claim_excludes"]["vpaths_without_effective_tree"] == 0


def test_TWIN_an_ordinary_vpath_failure_still_supports_a_negative(tmp_path, monkeypatch):
    """The refusal is about a CATALOG, not about any failure: a vpath with no effective
    tree is a legitimate absence (the engine does nothing there either) and stays licensed,
    disclosed through negative_claim_excludes as before."""
    monkeypatch.setattr(coverage, "basex_query", lambda *a, **k: "1234")
    out = tmp_path / "coverage-x4eff.json"
    rc = coverage.coverage_effective("x4eff", _manifest_with(
        tmp_path, ["md/x.xml: no effective tree (base absent and no overlay parsed)"]), out)
    d = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0 and d["status"] == "complete" and d["supports_negative_claim"] is True, d
    assert d["unreadable_catalogs"] == []
    assert d["negative_claim_excludes"]["vpaths_without_effective_tree"] == 1


def test_TWIN_a_vpath_whose_NAME_mentions_a_catalog_is_not_one(tmp_path, monkeypatch):
    """Matched on the `<mod>: catalog unreadable (` form the build writes, not on the words
    appearing anywhere in a line."""
    monkeypatch.setattr(coverage, "basex_query", lambda *a, **k: "1234")
    out = tmp_path / "coverage-x4eff.json"
    rc = coverage.coverage_effective("x4eff", _manifest_with(
        tmp_path, ["md/catalog unreadable.xml: write failed (disk full)"]), out)
    d = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0 and d["unreadable_catalogs"] == [], d
