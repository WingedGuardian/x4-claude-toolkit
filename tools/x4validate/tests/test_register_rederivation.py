"""`gates/register_rederivation.py` — a FIXED entry must name its evidence.

The gate exists because doing this audit by hand needed three instruments before
one of them was right. A keyword scan for "tests/" produced a false NEGATIVE (F69
names no test but has one); a grep for each entry's headline NUMBER produced false
positives everywhere, because "200" and "165" appear in unrelated fixtures. What
works is asking whether the entry names a check AND whether that file exists.

One test per clause, because each guard shadows the ones behind it.
"""

from __future__ import annotations

import json

import pytest

from conftest import import_gate

rr = import_gate("register_rederivation")

NL = chr(10)


def _doc(*entries: str) -> str:
    return NL.join(entries)


def test_a_fixed_entry_naming_an_existing_test_is_satisfied(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_real.py").write_text("", encoding="utf-8")
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "fixed by `tests/test_real.py`"), tmp_path)
    assert ok == ["F1"] and missing == []


def test_a_named_test_that_DOES_NOT_EXIST_does_not_count(tmp_path):
    """Worse than naming nothing: it reads as covered. This is the clause a
    keyword scan gets wrong, and it is why existence is checked."""
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "fixed by `tests/test_deleted_last_year.py`"), tmp_path)
    assert missing == ["F1"] and ok == []


def test_an_OPEN_entry_is_not_asked_for_evidence(tmp_path):
    """An open blind spot owes nothing yet; demanding a check would make the gate
    fire on the honest act of recording a problem you have not solved."""
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **SCOPE** · ⚠ OPEN 2026-01-01", "no fix yet"), tmp_path)
    assert ok == [] and missing == []


def test_an_explicit_NO_RE_DERIVATION_is_accepted(tmp_path):
    """A figure that genuinely cannot be re-derived is a statement a reader can
    weigh. Silence is not."""
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "NO RE-DERIVATION: the engine dump it measured no longer exists."), tmp_path)
    assert ok == ["F1"] and missing == []


def test_the_word_selftest_counts(tmp_path):
    """Several tools carry their own `--selftest` rather than a pytest file."""
    ok, _ = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "proven by its selftest, 14/14"), tmp_path)
    assert ok == ["F1"]


def test_a_gates_path_counts_as_well_as_a_tests_path(tmp_path):
    (tmp_path / "gates").mkdir()
    (tmp_path / "gates" / "g.py").write_text("", encoding="utf-8")
    ok, _ = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "re-derived by `gates/g.py`"), tmp_path)
    assert ok == ["F1"]


def test_entries_are_split_per_heading_not_merged(tmp_path):
    """A satisfied entry must not vouch for the one after it — the whole audit
    would pass on a single naming if the bodies ran together."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_real.py").write_text("", encoding="utf-8")
    ok, missing = rr.audit(
        _doc("## F1 — a · **DEFECT** · ✅ FIXED 2026-01-01",
             "fixed by `tests/test_real.py`",
             "## F2 — b · **DEFECT** · ✅ FIXED 2026-01-02",
             "fixed somehow"), tmp_path)
    assert ok == ["F1"] and missing == ["F2"]


def test_a_damaged_baseline_RAISES_rather_than_reading_as_empty(tmp_path, monkeypatch):
    """Returning [] there would flood the run with false NEW rows while looking
    like a clean first run — absence and non-answer collapsing into one value."""
    b = tmp_path / "b.json"
    b.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(rr, "BASELINE", b)
    with pytest.raises(RuntimeError):
        rr._baseline()


def test_an_absent_baseline_accepts_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "BASELINE", tmp_path / "nope.json")
    assert rr._baseline() == []


def test_a_baseline_is_read_back(tmp_path, monkeypatch):
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"missing": ["F9"]}), encoding="utf-8")
    monkeypatch.setattr(rr, "BASELINE", b)
    assert rr._baseline() == ["F9"]


def test_the_real_register_is_clean_against_its_recorded_baseline():
    """The end-to-end case. If this fails, an entry was marked FIXED without
    naming what proves it — which is the whole point."""
    assert rr.main() == 0

def test_a_shell_suite_counts_as_a_re_derivation(tmp_path):
    """Added 2026-08-29 on this gate's first serious use. F79's proof is
    `scripts/test-hooks.sh` -- every bit as much a check as a pytest file. A gate
    that only recognises evidence in ONE language reports a real proof as missing."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "test-hooks.sh").write_text("", encoding="utf-8")
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "proven by `scripts/test-hooks.sh`"), tmp_path)
    assert ok == ["F1"] and missing == []


def test_a_hook_suite_under_dot_claude_counts_too(tmp_path):
    d = tmp_path / ".claude" / "hooks"
    d.mkdir(parents=True)
    (d / "test-protect-bash.sh").write_text("", encoding="utf-8")
    ok, _ = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "proven by `.claude/hooks/test-protect-bash.sh`"), tmp_path)
    assert ok == ["F1"]


def test_a_named_shell_suite_that_does_NOT_exist_still_fails(tmp_path):
    """The falsification twin. Without it the two above would pass for a matcher
    that accepted any .sh string whether or not the file was ever written."""
    ok, missing = rr.audit(
        _doc("## F1 — a thing · **DEFECT** · ✅ FIXED 2026-01-01",
             "proven by `scripts/test-imaginary.sh`"), tmp_path)
    assert missing == ["F1"] and ok == []


# --- the two gates must agree about which heading an entry HAS ---------------- #


