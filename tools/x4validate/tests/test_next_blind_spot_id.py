"""Claiming an F-id must consult every BRANCH, not just your working copy.

MEASURED 2026-08-28: two concurrent sessions each computed "next free id" from their
OWN `docs/BLIND-SPOTS.md` and both got **F73**. Neither file was wrong; neither
session could see the other. `test_blind_spots_ids.py` cannot catch this — it reads
one file, and the two entries lived on two branches. It would have fired only at
merge, after both ids had been cited from commit messages and memories.

This is the same shared-mutable-counter shape that made the verifier register drop
running numbers for date+slug headings on 2026-08-27. The F-series kept ids
deliberately, because unlike that register **F-ids are cited BY ID** from CLAUDE.md,
memories and commits — so renumbering has a real cost that date+slug never had. The
answer is therefore to make CLAIMING safe, not to abandon ids.

⚠ Deliberately NOT a collision detector. Two branches legitimately carry the same id
with different text while one is merely behind: TODAY `session/tooling` has F71 as
*"rendered a WRONG FORM ... FIXED"* and another branch still has the superseded
*"cannot resolve a mod-owned vpath ... OPEN"*. Same finding, stale branch. A check
that flagged that would fire constantly on ordinary divergence and be ignored inside
a week.
"""
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "next-blind-spot-id.py"


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("nbsi", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    if not SCRIPT.is_file():
        pytest.skip(f"no {SCRIPT} — not checked")
    return _load()


def test_next_id_is_one_past_the_highest_across_ALL_branches(m):
    """The bug: each session took max+1 of its OWN file and both got 73."""
    per_branch = {"session/tooling": {70, 71, 73},
                  "other/branch":    {70, 71, 74}}
    assert m.next_free_id(per_branch) == 75


def test_a_branch_with_no_register_does_not_drag_the_answer_down(m):
    """A branch predating the register contributes nothing, not a zero."""
    per_branch = {"a": {70, 71}, "empty": set()}
    assert m.next_free_id(per_branch) == 72


def test_it_REFUSES_rather_than_guessing_when_nothing_could_be_read(m):
    """Absence vs non-answer. If no branch yielded a register, returning 1 would be a
    confident wrong answer that hands out an id already in use."""
    with pytest.raises(m.CannotAnswer):
        m.next_free_id({})
    with pytest.raises(m.CannotAnswer):
        m.next_free_id({"a": set(), "b": set()})


def test_the_id_parser_ignores_a_CONTINUATION_heading(m):
    """`## F11 — re-scoped after measuring` continues a finding; it does not declare a
    new one. Mirrors `test_blind_spots_ids.py`'s `_DECLARATION` rule, deliberately, so
    the two never disagree about what an id IS."""
    text = ("## F70 — a thing · **DEFECT** · confidence 90%\n"
            "## F70 — re-scoped after measuring\n"
            "## F71 — another · **SCOPE** · confidence 95%\n"
            "| F99 | a summary row is not a declaration |\n")
    assert m.declared_ids(text) == {70, 71}


def test_a_SUMMARY_ROW_still_CLAIMS_the_id_even_with_no_section(m):
    """G1-2, and it is why F94/F95 were each handed out twice.

    `declared_ids` is right that a row is not a DECLARATION. It was wrong as the
    input to ALLOCATION, which asks whether an id is SPOKEN FOR -- and this
    script's own printed instruction tells you to claim one by writing the row
    FIRST. So the tool that exists to prevent collisions offered an id another
    tree had already committed.
    """
    text = ("## F70 — a thing · **DEFECT** · confidence 90%\n"
            "| F99 | a row with no section is still a claim |\n")
    assert m.declared_ids(text) == {70}, "the declaration sense must not change"
    assert m.table_row_ids(text) == {99}
    assert m.claimed_ids(text) == {70, 99}
    # the consequence, stated as the number a caller acts on
    assert m.next_free_id({"b": m.claimed_ids(text)}) == 100, (
        "allocation used the declaration sense and would re-issue a committed id")


def test_allocation_is_not_dragged_down_by_a_row_only_branch(m):
    """The twin. Widening what counts as a claim must not make an id look FREE that
    a section already holds -- the union has to be a union, not a swap."""
    sections_only = "## F80 — x · **DEFECT** · confidence 90%\n"
    rows_only = "| F60 | y |\n"
    assert m.next_free_id({"a": m.claimed_ids(sections_only),
                           "b": m.claimed_ids(rows_only)}) == 81


def test_a_register_that_parses_to_nothing_is_a_NON_ANSWER(m):
    """Denominator guard: a heading-format change must not silently yield an empty set
    that then reads as 'this branch has no ids'."""
    with pytest.raises(m.CannotAnswer):
        m.next_free_id({"a": m.declared_ids("no headings here at all\n")})


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, check=True, capture_output=True)


