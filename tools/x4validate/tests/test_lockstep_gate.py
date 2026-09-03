"""`gates/lockstep.py` — the pair must agree in the blobs that SHIP.

The decisive test here is `test_F87_REPRODUCED`: a working tree where both halves agree
perfectly, over a commit where they do not. That is the state two sessions verified and
passed on 2026-08-28, and any gate that reads the working tree passes it too.

Every fixture builds real git repos, because the whole contract is "committed blob, not
file on disk" and a fake that stubs `git show` would test the stub.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

from conftest import import_gate

ls = import_gate("lockstep")

UI = ('<?xml version="1.0" encoding="utf-8"?>\n'
      '<addon>\n    <savedvariable name="%s" storage="userdata"/>\n</addon>\n')
CLI = 'DEFAULT_VAR = "%s"\n'


def _repo(path):
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=path, capture_output=True, check=True)
    return path


def _commit(repo, msg="c"):
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo,
                   capture_output=True, check=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two repos, wired into the gate. Returns a helper that sets each half's
    COMMITTED and WORKING-TREE value independently -- which is the only way to
    express the defect."""
    cli_repo = _repo(tmp_path / "toolkit")
    mod_repo = _repo(tmp_path / "dev")

    def setup(mod_committed, cli_committed, mod_tree=None, cli_tree=None):
        (cli_repo / "x4validate").mkdir(exist_ok=True)
        (cli_repo / "x4validate" / "_livedump.py").write_text(
            CLI % cli_committed, encoding="utf-8")
        _commit(cli_repo)
        d = mod_repo / "someprobe"
        d.mkdir(exist_ok=True)
        (d / "ui.xml").write_text(UI % mod_committed, encoding="utf-8")
        _commit(mod_repo)
        # now diverge the WORKING TREES, leaving the commits alone
        if mod_tree is not None:
            (d / "ui.xml").write_text(UI % mod_tree, encoding="utf-8")
        if cli_tree is not None:
            (cli_repo / "x4validate" / "_livedump.py").write_text(
                CLI % cli_tree, encoding="utf-8")

    monkeypatch.setattr(ls, "ROOT", cli_repo)
    monkeypatch.setattr(ls._env, "mods_dir", lambda: mod_repo)
    return setup


def test_F87_REPRODUCED_working_tree_agrees_while_the_COMMIT_does_not(world, capsys):
    """★ THE TEST THIS GATE EXISTS FOR.

    Both halves are correct on disk and would pass any amount of eyeballing. The
    commit -- the artifact that ships -- carries the old name on one side. This is
    verbatim the 2026-08-28 state, which two sessions checked and both passed.
    """
    world(mod_committed="__old_name", cli_committed="__x4live_dump",
          mod_tree="__x4live_dump", cli_tree="__x4live_dump")
    assert ls.main() == 1, (
        "the gate passed a commit whose two halves disagree -- it is reading the "
        "working tree, which is the exact defect F87 records")
    err = capsys.readouterr().err
    assert "MISMATCH" in err


def test_it_passes_when_the_COMMITS_agree(world):
    """The twin. Without it the gate could fail everything and the test above would
    still pass."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump")
    assert ls.main() == 0


def test_a_working_tree_MISMATCH_over_agreeing_commits_does_not_fail(world):
    """The mirror image, and it pins WHICH view is authoritative. Mid-rename the tree
    disagrees with itself constantly; that is not a shippable defect and must not be
    reported as one, or the gate becomes noise and gets ignored."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump",
          mod_tree="__half_renamed")
    assert ls.main() == 0


def test_an_UNCOMMITTED_mod_half_is_a_FAILURE_not_a_skip(world, tmp_path, capsys):
    """Present in the tree, absent from what ships -- F87's state in its purest form.
    Skipping here would report 'nothing to check' about the very thing that broke."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump")
    d = tmp_path / "dev" / "secondprobe"
    d.mkdir()
    (d / "ui.xml").write_text(UI % "__x4live_dump", encoding="utf-8")   # never committed
    assert ls.main() == 1
    assert "not committed" in capsys.readouterr().err


def test_it_REFUSES_rather_than_passing_when_the_CLI_half_is_unreadable(world):
    """exit 2, never 0. A gate that cannot tell 'they agree' from 'I did not look' is
    worse than no gate -- and 0 is the answer that gets believed."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump")
    saved = ls.CLI_PATHS
    try:
        # CLI_PATHS is a tuple of repo-relative CANDIDATES now, tried in order, so the
        # gate works both where tools/x4validate is the git root and where it is a
        # subdirectory. Point every candidate at a file that does not exist.
        ls.CLI_PATHS = ("x4validate/__no_such_file__.py",)
        with pytest.raises(SystemExit) as e:
            ls.main()
        assert e.value.code == 2
    finally:
        ls.CLI_PATHS = saved


