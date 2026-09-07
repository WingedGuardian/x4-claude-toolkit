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
    root = tmp_path.resolve()
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
             method: str = "separate"):
    """Run ONE of the two installers with identical intent.

    Parameterised rather than duplicated, because the point is that both reach the
    same VERDICT. `test_installers_agree.py` compares the two files as TEXT, so it
    would pass on two installers that agree about item lists and disagree about
    whether they clean up -- which is exactly what was true here: install.ps1 had
    `finally` where install.sh had none, and both still failed this path.
    """
    _refuse_unless_sandboxed(tmp_path, dest, tmp_path / "game",
                             tmp_path / "profile", tmp_path / "mods")
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
        cmd = [exe, INSTALL_SH.as_posix()]
        for k, v in common.items():
            cmd += ["--" + k, v]
        cmd += ["--over-existing", "--yes"]
        cmd += ["--" + f for f in flags]
    else:
        exe = shutil.which("pwsh") or shutil.which("powershell")
        if exe is None:
            pytest.skip("no PowerShell on this machine")
        cmd = [exe, "-NoProfile", "-File", INSTALL_PS1.as_posix()]
        for k, v in common.items():
            cmd += ["-" + k[:1].upper() + k[1:], v]
        cmd += ["-OverExisting", "-Yes"]
        cmd += ["-DryRun" if f == "dry-run" else "-" + f for f in flags]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT.as_posix())


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
@pytest.mark.parametrize("path,ignored,why", [
    (".claude/x4-paths.env", True, "the live config: machine paths and X4_NEXUS_KEY"),
    (".claude/x4-paths.env.bak-20260907-120000", True,
     "a backup of it, which the carry-over deliberately preserves the key into"),
    (".claude/settings.local.json", True, "per-machine settings"),
    (".claude/settings.local.json.bak-20260907-120000", True, "and its backups"),
    (".claude/x4-paths.env.example", False,
     "the TEMPLATE is tracked on purpose; a blanket x4-paths.env* would swallow it"),
])
def test_the_config_backups_cannot_be_committed(path, ignored, why):
    """`.gitignore` pinned the two config filenames EXACTLY, so the `.bak-<stamp>`
    files beside them were not ignored at all.

    That matters because `write_paths_env` carries over every key it does not own
    -- X4_NEXUS_KEY explicitly, per setup.sh -- so each backup holds the key plus
    that machine's absolute paths, and they show up in `git status` where a
    `git add -A` would take them. PRE-ARC: v3.0.0 already created `.bak-$stamp`.

    Both directions are asserted, because the obvious fix is a blanket
    `x4-paths.env*` and that silently stops tracking the `.example` template the
    installer ships.
    """
    r = subprocess.run(["git", "check-ignore", "-q", path],
                       cwd=ROOT.as_posix(), capture_output=True)
    is_ignored = (r.returncode == 0)
    assert is_ignored == ignored, (
        "%s should%s be git-ignored (%s)" % (path, "" if ignored else " NOT", why))
