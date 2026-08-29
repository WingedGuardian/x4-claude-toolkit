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

import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parent / "_x4v-tree.sh"
BASH = shutil.which("bash")

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
