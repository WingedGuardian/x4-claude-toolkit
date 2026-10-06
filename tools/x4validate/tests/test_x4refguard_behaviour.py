r"""What the reference deny (DE,DC,WD,AD) stops, and what it does NOT -- each row paired with
a CONTROL on an identical unprotected tree, so a broken probe cannot read as a working lock.

EVERY ROW IS JUDGED BY THE DISK, NEVER BY AN EXIT CODE. MEASURED 2026-10-02: `del /f /q`
exits 0 while printing "Access is denied". A test that trusted rc would read a blocked
delete as a success, and the control would not catch it either.

Scratch only: X4_REFERENCE points at tmp_path, X4_REFGUARD_SANDBOX confines every
mutating call of x4refguard to tmp_path, and every teardown resets the ACL through the
same sandboxed choke point (asserted under the system temp dir first).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="NTFS ACL behaviour (Windows mechanism)")

REPO = Path(__file__).resolve().parents[3]


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


x4refguard = _load("x4refguard", "scripts/x4refguard.py")
gitbash = _load("gitbash_rg", "scripts/gitbash.py")
from x4validate import _paths  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refguard_owner import own_or_skip  # noqa: E402

ORIG = "<wares/>"


def _under_temp(p) -> bool:
    tmp = os.path.normcase(str(Path(tempfile.gettempdir()).resolve()))
    q = os.path.normcase(str(Path(p).resolve()))
    return q.startswith(tmp + os.sep)


def _bash():
    b = gitbash.find_bash()      # never the WSL stub
    if not b:
        pytest.skip("no Git Bash")
    return b


def _ps(cmd, env):
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                          env=env, capture_output=True)


def _try(f, *a):
    try:
        f(*a)
    except OSError:
        pass


def _cmd(line, env):
    # a STRING, so cmd.exe sees the quotes verbatim (the list form re-quoted them and the
    # control failed too during the measurement -- a non-answer)
    return subprocess.run(line, env=env, capture_output=True)


#: DELETE / RENAME primitives (the 8 the plan names). Each must leave the tree unchanged.
DELETES = {
    "rm_f": lambda t, e: subprocess.run([_bash(), "-c", 'rm -f "$T/libraries/wares.xml"'], env=e, capture_output=True),
    "remove_item": lambda t, e: _ps('Remove-Item -Force -LiteralPath "$env:T\\libraries\\wares.xml"', e),
    "del_fq": lambda t, e: _cmd('cmd /c del /f /q "%T%\\libraries\\wares.xml"', e),
    "os_remove": lambda t, e: _try(os.remove, t / "libraries" / "wares.xml"),
    "rename": lambda t, e: _try(os.rename, t / "libraries" / "wares.xml", t / "libraries" / "moved.xml"),
    "cat_force": lambda t, e: _ps('Remove-Item -Force -LiteralPath "$env:T\\01.cat"', e),
    "rm_rf_tree": lambda t, e: subprocess.run([_bash(), "-c", 'rm -rf "$T/libraries"'], env=e, capture_output=True),
    "ri_recurse": lambda t, e: _ps('Remove-Item -Recurse -Force -LiteralPath "$env:T\\libraries"', e),
}

#: WRITE / CREATE primitives -- closed by WD,AD (audit F1 for this tree).
WRITES = {
    "open_w": lambda t, e: _try(lambda: open(t / "libraries" / "wares.xml", "w").write("x")),
    "write_text": lambda t, e: _try((t / "libraries" / "wares.xml").write_text, "x"),
    "append": lambda t, e: _try(lambda: open(t / "libraries" / "wares.xml", "a").write("x")),
    "truncate": lambda t, e: _try(os.truncate, t / "libraries" / "wares.xml", 0),
    "copy2_over": lambda t, e: _try(shutil.copy2, t / "01.cat", t / "libraries" / "wares.xml"),
    "copy_item_force": lambda t, e: _ps('Copy-Item -Force -LiteralPath "$env:T\\01.cat" '
                                        '-Destination "$env:T\\libraries\\wares.xml"', e),
    "bash_redirect": lambda t, e: subprocess.run([_bash(), "-c", 'echo x > "$T/libraries/wares.xml"'], env=e, capture_output=True),
    "new_file": lambda t, e: _try((t / "libraries" / "new.xml").write_text, "x"),
    "mkdir": lambda t, e: _try(os.mkdir, t / "newdir"),
}

PRIMS = {**DELETES, **WRITES}


def _tree(root):
    (root / "libraries").mkdir(parents=True)
    (root / "libraries" / "wares.xml").write_text(ORIG, encoding="utf-8")
    (root / "01.cat").write_text("cat", encoding="utf-8")
    (root / ".unpacked-and-locked").write_text("buildid 1", encoding="utf-8")
    return root


def _snapshot(root):
    """Every object's path, kind, size and CONTENT -- the disk is the verdict."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        out[str(p.relative_to(root))] = ("d", 0, b"") if p.is_dir() else (
            "f", p.stat().st_size, p.read_bytes())
    return out


