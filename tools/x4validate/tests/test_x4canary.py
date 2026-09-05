r"""`x4canary` must go RED on a loss, stay quiet on an edit, and REFUSE on a non-answer.

WHY. On 2026-09-03 the mod registry went from 196,363 bytes to 46. `dev/` is a git
repository and `git status` showed it immediately -- 8,222 deletions. Nobody ran it, and
the loss was found six hours later by accident. The detector existed; nothing invoked it
and nothing failed because of it.

So the tests that matter here are the negative ones. A check that cannot go red is
decoration (CLAUDE.md #26), and a check that fires on ordinary edits gets ignored, which
is the same outcome by a different route. Both directions are pinned below.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("x4canary",
                                               REPO / "scripts" / "x4canary.py")
x4canary = importlib.util.module_from_spec(_spec)
sys.modules["x4canary"] = x4canary
_spec.loader.exec_module(x4canary)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "core.autocrlf", "false")
    (r / "big.md").write_text("x" * 10000, encoding="utf-8")
    (r / "gone.md").write_text("z" * 500, encoding="utf-8")
    _git(r, "add", "big.md", "gone.md")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _check(repo: Path, monkeypatch) -> int:
    monkeypatch.setenv("X4_CANARY_REPOS", str(repo))
    monkeypatch.setattr(x4canary, "_paths", None)   # only the sandbox repo, nothing live
    return x4canary.main([])


def test_a_clean_repo_passes(repo, monkeypatch):
    assert _check(repo, monkeypatch) == 0


def test_an_emptied_file_is_a_loss(repo, monkeypatch):
    """The 2026-08-22 and 2026-09-03 shape: a write that truncated and then failed."""
    (repo / "big.md").write_bytes(b"")
    assert _check(repo, monkeypatch) == 1


def test_a_file_that_lost_most_of_itself_is_a_loss(repo, monkeypatch):
    """The registry shape: 196,363 bytes replaced by 46."""
    (repo / "big.md").write_text("x" * 100, encoding="utf-8")
    assert _check(repo, monkeypatch) == 1


def test_a_deleted_tracked_file_is_a_loss(repo, monkeypatch):
    (repo / "gone.md").unlink()
    assert _check(repo, monkeypatch) == 1


def test_an_ordinary_edit_does_NOT_fire(repo, monkeypatch):
    """A detector that cries wolf is ignored, which is how the last one failed."""
    (repo / "big.md").write_text("x" * 6000, encoding="utf-8")
    assert _check(repo, monkeypatch) == 0


def test_growth_does_NOT_fire(repo, monkeypatch):
    (repo / "big.md").write_text("x" * 20000, encoding="utf-8")
    assert _check(repo, monkeypatch) == 0


def test_a_new_untracked_file_does_NOT_fire(repo, monkeypatch):
    (repo / "brand-new.md").write_text("hello", encoding="utf-8")
    assert _check(repo, monkeypatch) == 0


def test_a_path_that_is_not_a_repository_REFUSES(tmp_path, monkeypatch):
    """rc 2, never 0. 'Could not look' must not render as 'nothing wrong' -- that
    conflation is the most repeated defect in this workspace."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    monkeypatch.setenv("X4_CANARY_REPOS", str(plain))
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 2


def test_a_missing_directory_REFUSES(tmp_path, monkeypatch):
    monkeypatch.setenv("X4_CANARY_REPOS", str(tmp_path / "nope"))
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 2


def test_no_repositories_at_all_REFUSES(monkeypatch):
    """'Nothing lost' over an empty set is a statement about nothing."""
    monkeypatch.delenv("X4_CANARY_REPOS", raising=False)
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 2


