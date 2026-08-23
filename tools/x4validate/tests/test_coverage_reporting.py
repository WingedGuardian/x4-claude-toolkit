"""B: a coverage statement must name the SCANNED SOURCE SET, not just failed reads.

`x4xref` already refused to render a bare zero-result -- it appended the files it
could not parse, modelled on `tools/basex/ask.py`. F10 slipped through that anyway,
because the mini-DLC were never *attempted*: they were not unreadable, they were
unenumerated, and a blind spot is by definition not in the failed-reads category.

"a real negative over 148,343 indexed rows" was true and useless. "...from base +
6 DLC + 71 mods" against a game with 8 DLC would have been self-evident on sight.
"""

from pathlib import Path

from x4validate import _xref


def _rows(*sources):
    return [_xref.XrefRow("cuedef", f"Cue{i}", s, "md/x.xml", "", 1)
            for i, s in enumerate(sources)]


def test_coverage_names_the_scanned_source_set():
    text = _xref.coverage_note(_rows("base", "dlc:ego_dlc_boron", "modA", "modB"))
    assert "base" in text
    assert "1 DLC" in text
    assert "2 mod" in text


def test_coverage_flags_a_dlc_shortfall(monkeypatch, tmp_path):
    """The decisive one: the index holds fewer DLC than the game actually has."""
    from x4validate import _merge
    eight = [tmp_path / f"ego_dlc_{n}" for n in
             ("boron", "pirate", "split", "terran", "timelines", "ventures",
              "mini_01", "mini_02")]
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: eight, raising=False)

    text = _xref.coverage_note(_rows("base", "dlc:ego_dlc_boron", "modA"))

    assert "INCOMPLETE" in text, "an index missing 7 of 8 DLC must say so, loudly"
    assert "1 of 8" in text


def test_coverage_is_quiet_when_every_dlc_is_present(monkeypatch, tmp_path):
    from x4validate import _merge
    two = [tmp_path / "ego_dlc_boron", tmp_path / "ego_dlc_mini_01"]
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: two, raising=False)
    text = _xref.coverage_note(_rows("base", "dlc:ego_dlc_boron", "dlc:ego_dlc_mini_01", "m"))
    assert "INCOMPLETE" not in text
    assert "2 DLC" in text


# --- F35: the same rule, for BaseX x4eff -------------------------------------
#
# `tools/basex/coverage.py` reconciled "documents produced" against "documents
# indexed" -- BOTH derived from the same build. A vpath the enumeration never
# reached is absent from the produced count, absent from the failure list, and
# absent from the deficit alike, so it reported COMPLETE over a population that
# had already lost 119 of 142 mini-DLC documents (F34). `ask.py` then gated every
# negative claim on that one boolean.
#
# Exactly the failure this module's docstring describes, one layer down: a blind
# spot is by definition not in the failed-reads category.

import importlib.util

import pytest
import io
import json
import contextlib

_COV_PATH = Path(__file__).resolve().parent.parent.parent / "basex" / "coverage.py"


def _coverage_module():
    """Load `tools/basex/coverage.py`, or SKIP.

    BaseX is deliberately dev-only and is NOT part of the public bundle (it needs
    a JVM and a multi-GB corpus). Without this guard these four tests FAIL on a
    fresh public clone -- MEASURED on the 2.4.0 port: 4 failed, 584 passed -- and
    a failing suite is the first thing a new user sees.

    A skip, not a silent pass: pytest reports it distinctly, so "not checked here"
    can never read as "checked and fine".
    """
    if not _COV_PATH.is_file():
        pytest.skip(f"no BaseX tooling at {_COV_PATH} (dev-only, not in the public bundle)")
    spec = importlib.util.spec_from_file_location("basex_coverage", _COV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, manifest, indexed):
    """coverage_effective over a synthetic manifest; returns (rc, coverage json)."""
    cov = _coverage_module()
    cov.basex_query = lambda db, xq: str(indexed)          # no BaseX, no JVM
    man = tmp_path / "effective-manifest.json"
    man.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "coverage-x4eff.json"
    with contextlib.redirect_stdout(io.StringIO()):
        rc = cov.coverage_effective("x4eff", man, out)
    return rc, json.loads(out.read_text(encoding="utf-8"))


def _manifest(sources, total=10, empty=()):
    return {
        "counts": {"documents_total": total},
        "failures": [], "merge_skips": [],
        "enumeration": {
            "sources_configured": len(sources),
            "documents_enumerated": total,
            "sources": {n: {"count": c, "read": "loose"} for n, c in sources.items()},
            "sources_contributing_nothing": list(empty),
        },
    }


def test_a_fully_scanned_build_still_supports_a_negative(tmp_path):
    """The control. Without it, a check that rejected everything would look
    identical to a check that works."""
    rc, cov = _run(tmp_path, _manifest({"reference": 8, "ego_dlc_x": 2}), indexed=10)
    assert rc == 0
    assert cov["status"] == "complete"
    assert cov["supports_negative_claim"] is True


def test_a_source_that_contributed_NOTHING_kills_the_negative(tmp_path):
    """THE GATE. produced == indexed here, so the old deficit arithmetic says
    'complete' -- and it is still not a population you may claim a negative over."""
    man = _manifest({"reference": 10, "ego_dlc_mini_01": 0}, empty=["ego_dlc_mini_01"])
    rc, cov = _run(tmp_path, man, indexed=10)
    assert rc == 4
    assert cov["status"] == "unexplained"
    assert cov["supports_negative_claim"] is False


def test_a_manifest_with_no_enumeration_record_is_UNKNOWN_not_fine(tmp_path):
    """An artifact that cannot say what it scanned is a NON-ANSWER, never an
    absence -- the same rule as an absent freshness fingerprint."""
    man = _manifest({"reference": 10})
    del man["enumeration"]
    rc, cov = _run(tmp_path, man, indexed=10)
    assert rc == 4
    assert cov["supports_negative_claim"] is False


def test_the_exclusions_are_machine_readable_not_only_printed(tmp_path):
    """The caveat existed all along -- in prose, on stdout, where `ask.py` could
    never read it. A negative over x4eff is a claim about the tree MINUS these."""
    man = _manifest({"reference": 10})
    man["failures"] = ["a.xml: no effective tree", "b.xml: no effective tree"]
    man["merge_skips"] = ["c.xml: unparseable"]
    _rc, cov = _run(tmp_path, man, indexed=10)
    assert cov["negative_claim_excludes"] == {
        "vpaths_without_effective_tree": 2, "unparseable_overlays": 1}
    assert cov["enumeration"]["sources_configured"] == 1
