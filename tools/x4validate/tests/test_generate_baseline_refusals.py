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


# --- a baseline that records NOTHING must not report success (v3.1.0 review, group A)
# The mod walk sat inside a bare `if [ -d "$EXT" ]`, so a missing extensions/ wrote a
# HEADER-ONLY installed-mods.tsv and the script still printed "Baseline written to: ..."
# and exited 0. This file's own script already argues that a baseline is a RECOVERY
# artifact and that "you find out at the moment you need to restore" -- an argument it
# applied to the game DIRECTORY and not to its contents.


def _tree(tmp_path, with_extensions=True, mods=(), profile_files=("content.xml",)):
    game = tmp_path / "game"
    (game / ".claude" / "backups").mkdir(parents=True)
    (game / "version.dat").write_text("7.60", encoding="utf-8")
    if with_extensions:
        (game / "extensions").mkdir()
        for m in mods:
            d = game / "extensions" / m
            d.mkdir()
            (d / "content.xml").write_text('<content id="%s"/>' % m, encoding="utf-8")
    prof = tmp_path / "profile"
    prof.mkdir()
    for f in profile_files:
        body = ("[=ERROR=] 12.34 boom 0xdeadbeef\n" if f == "debug.txt" else "<x/>")
        (prof / f).write_text(body, encoding="utf-8")
    return game, prof


def _out(game, stamp="baseline"):
    """`STAMP` defaults to "baseline" inside the script, and `_run` does not set it.

    ⚠ My first draft said "probe" here, and the missing-extensions test still PASSED
    -- because it asserts the TSV does not exist, and a wrong path does not exist
    either. It passed for the wrong reason, and only the happy-path twin (which reads
    the file) caught it. A negative assertion over a path nobody proved is a green
    that could not go red."""
    return game / ".claude" / "backups" / ("known-good-" + stamp)


def test_a_MISSING_extensions_dir_REFUSES_rather_than_recording_zero_mods(isolated,
                                                                          tmp_path):
    """Pre-fix: rc 0, "Baseline written to: ...", and a mod list with only a header --
    indistinguishable from a clean vanilla install."""
    game, prof = _tree(tmp_path, with_extensions=False)
    r = _run(isolated, str(game), str(prof))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "extensions" in r.stderr and "ZERO mods" in r.stderr
    assert not _out(game).exists(), (
        "a refused run must leave NOTHING behind -- an empty known-good-<stamp>/ "
        "directory is itself a partial artifact that looks like a baseline")


def test_an_EXISTING_but_EMPTY_extensions_dir_is_ACCEPTED_and_CALLED_OUT(isolated,
                                                                         tmp_path):
    """The twin. No mods is a real state a player can be in; only a MISSING directory
    is the looked-in-the-wrong-place case. Refusing both would make the check cry wolf
    on a vanilla install."""
    game, prof = _tree(tmp_path, mods=())
    r = _run(isolated, str(game), str(prof))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOTE" in r.stderr and "vanilla install" in r.stderr


def test_the_summary_is_an_INVENTORY_and_NAMES_what_was_not_captured(isolated, tmp_path):
    """"Baseline written to: ..." was the entire report, so a baseline missing its
    config and its error fingerprint announced itself in the same words as a complete
    one. What a recovery artifact does NOT contain is the thing you need to know
    before you rely on it."""
    game, prof = _tree(tmp_path, mods=("mymod",), profile_files=("content.xml",))
    r = _run(isolated, str(game), str(prof))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "contains:" in r.stdout
    assert "NOT CAPTURED" in r.stderr
    assert "config.xml" in r.stderr and "debug.txt" in r.stderr
    assert "NO error fingerprint" in r.stderr


def test_a_COMPLETE_baseline_says_so_and_skips_the_DLC(isolated, tmp_path):
    """The happy path, so the three above cannot pass on a script that always
    refuses -- and the DLC exclusion pinned while we are here, because
    the reference tree and `extensions/ego_dlc_*` are the same content (gotcha #20)."""
    game, prof = _tree(tmp_path, mods=("mymod", "ego_dlc_split"),
                       profile_files=("content.xml", "config.xml", "debug.txt"))
    r = _run(isolated, str(game), str(prof))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "installed mods recorded: 1" in r.stdout, "the DLC must not be counted"
    assert "NOT CAPTURED" not in r.stderr
    tsv = (_out(game) / "installed-mods.tsv").read_text(encoding="utf-8")
    assert "mymod" in tsv and "ego_dlc_split" not in tsv
    assert (_out(game) / "error-fingerprint.txt").is_file()
    # every data row must carry a real rollup: a row with no hash cannot detect a change
    rows = [l for l in tsv.splitlines()[1:] if l.strip()]
    assert rows and all(len(l.split(chr(9))[3]) == 64 for l in rows), rows
