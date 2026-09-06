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


# --------------------------------------------------------------------------- #
# The POPULATION, which is where this gate was blind. The verdict always came
# from a committed blob; the candidate LIST did not, so a declaration that ships
# could go unexamined. MEASURED 2026-09-04.
# --------------------------------------------------------------------------- #

def _mkrepo(root, files):
    root.mkdir(parents=True, exist_ok=True)
    _run = lambda *a: subprocess.run(["git", "-C", str(root), *a],
                                     check=True, capture_output=True)
    _run("init", "-q")
    _run("config", "user.email", "t@t")
    _run("config", "user.name", "t")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        _run("add", rel)
    _run("commit", "-q", "-m", "base")
    return root


def test_a_COMMITTED_but_tree_absent_declaration_is_still_examined(tmp_path):
    """The tree-only population missed exactly what SHIPS.

    Deleting a probe's ui.xml from the working tree, leaving HEAD untouched, took
    the gate from `!! probeB` rc 1 to `OK -- 1 ... agree` rc 0 while the disagreeing
    blob still shipped. F87's own failure mode, inside the gate written to close it.
    """
    repo = _mkrepo(tmp_path / "r", {
        "mods/probeA/ui.xml": UI % "__x4live_dump",
        "mods/probeB/ui.xml": UI % "__OLD_STALE_NAME",
    })
    (repo / "mods" / "probeB" / "ui.xml").unlink()
    rels, _ok = ls.candidate_ui_rels(repo, repo / "mods")
    assert "mods/probeB/ui.xml" in rels, (
        "a declaration that is committed but tree-absent must still be examined")


def test_a_tree_present_but_UNCOMMITTED_declaration_is_still_examined(tmp_path):
    """The control for the test above, and a real regression I introduced fixing it.

    Sourcing the population from `git ls-files` alone drops a ui.xml that was never
    committed -- which is F87 in its purest form. Neither source alone is the
    population; the union is.
    """
    repo = _mkrepo(tmp_path / "r", {"mods/probeA/ui.xml": UI % "__x4live_dump"})
    d = repo / "mods" / "probeC"
    d.mkdir(parents=True)
    (d / "ui.xml").write_text(UI % "__NEVER_COMMITTED", encoding="utf-8")
    rels, _ok = ls.candidate_ui_rels(repo, repo / "mods")
    assert "mods/probeC/ui.xml" in rels, (
        "a tree-present, never-committed declaration must still be examined")


def test_EVERY_declaration_in_a_file_is_compared_not_just_the_first(tmp_path):
    """`MOD_RE.search` took match 1. With a stale name as the SECOND declaration the
    gate printed "OK -- 1 committed mod declaration(s) agree" rc 0 while the stale
    one shipped uncompared -- and the printed count claimed DECLARATIONS while
    counting FILES."""
    two = ('<content>'
           '<savedvariable name="__x4live_dump"/>'
           '<savedvariable name="__OLD_STALE_NAME"/>'
           '</content>')
    repo = _mkrepo(tmp_path / "r", {"mods/probeB/ui.xml": two})
    text = ls.committed(repo, "mods/probeB/ui.xml")
    found = [m.group(1) for m in ls.MOD_RE.finditer(text)]
    assert found == ["__x4live_dump", "__OLD_STALE_NAME"], found


# --- and the WORKING TREE must not choose WHICH REPO is judged -------------------
#
# `candidate_ui_rels` fixed the POPULATION; selection was the third place the same
# question is asked and it was still a pure GLOB:
#
#     shipped = cli_repo / "mods"
#     if find_mod_uis(shipped):        # tree only
#         mods = shipped
#     else:
#         mods = _env.mods_dir()       # a DIFFERENT repository
#
# So deleting or moving the shipped mods/ copy in the working tree silently switched
# the gate to $X4_MODS, and a committed, disagreeing shipped ui.xml got rc 0 because
# the gate went and judged something else entirely. F87's shape a third time: true of
# the verdict, false of the population, and false of the SUBJECT.

