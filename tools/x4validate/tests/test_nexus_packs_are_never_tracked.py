"""Nexus release packs are the USER's local artifact. They must never be tracked.

WHY THIS EXISTS. `7e619b1` gave the packs "a permanent home in the repo". They are not
code: they are pasted into a Nexus page by hand, and deleted locally once posted, every
release (dev commit `a2b1641` records that routine). Tracked, each deletion left
tracked-but-absent files behind, so `gates/control_bytes.py` -- which builds its
population from `git ls-files` -- correctly REFUSED, and the suite sat at 2 failures
indefinitely. A permanently red suite is how a NEW red goes unnoticed. User decision,
2026-09-13: untrack them, ignore them, and make re-tracking them a failing test.

TWO MECHANISMS, because `.gitignore` alone does not stop `git add -f`:

* the ignore rule must be DECLARED (checked in every tree, including a cold archive), and
  it must actually DECIDE a path under the packs dir -- asked of git with
  `check-ignore -v --no-index`, never re-implemented. MEASURED 2026-09-13 on this git: a
  negation that wins returns rc 1 and prints nothing, and a negation under an excluded
  PARENT directory cannot re-include anything, so the parent's rule still decides. The
  test that wrote this first assumed the opposite and its own twin caught it.
* nothing under `release/nexus/` may be tracked, asked of git, never inferred from disk --
  the packs legitimately sit on disk as ignored files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PACKS = "release/nexus"
IGNORE_LINE = "release/nexus/"

_PKG = Path(__file__).resolve().parent.parent


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    """None when git itself cannot be run. A non-zero exit is returned, not hidden."""
    try:
        return subprocess.run(("git", "-C", str(root), *args), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _repo_root(pkg: Path) -> Path | None:
    """The repository root, ASKED of git. None outside a checkout (a cold archive)."""
    r = _git(pkg, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(r.stdout.strip())


def tracked_packs(root: Path) -> list[str]:
    r = _git(root, "ls-files", "--", PACKS)
    if r is None or r.returncode != 0:
        raise RuntimeError(f"git ls-files could not answer in {root}: "
                           f"{None if r is None else r.stderr.strip()}")
    return [line for line in r.stdout.splitlines() if line.strip()]


def ignore_pattern(root: Path) -> str | None:
    """The pattern that IGNORES a probe path under the packs dir, or None if nothing does.

    `--no-index` so the answer is about the RULES, not about whether the probe happens
    to be tracked. rc 1 is git's "not ignored" -- including when a negation wins.
    Any other failure RAISES: an unanswerable question is not "not ignored".
    """
    r = _git(root, "check-ignore", "-v", "--no-index", f"{PACKS}/v0.0.0/probe.txt")
    if r is None:
        raise RuntimeError("git could not be run")
    if r.returncode == 1:
        return None
    if r.returncode != 0:
        raise RuntimeError(f"git check-ignore failed: {r.stderr.strip()}")
    # "<source>:<line>:<pattern>\t<path>"
    head = r.stdout.split("\t", 1)[0]
    parts = head.split(":", 2)
    if len(parts) != 3 or not parts[2]:
        raise RuntimeError(f"unparseable check-ignore output: {r.stdout!r}")
    return parts[2]


def gitignore_declares(gitignore: Path) -> bool:
    """The exact rule as a live (non-comment) line. A mention in a comment is not a rule."""
    if not gitignore.is_file():
        return False
    lines = gitignore.read_bytes().decode("utf-8").splitlines()
    return any(line.strip() == IGNORE_LINE for line in lines)


# ---------------------------------------------------------------------------- the tree

ROOT = _repo_root(_PKG)
#: The package sits at tools/x4validate/ in this repo. Used only when git cannot name
#: the root (a cold archive), and only to find `.gitignore`.
_FALLBACK_ROOT = _PKG.parent.parent


def test_the_gitignore_declares_the_packs_ignored():
    """Checked in EVERY tree, a cold archive included -- `.gitignore` ships in it."""
    root = ROOT or _FALLBACK_ROOT
    assert gitignore_declares(root / ".gitignore"), (
        f"{root / '.gitignore'} has no live `{IGNORE_LINE}` line -- Nexus packs are the "
        f"user's local artifact and must stay out of git")


def test_nothing_under_the_packs_dir_is_tracked():
    if ROOT is None:
        pytest.skip("not a git checkout (cold archive) -- tracked state NOT CHECKED")
    tracked = tracked_packs(ROOT)
    assert tracked == [], (
        f"{len(tracked)} Nexus pack file(s) are tracked; untrack with "
        f"`git rm -r --cached {PACKS}`: {tracked[:5]}")


def test_git_itself_ignores_a_path_under_the_packs_dir():
    """The declared line is not enough on its own: a later negation could undo it."""
    if ROOT is None:
        pytest.skip("not a git checkout (cold archive) -- ignore resolution NOT CHECKED")
    pat = ignore_pattern(ROOT)
    assert pat is not None, f"git does not ignore a path under {PACKS}/"


# ------------------------------------------------------------- falsification twins


@pytest.fixture
def scratch_repo(tmp_path):
    r = _git(tmp_path, "init", "-q")
    if r is None or r.returncode != 0:
        pytest.skip("git unavailable -- the twins cannot build a repo")
    return tmp_path


def test_TWIN_a_tracked_pack_file_is_reported(scratch_repo):
    f = scratch_repo / PACKS / "v1.0.0" / "NEXUS-CHANGELOG.txt"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"posted by hand\n")
    r = _git(scratch_repo, "add", "-f", "--", f"{PACKS}/v1.0.0/NEXUS-CHANGELOG.txt")
    assert r is not None and r.returncode == 0, "precondition: the file was staged"
    assert tracked_packs(scratch_repo) == [f"{PACKS}/v1.0.0/NEXUS-CHANGELOG.txt"]


def test_TWIN_a_winning_negation_reads_as_NOT_ignored(scratch_repo):
    """`dir/*` then `!dir/sub/` re-includes -- git's rc 1, so the tree test goes red."""
    (scratch_repo / ".gitignore").write_bytes(
        f"{PACKS}/*\n!{PACKS}/v0.0.0/\n".encode("utf-8"))
    assert ignore_pattern(scratch_repo) is None


def test_TWIN_a_negation_under_an_excluded_parent_cannot_undo_the_rule(scratch_repo):
    """The shape the first version of this test got wrong: git cannot re-include a path
    whose PARENT directory is excluded, so the directory rule still decides."""
    (scratch_repo / ".gitignore").write_bytes(
        f"{IGNORE_LINE}\n!{PACKS}/v0.0.0/\n".encode("utf-8"))
    assert ignore_pattern(scratch_repo) == IGNORE_LINE


def test_TWIN_no_rule_at_all_resolves_to_None(scratch_repo):
    assert ignore_pattern(scratch_repo) is None


def test_TWIN_a_commented_rule_is_not_a_declared_rule(tmp_path):
    g = tmp_path / ".gitignore"
    g.write_bytes(f"# {IGNORE_LINE}\n".encode("utf-8"))
    assert gitignore_declares(g) is False
    g.write_bytes(f"dist/\n{IGNORE_LINE}\n".encode("utf-8"))
    assert gitignore_declares(g) is True


def test_TWIN_an_absent_gitignore_is_not_a_declared_rule(tmp_path):
    assert gitignore_declares(tmp_path / ".gitignore") is False