def test_entries_is_FIRST_wins_because_the_sibling_gate_says_so():
    """`tests/test_blind_spots_ids.py` documents the convention in as many words --
    "First heading wins: a continuation heading does not redeclare status" -- and names
    F11 as the legitimate two-heading case.

    `entries()` was a dict comprehension, which is LAST-wins, so the two gates read the
    same file and disagreed about which heading F11 has. MEASURED 2026-08-31: exactly 1
    of 92 entries differed, and it was the one that mattered -- F11's declaring heading
    has said FIXED since 2026-08-13 while this gate audited its CONTINUATION, where no
    status is declared. The entry was invisible to the "a FIXED entry must name its
    check" rule for eighteen days, and it named none.
    """
    text = (
        "## F1 - declared - FIXED\nbody one\n"
        "## F2 - something else\nunrelated\n"
        "## F1 - a later continuation with no status\nbody two\n"
    )
    got = rr.entries(text)
    head = got["F1"].split("\n")[0]
    assert "FIXED" in head, (
        "entries() took the CONTINUATION heading; a last-wins dict does this, and it "
        "hides the declared status")
    assert "body one" in got["F1"] and "body two" in got["F1"], (
        "the continuation body was discarded -- a check cited only there would be lost")


def test_a_continuation_is_not_counted_as_a_second_finding():
    """The count must not inflate. Two headings, one finding."""
    text = ("## F1 - declared - FIXED\na\n"
            "## F1 - continuation\nb\n")
    assert list(rr.entries(text)) == ["F1"]


def test_the_real_register_agrees_with_the_id_gate_about_every_heading():
    """The invariant itself, over the actual file rather than a fixture. If either gate
    changes convention, this goes red instead of one of them silently auditing a
    different entry than the other."""
    import re as _re

    text = rr.REGISTER.read_text(encoding="utf-8")
    mine = rr.entries(text)
    first_seen = {}
    for m in _re.finditer(r"(?m)^## (F\d+)([^\n]*)", text):
        first_seen.setdefault(m.group(1), m.group(2))
    assert set(mine) == set(first_seen)
    for fid, head in first_seen.items():
        assert mine[fid].split("\n")[0].rstrip("\r") == head.rstrip("\r"), (
            f"{fid}: this gate reads a different heading than the id gate does")


def test_a_PACKAGE_relative_citation_resolves_in_the_MIRROR_too(tmp_path, monkeypatch):
    """The mirror is a repo ROOT; this checkout is the PACKAGE root.

    (Written in the retired dev repository, whose root WAS the package: "the lane" is that
    checkout and "the mirror" is this repository. `_roots` now derives both from the
    layout; the search pinned here is unchanged.)

    So `scripts/fuzz-guard.py` (repo-relative) and `tests/test_x.py` (package-relative)
    live at different depths in the mirror, and `_roots` has to offer both or a citation
    that is TRUE reads as a missing check -- this gate's own worst case inverted. MEASURED
    2026-09-06 on the real trees: `scripts/fuzz-guard.py` resolved while
    `tests/test_bootstrap_scripts_are_portable.py` did not, though both ship in the mirror.

    Built as a synthetic mirror so it does not depend on what the real one happens to hold.
    """
    mirror = tmp_path / "mirror"
    (mirror / "scripts").mkdir(parents=True)
    (mirror / "scripts" / "repo-relative.sh").write_text("x", encoding="utf-8")
    pkg = mirror / "tools" / "x4validate" / "tests"
    pkg.mkdir(parents=True)
    (pkg / "test_package_relative.py").write_text("x", encoding="utf-8")

    lane = tmp_path / "lane"
    (lane / "scripts").mkdir(parents=True)
    monkeypatch.setattr(rr, "_roots",
                        lambda root: [lane, mirror, mirror / "tools" / "x4validate"])

    # package-relative: only findable via the nested root -- the case that was broken
    assert rr.names_a_check("see `tests/test_package_relative.py`", lane) \
        == "tests/test_package_relative.py"
    # repo-relative: still findable at the mirror root -- the case that already worked,
    # asserted so a fix cannot trade one for the other
    assert rr.names_a_check("see `scripts/repo-relative.sh`", lane) \
        == "scripts/repo-relative.sh"


def test_a_citation_to_a_file_that_exists_NOWHERE_is_still_None(tmp_path, monkeypatch):
    """The twin. Widening the search must not make every citation resolve -- naming a
    check that is not there is the failure this gate exists to catch."""
    lane = tmp_path / "lane"
    lane.mkdir()
    mirror = tmp_path / "mirror"
    (mirror / "tools" / "x4validate").mkdir(parents=True)
    monkeypatch.setattr(rr, "_roots",
                        lambda root: [lane, mirror, mirror / "tools" / "x4validate"])
    assert rr.names_a_check("see `tests/test_not_anywhere.py`", lane) is None


def test_roots_offers_the_package_AND_the_repo_that_nests_it():
    """The real `_roots` on this checkout -- no monkeypatch, and no skip.

    The tests above monkeypatch `_roots`, so they pin `names_a_check`'s search and not the
    root derivation itself. In the dev repository this test SKIPPED whenever no mirror was
    configured; with one repository the question always has an answer, so it asserts it.
    """
    pkg = rr.REGISTER.parent.parent
    roots = rr._roots(pkg)
    assert [r.resolve() for r in roots] == [pkg.resolve(), pkg.parent.parent.resolve()], roots
    assert (roots[1] / ".claude" / "hooks").is_dir(), (
        f"the second root {roots[1]} is not the repository root: no .claude/hooks there")


def test_TWIN_a_package_that_is_not_nested_gets_no_second_root(tmp_path):
    """The twin: the repo root is offered only when the nesting is REAL. A guessed second
    root would let a citation resolve against whatever happens to sit two levels up."""
    flat = tmp_path / "pkg"
    flat.mkdir()
    assert rr._roots(flat) == [flat]
