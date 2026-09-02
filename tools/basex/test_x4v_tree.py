"""`_x4v-tree.sh` -- which x4validate checkout drives a BaseX build.

The freshness `engine` axis hashes the BYTES of the engine sources, so the tree a
build resolves to is part of the artifact's identity. Defaulting to a POSITION
(`tools/x4validate`) rather than an identity means that with several checkouts
side by side -- one git worktree per concurrent session -- a build can stamp the
artifact with a different tree's engine hash, and a wrong engine hash reads as
FRESH rather than as an error.

MEASURED 2026-08-29: two checkouts existed and all 7 ENGINE_SOURCES were
byte-identical, so the fingerprint was right by luck. Latent, not active.

One test per clause of `x4v_resolve`, because each guard shadows the ones behind
it and a single probe only ever exercises the first one it trips.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parent / "_x4v-tree.sh"
# Not shutil.which: on Windows that is the WSL stub in System32, which runs a Linux
# bash in a filesystem where the C:/ paths this file asserts on do not exist.
_gb = Path(__file__).resolve().parents[2] / "scripts" / "gitbash.py"
_spec = importlib.util.spec_from_file_location("gitbash", _gb)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
BASH = _mod.find_bash()

pytestmark = pytest.mark.skipif(
    BASH is None or not HELPER.is_file(),
    reason="needs bash and _x4v-tree.sh")


def engine_tree(root: Path, name: str) -> Path:
    """A directory that LOOKS like an x4validate checkout to the resolver."""
    d = root / name / "x4validate"
    d.mkdir(parents=True)
    (d / "_merge.py").write_text("# engine\n", encoding="utf-8")
    return root / name


def run(basex_dir: Path, env_dir: str | None = None):
    script = f'. "{HELPER.as_posix()}"; x4v_resolve "{basex_dir.as_posix()}"'
    env = {"PATH": "/usr/bin:/bin"}
    if env_dir is not None:
        env["X4VALIDATE_DIR"] = env_dir
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.strip(), p.stderr


def layout(tmp_path: Path) -> Path:
    """`<root>/tools/basex` beside `<root>/tools/x4validate*`, as on disk."""
    b = tmp_path / "tools" / "basex"
    b.mkdir(parents=True)
    return b


def test_an_explicit_X4VALIDATE_DIR_wins_and_is_returned_verbatim(tmp_path):
    b = layout(tmp_path)
    engine_tree(b.parent, "x4validate")
    engine_tree(b.parent, "x4validate-tooling")          # ambiguous WITHOUT the var
    rc, out, _ = run(b, env_dir="/some/explicit/tree")
    assert rc == 0
    assert out == "/some/explicit/tree"


def test_exactly_one_checkout_resolves_without_complaint(tmp_path):
    """The public user's layout. The refusal must never fire for them."""
    b = layout(tmp_path)
    engine_tree(b.parent, "x4validate")
    rc, out, err = run(b)
    assert rc == 0, err
    assert out.endswith("/x4validate")


def test_two_real_checkouts_and_no_env_var_REFUSES(tmp_path):
    b = layout(tmp_path)
    engine_tree(b.parent, "x4validate")
    engine_tree(b.parent, "x4validate-tooling")
    rc, _, err = run(b)
    assert rc == 2
    assert "REFUSING" in err
    # Naming the candidates is the whole point -- a refusal you cannot act on is noise.
    assert "x4validate-tooling" in err


def test_a_NAME_MATCH_that_is_not_an_engine_tree_does_not_cause_a_refusal(tmp_path):
    """`x4validate-backup/`, an editor's `.orig`, a half-deleted clone. Matching the
    name alone would refuse a build that was never ambiguous -- and a guard that
    cries wolf is one you learn to bypass."""
    b = layout(tmp_path)
    engine_tree(b.parent, "x4validate")
    (b.parent / "x4validate-backup").mkdir()             # no x4validate/_merge.py
    rc, out, err = run(b)
    assert rc == 0, err
    assert out.endswith("/x4validate")


