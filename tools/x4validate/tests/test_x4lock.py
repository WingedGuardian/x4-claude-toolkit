r"""`x4lock` must actually stop a write, and must never claim a lock it did not verify.

WHY. Four irreplaceable files were destroyed here in twelve days by writes from inside
other processes -- where a command-string hook cannot see them. The read-only attribute
is the only layer that can. This pins what it does and, just as importantly, what it
does NOT do, so the docstring's table cannot quietly drift from the behaviour.

THE CONTROL IS THE POINT. Every "blocked" row is paired with the same primitive run
against an UNLOCKED file. Without that pairing a broken probe reads as a working lock:
measured 2026-09-04, the `bash` on Windows PATH is the WSL stub, it cannot open a
`C:/...` path, and its failure was recorded as `rm -f` being blocked. It is not.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("x4lock", REPO / "scripts" / "x4lock.py")
x4lock = importlib.util.module_from_spec(_spec)
sys.modules["x4lock"] = x4lock
_spec.loader.exec_module(x4lock)


def _fresh(p: Path) -> Path:
    p.write_text("IRREPLACEABLE\n", encoding="utf-8")
    return p


def _intact(p: Path) -> bool:
    return p.is_file() and p.read_text(encoding="utf-8") == "IRREPLACEABLE\n"


#: Primitives the attribute is expected to stop. Deliberately the ones that have
#: actually destroyed a file in this workspace: python text writes and a copy.
BLOCKED = {
    "open_w": lambda p, tmp: open(p, "w", encoding="utf-8").write("x"),
    "write_text": lambda p, tmp: p.write_text("x", encoding="utf-8"),
    "write_bytes": lambda p, tmp: p.write_bytes(b"x"),
    "truncate": lambda p, tmp: os.truncate(p, 0),
    "os_replace": lambda p, tmp: os.replace(tmp, p),
    "copy2": lambda p, tmp: shutil.copy2(tmp, p),
    "os_remove": lambda p, tmp: os.remove(p),
}


#: Primitives the attribute stops ONLY on Windows. On POSIX, delete and rename-over
#: are authorised by write permission on the DIRECTORY, so the read-only bit is not
#: consulted at all. MEASURED on CI (ubuntu, run 33994180317): both DID NOT RAISE.
#: The docstring table in x4lock.py carries the same two rows marked WINDOWS ONLY.
WINDOWS_ONLY = {"os_remove", "os_replace"}


@pytest.mark.parametrize("name", sorted(BLOCKED))
def test_a_locked_file_survives(name, tmp_path):
    p = _fresh(tmp_path / (name + ".md"))
    src = tmp_path / (name + ".src")
    src.write_text("x", encoding="utf-8")
    ok, msg = x4lock._apply(p, True)
    assert ok, "the lock step itself failed: " + msg
    if os.name != "nt" and name in WINDOWS_ONLY:
        # PIN the weaker guarantee rather than skip it: if POSIX ever starts refusing
        # these, the table's WINDOWS ONLY marks are wrong and must be revisited. A skip
        # here would let the docstring drift from the behaviour in silence. (And no
        # bare `return`: the suite's own guard reads that as an un-named pass.)
        BLOCKED[name](p, str(src))            # must NOT raise on POSIX
        assert not _intact(p), (
            name + " was blocked on POSIX -- x4lock's table says it is Windows-only; "
            "re-measure and update the table rather than leaving it weaker than reality")
    else:
        with pytest.raises(OSError):
            BLOCKED[name](p, str(src))
        assert _intact(p), "a locked file was modified by " + name


@pytest.mark.parametrize("name", sorted(BLOCKED))
def test_the_control_proves_the_primitive_works_unlocked(name, tmp_path):
    """Without this, a probe that is simply broken reads as a working lock."""
    p = _fresh(tmp_path / (name + ".md"))
    src = tmp_path / (name + ".src")
    src.write_text("x", encoding="utf-8")
    BLOCKED[name](p, str(src))
    assert not _intact(p), name + " had no effect even UNLOCKED -- the probe is broken"


def test_unlock_restores_writability(tmp_path):
    """A lock that cannot be lifted is its own kind of damage."""
    p = _fresh(tmp_path / "a.md")
    assert x4lock._apply(p, True)[0]
    assert x4lock.is_locked(p)
    with pytest.raises(OSError):
        p.write_text("x", encoding="utf-8")
    assert x4lock._apply(p, False)[0]
    assert not x4lock.is_locked(p)
    p.write_text("y", encoding="utf-8")          # must not raise
    assert p.read_text(encoding="utf-8") == "y"


def test_state_reports_missing_rather_than_guessing(tmp_path):
    assert x4lock.state(tmp_path / "nope.md") == "missing"


def test_apply_verifies_and_refuses_to_claim_an_unconfirmed_lock(tmp_path, monkeypatch):
    """`chmod` can succeed on a filesystem that ignores the attribute. Reporting a
    lock that is not there is the worst outcome, so _apply re-reads the state."""
    p = _fresh(tmp_path / "a.md")
    monkeypatch.setattr(x4lock.Path, "chmod", lambda self, mode: None)  # a no-op chmod
    ok, msg = x4lock._apply(p, True)
    assert not ok and "verification" in msg, (
        "a chmod that did nothing was reported as a successful lock")


def test_cfg_refuses_a_name_that_does_not_exist():
    """The first draft used getattr(..., lambda: None) and silently built a two-file
    manifest from two typo'd names, reporting it as complete."""
    with pytest.raises(AttributeError, match="does not exist"):
        x4lock._cfg("definitely_not_a_paths_function")


