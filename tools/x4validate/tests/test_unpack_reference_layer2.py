r"""`bin/unpack-reference.sh` and Layer 2: it must never lock anyone out of a re-unpack,
must never lift the protection itself, and must apply it after a verified unpack.

ISOLATION, ASSERTED BEFORE ANY WRITE. `_x4-env.sh` lets an exported X4_* win over the
config file (READ: its header + snapshot/restore block), and X4_TOOLKIT points at a
tmp dir with no `x4-paths.env`, so no real config is in play. Every run's banner
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from refguard_owner import own_or_skip  # noqa: E402

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


def _run(env, ref, *args, explicit=False):
    """Run the unpack with EXACTLY *args*. `explicit=True` adds `--toolkit $X4_TOOLKIT` -- the
    script acts for the toolkit it LIVES in and refuses a foreign $X4_TOOLKIT otherwise (B2) --
    and every caller says so itself. It used to be the DEFAULT, described as "the installer's
    shape", while neither installer passed it (FX-B2): a default that supplies the very
    argument under test is how a test cannot go red. The installers' own call is pinned in
    test_installers_agree.py."""
    b = gitbash.find_bash()
    if not b:
        pytest.skip("no Git Bash")
    if explicit and env.get("X4_TOOLKIT") and "--toolkit" not in args:
        args = ("--toolkit", env["X4_TOOLKIT"], *args)
    r = subprocess.run([b, str(UNPACK), *args], env=env, capture_output=True, text=True,
                       errors="replace")
    m = re.search(r"^Reference: (.*)$", r.stdout, re.M)
    if m:   # the banner is printed only once the script gets past its refusals
        assert os.path.normcase(m.group(1).strip().replace("/", os.sep)) == \
            os.path.normcase(str(ref)), ("the script resolved a different reference", m.group(1), ref)
    return r


def _guard(env, *args):
    if args and args[0] in ("apply", "remove"):     # B3 confirmation; B2 explicit toolkit
        args = (*args, "--yes", "--toolkit", env["X4_TOOLKIT"])
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
        r = _run(env, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(list((ref / "libraries").glob("f*.xml"))) == 5
        assert (ref / ".unpacked-and-locked").is_file()
    finally:
        _unprotect(tmp_path, ref)


def test_a_plain_rerun_REFUSES_and_names_the_lift_first(tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / ".unpacked-and-locked").write_text("buildid 1")
    r = _run(_env(tmp_path, ref), ref, explicit=True)
    assert r.returncode == 2
    assert "x4refguard.py remove" in r.stderr and ".unpacked-and-locked" in r.stderr
    assert r.stderr.index("x4refguard.py remove") < r.stderr.index("rm ")


@win
def test_FORCE_unpack_REFUSES_while_the_deny_is_on_and_names_the_lift(tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / ".unpacked-and-locked").write_text("buildid 1")
    own_or_skip(ref, x4refguard)          # an elevated runner creates it owned by Administrators
    env = _env(tmp_path, ref)
    assert _guard(env, "apply").returncode == 0
    try:
        r = _run({**env, "X4_FORCE_UNPACK": "1"}, ref, explicit=True)
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
    own_or_skip(ref, x4refguard)          # an elevated runner creates it owned by Administrators
    env = _env(tmp_path, ref)
    try:
        r = _run({**env, "X4_FORCE_UNPACK": "1"}, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        _unprotect(tmp_path, ref)


@win
def test_a_fresh_unpack_ends_PROTECTED_and_the_lift_then_rm_path_works(tmp_path):
    ref = tmp_path / "reference"
    env = _env(tmp_path, ref)
    try:
        r = _run(env, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Layer 2: reference/ protected" in r.stdout
        assert '"state": "protected"' in _guard(env, "status", "--json").stdout
        # THE ESCAPE HATCH, end to end (D8): lift, rm sentinel, re-unpack succeeds.
        assert _guard(env, "remove").returncode == 0
        (ref / ".unpacked-and-locked").unlink()
        r2 = _run(env, ref, explicit=True)
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
        r = _run(env, ref, explicit=True)
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
        r = _run(env, ref, explicit=True)
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
        r = _run(env, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Layer 2: not available on this OS" in r.stdout
    finally:
        _unprotect(tmp_path, ref)


def test_an_UNREADABLE_layer2_state_on_an_existing_tree_REFUSES(tmp_path):
    """v4.0.0 review R4-10: x4refguard reporting `error` (the protection state could not be
    read) let the unpack PROCEED into a tree that may be protected -- failing file by file,
    part-way through. A state nobody could read is not 'unprotected': refuse and say why."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    stub = tmp_path / "stubguard.py"
    stub.write_text("import sys\nprint('{\"state\": \"error\"}')\nsys.exit(2)\n", encoding="utf-8")
    env = _env(tmp_path, ref, X4_REFGUARD_SCRIPT=str(stub))
    r = _run(env, ref, explicit=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSING" in r.stderr and "error" in r.stderr
    assert not (ref / "libraries" / "f1.xml").exists(), "the unpack ran"


def test_TWIN_an_ABSENT_layer2_on_an_existing_tree_still_unpacks(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    stub = tmp_path / "stubguard.py"
    stub.write_text("import sys\nprint('{\"state\": \"absent\"}')\nsys.exit(1)\n", encoding="utf-8")
    env = _env(tmp_path, ref, X4_REFGUARD_SCRIPT=str(stub))
    r = _run(env, ref, explicit=True)
    assert "REFUSING" not in r.stderr, r.stdout + r.stderr
    assert (ref / "libraries" / "f1.xml").exists()


# --------------------------------------------- B2 (install red-team 2026-10-04)

def test_B2_a_FOREIGN_X4_TOOLKIT_without_toolkit_REFUSES_before_writing(tmp_path):
    ref = tmp_path / "reference"
    env = _env(tmp_path, ref)                  # X4_TOOLKIT = tmp/toolkit, not this checkout
    r = _run(env, ref, explicit=False)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--toolkit" in r.stderr and str(REPO.name) in r.stderr, r.stderr
    assert not ref.exists(), "it unpacked anyway"


def test_B2_TWIN_X4_TOOLKIT_naming_this_toolkit_is_not_refused(tmp_path):
    ref = tmp_path / "reference"
    # FX-B2 (reviewer C): pin the config. X4_TOOLKIT=REPO made the loader read the CHECKOUT's
    # own x4-paths.env -- on a developer machine, a real one.
    cfg = tmp_path / "pinned.env"
    cfg.write_text('X4_REFERENCE="%s"\n' % ref.as_posix(), encoding="utf-8")
    env = _env(tmp_path, ref, X4_TOOLKIT=str(REPO), X4_CONFIG=str(cfg))
    try:
        # FX-B3: an X4_CONFIG outside the acting toolkit now refuses unless --reference
        # chooses the tree -- so the pin is paired with the explicit choice it needs.
        r = _run(env, ref, "--reference", str(ref), explicit=False)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--toolkit" not in r.stderr, r.stderr
    finally:
        _unprotect(tmp_path, ref)


def test_B3_the_unpack_confirms_its_own_apply_with_yes(tmp_path):
    """The user ran the unpack, whose job includes protecting the tree it just counted; it
    passes --yes so its apply never blocks on a question nobody can answer (B3)."""
    ref = tmp_path / "reference"
    stub = tmp_path / "stubguard.py"
    stub.write_text("import sys\nprint(' '.join(sys.argv[1:]))\nsys.exit(0)\n", encoding="utf-8")
    env = _env(tmp_path, ref, X4_REFGUARD_SCRIPT=str(stub))
    r = _run(env, ref, explicit=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(ln.startswith("apply") and "--yes" in ln and "--toolkit" in ln
               and "--reference" in ln for ln in r.stdout.splitlines()), r.stdout


# --------------------------------- FX-B2: an INHERITED X4_REFERENCE vs the toolkit's config

def _tk_with_config(tmp_path, cfg_ref):
    """A toolkit (tmp/toolkit) whose x4-paths.env names *cfg_ref*."""
    tk = tmp_path / "toolkit"
    (tk / ".claude").mkdir(parents=True, exist_ok=True)
    (tk / "x4-paths.env").write_text('X4_REFERENCE="%s"\n' % Path(cfg_ref).as_posix(),
                                     encoding="utf-8")
    return tk


def test_FXB2_an_INHERITED_X4_REFERENCE_differing_from_the_config_REFUSES(tmp_path):
    """X4_REFERENCE stays SET (F160's test blanked it): the inherited tree is NOT the config's,
    so the unpack must refuse naming both and --reference, and write neither."""
    ref, other = tmp_path / "reference", tmp_path / "inherited"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, other)               # X4_REFERENCE = the inherited, foreign tree
    r = _run(env, other, explicit=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "--reference" in r.stderr and "DIFFERENT" in r.stderr, r.stderr
    assert "inherited" in r.stderr and "reference" in r.stderr, r.stderr
    assert not other.exists() and not ref.exists(), "it unpacked anyway"


def test_FXB2_TWIN_an_inherited_X4_REFERENCE_EQUAL_to_the_config_proceeds(tmp_path):
    ref = tmp_path / "reference"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, ref)
    try:
        r = _run(env, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "DIFFERENT" not in r.stderr, r.stderr
    finally:
        _unprotect(tmp_path, ref)


def test_FXB2_TWIN_reference_chooses_the_tree_explicitly(tmp_path):
    ref, other = tmp_path / "reference", tmp_path / "inherited"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, other)
    try:
        r = _run(env, ref, "--reference", str(ref), explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (ref / "libraries" / "f1.xml").exists() and not other.exists()
    finally:
        _unprotect(tmp_path, ref)


def test_FXB2_an_EMPTY_layer2_state_on_an_existing_tree_REFUSES(tmp_path):
    """A guard that answers NOTHING (a crash, unparseable output) is a non-answer, not
    `absent` -- the TWIN is test_TWIN_an_ABSENT_layer2_on_an_existing_tree_still_unpacks."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    stub = tmp_path / "stubguard.py"
    stub.write_text("import sys\nprint('Traceback: boom')\nsys.exit(1)\n", encoding="utf-8")
    env = _env(tmp_path, ref, X4_REFGUARD_SCRIPT=str(stub))
    r = _run(env, ref, explicit=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSING" in r.stderr and "not a known state" in r.stderr, r.stderr
    assert not (ref / "libraries" / "f1.xml").exists(), "the unpack ran"


# ---------------------- FX-B3: an INHERITED X4_CONFIG, and refusals that can be pasted as-is

def _foreign_cfg(tmp_path, names):
    cfg = tmp_path / "elsewhere" / "x4-paths.env"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('X4_REFERENCE="%s"\n' % Path(names).as_posix(), encoding="utf-8")
    return cfg


def test_FXB3_an_X4_CONFIG_OUTSIDE_the_toolkit_REFUSES_and_writes_nothing(tmp_path):
    """The loader took "this toolkit's config" from $X4_CONFIG: naming another config made
    the unpack write -- and protect -- the tree THAT config names. X4_REFERENCE is unset."""
    ref, other = tmp_path / "reference", tmp_path / "theirs"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, other, X4_CONFIG=str(_foreign_cfg(tmp_path, other)))
    env.pop("X4_REFERENCE")
    r = subprocess.run([gitbash.find_bash() or pytest.skip("no Git Bash"), str(UNPACK),
                        "--toolkit", env["X4_TOOLKIT"]], env=env, capture_output=True,
                       text=True, errors="replace")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "X4_CONFIG" in r.stderr and "OUTSIDE" in r.stderr and "--reference" in r.stderr, r.stderr
    assert not other.exists() and not ref.exists(), "it unpacked anyway"


def test_FXB3_an_X4_CONFIG_naming_a_MISSING_file_REFUSES(tmp_path):
    ref = tmp_path / "reference"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, ref, X4_CONFIG=str(tmp_path / "nope.env"))
    r = _run(env, ref, explicit=True)
    assert r.returncode == 2 and "does not exist" in r.stderr, r.stdout + r.stderr
    assert not ref.exists(), "it unpacked anyway"


def test_FXB3_TWIN_X4_CONFIG_naming_the_toolkit_s_OWN_config_proceeds(tmp_path):
    ref = tmp_path / "reference"
    tk = _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, ref, X4_CONFIG=str(tk / "x4-paths.env"))
    try:
        r = _run(env, ref, explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "REFUSED" not in r.stderr, r.stderr
    finally:
        _unprotect(tmp_path, ref)


def test_FXB3_TWIN_reference_lifts_the_X4_CONFIG_refusal(tmp_path):
    ref, other = tmp_path / "reference", tmp_path / "theirs"
    _tk_with_config(tmp_path, ref)
    env = _env(tmp_path, ref, X4_CONFIG=str(_foreign_cfg(tmp_path, other)))
    try:
        r = _run(env, ref, "--reference", str(ref), explicit=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (ref / "libraries" / "f1.xml").exists() and not other.exists()
    finally:
        _unprotect(tmp_path, ref)


def test_FXB3_the_DIFFERENT_refusal_names_an_ABSOLUTE_command_with_toolkit(tmp_path):
    """Reviewer F M1: `bash bin/unpack-reference.sh --reference ...` ran only from the toolkit
    root, and without --toolkit a foreign X4_TOOLKIT refused it again."""
    ref, other = tmp_path / "reference", tmp_path / "inherited"
    tk = _tk_with_config(tmp_path, ref)
    r = _run(_env(tmp_path, other), other, explicit=True)
    assert r.returncode == 2, r.stdout + r.stderr
    lines = [ln for ln in r.stderr.splitlines() if "--reference" in ln and "unpack-reference.sh" in ln]
    assert len(lines) == 2, r.stderr
    for ln in lines:
        assert "bash bin/" not in ln and "--toolkit" in ln, ln
        cmd_path = ln.split('bash "', 1)[1].split('"', 1)[0]
        assert cmd_path.endswith("/unpack-reference.sh") and cmd_path.startswith("/"), ln


# ------------- FX-B4 #2 (reviewer I): bash and Python agree on WHICH config $X4_CONFIG names
#
# `_x4_canon` turned a bare relative path into `/<name>`, so `cd <toolkit>; X4_CONFIG=x4-paths.env
# bash bin/unpack-reference.sh` was refused as a foreign config while every Python command took
# it; `x4-paths.env/` and (Windows) `x4-paths.env.` were "missing" to bash and read by Python.
# Each row runs BOTH: the unpack (which stops at "game dir not found" once past the check --
# X4_GAME names nothing -- so nothing is ever written) and `_paths.config_conflict()`.

_PY_CONFLICT = r'''
import sys
sys.path.insert(0, sys.argv[1])
from x4validate import _paths
_paths.use_toolkit(sys.argv[2])
print("CONFLICT" if _paths.config_conflict() is not None else "NONE")
'''


def _agree_box(tmp_path):
    tk = tmp_path / "tk long"
    (tk / ".claude").mkdir(parents=True)
    (tk / "sub").mkdir()
    (tk / "x4-paths.env").write_text('X4_GAME="%s"\nX4_REFERENCE="%s"\n' % (
        (tmp_path / "nogame").as_posix(), (tk / "refrel").as_posix()), encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "x4-paths.env").write_text('X4_GAME="%s"\n' % (tmp_path / "nogame").as_posix(),
                                                     encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("X4_")}
    env.update(X4_TOOLKIT=str(tk), X4_PROFILE=str(tmp_path / "profile"))
    return tk, env


def _unpack_verdict(tk, env, cwd):
    b = gitbash.find_bash() or pytest.skip("no Git Bash -- NOT CHECKED")
    r = subprocess.run([b, str(UNPACK), "--toolkit", str(tk)], env=env, cwd=str(cwd),
                       capture_output=True, text=True, errors="replace", timeout=120)
    if "REFUSED: the unpack" in r.stderr and "X4_CONFIG" in r.stderr:
        return "CONFLICT"
    if "DIFFERENT" in r.stderr:
        return "DIFFERENT"
    if "game dir not found" in r.stderr:
        return "NONE"
    raise AssertionError("an answer this table does not know: " + (r.stdout + r.stderr)[-600:])


_BS = chr(92)
CFG_SPELLINGS = [
    # id,                   spelling ({tk}, {tmp}; else relative to cwd), cwd ("tk"|"sub"|"tmp"), want, windows-only
    ("plain",               "{tk}/x4-paths.env",               "tmp", "NONE",     False),
    ("relative-bare",       "x4-paths.env",                    "tk",  "NONE",     False),
    ("relative-dot",        "./x4-paths.env",                  "tk",  "NONE",     False),
    ("relative-up-inside",  "../x4-paths.env",                 "sub", "NONE",     False),
    ("relative-other",      "../other/x4-paths.env",           "tk",  "CONFLICT", False),
    ("trailing-slash",      "{tk}/x4-paths.env/",              "tmp", "NONE",     False),
    ("relative-trailing",   "x4-paths.env/",                   "tk",  "NONE",     False),
    ("dotdot-escape",       "{tk}/../other/x4-paths.env",      "tmp", "CONFLICT", False),
    ("other",               "{tmp}/other/x4-paths.env",        "tmp", "CONFLICT", False),
    ("missing",             "{tk}/nope.env",                   "tmp", "CONFLICT", False),
    ("relative-missing",    "nope.env",                        "tk",  "CONFLICT", False),
    ("trailing-dot",        "{tk}/x4-paths.env.",              "tmp", "NONE",     True),
    ("backslashes",         "{tk}" + _BS + "x4-paths.env",     "tmp", "NONE",     True),
    ("upper-case",          "{TK}/X4-PATHS.ENV",               "tmp", "NONE",     True),
    ("msys-form",           "{msys_tk}/x4-paths.env",          "tmp", "NONE",     True),
]


def _msys(p) -> str:
    """C:/x/y -> /c/x/y, the Git Bash spelling of the same folder."""
    s = Path(p).as_posix()
    return "/" + s[0].lower() + s[2:] if os.name == "nt" and s[1:2] == ":" else s


@pytest.mark.parametrize("row", CFG_SPELLINGS, ids=[r[0] for r in CFG_SPELLINGS])
def test_FXB4_the_unpack_and_python_AGREE_on_every_X4_CONFIG_spelling(tmp_path, row):
    _id, spelling, where, want, win_only = row
    if win_only and os.name != "nt":
        pytest.skip("a Windows path spelling")
    tk, env = _agree_box(tmp_path)
    env["X4_CONFIG"] = spelling.format(tk=str(tk), TK=str(tk).upper(), tmp=str(tmp_path),
                                       msys_tk=_msys(tk))
    cwd = {"tk": tk, "sub": tk / "sub", "tmp": tmp_path}[where]
    py = subprocess.run([sys.executable, "-c", _PY_CONFLICT, str(REPO / "tools" / "x4validate"),
                         str(tk)], env=env, cwd=str(cwd), capture_output=True, text=True,
                        timeout=120)
    assert py.returncode == 0, py.stderr[-600:]
    assert (_unpack_verdict(tk, env, cwd), py.stdout.strip()) == (want, want), _id
    assert not (tk / "refrel").exists() and not (tmp_path / "nogame").exists()


REF_SPELLINGS = [
    # an INHERITED X4_REFERENCE spelling the config's tree ({tk}/refrel) relative to cwd
    ("absolute",           "{tk}/refrel",      "tmp", "NONE"),
    ("relative-bare",      "refrel",           "tk",  "NONE"),
    ("relative-dot",       "./refrel",         "tk",  "NONE"),
    ("relative-up",        "../refrel",        "sub", "NONE"),
    ("relative-trailing",  "refrel/",          "tk",  "NONE"),
    ("relative-OTHER",     "otherref",         "tk",  "DIFFERENT"),
    ("absolute-OTHER",     "{tmp}/refrel",     "tmp", "DIFFERENT"),
    # MEASURED: under %TEMP% Git Bash's `pwd -P` says /tmp/... for C:/... and /c/... for /c/...
    ("msys-form",          "{msys_tk}/refrel", "tmp", "NONE"),
]


@pytest.mark.parametrize("present", [False, True], ids=["tree-absent", "tree-present"])
@pytest.mark.parametrize("row", REF_SPELLINGS, ids=[r[0] for r in REF_SPELLINGS])
def test_FXB4_an_inherited_RELATIVE_X4_REFERENCE_is_the_tree_it_names(tmp_path, row, present):
    """MEASURED before the fix: every relative spelling of the config's own tree was REFUSED
    as "DIFFERENT" while the tree did not exist (`refrel` -> `/refrel`)."""
    _id, spelling, where, want = row
    tk, env = _agree_box(tmp_path)
    if present:
        (tk / "refrel").mkdir()
    env["X4_REFERENCE"] = spelling.format(tk=str(tk), tmp=str(tmp_path), msys_tk=_msys(tk))
    cwd = {"tk": tk, "sub": tk / "sub", "tmp": tmp_path}[where]
    assert _unpack_verdict(tk, env, cwd) == want, _id
    assert not (tmp_path / "nogame").exists()
