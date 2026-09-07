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
import os
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


def test_a_canary_that_cannot_work_out_WHAT_to_check_is_rc2_not_DATA_LOSS(
        repo, monkeypatch, capsys):
    """`check()` was guarded; `repos()` was not, and it runs FIRST.

    The guard added for a broken `check()` sits inside the per-repository loop, so it
    cannot cover the call that decides what that loop iterates over. `repos()` resolves
    `_paths.game_root()` and calls `Path(...).resolve()` on `$X4_CANARY_REPOS`; the
    `except OSError` there does not catch `ValueError`, which is what a NUL byte in a
    path raises on Windows. An exception escaping `main()` exits the interpreter 1, and
    the SessionStart hook renders rc 1 as "A TRACKED IRREPLACEABLE FILE HAS BEEN LOST".

    So the worst possible verdict about the user's files was reachable from the canary
    merely failing to enumerate its own inputs. Could-not-look is rc 2 -- the contract
    the docstring states and every gate in this repo uses.
    """
    def boom():
        raise PermissionError("simulated: cannot resolve the configured roots")
    monkeypatch.setattr(x4canary, "repos", boom)
    rc = x4canary.main([])
    err = capsys.readouterr().err
    assert rc == 2, "a canary that cannot enumerate its repos must be rc 2, got %r" % rc
    assert "REFUSING A VERDICT" in err and "PermissionError" in err, err
    assert "DATA LOSS" not in err, "a broken canary must never claim a loss"


def test_a_canary_that_cannot_LOAD_is_rc2_not_DATA_LOSS(tmp_path):
    """The last unguarded path: import time.

    `repos()` and `check()` were guarded (bd0d714 and earlier), but everything above
    `main()` still ran unprotected -- and this script exits 1 to mean A TRACKED FILE HAS
    BEEN LOST, which the SessionStart hook renders as
    "*** A TRACKED IRREPLACEABLE FILE HAS BEEN LOST ***". An uncaught exception also
    exits 1, so a canary that merely failed to LOAD reported the worst possible verdict
    about the user's files.

    The old `except ImportError` was narrower than the ways an import can fail: a
    SyntaxError raised WHILE executing `_paths.py` is not an ImportError and propagated
    straight out.

    Run in a SEPARATE PROCESS with a poisoned package on the path -- an import that dies
    during collection aborts the whole pytest session, so this cannot be an in-process
    monkeypatch. That is also why it asserts the real exit code rather than a return
    value: the exit code is what the hook reads.
    """
    import subprocess
    import sys

    # THE POISON HAS TO BE ON THE PATH THE SCRIPT ITSELF CHOOSES. x4canary does
    # `sys.path.insert(0, _HERE.parent / "tools" / "x4validate")`, which wins over
    # PYTHONPATH -- so poisoning via PYTHONPATH loads the REAL _paths and the test
    # passes with or without the fix. MEASURED: that first version stayed green
    # against a mutant restoring the narrow `except ImportError`. Mirroring the
    # layout is the only way to reach the branch.
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "x4canary.py"
    script.write_bytes(Path(REPO / "scripts" / "x4canary.py").read_bytes())
    poison = tmp_path / "tools" / "x4validate" / "x4validate"
    poison.mkdir(parents=True)
    (poison / "__init__.py").write_text("", encoding="utf-8")
    # NOT an ImportError: a module that blows up mid-execution. The old
    # `except ImportError` let this straight out, and an uncaught exception exits 1.
    (poison / "_paths.py").write_text("raise RuntimeError('poisoned')\n", encoding="utf-8")

    env = dict(os.environ)
    env["X4_CANARY_REPOS"] = str(tmp_path / "nope")
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       env=env)
    assert r.returncode != 1, (
        "a canary that could not load claimed DATA LOSS (rc 1). It must degrade to "
        f"'could not check':\n{r.stdout}\n{r.stderr}")
    assert r.returncode == 2, (
        f"expected rc 2 (could not check), got {r.returncode}\n{r.stdout}\n{r.stderr}")
    assert "DATA LOSS" not in r.stderr and "HAS BEEN LOST" not in r.stdout, (
        "a broken canary must never claim a loss")


# --- the v3.1.0 release review, group A (all PRE-ARC) -----------------------------


