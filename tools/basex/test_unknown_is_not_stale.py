"""Three UNKNOWNs that wore STALE's banner, and one unguarded json.loads.

`Verdict.determinable` exists, its docstring is explicit -- "a banner that says
STALE when it means UNKNOWN sends the reader to rebuild an index that may have been
perfectly current" -- and the UNKNOWN banner was written. `check()` simply never set
the field, so its ONLY producer was ask.py's own except-clause around the call.

Absence, non-answer and a superseded world are three states. An absent coverage
report, an unreadable one, one with no fingerprint, and a current fingerprint that
cannot be computed are all the middle state, and all four asserted the third.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import ask
import staleness


def _fake_tree(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    ext = tmp_path / "extensions"
    (ext / "mod_a").mkdir(parents=True)
    (ext / "mod_a" / "content.xml").write_bytes(b'<content id="mod_a" version="100"/>')
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "_merge.py").write_bytes(b"# merge v1\n")
    return ref, ext, engine


def test_an_ABSENT_coverage_report_is_UNKNOWN_not_STALE(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    v = staleness.check(tmp_path / "nope.json", ref, ext, engine)
    assert not v.fresh
    assert v.determinable is False
    assert "FRESHNESS UNKNOWN" in v.banner()


def test_an_UNREADABLE_coverage_report_is_UNKNOWN_not_STALE(tmp_path):
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text("{ this is not json", encoding="utf-8")
    v = staleness.check(cov, ref, ext, engine)
    assert not v.fresh and v.determinable is False


def test_a_report_with_NO_FINGERPRINT_is_UNKNOWN_not_STALE(tmp_path):
    """The code comment already said "Absent is UNKNOWN, never fresh" while the
    banner it produced said STALE."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff", "status": "complete"}), encoding="utf-8")
    v = staleness.check(cov, ref, ext, engine)
    assert not v.fresh and v.determinable is False


def test_a_CURRENT_fingerprint_that_cannot_be_computed_is_UNKNOWN(tmp_path, monkeypatch):
    """ask.py guards the CALLER side (a cold checkout). The comparison side can fail
    on a fully CONFIGURED machine whose roots have moved, and with no `now` there is
    nothing for the stored stamp to be compared against."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff",
                               "fingerprint": {"content": "a", "engine": "b"}}),
                   encoding="utf-8")

    def boom(*a, **k):
        raise OSError("reference root has moved")
    monkeypatch.setattr(staleness, "fingerprint", boom)
    v = staleness.check(cov, ref, ext, engine)
    assert not v.fresh and v.determinable is False


def test_a_REAL_content_change_is_STALE_and_stays_DETERMINABLE(tmp_path):
    """The twin, and without it every assertion above passes on a function that
    reports UNKNOWN unconditionally. Here the world genuinely moved, which is a
    FINDING and must keep saying so."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff",
                               "fingerprint": staleness.fingerprint(ref, ext, engine)}),
                   encoding="utf-8")
    assert staleness.check(cov, ref, ext, engine).fresh
    (ext / "mod_b").mkdir()
    (ext / "mod_b" / "content.xml").write_bytes(b'<content id="mod_b" version="1"/>')
    v = staleness.check(cov, ref, ext, engine)
    assert not v.fresh
    assert v.determinable is True, "a world that really moved is a finding, not an unknown"
    assert "FRESHNESS UNKNOWN" not in v.banner()


def test_an_UNREADABLE_coverage_file_does_not_escape_as_a_TRACEBACK(tmp_path,
                                                                    monkeypatch, capsys):
    """`load_coverage` sits on the path every query takes and called `json.loads`
    unguarded, so a truncated artifact died with rc 1 -- which in this toolkit means
    "the thing you asked about has findings". F39 removed that confusion from the
    CLIs; this reader was missed."""
    monkeypatch.setattr(ask, "BASEX_DIR", tmp_path)
    (tmp_path / "coverage-x4raw.json").write_text('{"db": "x4ra', encoding="utf-8")
    assert ask.load_coverage("x4raw") == {}
    assert "unreadable" in capsys.readouterr().err


def test_a_coverage_file_that_is_a_JSON_LIST_is_also_refused(tmp_path, monkeypatch):
    """Valid JSON, wrong shape: `.get` would raise on it just as loudly."""
    monkeypatch.setattr(ask, "BASEX_DIR", tmp_path)
    (tmp_path / "coverage-x4raw.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert ask.load_coverage("x4raw") == {}


def test_a_GOOD_coverage_file_still_loads(tmp_path, monkeypatch):
    """The twin for the two above."""
    monkeypatch.setattr(ask, "BASEX_DIR", tmp_path)
    (tmp_path / "coverage-x4raw.json").write_text(
        json.dumps({"db": "x4raw", "status": "complete"}), encoding="utf-8")
    assert ask.load_coverage("x4raw")["status"] == "complete"


def test_the_CLI_rc_matches_the_BANNER_it_prints(tmp_path, capsys):
    """The rc and the banner are two channels and they must not contradict.

    `main()` returned 5 (STALE) for every non-fresh verdict. Once `check()` could
    report UNKNOWN, that meant printing "FRESHNESS UNKNOWN -- nobody established
    which" while exiting with the code that means "the world moved". 6 is already
    this CLI's "cannot determine", used by both `_report_unknown` sites and --write.
    """
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff", "status": "complete"}), encoding="utf-8")

    import staleness as st
    orig = st._defaults
    st._defaults = lambda: (ref, ext, engine)
    try:
        rc = st.main(["--check", "--db", "x4eff", "--coverage", str(cov)])
    finally:
        st._defaults = orig
    err = capsys.readouterr().err
    assert "FRESHNESS UNKNOWN" in err
    assert rc == 6, "the banner said UNKNOWN; the exit code must not say STALE"


def test_a_GENUINELY_STALE_index_still_exits_5(tmp_path, capsys):
    """The twin. Without it the change above could have made every non-fresh
    verdict undeterminable, which would retire the stale signal entirely."""
    ref, ext, engine = _fake_tree(tmp_path)
    cov = tmp_path / "coverage-x4eff.json"
    cov.write_text(json.dumps({"db": "x4eff",
                               "fingerprint": staleness.fingerprint(ref, ext, engine)}),
                   encoding="utf-8")
    (ext / "mod_b").mkdir()
    (ext / "mod_b" / "content.xml").write_bytes(b'<content id="mod_b" version="1"/>')

    import staleness as st
    orig = st._defaults
    st._defaults = lambda: (ref, ext, engine)
    try:
        rc = st.main(["--check", "--db", "x4eff", "--coverage", str(cov)])
    finally:
        st._defaults = orig
    assert "FRESHNESS UNKNOWN" not in capsys.readouterr().err
    assert rc == 5
