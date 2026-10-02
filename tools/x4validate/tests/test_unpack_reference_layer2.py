r"""`bin/unpack-reference.sh` and Layer 2: it must never lock anyone out of a re-unpack,
must never lift the protection itself, and must apply it after a verified unpack.

ISOLATION, ASSERTED BEFORE ANY WRITE. `_x4-env.sh` lets an exported X4_* win over the
config file (READ: its header + snapshot/restore block), and X4_TOOLKIT points at a
tmp dir with no `.claude/x4-paths.env`, so no real config is in play. Every run's banner
line `Reference: <path>` is checked against tmp_path -- the fake xrcat refuses to write
anywhere else, so a misresolved reference fails the run instead of touching a real tree.
X4_REFGUARD_SANDBOX confines x4refguard's own mutating calls to tmp_path.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
UNPACK = REPO / "bin" / "unpack-reference.sh"
GUARD = REPO / "scripts" / "x4refguard.py"


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


gitbash = _load("gitbash_up", "scripts/gitbash.py")
x4refguard = _load("x4refguard", "scripts/x4refguard.py")

win = pytest.mark.skipif(os.name != "nt", reason="the Windows deny (POSIX path: test_the_sentinel...)")


def _under_temp(p) -> bool:
    tmp = os.path.normcase(str(Path(tempfile.gettempdir()).resolve()))
    return os.path.normcase(str(Path(p).resolve())).startswith(tmp + os.sep)


def _env(tmp_path, ref, **kw):
    assert _under_temp(tmp_path) and _under_temp(ref)
    game = tmp_path / "game"
    game.mkdir(exist_ok=True)
    (game / "01.cat").write_text("")
    toolkit = tmp_path / "toolkit"
    (toolkit / ".claude").mkdir(parents=True, exist_ok=True)
    fake = tmp_path / "fakexrcat"
    # The fake REFUSES any -out outside the scratch tree: the second, independent stop.
    fake.write_text(
        '#!/usr/bin/env bash\n'
        'while [ $# -gt 0 ]; do [ "$1" = -out ] && o="$2"; shift; done\n'
        'od=$(cd "$o" 2>/dev/null && pwd) || { echo "FAKE XRCAT: no -out dir $o" >&2; exit 96; }\n'
        'case "$od/" in "$SCRATCH"/*) ;; *) echo "FAKE XRCAT: refusing -out $od" >&2; exit 97;; esac\n'
        'mkdir -p "$o/libraries"; for i in 1 2 3 4 5; do echo x > "$o/libraries/f$i.xml"; done\n',
        encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    scratch = subprocess.run([gitbash.find_bash() or "bash", "-c", 'cd "$1" && pwd', "_", str(tmp_path)],
                             capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "X4_GAME": str(game), "X4_REFERENCE": str(ref), "X4_XRCAT": str(fake),
           "X4_UNPACK_FLOOR": "1", "X4_TOOLKIT": str(toolkit), "SCRATCH": scratch,
           x4refguard.SANDBOX_ENV: str(tmp_path), **kw}
    for k in ("X4_APPMANIFEST", "X4_FORCE_UNPACK", "X4_REFGUARD_SCRIPT", "X4_CONFIG"):
        if k not in kw:
            env.pop(k, None)
    return env


def _run(env, ref):
    b = gitbash.find_bash()
    if not b:
        pytest.skip("no Git Bash")
    r = subprocess.run([b, str(UNPACK)], env=env, capture_output=True, text=True, errors="replace")
    m = re.search(r"^Reference: (.*)$", r.stdout, re.M)
    if m:   # the banner is printed only once the script gets past its refusals
        assert os.path.normcase(m.group(1).strip().replace("/", os.sep)) == \
            os.path.normcase(str(ref)), ("the script resolved a different reference", m.group(1), ref)
    return r


def _guard(env, *args):
    return subprocess.run([sys.executable, str(GUARD), *args], env=env, capture_output=True,
                          text=True, errors="replace")


def _unprotect(tmp_path, ref):
    if not Path(ref).exists():
        return
    assert str(Path(ref).resolve()).lower().startswith(str(tmp_path.resolve()).lower())
    if os.name == "nt":
        x4refguard._mutate_run(["icacls", ref, "/reset", "/T", "/C", "/Q"], ref)
    else:
        for p in [Path(ref), *Path(ref).rglob("*")]:
            if not p.is_symlink():
                x4refguard._mutate_chmod(p, (p.stat().st_mode & 0o7777) | 0o200)


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    assert _under_temp(tmp_path)
    monkeypatch.setenv(x4refguard.SANDBOX_ENV, str(tmp_path))


def test_the_xrcat_override_is_honoured_and_the_unpack_lands_in_tmp(tmp_path):
    # Also the precondition every other test here relies on.
    ref = tmp_path / "reference"
    env = _env(tmp_path, ref)
    try:
        r = _run(env, ref)
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(list((ref / "libraries").glob("f*.xml"))) == 5
        assert (ref / ".unpacked-and-locked").is_file()
    finally:
        _unprotect(tmp_path, ref)


def test_a_plain_rerun_REFUSES_and_names_the_lift_first(tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / ".unpacked-and-locked").write_text("buildid 1")
    r = _run(_env(tmp_path, ref), ref)
    assert r.returncode == 2
    assert "x4refguard.py remove" in r.stderr and ".unpacked-and-locked" in r.stderr
    assert r.stderr.index("x4refguard.py remove") < r.stderr.index("rm ")


@win
def test_FORCE_unpack_REFUSES_while_the_deny_is_on_and_names_the_lift(tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / ".unpacked-and-locked").write_text("buildid 1")
    env = _env(tmp_path, ref)
    assert _guard(env, "apply").returncode == 0
    try:
        r = _run({**env, "X4_FORCE_UNPACK": "1"}, ref)
        assert r.returncode == 2 and "x4refguard.py remove" in r.stderr, r.stdout + r.stderr
        assert not (ref / "libraries").exists()          # it never started extracting
        assert _guard(env, "status", "--json").stdout.count('"state": "protected"') == 1
    finally:
        _unprotect(tmp_path, ref)


@win
def test_FORCE_unpack_WITHOUT_the_deny_still_runs(tmp_path):
    # Falsification twin: the refusal above is the deny clause, not X4_FORCE_UNPACK itself.
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / ".unpacked-and-locked").write_text("buildid 1")
    env = _env(tmp_path, ref)
    try:
        r = _run({**env, "X4_FORCE_UNPACK": "1"}, ref)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        _unprotect(tmp_path, ref)


@win
def test_a_fresh_unpack_ends_PROTECTED_and_the_lift_then_rm_path_works(tmp_path):
    ref = tmp_path / "reference"
    env = _env(tmp_path, ref)
    try:
        r = _run(env, ref)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Layer 2: reference/ protected" in r.stdout
        assert '"state": "protected"' in _guard(env, "status", "--json").stdout
        # THE ESCAPE HATCH, end to end (D8): lift, rm sentinel, re-unpack succeeds.
        assert _guard(env, "remove").returncode == 0
        (ref / ".unpacked-and-locked").unlink()
        r2 = _run(env, ref)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert '"state": "protected"' in _guard(env, "status", "--json").stdout
    finally:
        _unprotect(tmp_path, ref)


def test_a_FAILED_apply_is_exit_1_and_loud_but_the_unpack_stays(tmp_path):
    ref = tmp_path / "reference"
    # A sandbox that excludes the reference makes every mutating call of x4refguard raise
    # -- a real failure of the apply step, with no stub.
    other = tmp_path / "elsewhere"
    other.mkdir()
    env = _env(tmp_path, ref, **{x4refguard.SANDBOX_ENV: str(other)})
    try:
        r = _run(env, ref)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "Layer 2: FAILED" in r.stderr
        assert (ref / ".unpacked-and-locked").is_file() and (ref / "libraries" / "f1.xml").is_file()
    finally:
        _unprotect(tmp_path, ref)


def test_the_sentinel_still_parses_and_names_the_lift(tmp_path):
    ref = tmp_path / "reference"
    acf = tmp_path / "appmanifest_392160.acf"
    acf.write_text('"AppState"\n{\n\t"appid"\t\t"392160"\n\t"buildid"\t\t"23660954"\n}\n',
                   encoding="utf-8", newline="\n")
    env = _env(tmp_path, ref, X4_APPMANIFEST=str(acf))
    try:
        r = _run(env, ref)
        assert r.returncode == 0, r.stdout + r.stderr
        text = (ref / ".unpacked-and-locked").read_text(encoding="utf-8")
        # the parser in check-reference-version.sh: the FIRST buildid[^0-9]*[0-9]+
        assert re.search(r"buildid[^0-9]*([0-9]+)", text).group(1) == "23660954"
        assert "x4refguard.py remove" in text
        assert "Layer 2:" in r.stdout
    finally:
        _unprotect(tmp_path, ref)


def test_an_UNSUPPORTED_platform_continues_with_exit_0(tmp_path):
    # exit 3 from x4refguard is a disclosed gap, not a failure of the unpack. Driven by a
    # stub guard so the branch is reachable on every OS.
    ref = tmp_path / "reference"
    stub = tmp_path / "stubguard.py"
    stub.write_text("import sys\nprint('unsupported')\nsys.exit(3)\n", encoding="utf-8")
    env = _env(tmp_path, ref, X4_REFGUARD_SCRIPT=str(stub))
    try:
        r = _run(env, ref)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Layer 2: not available on this OS" in r.stdout
    finally:
        _unprotect(tmp_path, ref)
