r"""x4refguard must refuse every target that is not the configured, unpacked reference root,
and must never report "protected" for a state it did not confirm.

THE REAL REFERENCE TREE IS NEVER TOUCHED. Every test points X4_REFERENCE at a `tmp_path`
tree, and the autouse `_sandbox` fixture sets `X4_REFGUARD_SANDBOX` to that `tmp_path`:
x4refguard then refuses (SandboxViolation, which no `except Exception` swallows) every
mutating call -- icacls, chattr, chflags, chmod -- aimed anywhere else. The sandbox is
itself asserted to sit under the system temp dir before any test body runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("x4refguard", REPO / "scripts" / "x4refguard.py")
x4refguard = importlib.util.module_from_spec(_spec)
sys.modules["x4refguard"] = x4refguard
_spec.loader.exec_module(x4refguard)
from x4validate import _paths  # noqa: E402

SENTINEL = ".unpacked-and-locked"


def _under_temp(p: Path) -> bool:
    tmp = os.path.normcase(str(Path(tempfile.gettempdir()).resolve()))
    q = os.path.normcase(str(Path(p).resolve()))
    return q != tmp and q.startswith(tmp + os.sep)


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    assert _under_temp(tmp_path), "pytest tmp_path is not under the system temp dir: %s" % tmp_path
    monkeypatch.setenv(x4refguard.SANDBOX_ENV, str(tmp_path))
    yield


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    (root / "libraries").mkdir(parents=True)
    (root / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    (root / SENTINEL).write_text("Re-unpacked from X4 (steam buildid 1) on 2026-10-02.", encoding="utf-8")
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    yield root
    _paths.reload()


# ------------------------------------------------------------- Task 2: resolution

def test_resolve_returns_the_configured_root(ref):
    assert x4refguard.resolve_target(None, action="apply") == ref.resolve()


def test_a_path_that_is_not_the_configured_root_is_REFUSED(ref, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / SENTINEL).write_text("x")
    with pytest.raises(x4refguard.Refused, match="not the configured reference root"):
        x4refguard.resolve_target(other, action="apply")


def test_case_and_slash_variants_of_the_configured_root_are_ACCEPTED(ref):
    variant = Path(str(ref).replace("\\", "/"))
    if os.name == "nt":
        variant = Path(str(variant).upper())
    assert x4refguard.resolve_target(variant, action="apply") == ref.resolve()


def test_apply_REFUSES_a_root_without_the_sentinel(ref):
    (ref / SENTINEL).unlink()
    with pytest.raises(x4refguard.Refused, match="sentinel"):
        x4refguard.resolve_target(None, action="apply")


def test_remove_does_NOT_need_the_sentinel(ref):        # the escape hatch must always work
    (ref / SENTINEL).unlink()
    assert x4refguard.resolve_target(None, action="remove") == ref.resolve()


def test_apply_REFUSES_a_root_that_is_not_a_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("X4_REFERENCE", str(tmp_path / "nope"))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="not an existing directory"):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()


@pytest.mark.parametrize("bad", ["drive_root", "home", "home_parent", "git_root"])
def test_apply_REFUSES_dangerous_roots_even_when_configured(bad, tmp_path, monkeypatch):
    if bad == "drive_root":
        root = Path(Path.cwd().anchor)
    elif bad == "home":
        root = Path.home()
    elif bad == "home_parent":
        root = Path.home().parent
    else:
        root = tmp_path / "repo"
        (root / ".git").mkdir(parents=True)
        (root / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()


def test_the_git_root_refusal_is_the_git_clause_not_the_sentinel(tmp_path, monkeypatch):
    # Falsification twin of the git_root row: WITH the sentinel present, only the `.git`
    # clause can refuse it -- and without `.git` the same tree resolves.
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="git"):
            x4refguard.resolve_target(None, action="apply")
        (root / ".git").rmdir()
        assert x4refguard.resolve_target(None, action="apply") == root.resolve()
    finally:
        _paths.reload()


def test_apply_REFUSES_the_game_root(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    (game / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(game))
    monkeypatch.setenv("X4_GAME", str(game))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="game"):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()


def test_apply_REFUSES_an_ancestor_of_the_game_root(tmp_path, monkeypatch):
    game = tmp_path / "steam" / "game"
    game.mkdir(parents=True)
    (tmp_path / "steam" / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(tmp_path / "steam"))
    monkeypatch.setenv("X4_GAME", str(game))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="game"):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()


def test_apply_REFUSES_the_toolkit_root(monkeypatch):
    # The toolkit itself is a git checkout too, so this asserts the TOOLKIT clause by name.
    monkeypatch.setenv("X4_REFERENCE", str(REPO))
    _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="toolkit"):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()


def test_UNCONFIGURED_is_exit_2_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(x4refguard, "_configured_root", lambda: None)
    rc = x4refguard.main(["status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["state"] == "unconfigured"
    assert x4refguard.main(["apply"]) == 2
    assert x4refguard.main(["remove"]) == 2


def test_a_paths_IMPORT_failure_is_never_unconfigured_by_accident(monkeypatch):
    # x4lock's Unresolvable rule: "could not look" must not read as "nothing configured".
    monkeypatch.setattr(x4refguard, "_paths", None)
    with pytest.raises(x4refguard.Unresolvable):
        x4refguard._configured_root()


def test_an_unknown_platform_is_UNSUPPORTED_exit_3_never_protected(ref, monkeypatch, capsys):
    # Decision #15: exit 3 is ONLY for a platform with no mechanism at all. PIN, not skip.
    monkeypatch.setattr(x4refguard, "_platform", lambda: "sunos5")
    rc = x4refguard.main(["status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 3 and out["state"] == "unsupported"
    assert x4refguard.main(["apply"]) == 3
    assert x4refguard.main(["remove"]) == 3


def test_status_json_is_ONE_object_even_when_refusing(monkeypatch, capsys):
    monkeypatch.setattr(x4refguard, "_configured_root", lambda: None)
    x4refguard.main(["status", "--json"])
    out = capsys.readouterr().out.strip()
    assert out.count("\n") == 0
    obj = json.loads(out)
    for key in ("state", "root", "mask", "mask_expected", "sentinel", "owner_is_user",
                "sampled", "sample_ok", "sample_scope", "detail", "mechanism",
                "stops", "does_not_stop"):
        assert key in obj, key