def test_one_bad_repo_poisons_the_verdict(repo, tmp_path, monkeypatch):
    """A good repo alongside an uncheckable one must NOT average out to 'fine'."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    import os
    monkeypatch.setenv("X4_CANARY_REPOS", os.pathsep.join([str(repo), str(plain)]))
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 2


def test_configured_repos_EXTEND_rather_than_replace(repo, monkeypatch):
    """Sibling tools whose env vars mean opposite things are a trap: if this
    replaced the defaults, configuring the memory directory would silently stop
    checking the game root."""
    sentinel = Path("C:/sentinel-game-root") if sys.platform == "win32" \
        else Path("/sentinel-game-root")

    class FakePaths:
        @staticmethod
        def game_root():
            return sentinel

        @staticmethod
        def mods():
            return None

    monkeypatch.setenv("X4_CANARY_REPOS", str(repo))
    monkeypatch.setattr(x4canary, "_paths", FakePaths)
    got = {str(p) for p in x4canary.repos()}
    assert str(repo) in got and str(sentinel) in got, (
        "X4_CANARY_REPOS replaced the resolved roots instead of extending them")


# --------------------------------------------------------------------------- #
# Two shapes the canary got WRONG in opposite directions, both MEASURED 2026-09-04.
# The `repo` fixture always commits first, so neither was reachable by any existing
# test: one needs a repo with NO commits, the other a rename.
# --------------------------------------------------------------------------- #

def test_an_UNBORN_repository_refuses_rather_than_passing(tmp_path, monkeypatch):
    """`rev-parse --git-dir` succeeds the moment `git init` has run.

    So a repo with no commits reached every check below it: every file reads `??`,
    which is drift rather than loss, and the banner said "no tracked file lost" over
    a directory where nothing is tracked at all. That is this tool's own stated
    refusal condition -- "nothing is versioned there" -- arriving as a pass.

    Reachable in the scenario the canary exists for: the game-root repo was created
    in RESPONSE to these losses, so an `rm -rf .git && git init` recovery would have
    turned it permanently green.
    """
    r = tmp_path / "unborn"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "registry.yaml").write_text("x" * 500, encoding="utf-8")
    assert _check(r, monkeypatch) == 2, (
        "an unborn repository must REFUSE (2), not pass -- 'could not look' is "
        "never 'nothing wrong'")


def test_a_staged_RENAME_is_not_reported_as_data_loss(repo, monkeypatch):
    """Porcelain writes a rename as `R  old -> new`: TWO paths in one field.

    Read whole, `p.exists()` is False and an ordinary `git mv` was reported as
    "DELETED (tracked, now missing)" -- firing the SessionStart banner "A TRACKED
    IRREPLACEABLE FILE HAS BEEN LOST". The docstring's own argument is that a check
    which cries wolf gets ignored, "which is how the last one failed".
    """
    _git(repo, "mv", "gone.md", "renamed.md")
    assert _check(repo, monkeypatch) == 0, (
        "a git mv is not a loss; the destination exists and is what must be checked")


def test_a_real_DELETION_is_still_a_loss(repo, monkeypatch):
    """The control for the test above. Without it, a fix that simply stopped
    reporting deletions would look identical to a fix that stopped reporting
    RENAMES as deletions."""
    (repo / "gone.md").unlink()
    assert _check(repo, monkeypatch) == 1


def test_a_canary_that_ITSELF_breaks_is_rc2_not_DATA_LOSS(repo, monkeypatch, capsys):
    """The SessionStart hook renders rc 1 as "A TRACKED IRREPLACEABLE FILE HAS BEEN
    LOST -- recover it before doing anything else". An uncaught exception also exits 1,
    so a canary that broke was reported as the worst verdict about the user's files.
    MEASURED by the 2026-09-05 delta review with a stub that raised PermissionError.
    Could-not-look is rc 2, the contract every gate in this repo uses."""
    def boom(repo_path, verbose):
        raise PermissionError("simulated: cannot read the repository")
    monkeypatch.setattr(x4canary, "check", boom)
    rc = _check(repo, monkeypatch)
    err = capsys.readouterr().err
    assert rc == 2, "an exception inside the canary must be a NON-ANSWER (2), got %r" % rc
    assert "REFUSING A VERDICT" in err and "PermissionError" in err, err
    assert "DATA LOSS" not in err, "a broken canary must never claim a loss"
