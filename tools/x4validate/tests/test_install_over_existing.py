"""Installing OVER an existing install -- the path nothing drove until now.

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
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
INSTALL_SH = ROOT / "install.sh"
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

def _install(bash: str, tmp_path: pathlib.Path, dest: pathlib.Path, *extra: str):
    _refuse_unless_sandboxed(tmp_path, dest, tmp_path / "game",
                             tmp_path / "profile", tmp_path / "mods")
    cmd = [bash, INSTALL_SH.as_posix(),
           "--method", "separate",
           "--toolkit", dest.as_posix(),
           "--game", (tmp_path / "game").as_posix(),
           "--profile", (tmp_path / "profile").as_posix(),
           "--mods", (tmp_path / "mods").as_posix(),
           "--reference", (dest / "reference").as_posix(),
           "--extensions", (tmp_path / "game" / "extensions").as_posix(),
           "--over-existing", "--yes", *extra]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT.as_posix())


@pytest.fixture()
def bash():
    b = _bash()
    if b is None:
        pytest.skip("no Git Bash on this machine; the installer is a bash script")
    return b


def test_the_harness_can_install_at_all(bash, tmp_path):
    """Denominator first. Without this every assertion below could be passing
    because the installer never ran, and a skip is not a pass."""
    dest = _fresh(tmp_path)
    r = _install(bash, tmp_path, dest)
    assert r.returncode == 0, "unlocked install failed, so the harness proves nothing:\n%s\n%s" % (r.stdout[-2000:], r.stderr[-2000:])
    assert (dest / "scripts").is_dir(), "the installer reported success and copied no scripts/"


def test_UPGRADING_over_a_LOCKED_config_succeeds(bash, tmp_path):
    """THE DOCUMENTED PATH, and the one that was broken.

    Install, lock (which README tells the user to do), upgrade. The second run
    needs to change nothing about the config, so the lock must never bite --
    and before this fix it failed on item 1 of 16 with a bare
    `cp: Permission denied`.
    """
    dest = _fresh(tmp_path)
    assert _install(bash, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    before = cfg.read_bytes()
    cfg.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)      # what x4lock does

    r = _install(bash, tmp_path, dest)
    assert r.returncode == 0, (
        "upgrade over a read-only x4-paths.env failed (rc=%s). The toolkit tells "
        "users to lock, so this IS the documented upgrade path:\n%s" % (r.returncode, r.stderr[-2000:]))
    assert cfg.read_bytes() == before, "the upgrade rewrote a config it did not need to change"
    leftovers = sorted(p.name for p in (dest / ".claude").glob("x4-paths.env.bak-*"))
    assert not leftovers, (
        "a backup was left behind: %s -- nothing should be backed up, because "
        "nothing should have been overwritten" % leftovers)


def test_a_locked_config_that_MUST_change_refuses_UP_FRONT(bash, tmp_path):
    """The other half, and refusing is the right answer.

    An installer that silently unlocked would defeat the mechanism the user asked
    for. So it must refuse -- but BEFORE writing anything, naming the unlock
    command, rather than dying part-way through a 16-item copy.
    """
    dest = _fresh(tmp_path)
    assert _install(bash, tmp_path, dest).returncode == 0, "first install failed"
    cfg = dest / ".claude" / "x4-paths.env"
    cfg.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    (tmp_path / "game2").mkdir()

    r = _install(bash, tmp_path, dest, "--game", (tmp_path / "game2").as_posix())
    assert r.returncode != 0, "a config that cannot be written was reported as installed"
    out = (r.stdout + r.stderr).lower()
    assert "unlock" in out, (
        "the refusal does not name the remedy; the user sees a bare permission "
        "error and cannot tell it from a broken install:\n%s" % (r.stdout + r.stderr)[-2000:])
    assert "permission denied" not in out or "x4lock" in out, (
        "the failure is still a raw cp error rather than a precondition check")


def test_the_DRY_RUN_predicts_a_refusal_it_would_hit(bash, tmp_path):
    """Finding 3. A dry run that cannot go red carries no information.

    MEASURED before the fix: rc 0 and a clean 16-item list, immediately followed
    by a real run that failed on item 1.
    """
    dest = _fresh(tmp_path)
    assert _install(bash, tmp_path, dest).returncode == 0, "first install failed"
    (dest / ".claude" / "x4-paths.env").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    (tmp_path / "game2").mkdir()

    r = _install(bash, tmp_path, dest, "--game", (tmp_path / "game2").as_posix(), "--dry-run")
    assert r.returncode != 0 or "unlock" in (r.stdout + r.stderr).lower(), (
        "the dry run reported success for a run that cannot succeed:\n%s" % (r.stdout + r.stderr)[-1500:])


def test_the_dry_run_still_passes_when_the_install_WOULD_work(bash, tmp_path):
    """The twin. A precondition that always refuses is not a check."""
    dest = _fresh(tmp_path)
    assert _install(bash, tmp_path, dest).returncode == 0, "first install failed"
    (dest / ".claude" / "x4-paths.env").chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    r = _install(bash, tmp_path, dest, "--dry-run")
    assert r.returncode == 0, (
        "the dry run refused an upgrade that needs no config change:\n%s" % (r.stdout + r.stderr)[-1500:])