def test_a_NON_ASCII_path_that_was_merely_EDITED_is_not_DATA_LOSS(repo, monkeypatch):
    """TWO layers, and fixing either alone left it broken.

    (1) `core.quotePath` defaults to TRUE, so git returns `"caf\303\251.txt"` and the
        old reader did `.strip('"')` -- the escaped form matches no file on disk.
    (2) Underneath that, `_git` used `text=True` with no `encoding=`, so git's UTF-8
        was decoded with the LOCALE codepage (cp1252 here) and the path came back as
        mojibake even once unescaped. MEASURED by codepoints: 0xc3 0xa9 where the
        file on disk has 0xe9 -- found AFTER the first fix had been declared done.

    Either way `p.exists()` was False and an ordinary edit fired "*** DATA LOSS ***"
    with rc 1, which is what the SessionStart banner reads. A check that cries wolf
    gets ignored, which this tool's own docstring calls how the last one failed.
    """
    name = "caf" + chr(233) + ".md"
    (repo / name).write_text("y" * 400, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "add a non-ascii path")
    (repo / name).write_text("y" * 401, encoding="utf-8")     # an EDIT, not a loss
    assert _check(repo, monkeypatch) == 0


def test_a_NON_ASCII_path_that_really_WAS_emptied_is_still_a_loss(repo, monkeypatch):
    """The twin. The fix must not make non-ASCII paths invisible instead of
    mis-read -- that would be the same hole with better manners."""
    name = "caf" + chr(233) + ".md"
    (repo / name).write_text("y" * 400, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "add a non-ascii path")
    (repo / name).write_bytes(b"")
    assert _check(repo, monkeypatch) == 1


def test_unquote_decodes_what_git_still_escapes():
    """`core.quotePath=false` removes the octal class; git STILL quotes a path
    containing a quote, a backslash or a control character."""
    BS, DQ = chr(92), chr(34)
    assert x4canary._unquote("plain.md") == "plain.md"
    assert x4canary._unquote(DQ + "caf" + BS + "303" + BS + "251.md" + DQ) \
        == "caf" + chr(233) + ".md"
    assert x4canary._unquote(DQ + "a" + BS + DQ + "b.md" + DQ) == "a" + DQ + "b.md"
    assert x4canary._unquote(DQ + "a" + BS + "nb.md" + DQ) == "a" + chr(10) + "b.md"


def test_a_file_RENAMED_and_then_EMPTIED_is_a_loss(repo, monkeypatch):
    """`RM` -- renamed in the index, modified in the worktree -- was not in the
    four-code allow-list (M, MM, AM, T), so it went to drift UNSIZED and a bad `mv`
    reported as a benign change. That is precisely the shape this tool exists for.
    """
    _git(repo, "mv", "big.md", "renamed.md")
    (repo / "renamed.md").write_bytes(b"")
    assert _check(repo, monkeypatch) == 1


def test_a_file_RENAMED_and_merely_EDITED_is_NOT_a_loss(repo, monkeypatch):
    """The twin: widening the size check must not turn every rename into an alarm."""
    _git(repo, "mv", "big.md", "renamed.md")
    (repo / "renamed.md").write_text("x" * 10001, encoding="utf-8")
    assert _check(repo, monkeypatch) == 0


def test_a_CONFIRMED_loss_outranks_an_UNREADABLE_repository(repo, tmp_path,
                                                            monkeypatch, capsys):
    """One unreadable repo used to DOWNGRADE a real, already-detected loss in a
    DIFFERENT repo from rc 1 to rc 2. rc is what the SessionStart hook reads, so the
    "A TRACKED IRREPLACEABLE FILE HAS BEEN LOST" banner never fired: the loss was
    printed and nothing acted on it. "Could not look" must not outrank "I looked and
    it is gone"."""
    (repo / "big.md").write_bytes(b"")                       # a real loss
    notrepo = tmp_path / "notrepo"
    notrepo.mkdir()                                          # not a git repository
    monkeypatch.setenv("X4_CANARY_REPOS", os.pathsep.join([str(repo), str(notrepo)]))
    monkeypatch.setattr(x4canary, "_paths", None)
    rc = x4canary.main([])
    err = capsys.readouterr().err
    assert rc == 1, "a found loss must not be downgraded to could-not-check"
    assert "could not be checked" in err, "and the unreadable repo must still be named"


def test_an_UNREADABLE_repo_with_NO_loss_is_still_rc2(repo, tmp_path, monkeypatch):
    """The twin. Without it the change above could have retired rc 2 entirely."""
    notrepo = tmp_path / "notrepo"
    notrepo.mkdir()
    monkeypatch.setenv("X4_CANARY_REPOS", os.pathsep.join([str(repo), str(notrepo)]))
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 2


