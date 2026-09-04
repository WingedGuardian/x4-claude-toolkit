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
