"""`generate-baseline.sh` must refuse the same way for both halves of its config.

`bin/unpack-reference.sh` states the contract for the whole toolkit:

    Exit 2 == "this toolkit is not configured", everywhere in the toolkit. Kept
    distinct from 1 ("it ran and something was wrong") so a caller can tell "set
    X4_GAME" from "the unpack failed" -- they need opposite responses.

MEASURED 2026-09-05 on an isolated copy: `generate-baseline.sh` honoured that for a
missing GAME_DIR (rc 2, message on stderr) and broke it eight lines later for a missing
PROFILE_DIR (rc 1, message on **stdout**). Same condition class, same script, opposite
on both axes -- so a caller could not tell "you have not configured me" from "the
baseline failed", which is the one distinction the contract exists to make.

The script had no test of any kind before this file.

ISOLATION MATTERS HERE AND IS PROVEN, NOT ASSUMED. The script sources
`<its dir>/../.claude/x4-paths.env`, so clearing `X4_GAME`/`X4_PROFILE` from the
environment does NOT isolate it -- the config file puts them back. That is CLAUDE.md
#26's cold-is-not-cold trap, and it bit the session that wrote this test: a probe with
`GAME_DIR=""` fell through to the real game install and began hashing every installed
mod. So each case below runs a COPY of the script in a tmp tree with no config beside
it, and asserts that isolation first.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = ROOT / "scripts" / "generate-baseline.sh"

_spec = importlib.util.spec_from_file_location("_gitbash", ROOT / "scripts" / "gitbash.py")
_gitbash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gitbash)


@pytest.fixture()
def isolated(tmp_path: Path) -> Path:
    """A copy of the script with NO x4-paths.env anywhere above it."""
    (tmp_path / "scripts").mkdir()
    shutil.copy2(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    assert not (tmp_path / ".claude").exists(), (
        "the sandbox is not isolated -- the script would source a real config")
    return tmp_path / "scripts" / SCRIPT.name


def _run(script: Path, game: str, profile: str):
    bash = _gitbash.find_bash()
    if not bash:
        pytest.skip("no real bash available to run a shell script")
    env = {"PATH": __import__("os").environ.get("PATH", ""),
           "GAME_DIR": game, "PROFILE_DIR": profile}
    return subprocess.run([bash, str(script)], capture_output=True, text=True, env=env,
                          timeout=120)


def test_a_missing_GAME_DIR_refuses_with_2_on_stderr(isolated, tmp_path):
    """The CONTROL. Without it, the subject below could pass for the wrong reason --
    e.g. if the script refused everything with 2, or never ran at all."""
    r = _run(isolated, "", str(tmp_path))
    assert r.returncode == 2, "an unconfigured GAME_DIR must be rc 2, got %r" % r.returncode
    assert "ERROR" in r.stderr, "the refusal must go to stderr, got stdout=%r" % r.stdout


def test_a_missing_PROFILE_DIR_refuses_with_2_on_stderr(isolated, tmp_path):
    """The SUBJECT. Same class as the control: the toolkit is not configured."""
    game = tmp_path / "fakegame"
    game.mkdir()
    r = _run(isolated, str(game), "")
    assert r.returncode == 2, (
        "an unconfigured PROFILE_DIR is the same 'not configured' condition as a "
        "missing GAME_DIR and must also be rc 2, not 1 ('it ran and failed'), got %r"
        % r.returncode)
    assert "ERROR" in r.stderr, (
        "the refusal must go to stderr like every other refusal in this script; "
        "stdout=%r stderr=%r" % (r.stdout, r.stderr))


def test_a_PROFILE_DIR_that_is_not_a_directory_refuses_too(isolated, tmp_path):
    """Set-but-wrong is the same answer as unset: nothing can be captured from it."""
    game = tmp_path / "fakegame2"
    game.mkdir()
    r = _run(isolated, str(game), str(tmp_path / "does-not-exist"))
    assert r.returncode == 2, r.returncode
