"""The two halves of the toolkit must agree on which config source wins.

There were THREE statements of precedence and one disagreed:

    CLAUDE.md          "in this order: **env var > x4-paths.env > default**"
    _paths._layers()   [env, file_layer, _LOCAL_FALLBACK]        -- env wins
    _x4-env.sh         `set -a; . "$cfg"; set +a`                -- the FILE won

Two of three agreed, and the third is the one every hook runs on every tool call.

Why an inconsistency here is a safety problem rather than an untidiness: both halves
resolve paths for the SAME machine. Exporting `X4_GAME` pointed x4validate at one
install while the guards protecting the game folder read another -- so the protection
and the work could be aimed at different trees, with nothing saying so.

Nothing pinned the two together, which is exactly how they drifted. This file is that
pin, and it checks all three statements rather than two: a test that compared only the
two implementations would have stayed green while both drifted away from the promise
made to the user.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
ENV_SH = ROOT / ".claude" / "hooks" / "_x4-env.sh"
CLAUDE_MD = ROOT / "CLAUDE.md"


def _bash() -> str | None:
    """Git Bash, via the repo's own resolver.

    NOT `shutil.which("bash")`. On any Windows machine with WSL enabled -- which
    includes every Docker Desktop install -- that returns the stub at
    `C:\\Windows\\System32\\bash.exe`, and the first draft of this test failed with
      WSL (9 - Relay) ERROR: CreateProcessCommon:640: execvpe(/bin/bash) failed
    which is a broken test, not a broken precedence. `scripts/gitbash.py` exists for
    exactly this and has its own suite.
    """
    src = ROOT / "scripts" / "gitbash.py"
    if not src.is_file():
        return None
    spec = importlib.util.spec_from_file_location("gitbash_for_precedence", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_bash()


def test_the_python_half_puts_the_environment_FIRST():
    from x4validate import _paths

    layers = _paths._layers()
    assert len(layers) >= 2, layers
    # The env layer is built from os.environ, so a variable set here must appear in
    # layer 0 and nowhere earlier. Asserting the ORDER, not just membership: the bug
    # was a precedence inversion, which membership cannot see.
    key = "X4_PRECEDENCE_PROBE"
    os.environ[key] = "from-the-env"
    try:
        layers = _paths._layers()
        assert layers[0].get(key) == "from-the-env", (
            "the first layer is not the real environment")
    finally:
        os.environ.pop(key, None)


def test_the_documented_order_still_says_the_environment_wins():
    """If someone changes the promise, this test is where they find out that two
    implementations are pinned to it."""
    text = CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
    assert "env var > `x4-paths.env` > default" in text, (
        "CLAUDE.md no longer documents env > file > default; the two implementations "
        "below are pinned to that order")


def test_the_bash_half_lets_the_environment_win():
    """Runs the real `_x4-env.sh`, because the defect was in what it DID, not in what
    it said -- its own header described the inverted behaviour accurately."""
    bash = _bash()
    if bash is None:
        pytest.skip("no Git Bash found (the WSL stub does not count) -- NOT CHECKED")
    with tempfile.TemporaryDirectory() as td:
        tk = pathlib.Path(td)
        (tk / ".claude").mkdir()
        (tk / ".claude" / "x4-paths.env").write_text(
            'X4_GAME="/from/the/FILE"\nX4_PROFILE="/profile/from/FILE"\n',
            encoding="utf-8", newline="\n")
        env = dict(os.environ)
        env["X4_TOOLKIT"] = str(tk)
        env["X4_GAME"] = "/from/the/ENV"
        env.pop("X4_PROFILE", None)
        r = subprocess.run(
            [bash, "-c",
             '. "$1"; printf "%s\\n%s\\n" "$X4_GAME" "$X4_PROFILE"',
             "_", str(ENV_SH)],
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (r.returncode, r.stderr[-400:])
        game, profile = (r.stdout.splitlines() + ["", ""])[:2]

    assert game == "/from/the/ENV", (
        f"the FILE overrode an exported X4_GAME (got {game!r}); "
        "that is the precedence inversion this file exists to catch")
    # ...and the file must still supply what the environment does not. A fix that
    # simply stopped reading the file would pass the assertion above.
    assert profile == "/profile/from/FILE", (
        f"the file no longer supplies an unset key (got {profile!r})")