def test_it_REFUSES_when_the_pattern_matches_nothing(world, tmp_path):
    """A regex that finds nothing is a NON-ANSWER, not agreement. If DEFAULT_VAR is
    ever renamed or restyled, this must refuse rather than quietly compare nothing."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump")
    repo = tmp_path / "toolkit"
    (repo / "x4validate" / "_livedump.py").write_text(
        "SOMETHING_ELSE = 'x'\n", encoding="utf-8")
    _commit(repo, "restyle")
    with pytest.raises(SystemExit) as e:
        ls.main()
    assert e.value.code == 2


def test_it_reports_EVERY_declaring_mod_not_just_the_first(world, tmp_path):
    """Two probes each declaring a variable is a real possibility, and resolving to
    whichever sorted first would hide a mismatch in the other.

    ⚠ The name must sort AFTER the agreeing probe ("someprobe"), or this test passes
    for the wrong reason. The first version used "otherprobe" -- o < s -- so a mutant
    that compared only `uis[:1]` still picked the MISMATCHING mod and the test stayed
    green. Caught by that mutant surviving; the discriminating case is the one where
    truncating the list would leave only the agreeing half."""
    world(mod_committed="__x4live_dump", cli_committed="__x4live_dump")
    d = tmp_path / "dev" / "zz_last_probe"
    d.mkdir()
    (d / "ui.xml").write_text(UI % "__a_different_name", encoding="utf-8")
    _commit(tmp_path / "dev", "second probe")
    assert ls.main() == 1, "the second declaring mod was not compared"


def test_the_real_repos_are_in_lockstep():
    """End to end against the actual checkouts -- not a fixture. This is the one that
    would have caught F87 on the day.

    ⚠ On a machine with no mod tree the gate REFUSES with exit 2, which is correct
    behaviour and must read as "not applicable here", never as a failure. A fresh
    clone has no dev tree, and a suite that goes red on a new user's first run is the
    F63 defect this project has already shipped once. Caught by
    scripts/verify-cold.sh, which is the only run where that is true.
    """
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = ls.main()
    except SystemExit as exc:
        if exc.code == 2:
            # The gate's OWN reason, not a guess at it. This skip used to assert
            # "no mod tree configured" unconditionally -- and MEASURED 2026-09-02 the
            # real reason was that CLI_PATH named a path that does not exist in this
            # repository, so the gate refused on EVERY run, everywhere, while the skip
            # line explained it away as an environmental non-applicability. A permanent
            # skip carrying a reassuring and false explanation is worse than a failure.
            pytest.skip("the gate refused (rc 2), which is correct where it cannot "
                        "look. Its reason: " + buf.getvalue().strip().splitlines()[0]
                        if buf.getvalue().strip() else "the gate refused (rc 2)")
        raise
    assert rc == 0, buf.getvalue()[-500:]


def test_the_gate_can_actually_LOOK_in_this_repository():
    """The refusal above is correct behaviour and must not become the normal outcome.

    MEASURED 2026-09-02: `gates/lockstep.py` refused on every run in this repo because
    `CLI_PATH` was a path relative to a git root where `tools/x4validate` IS the root --
    true in the private dev workspace, never here. `git log --follow` shows the value had
    never changed, so the control written for F87 had not once looked at anything in the
    tree that ships, and the skip above recorded that as "not applicable".

    So: in a git checkout that carries both halves, the gate must REACH a verdict.
    """
    import contextlib
    import io
    import subprocess

    repo = pathlib.Path(__file__).resolve().parents[3]
    if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(repo),
                      capture_output=True).returncode != 0:
        pytest.skip("not a git checkout, so there are no committed blobs to compare")
    if not list((repo / "mods").glob("*/ui.xml")):
        pytest.skip("this checkout ships no mod ui.xml to compare against")

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = ls.main()
    except SystemExit as exc:
        raise AssertionError(
            "the gate refused (rc %s) in a checkout that carries BOTH halves, so it "
            "reached no verdict:%s%s" % (exc.code, chr(10), buf.getvalue()[-600:]))
    assert rc == 0, buf.getvalue()[-600:]
    assert "ui.xml" in buf.getvalue(), (
        "the gate returned 0 without naming a mod declaration -- it examined nothing")