def test_a_root_that_does_NOT_RESOLVE_is_NAMED_beside_the_count(repo, monkeypatch,
                                                                capsys):
    """An unresolved root used to vanish from `repos()`, and the run then printed
    "1 repository checked, no tracked file lost" -- true, and silent about the tree
    this tool was built to watch. Not an error (an unconfigured root is a real setup
    state, and rc 2 would fire on every cold clone), but the count in the verdict has
    to be a denominator the reader can check."""
    class _Half:
        @staticmethod
        def game_root():
            return None
        @staticmethod
        def mods():
            return None
    monkeypatch.setenv("X4_CANARY_REPOS", str(repo))
    monkeypatch.setattr(x4canary, "_paths", _Half)
    assert x4canary.main([]) == 0
    out = capsys.readouterr().out
    assert "NOT CHECKED" in out and "game_root" in out and "mods" in out


# --- the loss report is a BOUNDED channel, and its directive must survive ------
#
# MEASURED 2026-09-07, CC 2.1.263: Claude Code files hook output above 10,000
# CHARACTERS and shows the model a ~2 KB preview -- silently, exit code
# unchanged. session-canary.sh pipes this tool's whole output into that channel,
# so the loss report has a hard ceiling it never knew about.
#
# The failure is INVERTED AGAINST SEVERITY: one lost file sails under the cap,
# and a directory-level loss -- the case that actually matters -- is the one that
# gets filed. Worse, the preview keeps the HEAD, so what survives is the
# inventory and what is cut is "do not re-run whatever wrote it", the single
# line that stops the recoverable state being destroyed.
#
# Upper bound on the old behaviour: the list crossed 10,000 characters at about
# 81 files against the 473 tracked across the two watched repos. "About" and
# "upper bound" because a renamed-and-emptied file now carries the wider
# "new.md (was old.md)" form, which crosses sooner.
def _lose_many(repo: Path, n: int) -> None:
    """Commit n small tracked files, then empty every one of them."""
    names = ["f%03d.md" % i for i in range(n)]
    for nm in names:
        (repo / nm).write_text("y" * 400, encoding="utf-8")
    _git(repo, "add", *names)
    _git(repo, "commit", "-q", "-m", "many")
    for nm in names:
        (repo / nm).write_text("", encoding="utf-8")


def test_the_recovery_directive_PRECEDES_the_file_list(repo, monkeypatch, capsys):
    """The preview keeps the HEAD, so the directive must be in the head.

    Printed after the list, it is the first thing dropped -- and it is the only
    actionable sentence in the report.
    """
    _lose_many(repo, 12)
    assert _check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    directive = err.index("do not re-run whatever wrote it")
    first_item = err.index("f000.md")
    assert directive < first_item, (
        "the recovery directive is printed AFTER the file list, so truncation "
        "keeps the inventory and drops the instruction")


def test_a_large_loss_list_is_CAPPED_and_says_so(repo, monkeypatch, capsys):
    """A narrowing step must announce itself (CLAUDE.md, and _scan.count_line).

    250, not 120: at 120 the fixture's short names total ~5,600 characters, so the
    length assertion below COULD NOT FAIL and was decoration. Both assertions have
    to be reachable or the test only pins the half someone happened to break.
    """
    _lose_many(repo, 250)
    assert _check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    assert len(err) <= 10000, (
        "the loss report is %d characters -- above the 10,000-char cap, so "
        "Claude Code files it and the session sees only a preview" % len(err))
    assert "NOT LISTED" in err, "the list was capped with no disclosure"
    # NOT `"250" in err` -- that is satisfied by the "*** DATA LOSS in 250
    # tracked file(s) ***" HEADER, so mutating _emit's total to 999999 left it
    # green. The claim under test is that the DISCLOSURE states the true total.
    assert "showing 40 of 250" in err, err[:400]


def test_a_SMALL_loss_list_is_listed_in_full(repo, monkeypatch, capsys):
    """The twin. A cap that fires when it should not is the other failure."""
    _lose_many(repo, 3)
    assert _check(repo, monkeypatch) == 1
    err = capsys.readouterr().err
    for nm in ("f000.md", "f001.md", "f002.md"):
        assert nm in err, "%s was dropped from a list well under the cap" % nm
    assert "NOT LISTED" not in err, "the cap fired on a 3-item list"