def _reset(tmp_path, root):
    assert _under_temp(root) and str(Path(root).resolve()).lower().startswith(
        str(tmp_path.resolve()).lower()), root
    if Path(root).exists():
        x4refguard._mutate_run(["icacls", root, "/reset", "/T", "/C", "/Q"], root)


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    assert _under_temp(tmp_path)
    monkeypatch.setenv(x4refguard.SANDBOX_ENV, str(tmp_path))
    # FX-B2: NO real config. Without this the resolver read the CHECKOUT's own x4-paths.env --
    # on a developer machine a real one, whose X4_REFERENCE differs from the scratch tree the
    # tests export, and an apply/remove then (correctly) refuses on the disagreement. An
    # X4_CONFIG naming no file means "read none": the exported X4_REFERENCE is the config.
    monkeypatch.setenv("X4_CONFIG", str(tmp_path / "no-x4-paths.env"))
    monkeypatch.setattr(_paths, "_NOTICED", set(), raising=False)
    _paths.reload()
    yield
    _paths.reload()


@pytest.fixture
def protected(tmp_path, monkeypatch):
    root = _tree(tmp_path / "reference")
    own_or_skip(root, x4refguard)          # an elevated runner creates it owned by Administrators
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    try:
        assert x4refguard.main(["apply", "--yes"]) == 0
        assert x4refguard.report()["state"] == "protected"
        yield root
    finally:
        _reset(tmp_path, root)
        _reset(tmp_path, tmp_path / "reference.old")
        _paths.reload()


@pytest.mark.parametrize("name", sorted(PRIMS))
def test_the_deny_STOPS(name, protected):
    before = _snapshot(protected)
    PRIMS[name](protected, {**os.environ, "T": str(protected)})
    assert _snapshot(protected) == before, name + " changed the tree under the deny"


@pytest.mark.parametrize("name", sorted(PRIMS))
def test_CONTROL_the_primitive_changes_an_unprotected_tree(name, tmp_path):
    root = _tree(tmp_path / "plain")
    before = _snapshot(root)
    PRIMS[name](root, {**os.environ, "T": str(root)})
    assert _snapshot(root) != before, name + " changed nothing even unprotected: the PROBE is broken"


def test_del_fq_EXITS_0_while_blocked__which_is_why_rc_is_never_the_verdict(protected):
    before = _snapshot(protected)
    r = _cmd('cmd /c del /f /q "%T%\\libraries\\wares.xml"', {**os.environ, "T": str(protected)})
    assert _snapshot(protected) == before          # blocked, by the disk
    assert r.returncode == 0                       # ... and rc says "fine" (MEASURED 2026-10-02)


def test_reads_still_work(protected, tmp_path):
    f = protected / "libraries" / "wares.xml"
    assert f.read_text(encoding="utf-8") == ORIG
    assert f.read_bytes() == ORIG.encode()
    out = subprocess.run(["cmd", "/c", "type", str(f)], capture_output=True)
    assert out.stdout.decode().strip() == ORIG
    ps = _ps('Get-Content -Raw -LiteralPath "$env:T\\libraries\\wares.xml"',
             {**os.environ, "T": str(protected)})
    assert ps.stdout.decode().strip() == ORIG
    # a copy OUT of reference/ (into dev/) carries no deny and is fully usable
    dst = tmp_path / "dev" / "wares.xml"
    dst.parent.mkdir()
    shutil.copy2(f, dst)
    dst.write_text("edited", encoding="utf-8")
    assert dst.read_text(encoding="utf-8") == "edited"
    dst.unlink()
    assert not dst.exists()


def test_apply_and_remove_move_no_mtime_or_size(tmp_path, monkeypatch):   # the _freshness axes
    root = _tree(tmp_path / "reference")
    own_or_skip(root, x4refguard)

    def stamp():
        return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}
    before = stamp()
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    try:
        assert x4refguard.main(["apply", "--yes"]) == 0
        mid = stamp()
        assert x4refguard.main(["remove", "--yes"]) == 0
    finally:
        _reset(tmp_path, root)
        _paths.reload()
    assert mid == before and stamp() == before and len(before) == 3


def test_KNOWN_GAP_the_ROOT_itself_can_be_renamed(protected, tmp_path):
    # MEASURED (M-e): the PARENT grants delete-child, so the root renames. Pinned, not fixed:
    # status must then say the configured root is gone -- never "protected" -- and the
    # children inside the renamed tree still refuse deletion.
    old = tmp_path / "reference.old"
    os.rename(protected, old)
    assert old.is_dir() and not protected.exists()
    r = x4refguard.report()
    assert r["state"] == "unconfigured" and "does not exist" in r["detail"]
    assert x4refguard.main(["status"]) == 2
    _try(os.remove, old / "libraries" / "wares.xml")
    assert (old / "libraries" / "wares.xml").read_text(encoding="utf-8") == ORIG
