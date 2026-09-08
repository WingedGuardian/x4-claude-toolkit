"""Installing OVER an existing install -- BOTH installers, the path nothing drove.

The installer had two static test files and neither executes it. That is why a
guaranteed runtime failure was invisible: `install.sh` cannot install over a
toolkit whose config the toolkit own lock has made read-only, and the README
(since aa1c67d) tells users to run that lock.

REPRODUCED 2026-09-07 against a real install, then reduced to the fixture below:

    cp: cannot create regular file '.../.claude/./x4-paths.env': Permission denied

and because the script runs under `set -euo pipefail` and copies SIXTEEN items in
a loop, it died on item 1 leaving `.claude` half-populated, an orphaned
`x4-paths.env.bak-<stamp>` beside it, and nothing printed about what had landed.
`tools` is item 2 -- on a developer machine that is a live tree.

Two properties are pinned here and they are different questions:
  * the install SUCCEEDS over a locked config (it must not need the lock lifted);
  * the config is never touched (byte-identical afterwards, no backup left).

The second is the one that matters. An install that succeeded by overwriting the
users paths would pass the first and be worse than the failure.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import stat
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
INSTALL_SH = ROOT / "install.sh"
INSTALL_PS1 = ROOT / "install.ps1"
SENTINEL = "SENTINEL_DO_NOT_CLOBBER=1"


def _bash() -> str | None:
    """Git Bash via the repo own resolver, never a bare `bash`.

    On Windows with WSL enabled, `shutil.which("bash")` returns the System32 stub
    and the test fails with a WSL relay error -- a broken test, not a broken
    installer. `scripts/gitbash.py` exists for this and has its own suite.
    """
    src = ROOT / "scripts" / "gitbash.py"
    if not src.is_file():
        return None
    spec = importlib.util.spec_from_file_location("gitbash_for_install", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_bash()


#: Locations this suite must never be pointed at, however it is edited later.
#:
#: The installer WRITES, and it once wrote 1,642 files into a real install. A test
#: that names a real destination is one typo away from an upgrade nobody asked
#: for, and the damage would be indistinguishable from a deliberate install.
#:
#: Two checks rather than one, because they fail differently: CONTAINMENT is the
#: real guarantee (everything under pytest tmp_path), and the NAME blocklist
#: catches the case where containment is somehow satisfied by a path that is
#: still a live tree -- a symlinked temp dir, a reconfigured TMPDIR.
_FORBIDDEN_FRAGMENTS = ("x4 foundations", "desktop/modding", "egosoft",
                        "program files", "steamapps")


def _refuse_unless_sandboxed(tmp_path: pathlib.Path, *paths: pathlib.Path) -> None:
    """Every path the installer may WRITE must be inside the pytest sandbox.

    ⚠ CLAUDE_CONFIG_DIR and HOME are checked too, and they were the hole: the
    global arm writes to `<claude-dir>/skills`, `<claude-dir>/agents` and
    `settings.json`, which are NOT among the six path flags. Only one test drove
    that arm and only with --dry-run, so the first non-dry-run global case anyone
    added would have written into the developer's real ~/.claude. Guarding the
    flags and not the destination is the same shape as a precheck that covers one
    file of twenty-six.
    """
    root = tmp_path.resolve()
    # The paths PASSED here, not the ambient environment: the caller overrides
    # CLAUDE_CONFIG_DIR/HOME for the child, so validating os.environ would refuse
    # on the developer's real home while the child never sees it. Check what the
    # child will actually get.
    for p in paths:
        rp = pathlib.Path(p).resolve()
        if root not in rp.parents and rp != root:
            raise AssertionError(
                "REFUSING to run the installer: %s is not under the pytest "
                "sandbox %s. This suite writes, and it must never be aimed at a "
                "real tree." % (rp, root))
        s = rp.as_posix().lower()
        for bad in _FORBIDDEN_FRAGMENTS:
            if bad in s:
                raise AssertionError(
                    "REFUSING to run the installer: %s looks like a live "
                    "installation (matched %r), even though it is under the "
                    "sandbox root." % (rp, bad))

def _fresh(tmp_path: pathlib.Path) -> pathlib.Path:
    """An empty destination plus the directories the installer is pointed at."""
    dest = tmp_path / "toolkit"
    dest.mkdir()
    for d in ("game", "profile", "mods"):
        (tmp_path / d).mkdir()
    return dest

def _install(installer: str, tmp_path: pathlib.Path, dest: pathlib.Path, *extra: str,
             method: str = "separate", from_dest: bool = False,
             source: pathlib.Path | None = None):
    """Run ONE of the two installers with identical intent.

    Parameterised rather than duplicated, because the point is that both reach the
    same VERDICT. `test_installers_agree.py` compares the two files as TEXT, so it
    would pass on two installers that agree about item lists and disagree about
    whether they clean up -- which is exactly what was true here: install.ps1 had
    `finally` where install.sh had none, and both still failed this path.
    """
    fake_home = tmp_path / "fake-claude-home"
    _refuse_unless_sandboxed(tmp_path, dest, tmp_path / "game",
                             tmp_path / "profile", tmp_path / "mods", fake_home)
    common = {
        "method": method,
        "toolkit": dest.as_posix(),
        "game": (tmp_path / "game").as_posix(),
        "profile": (tmp_path / "profile").as_posix(),
        "mods": (tmp_path / "mods").as_posix(),
        "reference": (dest / "reference").as_posix(),
        "extensions": (tmp_path / "game" / "extensions").as_posix(),
    }
    # OVERRIDES REPLACE, they do not append. Appending a second `--game` is
    # tolerated by bash (last wins) and REJECTED by PowerShell with "parameter
    # 'Game' is specified more than once" -- so the harness would have reported a
    # missing refusal when the installer never ran. A parameterised test has to
    # express intent, not one dialect spelled twice.
    flags = []
    it = iter(extra)
    for a in it:
        if a == "--game":
            common["game"] = next(it)
        elif a == "--dry-run":
            flags.append("dry-run")
        else:
            raise AssertionError("unmapped flag: %s" % a)

    if installer == "sh":
        exe = _bash()
        if exe is None:
            pytest.skip("no Git Bash on this machine")
        script = (dest / "install.sh") if from_dest else (source / "install.sh" if source else INSTALL_SH)
        cmd = [exe, script.as_posix()]
        for k, v in common.items():
            cmd += ["--" + k, v]
        cmd += ["--over-existing", "--yes"]
        cmd += ["--" + f for f in flags]
    else:
        exe = shutil.which("pwsh") or shutil.which("powershell")
        if exe is None:
            pytest.skip("no PowerShell on this machine")
        script = (dest / "install.ps1") if from_dest else (source / "install.ps1" if source else INSTALL_PS1)
        cmd = [exe, "-NoProfile", "-File", script.as_posix()]
        for k, v in common.items():
            cmd += ["-" + k[:1].upper() + k[1:], v]
        cmd += ["-OverExisting", "-Yes"]
        cmd += ["-DryRun" if f == "dry-run" else "-" + f for f in flags]
    cwd = dest.as_posix() if from_dest else (source.as_posix() if source else ROOT.as_posix())
    # The global arm writes to <claude-dir>, which is NOT one of the six path
    # flags. Pin it into the sandbox for every run rather than hoping no test
    # ever drives that arm without --dry-run.
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = fake_home.as_posix()
    env["HOME"] = tmp_path.as_posix()
    env["USERPROFILE"] = tmp_path.as_posix()
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_harness_can_install_at_all(installer, tmp_path):
    """Denominator first. Without this every assertion below could be passing
    because the installer never ran, and a skip is not a pass."""
    dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest)
    assert r.returncode == 0, "unlocked install failed, so the harness proves nothing:\n%s\n%s" % (r.stdout[-2000:], r.stderr[-2000:])
    assert (dest / "scripts").is_dir(), "the installer reported success and copied no scripts/"


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_UPGRADING_over_a_LOCKED_config_succeeds(installer, tmp_path):
    """THE DOCUMENTED PATH, and the one that was broken.

    Install, lock (which README tells the user to do), upgrade. The second run
    needs to change nothing about the config, so the lock must never bite --
    and before this fix it failed on item 1 of 16 with a bare
    `cp: Permission denied`.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    before = cfg.read_bytes()
    cfg.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)      # what x4lock does

    r = _install(installer, tmp_path, dest)
    assert r.returncode == 0, (
        "upgrade over a read-only x4-paths.env failed (rc=%s). The toolkit tells "
        "users to lock, so this IS the documented upgrade path:\n%s" % (r.returncode, r.stderr[-2000:]))
    assert cfg.read_bytes() == before, "the upgrade rewrote a config it did not need to change"
    leftovers = sorted(p.name for p in (dest / ".claude").glob("x4-paths.env.bak-*"))
    assert not leftovers, (
        "a backup was left behind: %s -- nothing should be backed up, because "
        "nothing should have been overwritten" % leftovers)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_locked_config_that_MUST_change_refuses_UP_FRONT(installer, tmp_path):
    """The other half, and refusing is the right answer.

    An installer that silently unlocked would defeat the mechanism the user asked
    for. So it must refuse -- but BEFORE writing anything, naming the unlock
    command, rather than dying part-way through a 16-item copy.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    cfg.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    (tmp_path / "game2").mkdir()

    r = _install(installer, tmp_path, dest, "--game", (tmp_path / "game2").as_posix())
    assert r.returncode != 0, "a config that cannot be written was reported as installed"
    out = (r.stdout + r.stderr).lower()
    assert "unlock" in out, (
        "the refusal does not name the remedy; the user sees a bare permission "
        "error and cannot tell it from a broken install:\n%s" % (r.stdout + r.stderr)[-2000:])
    assert "permission denied" not in out or "x4lock" in out, (
        "the failure is still a raw cp error rather than a precondition check")


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_DRY_RUN_predicts_a_refusal_it_would_hit(installer, tmp_path):
    """Finding 3. A dry run that cannot go red carries no information.

    MEASURED before the fix: rc 0 and a clean 16-item list, immediately followed
    by a real run that failed on item 1.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    (dest / ".claude" / "x4-paths.env").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    (tmp_path / "game2").mkdir()

    r = _install(installer, tmp_path, dest, "--game", (tmp_path / "game2").as_posix(), "--dry-run")
    assert r.returncode != 0 or "unlock" in (r.stdout + r.stderr).lower(), (
        "the dry run reported success for a run that cannot succeed:\n%s" % (r.stdout + r.stderr)[-1500:])


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_dry_run_still_passes_when_the_install_WOULD_work(installer, tmp_path):
    """The twin. A precondition that always refuses is not a check."""
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    (dest / ".claude" / "x4-paths.env").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    r = _install(installer, tmp_path, dest, "--dry-run")
    assert r.returncode == 0, (
        "the dry run refused an upgrade that needs no config change:\n%s" % (r.stdout + r.stderr)[-1500:])
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_DRY_RUN_writes_NOTHING_on_the_arm_that_SKIPS_the_copy(installer, tmp_path):
    """THE ARM MY OTHER DRY-RUN CASES COULD NOT REACH, and a CRITICAL lived in it.

    Under `--method separate` the COPY step refuses first and exits, so the config
    writer is never reached -- which is why ten passing tests said nothing about
    it. `--method global` never copies, so the writer's own gate is the only thing
    between a dry run and a real write.

    MEASURED before the fix, ps1, with `.claude` present: rc 0,
    `.claude/x4-paths.env` WRITTEN, "wrote <path>" printed, and then
    "=== dry run complete: nothing was changed ===". A brace error had nested the
    gate inside `if (Test-Path $f)`, so with the config ABSENT -- the state of
    every fresh clone, since it is gitignored -- the gate was skipped entirely and
    execution fell through to the write. bash on the same intent wrote 0 files.

    Asserting on the ARTIFACT rather than on the wording, because the wording said
    nothing was changed while it was untrue.
    """
    dest = _fresh(tmp_path)
    (dest / ".claude").mkdir()          # present, which is what makes the write reachable
    r = _install(installer, tmp_path, dest, "--dry-run", method="global")
    written = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert not written, (
        "--dry-run wrote %d file(s): %s (rc=%s) %s"
        % (len(written), written[:8], r.returncode, (r.stdout + r.stderr)[-600:]))
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_LOCKED_file_anywhere_in_the_copy_set_refuses_UP_FRONT(installer, tmp_path):
    """precheck_config guarded ONE file; x4lock locks about twenty-six.

    Under `--method in-game` the game root IS the destination, and x4lock's
    manifest there covers CLAUDE.md, KNOWLEDGEBASE.md, .claude/settings.json,
    the hooks, the skills and the agents -- all of which are inside the 16-item
    copy set. Guarding only x4-paths.env moved the failure from one filename to
    another rather than removing it.

    Reproduced with `separate` because the DEFECT is not method-specific: it is
    "a locked file in the copy set", and a user may lock anything.

    Both halves matter and they fail differently:
      * bash dies mid-copy with a bare `cp: Permission denied` and a half-copied
        destination, no unlock hint and no INCOMPLETE banner;
      * PowerShell's `Copy-Item -Force` CLEARS the read-only attribute and
        overwrites, so it returns 0 and reports success while destroying the very
        files the lock was protecting.

    One of those is wrong and nothing decided which. Refusing up front is the only
    answer that is right for both.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    victim = dest / ".claude" / "hooks" / "protect-bash.sh"
    assert victim.is_file(), "fixture assumption broken: the installer did not place %s" % victim
    # DISTINGUISHABLE content first. Source and destination otherwise hold the
    # same bytes, so `read_bytes() == before` would hold whether or not the file
    # was overwritten -- an assertion that cannot fail for the case it exists to
    # catch. Marking it makes a clobber visible.
    victim.write_bytes(b"# SENTINEL - the installer must not replace a locked file")
    before = victim.read_bytes()
    victim.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    r = _install(installer, tmp_path, dest)
    out = (r.stdout + r.stderr).lower()

    assert victim.read_bytes() == before, (
        "a LOCKED file in the copy set was overwritten -- the lock exists to stop "
        "exactly this, and the installer cleared it")
    assert r.returncode != 0, (
        "the installer reported success over a locked file it could not legitimately "
        "replace (rc=%s)" % r.returncode)
    assert "unlock" in out, (
        "the refusal does not name the remedy, so the user sees a bare permission "
        "error: %s" % (r.stdout + r.stderr)[-900:])


def _probe_repo(tmp_path):
    """A throwaway repo carrying the SHIPPED .gitignore.

    The assertion is about the file the release ships, so it must be made
    against that file rather than against whatever repo the suite happens to be
    standing in -- which in a `git archive` cold extract is no repo at all.
    """
    repo = tmp_path / "probe"
    (repo / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo.as_posix(), check=True,
                   capture_output=True)
    shutil.copy2(ROOT / ".gitignore", repo / ".gitignore")
    return repo


def _is_git_ignored(repo, path):
    """0 = ignored, 1 = not ignored, ANYTHING ELSE = git could not answer.

    Reading "non-zero" as "not ignored" is what made the old form pass in cold
    for the wrong reason: `git check-ignore` exits 128 outside a repository, and
    an error is not an allow.
    """
    r = subprocess.run(["git", "check-ignore", "-q", path],
                       cwd=str(repo), capture_output=True)
    if r.returncode not in (0, 1):
        raise AssertionError(
            "REFUSING a verdict: `git check-ignore` exited %d for %s, which is "
            "neither 'ignored' nor 'not ignored'. %s"
            % (r.returncode, path, r.stderr.decode("utf-8", "replace")[:200]))
    return r.returncode == 0


def test_a_non_repo_REFUSES_rather_than_reading_as_NOT_IGNORED(tmp_path):
    """The falsification twin for the refusal clause.

    Without it the six positive cases below pass only where a repo happens to
    exist, and the `.example` case -- the one that expects False -- passes
    ANYWHERE, including where nothing was checked at all.
    """
    bare = tmp_path / "not-a-repo"
    (bare / ".claude").mkdir(parents=True)
    with pytest.raises(AssertionError, match="REFUSING a verdict"):
        _is_git_ignored(bare, ".claude/x4-paths.env")


@pytest.mark.parametrize("path,ignored,why", [
    (".claude/x4-paths.env", True, "the live config: machine paths and X4_NEXUS_KEY"),
    (".claude/x4-paths.env.tmp12345", True,
     "the RENDER TARGET: it holds the key by construction, and survives a crash "
     "between render and move"),
    (".claude/settings.local.json.tmp999", True, "the same sibling on the other file"),
    (".claude/x4-paths.env.bak-20260907-120000", True,
     "a backup of it, which the carry-over deliberately preserves the key into"),
    (".claude/settings.local.json", True, "per-machine settings"),
    (".claude/settings.local.json.bak-20260907-120000", True, "and its backups"),
    (".claude/x4-paths.env.example", False,
     "the TEMPLATE is tracked on purpose; a blanket x4-paths.env* would swallow it"),
])
def test_the_config_backups_cannot_be_committed(path, ignored, why, tmp_path):
    """Asserts the SHIPPED .gitignore, in a repo built for the purpose.

    WHY the rule exists: `.gitignore` pinned the two config filenames EXACTLY, so
    the `.bak-<stamp>` files beside them were not ignored at all -- and
    `write_paths_env` carries over every key it does not own (X4_NEXUS_KEY
    explicitly, per setup.sh), so each backup holds the key plus that machine's
    absolute paths, and they show up in `git status` where a `git add -A` would
    take them. PRE-ARC: v3.0.0 already created `.bak-$stamp`. Both directions are
    asserted, because the obvious fix is a blanket `x4-paths.env*` and that
    silently stops tracking the `.example` template the installer ships.

    WHY it is built here rather than run in place. It used to run `git check-ignore` in whatever repo the suite was standing in.
    Two things were wrong with that, and the second is worse:

    * `verify-cold.sh` extracts via `git archive HEAD` into a directory that is
      NOT a git repo, so check-ignore exited 128 and every case read as "not
      ignored" -- six failed and the release gate went red.
    * rc 128 is an ERROR, not a negative answer. Treating any non-zero as "not
      ignored" conflated "git could not look" with "git says no", so the
      `.example` case PASSED IN COLD FOR THE WRONG REASON: it cannot tell
      "correctly not ignored" from "there is no repo here". An error is not an
      allow.

    Building the repo here fixes both, and makes the test assert the file the
    release SHIPS rather than the ignore behaviour of the tree it happens to run
    in -- which is the thing the claim was always about.
    """
    is_ignored = _is_git_ignored(_probe_repo(tmp_path), path)
    assert is_ignored == ignored, (
        "%s should%s be git-ignored (%s)" % (path, "" if ignored else " NOT", why))


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_refusal_LIST_is_bounded_and_says_how_many_it_hid(installer, tmp_path):
    """A regression pin for a branch I wrote and never exercised.

    The refusal prints at most 8 paths plus a count of the rest. Written that way
    because an UNBOUNDED warning is the defect this same session fixed in the
    canary -- a report whose length grows with the severity it describes is filed
    by the harness exactly when it matters. But the >8 branch had no case, so
    "bounded" was a claim about code nobody had run.

    Locks 12 files so the cap actually bites, and asserts BOTH halves: the list is
    capped, and the hidden count is stated rather than silently dropped.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    hooks = dest / ".claude" / "hooks"
    victims = sorted(p for p in hooks.glob("*") if p.is_file())[:12]
    assert len(victims) >= 10, "fixture needs >8 lockable files, found %d" % len(victims)
    for v in victims:
        v.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    r = _install(installer, tmp_path, dest)
    out = r.stdout + r.stderr
    assert r.returncode != 0, "reported success over %d locked files" % len(victims)
    # ASSERTED, not merely computed. This was assigned and never used while the
    # docstring claimed both halves were pinned -- a variable that looks like a
    # check and is not one.
    listed = sum(1 for ln in out.splitlines()
                 if ln.strip().startswith(("C:", "/")) and "hooks" in ln)
    assert listed <= 8, (
        "the refusal listed %d paths; the cap is 8 plus a count" % listed)
    assert "NOT LISTED" in out, (
        "more than 8 files were blocked and the refusal did not say how many it "
        "hid -- a narrowing step must announce itself:\n%s" % out[-1200:])
    assert "unlock" in out.lower()
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_config_write_leaves_no_temp_behind(installer, tmp_path):
    """The config is rendered to a temp, verified, then moved.

    Both installers used to write the LIVE config and verify it AFTERWARDS, so a
    render that failed part way left a half-written file and the check then
    reported a failure about something it was too late to protect. Third instance
    of one shape today, after `_effective._write_db` and the round trip removed
    from copy_toolkit.

    ⚠ WHAT THIS DOES AND DOES NOT PROVE. It asserts the observable half: no temp
    survives a successful run, and the installed config is sourceable. It does NOT
    inject a mid-write failure -- the escaping exists to make an unsourceable
    render impossible, so there is no honest way to provoke one from outside. The
    partial-write window is closed BY CONSTRUCTION (the live path is never the
    target of the render), and that is a claim about the code, not about this
    test.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    assert cfg.is_file(), "no config was written"
    strays = sorted(p.name for p in (dest / ".claude").glob("x4-paths.env.tmp*"))
    assert not strays, "the config write left a temp behind: %s" % strays
    body = cfg.read_text(encoding="utf-8")
    assert "X4_TOOLKIT=" in body, "the installed config is not the rendered one"
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_an_IN_PLACE_dry_run_runs_NOTHING(installer, tmp_path):
    """THE SHAPE NO FIXTURE HERE HAD, and the fourth critical of this arc lived in it.

    Every other case points --toolkit at a NEW directory, so `same_dir` is false,
    the copy step runs and ITS dry-run gate exits first. When a user re-runs the
    installer from inside an existing install to preview an upgrade, `same_dir` is
    TRUE: no copy, so `write_paths_env` is the only writer reached -- and its
    "nothing to change" fast path returned ABOVE the dry-run gate.

    MEASURED before the fix, all four arms: rc 0, no dry-run banner, "install
    complete" printed, and `setup.sh` RAN -- syncing dependencies with uv. With
    --unpack it would also have run bin/unpack-reference.sh, which unpacks the
    game archives. Proven a regression of this arc against the same fixture at
    c6fe0f0^, where the banner appeared and setup.sh did not run.

    ★ The structural half matters more than the ordering bug: `setup.sh` and
    `bin/unpack-reference.sh` are invoked at TOP LEVEL, outside all three writers,
    so a gate placed in the writers is incapable of covering them however
    carefully it is positioned. refuse_if_dry_run's own docstring claimed every
    write goes through one of the three. It does not.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    marker = dest / "tools" / "x4validate" / ".venv"
    had_venv = marker.exists()

    r = _install(installer, tmp_path, dest, "--dry-run", from_dest=True)
    out = (r.stdout + r.stderr)
    low = out.lower()

    assert "dry run complete" in low, (
        "an in-place --dry-run printed no dry-run banner:\n%s" % out[-1200:])
    assert "install complete" not in low, (
        "an in-place --dry-run reported a completed INSTALL:\n%s" % out[-1200:])
    assert "modding toolkit setup" not in low, (
        "an in-place --dry-run RAN setup.sh -- it syncs dependencies and writes to "
        "disk:\n%s" % out[-1500:])
    assert marker.exists() == had_venv, "a dry run created or removed the virtualenv"
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_an_UNREADABLE_config_REFUSES_with_a_crafted_message(installer, tmp_path):
    """A read that cannot succeed must not be reported as "everything changed".

    `Get-OwnedEnvLinesFromFile` / `_owned_lines_old` read the live config to decide
    whether a write is needed. Unguarded, a config held open FileShare::None -- an
    editor, an AV scanner, a sync client -- gave a raw interpreter dump naming the
    line and the file, with no crafted message and no INCOMPLETE accounting. Worse,
    an empty result would compare unequal to the rendered lines and be read as
    "the paths changed", which is a different claim from "I could not look".

    A directory standing where the config belongs is the same failure and can
    actually be created, which is what makes this a test rather than an argument.
    The point is not the directory; it is that the guard FIRES and says something
    a user can act on.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    cfg.unlink()
    cfg.mkdir()                      # unreadable as a file, and creatable

    r = _install(installer, tmp_path, dest)
    out = (r.stdout + r.stderr)
    low = out.lower()
    assert r.returncode != 0, "an unreadable config was reported as a successful install"
    assert "refusing" in low or "cannot read" in low, (
        "the failure is a raw interpreter error rather than a crafted message:\n%s"
        % out[-1200:])
    assert "nothing has been changed" in low or "untouched" in low, (
        "the refusal does not tell the user whether anything was written:\n%s" % out[-1200:])
def _synthetic_source(tmp_path: pathlib.Path) -> pathlib.Path:
    """A toolkit source that has been installed FROM at least once.

    Which is every maintainer checkout: `.bak-<stamp>` is created on every
    config-changing run and accumulates, and `.tmp<pid>` survives a crash between
    render and move. A pristine clone has neither, which is why nothing noticed.
    """
    src = tmp_path / "src"
    (src / ".claude").mkdir(parents=True)
    for name in ("install.sh", "install.ps1", "setup.sh"):
        shutil.copy2(ROOT / name, src / name)
    secret = 'X4_NEXUS_KEY="SECRET_FROM_THE_SOURCE_MACHINE"\n'
    (src / ".claude" / "x4-paths.env").write_text(secret, encoding="utf-8")
    (src / ".claude" / "x4-paths.env.bak-20260101-000000").write_text(secret, encoding="utf-8")
    (src / ".claude" / "x4-paths.env.tmp4242").write_text(secret, encoding="utf-8")
    (src / ".claude" / "settings.local.json.bak-20260101-000000").write_text(secret, encoding="utf-8")
    # the two TEMPLATES ship and must still travel
    (src / ".claude" / "x4-paths.env.example").write_text("X4_TOOLKIT=\n", encoding="utf-8")
    (src / ".claude" / "settings.local.json.example").write_text("{}\n", encoding="utf-8")
    return src


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_SOURCE_machines_config_siblings_do_not_travel(installer, tmp_path):
    """The keep-list matched two EXACT names; the siblings beside them travelled.

    MEASURED before the fix, both installers: a source carrying
    `x4-paths.env.bak-<stamp>` and `x4-paths.env.tmp<pid>` copied BOTH into the
    destination, rc 0, silent -- and the carry-over deliberately preserves
    X4_NEXUS_KEY into every rewrite, so each holds the source machine's key plus
    its absolute paths.

    ★ This is the previous defect with the roles REVERSED. In the same arc I
    widened `.gitignore` from two exact names to `x4-paths.env.*` and wrote a
    comment explaining why -- and did not widen the COPY rule in step. The ignore
    rule and the copy rule describe the same set and only one of them knew it.

    Both directions, because a blanket prefix skip would stop shipping the
    templates the installer is supposed to install.
    """
    src = _synthetic_source(tmp_path)
    dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, source=src)
    # rc is NOT asserted: setup.sh cannot succeed against a synthetic source with
    # no tools/x4validate, and that failure belongs to the fixture rather than the
    # installer. What matters is what the COPY did.
    #
    # DENOMINATOR FIRST. Without it, "no secret travelled" is equally true of a
    # run that copied nothing at all.
    assert (dest / ".claude").is_dir(), "the copy did not run; this proves nothing"

    leaked = sorted(p.relative_to(dest).as_posix()
                    for p in dest.rglob("*") if p.is_file()
                    and "SECRET_FROM_THE_SOURCE_MACHINE" in p.read_text(encoding="utf-8", errors="ignore"))
    assert not leaked, (
        "the source machine's secret travelled to the destination in %d file(s): %s"
        % (len(leaked), leaked))

    for tpl in ("x4-paths.env.example", "settings.local.json.example"):
        assert (dest / ".claude" / tpl).is_file(), (
            "%s did not travel -- the skip is too broad and the installer no "
            "longer ships its own template" % tpl)
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_CRLF_config_is_still_recognised_as_UNCHANGED(installer, tmp_path):
    """One input, and the two installers reached opposite verdicts on it.

    bash reads with `read -r`, which KEEPS the trailing carriage return, while the
    renderer emits none -- so a config saved by any Windows editor compared
    unequal forever. PowerShell's Get-Content strips it and said "already
    matches".

    MEASURED before the fix, same fixture, values byte-identical apart from line
    endings: install.sh rc 1 "REFUSING: your path config must change, and it is
    READ-ONLY", install.ps1 rc 0 "already matches these paths; left untouched".
    The config header says "edit freely" and CLAUDE.md names Notepad++ as the
    editor, so opening the file once was enough -- and the refusal's remedy
    (unlock, re-run, re-lock) cannot help, because the "change" is invisible.
    Unlocked, bash instead rewrote the config on EVERY run, losing the
    hand-written comments the fast path exists to preserve.

    `test_UPGRADING_over_a_LOCKED_config_succeeds` could not see this: the
    installer it had just run wrote LF.
    """
    dest = _fresh(tmp_path)
    assert _install(installer, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    body = cfg.read_bytes()
    assert b"\r\n" not in body, "fixture assumption broken: the installer wrote CRLF"
    cfg.write_bytes(body.replace(b"\n", b"\r\n"))          # the only change
    cfg.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # what x4lock does

    r = _install(installer, tmp_path, dest)
    out = (r.stdout + r.stderr).lower()
    assert r.returncode == 0, (
        "a CRLF config was treated as CHANGED, so the locked upgrade was refused "
        "over line endings alone:\n%s" % (r.stdout + r.stderr)[-1000:])
    assert "already matches" in out, (
        "the config was not recognised as unchanged:\n%s" % (r.stdout + r.stderr)[-1000:])


def _global_fixture(tmp_path, toolkit_name: str = "toolkit"):
    """A toolkit that ships one skill, beside a user who keeps notes in it.

    The destination directory `x4-balance` is one the toolkit OWNS, which is the
    whole point: the existing guard is keyed on that name, so it protects
    `my-own-thing/` and waves through a user file sitting inside `x4-balance/`.

    `toolkit_name` is a parameter because one twin needs a path carrying `[` and
    `]`, which is a metacharacter hazard measured on this file rather than an
    invented one.
    """
    dest = tmp_path / toolkit_name
    dest.mkdir()
    for d in ("game", "profile", "mods"):
        (tmp_path / d).mkdir(exist_ok=True)
    sk = dest / ".claude" / "skills" / "x4-balance"
    sk.mkdir(parents=True)
    # NESTED, because the loop recurses and a mapping bug shows up here first:
    # a top-level file survives some wrong prefixes that a nested one does not.
    (sk / "nested").mkdir()
    (sk / "nested" / "DEEP.md").write_text("deep $CLAUDE_PROJECT_DIR/x" + chr(10),
                                           encoding="utf-8")
    (sk / "SKILL.md").write_text("run $CLAUDE_PROJECT_DIR/tools/x4validate\n",
                                 encoding="utf-8")
    quiet = dest / ".claude" / "skills" / "x4-debug"
    quiet.mkdir(parents=True)
    (quiet / "SKILL.md").write_text("this one names no variable at all\n",
                                    encoding="utf-8")
    ag = dest / ".claude" / "agents"
    ag.mkdir(parents=True)
    (ag / "mod-research.md").write_text("see $CLAUDE_PROJECT_DIR/reference\n",
                                        encoding="utf-8")
    # setup.sh is invoked at the end of a real run; without it the installer
    # reports a failed step and the rewrite result would be read through a
    # non-zero rc that has nothing to do with this claim.
    (dest / "setup.sh").write_text("exit 0\n", encoding="utf-8")

    home = tmp_path / "fake-claude-home"
    mine = home / "skills" / "x4-balance"
    mine.mkdir(parents=True)
    (mine / "MY_NOTES.md").write_text("my dir is $CLAUDE_PROJECT_DIR/notes\n",
                                      encoding="utf-8")
    theirs = home / "skills" / "my-own-thing"
    theirs.mkdir(parents=True)
    (theirs / "THEIRS.md").write_text("my dir is $CLAUDE_PROJECT_DIR/mine\n",
                                      encoding="utf-8")
    return dest, home


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_global_rewrite_touches_only_files_the_TOOLKIT_SHIPS(installer, tmp_path):
    """`--method global --over-existing` rewrote a user's own file and deleted the backup.

    install.sh derives the DIRECTORY list from the toolkit -- its comment says
    "never from a destination glob (a pre-existing user skill named x4-* must not
    match)" -- and then runs `grep -rl CLAUDE_PROJECT_DIR "$tgt"` over the
    DESTINATION directory. With --over-existing that directory holds the toolkit's
    files MERGED with the user's, so every user file inside a shipped skill was
    rewritten by `sed -i.bak ... && rm -f "$f.bak"`: edited in place, only copy
    deleted, rc 0, nothing printed.

    Toolkit-derived for directories and destination-derived for files is the
    wrong-baseline shape: the list is not the thing the comment claims it is.

    install.ps1 already builds `$copied` from `$srcRoot`, so it is the immune case
    and it names the cause -- the operand was right there in the sibling.
    """
    dest, home = _global_fixture(tmp_path)
    r = _install(installer, tmp_path, dest, method="global")

    shipped = (home / "skills" / "x4-balance" / "SKILL.md").read_text(encoding="utf-8")
    # THE CONTROL, and it must come first: if the rewrite step never ran, every
    # "unchanged" assertion below passes for the wrong reason.
    assert "$X4_TOOLKIT" in shipped, (
        "the rewrite never ran, so this test proves nothing about what it spares "
        "(rc=%s) %s" % (r.returncode, (r.stdout + r.stderr)[-800:]))

    mine = (home / "skills" / "x4-balance" / "MY_NOTES.md").read_text(encoding="utf-8")
    assert mine == "my dir is $CLAUDE_PROJECT_DIR/notes\n", (
        "the user's own file inside a SHIPPED skill directory was rewritten: %r" % mine)

    theirs = (home / "skills" / "my-own-thing" / "THEIRS.md").read_text(encoding="utf-8")
    assert theirs == "my dir is $CLAUDE_PROJECT_DIR/mine\n", (
        "a user skill the toolkit does not ship was rewritten: %r" % theirs)

    left = sorted(p.name for p in home.rglob("*.bak*"))
    assert not left, "left backups behind: %s" % left


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_shipped_file_with_NO_token_is_left_alone_and_does_not_fail_the_run(
        installer, tmp_path):
    """The status twin. 2 of the 7 real skills contain no $CLAUDE_PROJECT_DIR.

    grep exits 1 on no match and `set -o pipefail` + `set -e` once killed the
    installer here, after copying and before writing any env -- so "needs no
    rewrite" must stay the normal case, not an error.
    """
    dest, home = _global_fixture(tmp_path)
    r = _install(installer, tmp_path, dest, method="global")
    assert r.returncode == 0, (
        "a skill needing no rewrite failed the run:\n%s" % (r.stdout + r.stderr)[-1200:])
    quiet = (home / "skills" / "x4-debug" / "SKILL.md").read_text(encoding="utf-8")
    assert quiet == "this one names no variable at all\n", "rewrote a file with no token"


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_source_to_destination_MAPPING_survives_a_BRACKETED_toolkit_path(
        installer, tmp_path):
    """The twin for the PATH-PARSING clause, which the other three cannot reach.

    They vary WHICH files the loop selects and hold the path shape constant. This
    one varies the path and holds the selection constant, because the failure is
    not a wrong selection: `${src#"$TOOLKIT/.claude/skills/"}` unquoted treats
    `[v3]` as a character CLASS matching one of v/3, so it does not match the
    literal four characters, the prefix is not stripped, `$rel` keeps the whole
    absolute path, and the destination mapping points outside the skill entirely.
    The file is then simply not rewritten -- or, with a different prefix, written
    somewhere in the user's ~/.claude that nobody asked for.

    It is a test rather than the one-off probe it started as because THIS COMMIT
    made that expression load-bearing. Before the fix the file list came from
    `grep -rl`, which yields absolute paths and never went through a prefix strip,
    so nothing in the suite had ever exercised it. A construct that moves onto the
    path needs coverage on the axis it introduced, not on the axis that was
    already covered.

    `[` and `]` in a toolkit path is a MEASURED hazard on this file, not a
    hypothetical: `toolkit [v3]` is what made the PowerShell arm's bare path
    cmdlets match nothing and report "installed" over an empty directory.
    test_installer_literal_paths.py pins that, but it never drives --method
    global, so it cannot cover this.
    """
    dest, home = _global_fixture(tmp_path, toolkit_name="toolkit [v3]")
    r = _install(installer, tmp_path, dest, method="global")

    for rel in ("SKILL.md", "nested/DEEP.md"):
        f = home / "skills" / "x4-balance" / rel
        assert f.is_file(), (
            "%s never arrived at its destination, so the source->destination "
            "mapping did not survive the bracketed path (rc=%s) %s"
            % (rel, r.returncode, (r.stdout + r.stderr)[-800:]))
        body = f.read_text(encoding="utf-8")
        assert "$X4_TOOLKIT" in body and "$CLAUDE_PROJECT_DIR" not in body, (
            "%s was copied but NOT rewritten -- the prefix strip did not strip, so "
            "the mapped path named no real file and the loop skipped it: %r"
            % (rel, body))

    mine = (home / "skills" / "x4-balance" / "MY_NOTES.md").read_text(encoding="utf-8")
    assert mine == "my dir is $CLAUDE_PROJECT_DIR/notes\n", (
        "a bracketed toolkit path must not widen what gets rewritten either: %r" % mine)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_the_upgrade_KEEPS_the_recovery_store_and_still_PRUNES_build_artifacts(
        installer, tmp_path):
    """`.claude/backups/` is the RECOVERY STORE, and the upgrade deleted it.

    X4_COPY_PRUNE is dual-purpose -- skipped on the way IN and `rm -rf`'d from the
    destination on the way OUT, twice. v3.0.0's list held three build artifacts.
    24da65e added `.claude/backups` to stop the SOURCE's backup files travelling,
    and the path silently inherited the destructive second meaning: an upgrade
    erased every known-good snapshot and the whole audit trail, rc 0, with the word
    "backup" appearing nowhere in the output.

    That store is not a build artifact. `backup-before-edit.sh` writes every
    pre-edit backup there, `generate-baseline.sh` writes the known-good snapshots
    CLAUDE.md mandates before any experiment, `restore-from-backup.sh` reads it --
    and `x4lock.py` deliberately leaves it UNLOCKED, so the lock guard cannot catch
    this either. MEASURED on the live install when this was found: 982 files,
    60 MB, 33 named snapshots.

    FOUR arms, because the obvious repair fails two of them:

      SUBJECT   the destination's own store survives          (the defect)
      TRAVEL    the SOURCE's store does NOT arrive            (what 24da65e fixed)
      CONTROL   a real build artifact is STILL pruned         (or this passes for
                                                               an installer that
                                                               prunes nothing)
      TWIN      an unrelated user directory under .claude/    (bounds it to the
                survives                                       list, not blanket)

    SUBJECT and TRAVEL are asserted as one exact set, so neither can be satisfied
    by the other going wrong.
    """
    dest = _fresh(tmp_path)

    store = dest / ".claude" / "backups" / "known-good-2026-09-01"
    store.mkdir(parents=True)
    (store / "snapshot.xml").write_text("MY-IRREPLACEABLE-SNAPSHOT", encoding="utf-8")
    audit = dest / ".claude" / "backups" / "AUDIT_LOG.txt"
    audit.write_text("MY-AUDIT-TRAIL", encoding="utf-8")

    artifact = dest / "scripts" / "__pycache__"
    artifact.mkdir(parents=True)
    (artifact / "stale.pyc").write_bytes(b"\x00stale")

    mine = dest / ".claude" / "my-own-notes"
    mine.mkdir(parents=True)
    (mine / "README.md").write_text("MY-OWN-NOTES", encoding="utf-8")

    r = _install(installer, tmp_path, dest)
    assert r.returncode == 0, "the install failed: %s" % (r.stdout + r.stderr)[-1500:]

    # SUBJECT + TRAVEL as one exact set: exactly what I put there, nothing else.
    got = sorted(p.relative_to(dest / ".claude" / "backups").as_posix()
                 for p in (dest / ".claude" / "backups").rglob("*") if p.is_file())
    assert got == ["AUDIT_LOG.txt", "known-good-2026-09-01/snapshot.xml"], (
        "the recovery store is wrong after the upgrade. Either the destination's own "
        "store was destroyed, or the SOURCE machine's backups travelled into it. "
        "got=%r" % (got,))
    assert (store / "snapshot.xml").read_text(encoding="utf-8") == "MY-IRREPLACEABLE-SNAPSHOT"
    assert audit.read_text(encoding="utf-8") == "MY-AUDIT-TRAIL"

    # CONTROL: without this the test passes for an installer that prunes nothing.
    assert not (artifact / "stale.pyc").exists(), (
        "the build-artifact prune stopped working, so the SUBJECT assertion above "
        "proves nothing about the prune list")

    # TWIN: bounds the change to the list rather than to deletion in general.
    assert (mine / "README.md").read_text(encoding="utf-8") == "MY-OWN-NOTES", (
        "an unrelated user directory under .claude/ was removed")
