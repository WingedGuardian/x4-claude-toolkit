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
        pytest.skip(f"no {SCRIPT} (dev-only script) — not checked")
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


def test_a_register_that_parses_to_nothing_is_a_NON_ANSWER(m):
    """Denominator guard: a heading-format change must not silently yield an empty set
    that then reads as 'this branch has no ids'."""
    with pytest.raises(m.CannotAnswer):
        m.next_free_id({"a": m.declared_ids("no headings here at all\n")})