def test_the_manifest_never_contains_a_directory_or_a_missing_path(tmp_path):
    for p in x4lock.manifest():
        assert p.is_file(), "manifest contains a non-file: " + str(p)


def test_extra_protected_paths_are_added_from_the_environment(tmp_path, monkeypatch):
    extra = _fresh(tmp_path / "site-specific.md")
    monkeypatch.setenv("X4_PROTECTED", str(extra))
    got = {str(p.resolve()).lower() for p in x4lock.manifest()}
    assert str(extra.resolve()).lower() in got


@pytest.mark.skipif(os.name != "nt", reason="the -Force gap is Windows-specific")
def test_the_KNOWN_GAP_is_still_the_gap(tmp_path):
    """Pins the documented limit. If PowerShell ever stops clearing the attribute this
    goes red, and the docstring's table -- and the layered defence built on it -- must
    be revisited rather than silently becoming stronger than claimed."""
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available; the gap cannot be measured here")
    p = _fresh(tmp_path / "gap.md")
    assert x4lock._apply(p, True)[0]
    r = subprocess.run(["pwsh", "-NoProfile", "-Command",
                        "Remove-Item -Force '%s'" % p], capture_output=True)
    assert r.returncode == 0 and not p.exists(), (
        "pwsh -Force no longer defeats the read-only attribute -- update x4lock's "
        "documented table and the guard layering that assumes this gap")


def test_a_sandbox_copy_of_a_LOCKED_file_is_writable(tmp_path):
    r"""A gate copies the user's registry into a throwaway sandbox and writes to it.

    `shutil.copy2` preserves permission bits, so once the real registry was locked for
    the first time the SANDBOX copy was read-only too and `registry_provenance` failed
    on its own scratch file -- protecting nothing and looking exactly like the tool
    being broken. MEASURED 2026-09-04, within minutes of the first lock.

    `_env.sandbox_copy` is the fix, and this pins it: a sandbox exists to be written,
    and the protection belongs to the original.
    """
    import shutil
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
    import _env

    src = _fresh(tmp_path / "protected.yaml")
    assert x4lock._apply(src, True)[0]

    naive = tmp_path / "naive.yaml"
    shutil.copy2(src, naive)
    assert x4lock.is_locked(naive), (
        "precondition: copy2 is supposed to carry the read-only bit; if it no longer "
        "does, this whole failure mode is gone and the helper may be unnecessary")

    good = _env.sandbox_copy(src, tmp_path / "sandbox" / "copy.yaml")
    assert not x4lock.is_locked(good), "sandbox_copy produced a read-only sandbox"
    good.write_text("written", encoding="utf-8")          # must not raise
    assert good.read_text(encoding="utf-8") == "written"
    assert x4lock.is_locked(src), "the ORIGINAL must still be protected"


def test_a_DELETED_protected_file_is_NAMED_not_dropped(tmp_path, monkeypatch):
    """`manifest()` filtered out anything that is not a file, so deleting a locked
    file simply made the manifest smaller and `status` printed a clean total.

    MEASURED 2026-09-04: 3 protected -> delete one -> "2 protected file(s): 2
    locked", exit 0. That matters more than it looks, because this module's own
    table names `rm -f` and `Remove-Item -Force` as the primitives the read-only
    bit does NOT stop -- deletion is the documented residual risk, and it was
    rendering as a clean sweep.
    """
    a = _fresh(tmp_path / "a.md")
    b = _fresh(tmp_path / "b.md")
    monkeypatch.setenv("X4_PROTECTED", os.pathsep.join([str(a), str(b)]))
    assert not [p for p in x4lock.missing() if p.name in ("a.md", "b.md")]
    b.unlink()
    gone = [p.name for p in x4lock.missing()]
    assert "b.md" in gone, "a deleted protected file must be NAMED, not dropped"
    assert "b.md" not in [p.name for p in x4lock.manifest()], (
        "manifest() still returns only lockable files -- absences belong to missing()")


def test_an_unimportable_paths_module_REFUSES(monkeypatch):
    """The ImportError fallback left `_paths = None`, and the manifest then held only
    this checkout's own x4-paths.env -- 1 of 26 on this machine -- reported as a
    complete, healthy manifest with exit 0. A partial manifest presented as whole is
    the narrowing-step-that-reports-success shape this tool exists to stop."""
    monkeypatch.setattr(x4lock, "_paths", None)
    with pytest.raises(x4lock.Unresolvable):
        x4lock.manifest()
    assert x4lock.main(["status"]) == 2