def test_no_checkout_at_all_keeps_the_historical_default(tmp_path):
    """So preflight reports the real problem -- a missing tree -- rather than this
    helper inventing a different one."""
    b = layout(tmp_path)
    rc, out, _ = run(b)
    assert rc == 0
    assert out.endswith("/x4validate")


# --- x4v_announce: 0 of 4 mutants killed (2026-09-02) ------------------------
#
# MEASURED: announcing the WRONG tree, inverting the "chosen by" branch, dropping the
# git line, and DELETING THE WHOLE FUNCTION all left the suite green. The first is the
# one that matters -- it makes the build log state a tree that was never used, which is
# precisely the false provenance this file exists to prevent, and the freshness
# fingerprint hashes the ENGINE BYTES of whichever tree really was used.
#
# Deletion survived too, and would have broken a real build with `command not found`
# under `set -euo pipefail` -- a failure mode no test could see.


def announce(basex_dir: Path, target: Path, env_dir: str | None = None):
    script = (f'. "{HELPER.as_posix()}"; x4v_announce "{target.as_posix()}"')
    env = {"PATH": "/usr/bin:/bin"}
    if env_dir is not None:
        env["X4VALIDATE_DIR"] = env_dir
    p = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


def test_announce_names_the_tree_it_was_GIVEN(tmp_path):
    """Kills the mutant that announces a different path: the log must be able to be
    audited afterwards, which requires it to be true."""
    b = layout(tmp_path)
    tree = engine_tree(b.parent, "x4validate")
    rc, out, err = announce(b, tree)
    assert rc == 0, err
    # Compared on a dialect-independent TAIL. `pwd` inside git-bash prints the MSYS
    # form (/tmp/...) while Path.as_posix() prints the Windows one (C:/Users/...) --
    # the same directory in two spellings, which is exactly the translation gotcha the
    # rest of this toolkit keeps tripping over. The tail is unique to this tmpdir.
    tail = "/".join(tree.resolve().as_posix().split("/")[-3:])
    assert tail in out.replace(chr(92), "/"), (tail, out)


def test_announce_does_NOT_name_a_tree_it_was_not_given(tmp_path):
    """The twin: a function printing every path it can find would pass the test above."""
    b = layout(tmp_path)
    tree = engine_tree(b.parent, "x4validate")
    other = engine_tree(b.parent, "x4validate-decoy")
    rc, out, _ = announce(b, tree)
    assert rc == 0
    assert "x4validate-decoy" not in out, out


def test_announce_says_WHICH_MECHANISM_chose_the_tree(tmp_path):
    b = layout(tmp_path)
    tree = engine_tree(b.parent, "x4validate")
    _rc, with_var, _ = announce(b, tree, env_dir=str(tree))
    assert "chosen by X4VALIDATE_DIR" in with_var, with_var
    _rc, without, _ = announce(b, tree)
    assert "default position" in without, without
    assert "chosen by X4VALIDATE_DIR" not in without, without


def test_announce_reports_the_git_revision_when_there_is_one(tmp_path):
    """The build log must be able to say WHICH revision of the engine produced an
    artifact, not merely which directory."""
    b = layout(tmp_path)
    tree = engine_tree(b.parent, "x4validate")
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
        r = subprocess.run(["git", *cmd], cwd=tree, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"git unavailable here: {r.stderr.strip()[:60]}")
    rc, out, err = announce(b, tree)
    assert rc == 0, err
    assert "git:" in out, out


def test_announce_EXISTS(tmp_path):
    """Deleting the function entirely survived every other check, and both callers run
    under `set -euo pipefail` -- so its absence is a broken build, not a quiet no-op."""
    rc, out, err = subprocess.run(
        [BASH, "-c", f'. "{HELPER.as_posix()}"; type x4v_announce'],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}
    ).returncode, "", ""
    assert rc == 0, "x4v_announce is not defined by _x4v-tree.sh"
