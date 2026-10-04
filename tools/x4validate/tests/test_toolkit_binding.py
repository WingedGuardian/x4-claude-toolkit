r"""B2 (install red-team, 2026-10-04): a script or tool acts for the toolkit it LIVES IN.

THE INCIDENT. A cold red-team installed a second toolkit copy (B) in a scratch folder, in a
shell that had inherited `X4_TOOLKIT` pointing at the user's real toolkit (A). It ran B's
`x4refguard.py apply`. B's script imported B's `_paths`, which located the config through
`$X4_TOOLKIT` -- A's -- and so resolved A's `X4_REFERENCE`: the user's REAL reference tree.
It was killed after ~2 minutes; a full census afterwards found nothing applied.

THE POLICY (DECISIONS.md, lane FX-R; binding):
  * a script/tool acts for the toolkit it lives in;
  * if $X4_TOOLKIT names a different directory, ONE line names both roots;
  * system-changing commands (x4refguard apply/remove, x4config migrate --apply,
    x4lock lock/unlock) REFUSE unless --toolkit is passed explicitly.

EVERY PROBE HERE RUNS IN SCRATCH. Two toolkit copies are built under tmp_path; X4_TOOLKIT,
X4_CONFIG and X4_REFERENCE are always set explicitly (the last two to "", which every loader
treats as unset), and X4_REFGUARD_SANDBOX confines every mutating call to B's own tree -- so a
regression that aimed at A raises SandboxViolation instead of touching anything.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from x4validate import _paths

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "tools" / "x4validate" / "x4validate"


def _under_temp(p: Path) -> bool:
    tmp = os.path.normcase(str(Path(tempfile.gettempdir()).resolve()))
    q = os.path.normcase(str(Path(p).resolve()))
    return q != tmp and q.startswith(tmp + os.sep)


def _kit(root: Path, ref_name: str | None) -> Path:
    """A toolkit copy: the package, the three system-changing scripts, a config naming its OWN
    reference tree (a finished unpack: sentinel present), or no config at all."""
    shutil.copytree(PKG, root / "tools" / "x4validate" / "x4validate",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (root / "scripts").mkdir(parents=True)
    for s in ("x4refguard.py", "x4config.py", "x4lock.py"):
        shutil.copy2(REPO / "scripts" / s, root / "scripts" / s)
    if ref_name is not None:
        ref = root / ref_name
        (ref / "libraries").mkdir(parents=True)
        (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
        (ref / ".unpacked-and-locked").write_text("buildid 1", encoding="utf-8")
        (root / "x4-paths.env").write_text(
            'X4_REFERENCE="%s"\n' % ref.as_posix(), encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def kits(tmp_path):
    assert _under_temp(tmp_path)
    a = _kit(tmp_path / "A", "refA")
    b = _kit(tmp_path / "B", "refB")
    return a, b


def _env(x4_toolkit, sandbox: Path) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith("X4_")}
    e.update(X4_CONFIG="", X4_REFERENCE="", X4_REFGUARD_SANDBOX=str(sandbox),
             PYTHONDONTWRITEBYTECODE="1")
    if x4_toolkit is not None:
        e["X4_TOOLKIT"] = str(x4_toolkit)
    return e


def _run(kit: Path, script: str, *args, env) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(kit / "scripts" / script), *args],
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                          timeout=120)


def _status_root(r) -> str:
    return os.path.normcase(str(Path(json.loads(r.stdout)["root"]).resolve()))


def _nc(p: Path) -> str:
    return os.path.normcase(str(p.resolve()))


# ------------------------------------------------------------ the incident, recreated

def test_INCIDENT_B_status_acts_for_B_and_names_both_roots(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "status", "--json", env=_env(a, b))
    assert _status_root(r) == _nc(b / "refB"), (
        "B's x4refguard resolved %s -- with X4_TOOLKIT=A it must still act for B" % r.stdout)
    lines = [ln for ln in r.stderr.splitlines() if str(a) in ln and str(b) in ln]
    assert len(lines) == 1, "expected ONE notice line naming both roots:\n" + r.stderr


def test_INCIDENT_B_apply_without_toolkit_REFUSES_rc2_and_touches_nothing(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "apply", "--yes", env=_env(a, b))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "--toolkit" in r.stderr, r.stderr
    assert "SandboxViolation" not in r.stderr, "it reached a mutating call: " + r.stderr


def test_INCIDENT_B_remove_without_toolkit_REFUSES_rc2(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "remove", "--yes", env=_env(a, b))
    assert r.returncode == 2 and "--toolkit" in r.stderr, (r.returncode, r.stderr)


def test_INCIDENT_B_without_its_own_config_never_derives_A_reference(tmp_path):
    """The derivation `<X4_TOOLKIT>/reference` was the second route to A's tree: B with no
    config at all must derive from B, never from the inherited X4_TOOLKIT."""
    a = _kit(tmp_path / "A", None)
    (a / "reference").mkdir()
    b = _kit(tmp_path / "B", None)
    r = _run(b, "x4refguard.py", "status", "--json", env=_env(a, b))
    root = json.loads(r.stdout)["root"]
    assert root is None or _nc(Path(root)) != _nc(a / "reference"), r.stdout


def test_twin_X4_TOOLKIT_naming_B_itself_prints_no_notice_and_is_not_refused(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "remove", env=_env(b, b))
    # nothing is applied on refB, so remove is a verified no-op: rc 0, no confirmation needed
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert str(a) not in r.stderr and "--toolkit" not in r.stderr, r.stderr


def test_twin_X4_TOOLKIT_unset_acts_for_B(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "status", "--json", env=_env(None, b))
    assert _status_root(r) == _nc(b / "refB"), r.stdout
    assert "X4_TOOLKIT" not in r.stderr, r.stderr


def test_explicit_toolkit_B_is_accepted_for_a_mutating_op(kits):
    a, b = kits
    r = _run(b, "x4refguard.py", "remove", "--toolkit", str(b), env=_env(a, b))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "nothing to remove" in r.stdout and str(b / "refB").lower() in r.stdout.lower(), r.stdout


@pytest.mark.skipif(os.name != "nt", reason="the real Windows apply (icacls) on scratch")
def test_explicit_toolkit_B_apply_protects_B_and_never_A(kits, tmp_path):
    a, b = kits
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from refguard_owner import own_or_skip
    import importlib.util
    spec = importlib.util.spec_from_file_location("x4refguard_b2", REPO / "scripts" / "x4refguard.py")
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    old = os.environ.get(rg.SANDBOX_ENV)
    os.environ[rg.SANDBOX_ENV] = str(b)
    try:
        own_or_skip(b / "refB", rg)
        r = _run(b, "x4refguard.py", "apply", "--toolkit", str(b), "--yes", env=_env(a, b))
        try:
            assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
            sa = _run(a, "x4refguard.py", "status", "--json", env=_env(a, a))
            assert json.loads(sa.stdout)["state"] == "absent", sa.stdout
            sb = _run(b, "x4refguard.py", "status", "--json", env=_env(b, b))
            assert json.loads(sb.stdout)["state"] == "protected", sb.stdout
        finally:
            rg._mutate_run(["icacls", b / "refB", "/reset", "/T", "/C", "/Q"], b / "refB")
    finally:
        if old is None:
            os.environ.pop(rg.SANDBOX_ENV, None)
        else:
            os.environ[rg.SANDBOX_ENV] = old


# ------------------------------------------------------- the other system-changing commands

def test_x4config_migrate_apply_REFUSES_under_a_foreign_X4_TOOLKIT(kits):
    a, b = kits
    legacy = b / ".claude" / "x4-paths.env"
    legacy.parent.mkdir()
    (b / "x4-paths.env").rename(legacy)
    r = _run(b, "x4config.py", "migrate", "--apply", env=_env(a, b))
    assert r.returncode == 2 and "--toolkit" in r.stderr, (r.returncode, r.stdout, r.stderr)
    assert legacy.is_file() and not (b / "x4-paths.env").exists(), "it moved a file anyway"


def test_x4config_migrate_DRY_RUN_is_allowed_and_looks_at_B(kits):
    a, b = kits
    legacy = b / ".claude" / "x4-paths.env"
    legacy.parent.mkdir()
    (b / "x4-paths.env").rename(legacy)
    r = _run(b, "x4config.py", "migrate", env=_env(a, b))
    assert r.returncode == 0 and str(legacy) in r.stdout, (r.returncode, r.stdout, r.stderr)


def test_x4config_migrate_apply_with_explicit_toolkit_acts_for_it(kits):
    a, b = kits
    legacy = b / ".claude" / "x4-paths.env"
    legacy.parent.mkdir()
    (b / "x4-paths.env").rename(legacy)
    r = _run(b, "x4config.py", "migrate", "--apply", "--toolkit", str(b), env=_env(a, b))
    assert r.returncode == 0 and (b / "x4-paths.env").is_file(), (r.stdout, r.stderr)


@pytest.mark.parametrize("args", [("lock",), ("unlock", "--all")])
def test_x4lock_lock_and_unlock_REFUSE_under_a_foreign_X4_TOOLKIT(kits, args):
    a, b = kits
    cfg = b / "x4-paths.env"
    r = _run(b, "x4lock.py", *args, env=_env(a, b))
    assert r.returncode == 2 and "--toolkit" in r.stderr, (r.returncode, r.stdout, r.stderr)
    assert os.access(cfg, os.W_OK), "x4lock locked a file although it refused"


def test_x4lock_status_is_read_only_and_allowed(kits):
    a, b = kits
    r = _run(b, "x4lock.py", "status", env=_env(a, b))
    assert "--toolkit" not in r.stderr or "REFUS" not in r.stderr, r.stderr


# ------------------------------------------------------------- _paths, in process

@pytest.fixture
def clean(monkeypatch):
    for k in [k for k in os.environ if k.startswith("X4_")]:
        monkeypatch.delenv(k)
    monkeypatch.setattr(_paths, "_NOTICED", set(), raising=False)
    monkeypatch.setattr(_paths, "_EXPLICIT", None, raising=False)
    _paths.reload()
    yield
    _paths.reload()


def test_self_root_is_the_toolkit_this_module_lives_in(clean):
    assert _paths.self_toolkit() == REPO


def test_toolkit_root_ignores_a_foreign_X4_TOOLKIT(clean, monkeypatch, tmp_path):
    monkeypatch.setenv("X4_TOOLKIT", str(tmp_path))
    assert _paths.toolkit_root() == REPO
    assert _paths.toolkit_conflict() == (REPO, tmp_path)


def test_no_conflict_when_X4_TOOLKIT_names_this_toolkit(clean, monkeypatch):
    monkeypatch.setenv("X4_TOOLKIT", str(REPO))
    assert _paths.toolkit_conflict() is None


def test_the_env_layer_derives_reference_from_the_ACTING_toolkit(clean, monkeypatch, tmp_path):
    monkeypatch.setenv("X4_TOOLKIT", str(tmp_path))
    monkeypatch.setattr(_paths, "_SELF", tmp_path / "self", raising=False)
    _paths.reload()
    assert _paths.reference() == tmp_path / "self" / "reference"


def test_explicit_toolkit_wins_and_clears_the_refusal(clean, monkeypatch, tmp_path):
    monkeypatch.setenv("X4_TOOLKIT", str(tmp_path))
    assert _paths.foreign_toolkit_refusal("apply") is not None
    _paths.use_toolkit(tmp_path)
    assert _paths.toolkit_root() == tmp_path
    assert _paths.foreign_toolkit_refusal("apply") is None


def test_outside_a_toolkit_X4_TOOLKIT_still_decides(clean, monkeypatch, tmp_path):
    """A package installed outside any toolkit (no tools/x4validate/x4validate shape) has no
    'own' toolkit: X4_TOOLKIT is then the only answer, as before."""
    monkeypatch.setattr(_paths, "_SELF", None, raising=False)
    monkeypatch.setenv("X4_TOOLKIT", str(tmp_path))
    assert _paths.toolkit_root() == tmp_path and _paths.toolkit_conflict() is None