def _repo_with_register(tmp_path, rel):
    reg = tmp_path / rel / "docs" / "BLIND-SPOTS.md"
    reg.parent.mkdir(parents=True)
    nl = chr(10)
    reg.write_text("## F7 — x · **DEFECT** · confidence 90%" + nl + "| F9 | a row |" + nl,
                   encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", str(reg.relative_to(tmp_path)))
    _git(tmp_path, "commit", "-q", "-m", "register")


def test_the_scan_reads_a_register_NESTED_below_the_repo_root(m, tmp_path):
    """The script moved in from a repo whose root WAS the package; here the package is
    `tools/x4validate/`. Reading `<branch>:docs/BLIND-SPOTS.md` from the repo root finds
    nothing on any branch, so every id request would have been refused. The path is now
    asked of git from the package directory."""
    pkg = tmp_path / "tools" / "x4validate"
    _repo_with_register(tmp_path, "tools/x4validate")
    per = m.scan_branches(pkg)
    assert "HEAD" in per and len(per) == 2, per
    assert all(ids == {7, 9} for ids in per.values()), per
    assert m.next_free_id(per) == 10


def test_TWIN_a_register_elsewhere_in_the_repo_is_not_mistaken_for_this_one(m, tmp_path):
    """The twin: the scan must read the PACKAGE's register, not any docs/BLIND-SPOTS.md.
    One committed at the repo root is invisible from a nested package, and that
    non-answer must refuse rather than hand out F1."""
    pkg = tmp_path / "tools" / "x4validate"
    pkg.mkdir(parents=True)
    _repo_with_register(tmp_path, ".")
    per = m.scan_branches(pkg)
    assert all(ids == set() for ids in per.values()) and per, per
    with pytest.raises(m.CannotAnswer):
        m.next_free_id(per)


def test_a_DETACHED_HEAD_is_consulted_and_invents_no_branches(m, tmp_path):
    """`git branch` prints a detached HEAD as "(HEAD detached at <sha>)"; splitting that on
    whitespace consulted four branches that do not exist, and an id claimed only on the
    detached commit was invisible (review, 2026-09-14)."""
    pkg = tmp_path / "tools" / "x4validate"
    _repo_with_register(tmp_path, "tools/x4validate")
    _git(tmp_path, "checkout", "-q", "--detach")
    reg = pkg / "docs" / "BLIND-SPOTS.md"
    reg.write_text(reg.read_text(encoding="utf-8") + "| F20 | claimed while detached |" + chr(10),
                   encoding="utf-8")
    _git(tmp_path, "add", str(reg.relative_to(tmp_path)))
    _git(tmp_path, "commit", "-q", "-m", "claim")
    per = m.scan_branches(pkg)
    assert not any(" " in b or "(" in b or "detached" in b for b in per), per
    assert 20 in per["HEAD"], per
    assert m.next_free_id(per) == 21


def test_only_a_MISSING_PATH_is_an_absence_every_other_git_failure_refuses(m):
    assert m._is_absence("fatal: path 'tools/x4validate/docs/BLIND-SPOTS.md' does not exist in 'old'")
    assert m._is_absence("fatal: path 'docs/BLIND-SPOTS.md' exists on disk, but not in 'HEAD'")
    assert not m._is_absence("fatal: bad object deadbeef")
    assert not m._is_absence("")
