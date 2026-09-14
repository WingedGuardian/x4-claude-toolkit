#!/usr/bin/env python3
"""Next free blind-spot id, computed across EVERY branch — not just your checkout.

WHY THIS EXISTS.
================
MEASURED 2026-08-28: two concurrent sessions each computed "next free id" from their
own `docs/BLIND-SPOTS.md` and both got **F73**. Neither file was wrong. Neither
session could see the other. `tests/test_blind_spots_ids.py` enforces uniqueness
WITHIN a file, so it could not fire — the two entries lived on two branches, and it
would only have caught them at merge, after both ids were cited from commit messages
and memories.

That is the same shared-mutable-counter shape the verifier register abandoned for
date+slug headings on 2026-08-27. The F-series deliberately kept numeric ids, because
unlike that register **F-ids are cited BY ID** from CLAUDE.md, memories and commits,
so renumbering costs something date+slug never did. So the fix is to make CLAIMING
safe rather than to abandon ids.

WHAT IT DELIBERATELY IS NOT.
============================
Not a collision detector. Two branches legitimately hold the same id with different
text while one is simply behind — today one branch has F71 as the corrected
*"rendered a WRONG FORM"* and another still has the superseded *"cannot resolve a
mod-owned vpath"*. Same finding, stale branch. Flagging that would fire on ordinary
divergence and be ignored within a week (CLAUDE.md: a check that floods is worse than
no check).

    uv run python scripts/next-blind-spot-id.py

  rc 0 = an id to claim   rc 2 = cannot answer (never a guess)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REGISTER = "docs/BLIND-SPOTS.md"        # relative to the PACKAGE, not the repo
PKG = Path(__file__).resolve().parent.parent

#: Same rule as tests/test_blind_spots_ids.py::_DECLARATION, on purpose: a heading
#: DECLARES a finding only when it carries the status/confidence tail. A continuation
#: (`## F11 — re-scoped after measuring`) is not a second claim. If the two ever
#: disagree about what an id IS, one of them hands out an id already in use.
_DECLARATION = re.compile(r"^## F(\d+) .*?confidence", re.M)

#: A SUMMARY TABLE ROW. Allocation asks a different question from duplicate
#: detection: not "do two findings share an id?" but "is this id SPOKEN FOR?" --
#: and a row speaks for it, because the instruction this very script prints says
#: to claim an id by writing the row FIRST ("a row is the cheapest thing to push,
#: and it makes the claim visible to the other trees").
#:
#: Counting only sections is how F94 and F95 were each handed out TWICE: one tree
#: committed them as rows, this parser could not see rows, and it offered them
#: again to the next tree that asked. The tool that exists to prevent collisions
#: caused one. Keyed on the leading cell alone -- the row format is not stable
#: further right (some rows carry 5 cells, one carries 6).
_TABLE_ROW = re.compile(r"^\| F(\d+) \|", re.M)


class CannotAnswer(RuntimeError):
    """Raised rather than returning a number nobody should act on.

    Returning 1 from an empty scan would be a confident wrong answer that hands out
    an id already in use — the founding defect shape of this whole toolkit.
    """


def declared_ids(text: str) -> set[int]:
    """Ids with a full SECTION. Unchanged, and deliberately so -- this is the
    duplicate-detection sense that `test_blind_spots_ids.py` mirrors."""
    return {int(n) for n in _DECLARATION.findall(text)}


def table_row_ids(text: str) -> set[int]:
    return {int(n) for n in _TABLE_ROW.findall(text)}


def claimed_ids(text: str) -> set[int]:
    """Every id SPOKEN FOR, by a section or a row. This is what allocation must
    use; a row-only claim is still a claim."""
    return declared_ids(text) | table_row_ids(text)


def next_free_id(per_branch: dict[str, set[int]]) -> int:
    """One past the highest id declared on ANY branch.

    *per_branch* maps branch -> ids. A branch that predates the register contributes
    an empty set and must not drag the answer down; but if EVERY branch is empty the
    scan told us nothing, which is a non-answer, not "start at 1".
    """
    seen = {i for ids in per_branch.values() for i in ids}
    if not seen:
        raise CannotAnswer(
            "no branch yielded a parseable register: either none has "
            f"{REGISTER}, or the heading format changed and the parser matched "
            "nothing. Refusing to guess an id.")
    return max(seen) + 1


def _git(pkg: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(pkg), *args], capture_output=True, text=True,
                         check=False)
    if out.returncode != 0:
        raise CannotAnswer(f"git {' '.join(args)}: {out.stderr.strip()[:160]}")
    return out.stdout


def _is_absence(stderr: str) -> bool:
    """True only for git's two "that path is not in this commit" messages."""
    return "does not exist in" in stderr or "exists on disk, but not in" in stderr


