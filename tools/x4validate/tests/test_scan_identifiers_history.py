"""`git push` publishes COMMITS, not the working tree.

Every identifier check in this repo scans the TREE -- `scan-identifiers.py` in its
default mode, and the static check inside `scripts/test-hooks.sh`. So all of them
return CLEAN on precisely the case that matters: an identifier that was committed,
noticed, and removed. It is gone from the tree and still in the objects, and a push
publishes it.

MEASURED 2026-09-07 and the trigger was real: a concurrent session hardcoded a
profile path into a tracked test file, caught it, and replaced it. Only a history
scan could establish whether it had reached a commit (it had not -- zero occurrences
across all 274 commits). "Clean" and "assumed clean" are different states.

⚠ Two TREE-scanning instruments disagreeing about this is EXPECTED and is not a bug
in either: they run at different moments and the tree changes between them. Two
moments, not two populations.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "scan-identifiers.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _run(repo: Path, *args: str):
    """Run a COPY of the script inside the sandbox repo.

    `_anchor_to_repo_root()` chdirs to the script's own parent's parent, by design
    (running it from `scripts/` once produced a false failure). So `cwd=` alone does
    not point it at another repo -- it lands back on the real one and the sandbox
    SHAs resolve to nothing. Same pattern as `test_generate_baseline_refusals.py`."""
    # NO `EXTRA_FORBIDDEN`. Forcing the committer's name into the ban list makes the
    # TREE scan flag LICENSE, where that name sits as deliberate attribution -- the
    # allow-list working correctly against a test fighting it. The detector this
    # fixture relies on is the ACCOUNT PATTERN, which needs no token list.
    return subprocess.run([sys.executable, str(repo / "scripts" / SCRIPT.name), *args],
                          cwd=str(repo), capture_output=True, text=True)


@pytest.fixture()
def planted(tmp_path):
    """A repo where an identifier was COMMITTED and then removed from the tree."""
    if not SCRIPT.is_file():
        pytest.skip("no scripts/scan-identifiers.py (dev-only script) -- not checked")
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", ".")
    _git(r, "config", "user.name", "Testy McTest")
    _git(r, "config", "user.email", "testy@example.invalid")
    # The copyright holder is deliberately NOT the committer. If they match, the
    # committer name is "deliberate attribution" and the derived ban list comes
    # back EMPTY -- at which point the scan REFUSES (rc 2) rather than reporting
    # a vacuous pass, correctly, and the fixture tests the refusal instead of
    # what it meant to test. Detection here rests on the ACCOUNT PATTERN, which
    # needs no token list at all.
    (r / "LICENSE").write_text("Copyright (c) 2026 The Project Authors" + chr(10), encoding="utf-8")
    (r / "a.txt").write_text("clean\n", encoding="utf-8")
    _git(r, "add", "LICENSE", "a.txt")
    _git(r, "commit", "-qm", "base")
    base = _git(r, "rev-parse", "HEAD").stdout.strip()
    # ASSEMBLED AT RUNTIME, and that is not squeamishness. The planted value has to
    # be one the tool DETECTS -- so not a PLACEHOLDER_IDS entry and not a
    # PLACEHOLDER_USERS name -- which means a literal here would make THIS FILE a
    # hit and turn the repo-wide tree scan red on the test that tests the scanner.
    # Split so no single LINE carries either pattern, while the sandbox COMMIT does.
    # (Found by exactly that: the tree scan went red twice, first on the profile id
    # and then on the user path, which is the scanner working correctly on a
    # population I had widened by writing the test.)
    _user = "Testy"
    _pid = "7418" + "5296"
    _leak = ("PROF = 'C:/Users/" + _user + "/Documents/Egosoft/X4/" + _pid + "'")
    (r / "a.txt").write_text(_leak + chr(10), encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "oops")
    (r / "a.txt").write_text("PROF = os.environ['X4_PROFILE']\n", encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "fixed it")
    clean_from = _git(r, "rev-parse", "HEAD").stdout.strip()
    (r / "b.txt").write_text("also clean\n", encoding="utf-8")
    _git(r, "add", "b.txt")
    _git(r, "commit", "-qm", "an ordinary clean commit")

    # The script copy must be IGNORED, not merely untracked: `population()` includes
    # untracked files, and the script's own docstring carries the account PATTERNS it
    # detects -- so an untracked copy makes the TREE scan flag the scanner. (Found by
    # this test going red for that reason, which is the scanner working correctly on
    # a population I had accidentally widened.)
    (r / ".gitignore").write_text("scripts/\n", encoding="utf-8")
    _git(r, "add", ".gitignore")
    _git(r, "commit", "-qm", "ignore the harness copy")
    import shutil
    (r / "scripts").mkdir()
    shutil.copy2(SCRIPT, r / "scripts" / SCRIPT.name)
    return r, base, clean_from


def test_the_TREE_scan_is_CLEAN_on_a_committed_then_removed_identifier(planted):
    """Not a defect in the tree scan -- it answers the question it was asked. This
    test exists to pin WHY the history mode is needed, so nobody deletes it as
    redundant."""
    r, _base, _clean = planted
    assert _run(r).returncode == 0


def test_the_HISTORY_scan_CATCHES_it(planted):
    r, base, clean_from = planted
    got = _run(r, "--history", base + "..HEAD")
    assert got.returncode == 1, got.stdout + got.stderr
    assert "a push publishes it" in got.stdout


def test_the_history_scan_does_NOT_fire_on_the_commit_that_REMOVED_it(planted):
    """Only ADDED lines count. A commit that removes an identifier is the fix, and
    flagging it would make the remedy trip the check -- so the range starting AFTER
    the offending commit must be clean even though the removal is inside it."""
    r, _base, _clean = planted
    offending = _git(r, "rev-parse", "HEAD~1").stdout.strip()
    got = _run(r, "--history", offending + "..HEAD")
    assert got.returncode == 0, got.stdout + got.stderr


def test_a_CLEAN_history_passes(planted):
    """The twin: without it every assertion above holds on a mode that always fails."""
    r, _base, clean_from = planted
    # `clean_from..HEAD` spans only commits AFTER the identifier was removed, so it
    # is a genuinely clean non-empty range. My first draft used `base..base`, which
    # is EMPTY -- `base` is the root commit -- so it tested the refusal path while
    # claiming to test the clean one.
    got = _run(r, "--history", clean_from + "..HEAD")
    assert got.returncode == 0, got.stdout + got.stderr
    assert "clean" in got.stdout


def test_an_EMPTY_range_REFUSES_rather_than_reporting_clean(planted):
    """Zero commits scanned is a non-answer. The file's other refusals already say
    so for a depth-1 checkout and an empty token list."""
    r, base, clean_from = planted
    got = _run(r, "--history", base + ".." + base)
    assert got.returncode == 2
    assert "prove nothing" in got.stdout


def test_the_REAL_repo_history_is_clean_across_the_push_range():
    """The live check, and the reason this mode exists. Skips where there is no tag
    to scan from rather than passing over nothing."""
    if not SCRIPT.is_file():
        pytest.skip("no scripts/scan-identifiers.py (dev-only script) -- not checked")
    if _git(REPO, "rev-parse", "-q", "--verify", "v3.0.0^{}").returncode != 0:
        pytest.skip("tag v3.0.0 not present in this clone -- not checked")
    got = subprocess.run([sys.executable, str(SCRIPT), "--history", "v3.0.0..HEAD"],
                         cwd=str(REPO), capture_output=True, text=True, timeout=900)
    assert got.returncode == 0, got.stdout + got.stderr


def test_an_identifier_in_a_COMMIT_MESSAGE_is_caught(planted):
    """`git show --format=` SUPPRESSES the message, so the first version of this
    mode read only the diff -- in a check whose premise is that a push publishes
    COMMITS. A message is part of the commit.

    Not hypothetical: the round-2 reviewer measured exactly one commit-message hit
    in this repository's real history, carrying an identity token that appears in
    NO tracked file. Tree mode was correctly clean about it; history mode returned
    rc 0 over the one case it exists for.
    """
    r, _base, clean_from = planted
    _user = "Testy"
    _pid = "7418" + "5296"
    (r / "c.txt").write_text("harmless" + chr(10), encoding="utf-8")
    _git(r, "add", "c.txt")
    # the DIFF is clean; only the MESSAGE carries it
    _git(r, "commit", "-qm",
         "fix the path " + chr(39) + "C:/Users/" + _user + "/Documents/Egosoft/X4/"
         + _pid + chr(39))
    got = _run(r, "--history", clean_from + "..HEAD")
    assert got.returncode == 1, got.stdout + got.stderr
    assert "a push publishes it" in got.stdout


def test_the_summary_line_NAMES_the_channels_it_covered(planted):
    """A count without a denominator is what let the message channel go missing
    unnoticed: "63 commit(s) scanned" reads complete whatever it read."""
    r, _base, clean_from = planted
    got = _run(r, "--history", clean_from + "..HEAD")
    assert "commit MESSAGE" in got.stdout and "diff lines" in got.stdout