def test_the_NOT_CHECKED_note_reaches_EVERY_exit_path(repo, tmp_path, monkeypatch, capsys):
    """It lived in the rc-0 branch alone, and rc 0 is the branch `session-canary.sh`
    discards (`0) : ;;  # stay quiet`) — so the disclosure added THIS RELEASE to stop
    the run being "silent about the tree this tool was built to watch" reached nobody.

    A channel with no reachable reader is decoration. Checked on all three codes.
    """
    class _Half:
        @staticmethod
        def game_root():
            return None          # unresolved: the note must appear
        @staticmethod
        def mods():
            return None
    monkeypatch.setattr(x4canary, "_paths", _Half)

    # rc 0 — clean
    monkeypatch.setenv("X4_CANARY_REPOS", str(repo))
    assert x4canary.main([]) == 0
    assert "NOT CHECKED" in capsys.readouterr().out

    # rc 1 — a real loss
    (repo / "big.md").write_bytes(b"")
    assert x4canary.main([]) == 1
    assert "NOT CHECKED" in capsys.readouterr().err

    # rc 2 — could not check
    (repo / "big.md").write_text("x" * 10000, encoding="utf-8")
    notrepo = tmp_path / "notrepo2"
    notrepo.mkdir()
    monkeypatch.setenv("X4_CANARY_REPOS", os.pathsep.join([str(repo), str(notrepo)]))
    assert x4canary.main([]) == 2
    assert "NOT CHECKED" in capsys.readouterr().err


def test_a_FULLY_RESOLVED_run_stays_quiet_on_every_path(repo, monkeypatch, capsys):
    """The twin. Without it the change above could print the note unconditionally,
    which is noise at session start on every clean machine."""
    monkeypatch.setenv("X4_CANARY_REPOS", str(repo))
    monkeypatch.setattr(x4canary, "_paths", None)
    assert x4canary.main([]) == 0
    out = capsys.readouterr()
    assert "NOT CHECKED" not in out.out and "NOT CHECKED" not in out.err


def test_an_UNSIZEABLE_file_does_not_discard_the_losses_already_found(repo, monkeypatch,
                                                                      capsys):
    """`check()` returned a FRESH list on a sizing error, so ONE file that cannot be
    sized threw away every confirmed loss in that repository — and `main()` then filed
    the survivors as "reasons", never as losses.

    MEASURED by the reviewer on three genuine losses: control rc 1 naming all three;
    with one file un-sizeable, rc 2 and 0 of 3 printed. The arc added "A CONFIRMED
    LOSS OUTRANKS AN UNREADABLE REPOSITORY" and implemented it ACROSS repos only —
    within a repo a confirmed loss still lost to an unreadable neighbour, and rc is
    what session-canary.sh reads. This is the canary's single job.
    """
    (repo / "big.md").write_bytes(b"")          # a real, confirmed loss
    (repo / "gone.md").write_text("z" * 400, encoding="utf-8")

    real = x4canary._git

    def flaky(r, *args):
        if args and args[0] == "cat-file" and args[-1].endswith("gone.md"):
            return 0, "not-a-number"            # unsizeable: the reason, not a verdict
        return real(r, *args)

    monkeypatch.setattr(x4canary, "_git", flaky)
    rc = _check(repo, monkeypatch)
    err = capsys.readouterr().err
    assert rc == 1, "a confirmed loss must outrank an unreadable file IN THE SAME repo"
    assert "big.md" in err, "the loss found before the unreadable file must survive"
    assert "cannot size" in err, "and the unreadable file must still be named"


def test_a_rename_with_BOTH_paths_quoted_is_not_a_false_DATA_LOSS(repo, monkeypatch):
    """`_unquote` was applied to the WHOLE field before the ` -> ` split, and its
    outer-quote test matches `"old" -> "new"` — so it stripped the outer pair and
    decoded ACROSS the separator, yielding two paths naming no file. `p.exists()`
    False, DELETED, rc 1, SessionStart banner. One-sided quoting parsed correctly,
    which is why it survived review.

    Driven through the real parse by feeding porcelain directly, because a filename
    containing a quote cannot be created on Windows.
    """
    BS, DQ = chr(92), chr(34)
    line = 'R  ' + DQ + 'we' + BS + DQ + 'ird.yaml' + DQ + ' -> ' + DQ + 'al' + BS + DQ + 'so.yaml' + DQ
    code, rel = line[:2], line[3:].strip()
    assert code and code[0] in ("R", "C") and " -> " in rel
    was_rel, new_rel = (x4canary._unquote(part.strip())
                        for part in rel.split(" -> ", 1))
    assert was_rel == 'we' + DQ + 'ird.yaml', was_rel
    assert new_rel == 'al' + DQ + 'so.yaml', new_rel


def test_a_ONE_SIDED_quoted_rename_still_parses(repo):
    """The twin: the form that already worked must keep working."""
    DQ = chr(34)
    rel = 'plain.md -> ' + DQ + 'quoted name.md' + DQ
    was_rel, new_rel = (x4canary._unquote(part.strip())
                        for part in rel.split(" -> ", 1))
    assert was_rel == "plain.md" and new_rel == "quoted name.md"