# --- F119: a LINKED git worktree has no checkout-local config, by design ------------- #
#
# `.claude/x4-paths.env` is gitignored per-machine config written by the installer, so a
# linked worktree never carries one -- and CLAUDE.md MANDATES a worktree per concurrent
# session. Demanding it there made every compliant session see a red `x4lock status`.
# The main checkout must still report a deleted one, a SUBMODULE (whose `.git` is also a
# file) is not a worktree, and the waiver must never cost the configured toolkit's copy.

def _checkout(tmp_path, kind: str) -> Path:
    """A checkout root shaped like git lays it out: `.git` a DIRECTORY for the main
    checkout, a FILE pointing into `<common>/.git/worktrees/<name>` for a linked
    worktree, and a FILE pointing into `.git/modules/<name>` for a submodule."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    if kind == "main":
        (root / ".git").mkdir()
    elif kind == "worktree":
        (root / ".git").write_text(
            "gitdir: C:/somewhere/toolkit/.git/worktrees/checkout\n", encoding="utf-8")
    elif kind == "submodule":
        (root / ".git").write_text("gitdir: ../.git/modules/checkout\n", encoding="utf-8")
    else:
        raise AssertionError(kind)
    return root


def _local_env(root: Path) -> Path:
    return root / ".claude" / "x4-paths.env"


def _named(paths, target: Path) -> bool:
    want = str(target.resolve()).lower()
    return any(str(p.resolve()).lower() == want for p in paths)


def test_a_linked_WORKTREE_does_not_demand_its_own_x4_paths_env(tmp_path, monkeypatch, capsys):
    root = _checkout(tmp_path, "worktree")
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    monkeypatch.delenv("X4_TOOLKIT", raising=False)
    assert not _named(x4lock.missing(), _local_env(root)), (
        "a linked worktree never has its own x4-paths.env; demanding it is F119")
    monkeypatch.setenv("X4_PROTECTED", str(_fresh(tmp_path / "protected.md")))
    x4lock.main(["status"])
    out = capsys.readouterr()
    assert "linked git worktree" in out.out, "the waiver must be ANNOUNCED, never silent"
    assert str(_local_env(root)) not in out.err


def test_the_MAIN_checkout_still_reports_a_deleted_x4_paths_env(tmp_path, monkeypatch, capsys):
    """The twin: without it, dropping the candidate for EVERY checkout would pass the
    test above and lose the only report of a deleted config in the main checkout."""
    root = _checkout(tmp_path, "main")
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    assert _named(x4lock.missing(), _local_env(root))
    monkeypatch.setenv("X4_PROTECTED", str(_fresh(tmp_path / "protected.md")))
    x4lock.main(["status"])
    assert "linked git worktree" not in capsys.readouterr().out


def test_a_SUBMODULE_is_not_a_worktree_and_still_demands_its_env(tmp_path, monkeypatch):
    """A submodule's `.git` is a FILE too. Treating every `.git` file as a worktree
    would waive the config of a toolkit vendored as a submodule."""
    root = _checkout(tmp_path, "submodule")
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    assert _named(x4lock.missing(), _local_env(root))


def test_a_worktree_env_file_that_DOES_exist_is_still_protected(tmp_path, monkeypatch):
    """The waiver covers ABSENCE only. A worktree that does carry a config keeps it in
    the manifest, where it gets locked like any other."""
    root = _checkout(tmp_path, "worktree")
    env = _local_env(root)
    env.parent.mkdir(parents=True)
    _fresh(env)
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    assert _named(x4lock.manifest(), env)


def test_a_worktree_still_demands_the_CONFIGURED_toolkits_env(tmp_path, monkeypatch):
    """When the worktree waiver applies, the config that matters is the one $X4_TOOLKIT
    names. `_paths._find_env_file` returns nothing for a DELETED file, so without an
    explicit candidate that deletion would be reported by nobody."""
    root = _checkout(tmp_path, "worktree")
    toolkit = tmp_path / "toolkit"
    (toolkit / ".claude").mkdir(parents=True)
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    monkeypatch.setenv("X4_TOOLKIT", str(toolkit))
    assert _named(x4lock.missing(), toolkit / ".claude" / "x4-paths.env")
    assert not _named(x4lock.missing(), _local_env(root))


def test_an_UNREADABLE_git_file_fails_closed(tmp_path, monkeypatch):
    """Anything that cannot be proven a linked worktree is treated as a checkout that
    should have its config -- a false MISSING is visible, a false waiver is not."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / ".git").write_text("not a gitdir line\n", encoding="utf-8")
    monkeypatch.setattr(x4lock, "_HERE", root / "scripts")
    assert _named(x4lock.missing(), _local_env(root))