def test_a_tree_absent_but_COMMITTED_shipped_mod_is_still_the_SUBJECT(tmp_path):
    """The repo carries a shipped mods/ in HEAD; only the tree copy is gone.

    It must still be the thing under test -- not $X4_MODS, whatever that holds.
    """
    repo = _mkrepo(tmp_path / "shipped", {
        "mods/probeA/ui.xml": UI % "__x4live_dump",
    })
    (repo / "mods" / "probeA" / "ui.xml").unlink()
    assert not ls.find_mod_uis(repo / "mods"), (
        "precondition: the tree-only glob must now find nothing, or this proves nothing")
    rels, _ = ls.candidate_ui_rels(repo, repo / "mods")
    assert rels == ["mods/probeA/ui.xml"], (
        "selection consulted the tree only, so a repo that SHIPS a mod would be "
        "passed over in favour of $X4_MODS: %s" % rels)


def test_selection_still_falls_through_when_the_repo_SHIPS_no_mod(tmp_path):
    """The twin. A repo with no shipped mods/ in either git or the tree must still
    fall through to the configured directory -- that fallback is what the private
    dev workspace runs on, and breaking it would trade one false pass for another."""
    repo = _mkrepo(tmp_path / "nomods", {"README.md": "no mod here\n"})
    rels, _ = ls.candidate_ui_rels(repo, repo / "mods")
    assert rels == [], (
        "a repo shipping no mod must select nothing, so the caller falls through: %s"
        % rels)


def test_the_two_selection_sources_DISAGREE_only_in_the_direction_that_matters(tmp_path):
    """States the property directly, so the next reader does not have to infer it:
    git-or-tree is a SUPERSET of tree-alone. Selection may therefore only ever
    become MORE willing to judge the shipped repo, never less."""
    repo = _mkrepo(tmp_path / "both", {
        "mods/kept/ui.xml": UI % "__x4live_dump",
        "mods/gone/ui.xml": UI % "__x4live_dump",
    })
    (repo / "mods" / "gone" / "ui.xml").unlink()
    tree_only = {p.relative_to(repo).as_posix() for p in ls.find_mod_uis(repo / "mods")}
    both, _ = ls.candidate_ui_rels(repo, repo / "mods")
    assert tree_only <= set(both), (tree_only, both)
    assert "mods/gone/ui.xml" in both and "mods/gone/ui.xml" not in tree_only


def test_a_tree_absent_SHIPPED_mod_is_judged_not_passed_over_for_X4_MODS(
        tmp_path, monkeypatch, capsys):
    r"""THE SELECTION DEFECT, end to end through `main()`.

    The repo SHIPS `mods/probe/ui.xml` and its committed blob DISAGREES with the CLI.
    Only the working-tree copy is missing -- deleted, moved, or simply a checkout
    where it was never materialised. `$X4_MODS` points at a repo that AGREES.

    Pre-fix the selection was a pure glob over the tree, found nothing, and quietly
    judged `$X4_MODS` instead: rc 0, "committed mod declaration(s) agree", while the
    disagreeing blob is the one that ships. The gate looked, and looked at the wrong
    repository.

    The three tests above pin `candidate_ui_rels`, which was already correct -- they
    pass with or without this fix. This one is the twin that could go red, and it
    does: it is the only one that reaches the selection.
    """
    cli_repo = _repo(tmp_path / "toolkit")
    (cli_repo / "x4validate").mkdir(exist_ok=True)
    (cli_repo / "x4validate" / "_livedump.py").write_text(
        CLI % "__x4live_dump", encoding="utf-8")
    shipped = cli_repo / "mods" / "probe"
    shipped.mkdir(parents=True, exist_ok=True)
    (shipped / "ui.xml").write_text(UI % "__OLD_STALE_NAME", encoding="utf-8")
    _commit(cli_repo)
    (shipped / "ui.xml").unlink()          # committed, tree-absent

    other = _repo(tmp_path / "dev")        # what $X4_MODS points at: it AGREES
    d = other / "someprobe"
    d.mkdir(exist_ok=True)
    (d / "ui.xml").write_text(UI % "__x4live_dump", encoding="utf-8")
    _commit(other)

    monkeypatch.setattr(ls, "ROOT", cli_repo)
    monkeypatch.setattr(ls._env, "mods_dir", lambda: other)

    rc = ls.main()
    err = capsys.readouterr().err
    assert rc == 1, (
        "the gate passed a repo whose SHIPPED mod half disagrees, because the "
        "working tree was consulted to decide which repository to judge (rc=%s)" % rc)
    assert "__OLD_STALE_NAME" in err or "MISMATCH" in err, err