def scan_branches(pkg: Path = PKG) -> dict[str, set[int]]:
    # The register sits under the package, and the package is NESTED in this repo
    # (tools/x4validate/). It was written in a repo whose root WAS the package, so
    # `<branch>:docs/BLIND-SPOTS.md` named a path that does not exist here and every
    # branch read as "no register" -- a refusal at best. Ask git for the prefix.
    prefix = _git(pkg, "rev-parse", "--show-prefix").strip()
    # One name per LINE, from refs/heads only. `git branch` prints a detached HEAD as
    # "(HEAD detached at 1a2b3c)", and splitting that on whitespace consulted four
    # branches that do not exist (review, 2026-09-14). HEAD is consulted as well, so an
    # id claimed on a detached checkout is not invisible.
    branches = [b.strip() for b in _git(pkg, "for-each-ref", "--format=%(refname:short)",
                                        "refs/heads").splitlines() if b.strip()]
    if not branches:
        raise CannotAnswer("no branches found — is this a git repository?")
    branches.append("HEAD")
    per: dict[str, set[int]] = {}
    for b in branches:
        got = subprocess.run(["git", "-C", str(pkg), "show", f"{b}:{prefix}{REGISTER}"],
                             capture_output=True, check=False)
        # A branch without the register is an ABSENCE, not a failure: the register is
        # younger than most branches here (it arrived from the retired dev repository
        # on 2026-09-13). Recorded as empty so the printout
        # still names every branch that was consulted.
        if got.returncode == 0:
            per[b] = claimed_ids(got.stdout.decode("utf-8", "replace"))
        elif _is_absence(got.stderr.decode("utf-8", "replace")):
            per[b] = set()
        else:
            # Every other failure used to read as "no register" too, so a read that
            # failed looked exactly like a branch that predates the register.
            raise CannotAnswer(f"git show {b}:{prefix}{REGISTER} failed: "
                               f"{got.stderr.decode('utf-8', 'replace').strip()[:160]}")
    return per


def main(argv=None) -> int:
    try:
        per = scan_branches()
        nxt = next_free_id(per)
    except CannotAnswer as exc:
        print(f"CANNOT ANSWER: {exc}", file=sys.stderr)
        return 2
    print(f"consulted {len(per)} branch(es):")
    for b, ids in sorted(per.items()):
        top = max(ids) if ids else None
        print(f"  {b:<44} {len(ids):>3} declaration(s)"
              f"{f', highest F{top}' if top else ', no register'}")
    print(f"\nNEXT FREE ID:  F{nxt}")
    print("Claim it by writing the summary table ROW first, then the entry — a row is\n"
          "the cheapest thing to push, and it makes the claim visible to the other trees.")
    # Say what this answer CANNOT see. `git show <branch>:<register>` reads
    # COMMITTED state only, so an id claimed in a working tree and not yet
    # committed is invisible here -- the other half of how F94/F95 collided.
    # Naming the limit is the difference between an answer and a confident
    # wrong one.
    print("\nScanned COMMITTED registers only. An id claimed in an uncommitted working"
          "\ntree is invisible to this scan -- commit the row before you rely on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
