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
    # Plan 2: AGENTS.md carries the same shared core, so it makes the same promise.
    docs = [p for p in (CLAUDE_MD, ROOT / "AGENTS.md") if p.is_file()]
    assert CLAUDE_MD in docs, "no CLAUDE.md at the repo root"
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        assert "env var > `x4-paths.env` > default" in text, (
            f"{doc.name} no longer documents env > file > default; the two implementations "
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


# --- Plan 3 lane I: the location MATRIX, both loaders, one table ------------------------
#
# Each row is the falsification twin of ONE clause of the selection rule:
#   new_only -> "new is read"            old_only   -> "legacy still read"
#   both_*   -> "new outranks legacy"    both_differ -> the ORDER (a swap reads /xgame/old)
#   neither  -> "nothing is invented"    explicit*  -> "$X4_CONFIG decides, even when absent"
#   env_wins -> "an exported value beats every file"
import json
import sys

NEW, OLD = "x4-paths.env", ".claude/x4-paths.env"
MATRIX = [
    # id,                files {rel: X4_GAME},                         X4_CONFIG,      exported X4_GAME, file read,       state,              X4_GAME
    ("new_only",         {NEW: "/xgame/new"},                          None,           None,     NEW,             "new",              "/xgame/new"),
    ("old_only",         {OLD: "/xgame/old"},                          None,           None,     OLD,             "legacy",           "/xgame/old"),
    ("both_agree",       {NEW: "/xgame/same", OLD: "/xgame/same"},     None,           None,     NEW,             "both",             "/xgame/same"),
    ("both_differ",      {NEW: "/xgame/new", OLD: "/xgame/old"},       None,           None,     NEW,             "both",             "/xgame/new"),
    ("neither",          {},                                           None,           None,     None,            "none",             ""),
    ("explicit",         {NEW: "/xgame/new", "elsewhere.env": "/xgame/x"}, "elsewhere.env", None, "elsewhere.env", "explicit",        "/xgame/x"),
    ("explicit_missing", {NEW: "/xgame/new"},                          "absent.env",   None,     None,            "explicit-missing", ""),
    ("env_wins",         {NEW: "/xgame/new"},                          None,           "/xgame/env", NEW,         "new",              "/xgame/env"),
]
IDS = [r[0] for r in MATRIX]
PKG = ROOT / "tools" / "x4validate"


def _n(v):
    return "" if v in (None, "") else str(v).replace("\\", "/").rstrip("/").lower()


def _box(tmp: pathlib.Path, row):
    _id, files, xcfg, xgame, *_ = row
    tk = tmp / "tk"
    tk.mkdir()
    for rel, game in files.items():
        p = tk / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'X4_GAME="{game}"\n', encoding="utf-8", newline="\n")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("X4_") and k not in ("CLAUDE_PROJECT_DIR", "HOOK_DIR")}
    env["X4_TOOLKIT"] = str(tk)
    if xcfg:
        env["X4_CONFIG"] = str(tk / xcfg)
    if xgame:
        env["X4_GAME"] = xgame
    return tk, env


def _bash_view(tk, env):
    bash = _bash()
    if bash is None:
        pytest.skip("no Git Bash found (the WSL stub does not count) -- NOT CHECKED")
    r = subprocess.run([bash, "-c", '. "$1"; printf "%s\\n" "$_x4_cfg" "$_x4_cfg_src" '
                        '"${X4_GAME:-}" "$X4_REFERENCE" "$_x4_ref_defaulted"', "_", str(ENV_SH)],
                       capture_output=True, text=True, env=env, cwd=str(tk))
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stderr == "", "the loader must print NOTHING per call (M5): " + r.stderr[-300:]
    f, s, g, ref, d = (r.stdout.splitlines() + [""] * 5)[:5]
    return {"file": f, "state": s, "game": g, "reference": ref, "defaulted": d}


_PY = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from x4validate import _paths
f = _paths._find_env_file(); g = _paths.game_root()
print(json.dumps({"file": None if f is None else str(f), "state": _paths.config_state(),
                  "game": "" if g is None else g.as_posix(), "reference": str(_paths.reference())}))
'''


def _py_view(tk, env):
    r = subprocess.run([sys.executable, "-c", _PY, str(PKG)], capture_output=True, text=True,
                       env=env, cwd=str(tk))
    assert r.returncode == 0, r.stderr[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _expect(tk, row, view, collapse=False):
    _id, _f, _x, _g, want_file, want_state, want_game = row
    state = view["state"]
    if collapse and state in ("both-agree", "both-differ"):
        state = "both"
    assert _n(view["file"]) == _n(tk / want_file if want_file else None), (_id, view)
    assert state == want_state, (_id, view)
    assert _n(view["game"]) == _n(want_game), (_id, view)


@pytest.mark.parametrize("row", MATRIX, ids=IDS)
def test_bash_loader_matrix(tmp_path, row):
    tk, env = _box(tmp_path, row)
    v = _bash_view(tk, env)
    _expect(tk, row, v)
    # the reference default is RECORDED, never silent: defaulted only where no file gave one
    assert v["defaulted"] == "1" and _n(v["reference"]) == _n(tk / "reference"), (row[0], v)


@pytest.mark.parametrize("row", MATRIX, ids=IDS)
def test_python_loader_matrix(tmp_path, row):
    tk, env = _box(tmp_path, row)
    _expect(tk, row, _py_view(tk, env), collapse=True)


@pytest.mark.parametrize("row", MATRIX, ids=IDS)
def test_config_precedence_agrees(tmp_path, row):
    """Bash and Python, same box, same env: same file, same state, same game, same reference."""
    tk, env = _box(tmp_path, row)
    b, p = _bash_view(tk, env), _py_view(tk, env)
    ps = "both" if p["state"] in ("both-agree", "both-differ") else p["state"]
    assert (_n(b["file"]), b["state"], _n(b["game"]), _n(b["reference"])) == \
           (_n(p["file"]), ps, _n(p["game"]), _n(p["reference"])), (row[0], b, p)


def test_TWIN_an_exported_reference_is_not_DEFAULTED(tmp_path):
    """The `_x4_ref_defaulted` flag is what the banner and x4doctor read: it must go to 0
    the moment anything real names the reference."""
    tk, env = _box(tmp_path, MATRIX[4])                   # neither
    env["X4_REFERENCE"] = str(tmp_path / "realref")
    v = _bash_view(tk, env)
    assert v["defaulted"] == "0" and _n(v["reference"]) == _n(tmp_path / "realref")
