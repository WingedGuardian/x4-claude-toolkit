"""Plan 3 lane I: where the path config lives, how the old place is still read, and how it moves.

The rule (ONE, mirrored by _x4-env.sh -- test_config_precedence_agrees pins the two together):
    $X4_CONFIG (explicit; naming no file means NO file) > <toolkit>/x4-paths.env
    > <toolkit>/.claude/x4-paths.env (3.x, deprecated) > none
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from x4validate import _paths

NEW, OLD = Path("x4-paths.env"), Path(".claude") / "x4-paths.env"
SECRET = "nexus-SECRET-value-must-never-print"


@pytest.fixture
def tk(monkeypatch, tmp_path):
    for k in [k for k in os.environ if k.startswith("X4_")]:
        monkeypatch.delenv(k)
    root = tmp_path / "tk"
    (root / "sub" / "deeper").mkdir(parents=True)
    monkeypatch.setenv("X4_TOOLKIT", str(root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_paths, "_NOTICED", set(), raising=False)
    _paths.reload()
    yield root
    _paths.reload()


def put(root: Path, rel: Path, game: str, extra: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'X4_GAME="{game}"\n{extra}', encoding="utf-8", newline="\n")
    return p


# --- the selection rule: one row per clause ---------------------------------------------

def test_new_location_is_read(tk):
    put(tk, NEW, "/xgame/new")
    assert _paths._find_env_file() == tk / NEW
    assert _paths.config_state() == "new"


def test_legacy_location_is_still_read(tk):
    put(tk, OLD, "/xgame/old")
    assert _paths._find_env_file() == tk / OLD
    assert _paths.config_state() == "legacy"


def test_new_OUTRANKS_legacy_when_they_differ(tk):
    put(tk, NEW, "/xgame/new"); put(tk, OLD, "/xgame/old")
    assert _paths._find_env_file() == tk / NEW
    assert _paths.game_root().as_posix() == "/xgame/new"
    assert _paths.config_state() == "both-differ"


def test_agreeing_copies_are_told_apart_from_differing_ones(tk):
    put(tk, NEW, "/xgame/same", "# a comment only the new one has\n")
    (tk / OLD).parent.mkdir(parents=True, exist_ok=True)
    (tk / OLD).write_bytes(b'  X4_GAME="/xgame/same"\r\n')       # indent + CRLF: same assignment
    assert _paths.config_state() == "both-agree"


def test_UNREADABLE_copies_are_never_reported_as_agreeing(tk, monkeypatch):
    """An unreadable config is a NON-ANSWER, not an empty one: comparing two unreadable
    copies as `[] == []` once said 'both-agree' (test_no_silent_swallow found the bare
    `except OSError: return []`). It must say they differ -- the conservative answer that
    makes the notice name both files."""
    put(tk, NEW, "/xgame/same"); put(tk, OLD, "/xgame/same")
    real = Path.read_text

    def boom(self, *a, **k):
        if self.name == "x4-paths.env":
            raise OSError("simulated: access denied")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", boom)
    assert _paths.config_state() == "both-differ"


def test_TWIN_readable_identical_copies_still_agree(tk):
    put(tk, NEW, "/xgame/same"); put(tk, OLD, "/xgame/same")
    assert _paths.config_state() == "both-agree"


def test_explicit_X4_CONFIG_wins_and_an_absent_one_reads_NOTHING(tk, monkeypatch):
    put(tk, NEW, "/xgame/new")
    other = put(tk, Path("elsewhere.env"), "/xgame/x")
    monkeypatch.setenv("X4_CONFIG", str(other)); _paths.reload()
    assert _paths._find_env_file() == other and _paths.config_state() == "explicit"
    monkeypatch.setenv("X4_CONFIG", str(tk / "absent.env")); _paths.reload()
    assert _paths._find_env_file() is None and _paths.config_state() == "explicit-missing"


def test_a_NAMED_toolkit_without_a_config_is_not_rescued_by_the_cwd_walk(tk, monkeypatch):
    """Twin of the walk below: bash never walks, so a walk here was a silent disagreement."""
    put(tk.parent, NEW, "/xgame/walked")              # an ancestor of the cwd holds one
    monkeypatch.chdir(tk / "sub" / "deeper"); _paths.reload()
    assert _paths._find_env_file() is None and _paths.config_state() == "none"


def test_with_no_toolkit_named_the_walk_finds_new_before_legacy(tk, monkeypatch):
    monkeypatch.delenv("X4_TOOLKIT")
    put(tk, NEW, "/xgame/new"); put(tk, OLD, "/xgame/old")
    monkeypatch.chdir(tk / "sub" / "deeper"); _paths.reload()
    assert _paths._find_env_file() == tk / NEW


def test_with_no_toolkit_named_the_walk_still_finds_a_legacy_only_config(tk, monkeypatch):
    """Twin of the walk above: the walk keeps the 3.x location readable too."""
    monkeypatch.delenv("X4_TOOLKIT")
    put(tk, OLD, "/xgame/old")
    monkeypatch.chdir(tk / "sub" / "deeper"); _paths.reload()
    assert _paths._find_env_file() == tk / OLD
    assert _paths.config_state() == "legacy"


def test_neither_reads_nothing_and_the_reference_is_marked_DEFAULTED(tk):
    assert _paths._find_env_file() is None and _paths.config_state() == "none"
    assert _paths.reference() == tk / "reference"
    assert any("reference" in l and "DEFAULT" in l for l in _paths.describe())


def test_TWIN_a_configured_reference_is_not_marked_DEFAULTED(tk):
    put(tk, NEW, "/xgame/new", 'X4_REFERENCE="/xref/real"\n')
    assert not any("DEFAULT" in l for l in _paths.describe())


# --- the notice: once, paths and KEY names, never values -------------------------------

def test_legacy_prints_ONE_notice_naming_both_paths_and_no_value(tk, capsys):
    put(tk, OLD, "/xgame/old", f'X4_NEXUS_KEY="{SECRET}"\n')
    _paths.game_root(); _paths.reload(); _paths.game_root()
    err = capsys.readouterr().err
    assert err.count("deprecated") == 1, err
    assert str(tk / OLD) in err and str(tk / NEW) in err and "x4config.py migrate" in err
    assert SECRET not in err


def test_both_differing_notice_names_the_KEY_and_no_value(tk, capsys):
    put(tk, NEW, "/xgame/new", f'X4_NEXUS_KEY="{SECRET}"\n'); put(tk, OLD, "/xgame/old")
    _paths.game_root()
    err = capsys.readouterr().err
    assert err.count("deprecated") == 1 and "X4_GAME" in err, err
    assert SECRET not in err and "/xgame/" not in err


def test_new_only_prints_nothing(tk, capsys):
    put(tk, NEW, "/xgame/new")
    _paths.game_root()
    assert capsys.readouterr().err == ""


# --- migration: the five rows ----------------------------------------------------------

def test_migrate_moves_a_legacy_only_config_byte_for_byte(tk):
    src = put(tk, OLD, "/xgame/old", f'X4_NEXUS_KEY="{SECRET}"\n')
    before = src.read_bytes()
    assert _paths.migrate_legacy_config(tk)[0] == "would-move" and src.exists()     # dry by default
    action, msg = _paths.migrate_legacy_config(tk, apply=True)
    assert action == "moved" and not src.exists() and (tk / NEW).read_bytes() == before
    assert SECRET not in msg


@pytest.mark.skipif(os.name != "nt", reason="the read-only bit is the Windows lock (x4lock)")
def test_migrate_moves_a_LOCKED_config_and_the_lock_travels(tk):
    src = put(tk, OLD, "/xgame/old"); src.chmod(stat.S_IREAD)
    assert _paths.migrate_legacy_config(tk, apply=True)[0] == "moved"
    assert not ((tk / NEW).stat().st_mode & stat.S_IWRITE)
    (tk / NEW).chmod(stat.S_IREAD | stat.S_IWRITE)


def test_migrate_retires_an_AGREEING_legacy_copy_to_a_backup_name(tk):
    put(tk, NEW, "/xgame/same"); put(tk, OLD, "/xgame/same")
    assert _paths.migrate_legacy_config(tk)[0] == "would-retire-old" and (tk / OLD).exists()
    assert _paths.migrate_legacy_config(tk, apply=True)[0] == "retired-old"
    assert not (tk / OLD).exists()
    assert len(list((tk / ".claude").glob("x4-paths.env.bak-*"))) == 1


def test_migrate_REFUSES_differing_copies_and_changes_nothing(tk):
    put(tk, NEW, "/xgame/new", f'X4_NEXUS_KEY="{SECRET}"\n'); put(tk, OLD, "/xgame/old")
    snap = {p: p.read_bytes() for p in (tk / NEW, tk / OLD)}
    action, msg = _paths.migrate_legacy_config(tk, apply=True)
    assert action == "refused" and "X4_GAME" in msg and SECRET not in msg
    assert {p: p.read_bytes() for p in snap} == snap


@pytest.mark.parametrize("layout", ["neither", "new_only"])
def test_migrate_has_nothing_to_do(tk, layout):
    if layout == "new_only":
        put(tk, NEW, "/xgame/new")
    assert _paths.migrate_legacy_config(tk, apply=True)[0] == "none"


def test_config_file_in_prefers_new_then_legacy_then_names_new(tk):
    assert _paths.config_file_in(tk) == tk / NEW                 # neither: the one to demand
    put(tk, OLD, "/xgame/old")
    assert _paths.config_file_in(tk) == tk / OLD
    put(tk, NEW, "/xgame/new")
    assert _paths.config_file_in(tk) == tk / NEW


# --- scripts/x4config.py: the one command every notice names ---------------------------

import subprocess
import sys

X4CONFIG = Path(__file__).resolve().parents[3] / "scripts" / "x4config.py"


def _cli(*args, env=None):
    return subprocess.run([sys.executable, str(X4CONFIG), *args], capture_output=True, text=True,
                          env=env)


def _clean_env(tk):
    e = {k: v for k, v in os.environ.items() if not k.startswith("X4_")}
    e["X4_TOOLKIT"] = str(tk)
    return e


def test_x4config_migrate_is_a_DRY_RUN_by_default(tk):
    put(tk, OLD, "/xgame/old")
    r = _cli("migrate", "--root", str(tk), env=_clean_env(tk))
    assert r.returncode == 0 and "would move" in r.stdout and (tk / OLD).exists(), r


def test_x4config_migrate_apply_moves_and_says_so(tk):
    put(tk, OLD, "/xgame/old")
    r = _cli("migrate", "--root", str(tk), "--apply", env=_clean_env(tk))
    assert r.returncode == 0 and "moved" in r.stdout and (tk / NEW).exists() and not (tk / OLD).exists(), r


def test_x4config_refuses_differing_copies_with_rc_1(tk):
    put(tk, NEW, "/xgame/new"); put(tk, OLD, "/xgame/old")
    r = _cli("migrate", "--root", str(tk), "--apply", env=_clean_env(tk))
    assert r.returncode == 1 and "X4_GAME" in (r.stdout + r.stderr), r


def test_x4config_status_names_the_state(tk):
    put(tk, OLD, "/xgame/old")
    r = _cli("status", "--root", str(tk), env=_clean_env(tk))
    assert r.returncode == 0 and "legacy" in r.stdout, r


def test_x4config_status_names_the_differing_KEYS_and_no_value(tk):
    put(tk, NEW, "/xgame/new", f'X4_NEXUS_KEY="{SECRET}"\n'); put(tk, OLD, "/xgame/old")
    r = _cli("status", "--root", str(tk), env=_clean_env(tk))
    assert "both-differ" in r.stdout and "X4_GAME" in r.stdout, r
    assert SECRET not in r.stdout + r.stderr and "/xgame/" not in r.stdout + r.stderr


# --- setup.sh: the example lives at the root; setup never SHADOWS a 3.x config ---------

import importlib.util
import shutil

REPO = Path(__file__).resolve().parents[3]


def _gitbash():
    spec = importlib.util.spec_from_file_location("gitbash_for_lanei", REPO / "scripts" / "gitbash.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bash = mod.find_bash()
    if bash is None:
        pytest.skip("no Git Bash found (the WSL stub does not count) -- NOT CHECKED")
    return bash


def _setup_config_only(root: Path):
    shutil.copy2(REPO / "setup.sh", root / "setup.sh")
    shutil.copy2(REPO / "x4-paths.env.example", root / "x4-paths.env.example")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("X4_") and k not in ("CLAUDE_PROJECT_DIR", "HOOK_DIR")}
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return subprocess.run([_gitbash(), str(root / "setup.sh"), "--config-only"],
                          capture_output=True, text=True, env=env, cwd=str(root), timeout=120)


def test_setup_does_NOT_create_a_new_config_beside_a_legacy_one(tmp_path):
    """The trap: new outranks legacy, so a fresh copy of the example at the root would
    SHADOW a real 3.x config with blank values."""
    put(tmp_path, OLD, "/xgame/old")
    r = _setup_config_only(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / NEW).exists(), r.stdout
    assert "DEPRECATED" in r.stdout and "x4config.py migrate" in r.stdout, r.stdout


def test_setup_creates_the_config_from_the_example_when_there_is_none(tmp_path):
    r = _setup_config_only(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / NEW).read_bytes() == (REPO / "x4-paths.env.example").read_bytes()
    assert not (tmp_path / OLD).exists()


def test_the_example_ships_at_the_root_and_not_in_claude():
    def tracked(rel):
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", rel],
                             capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("not a git checkout (cold extract) -- checked by file presence below")
        return [l for l in out.stdout.splitlines() if l.strip()]
    assert (REPO / "x4-paths.env.example").is_file()
    assert tracked("x4-paths.env.example") == ["x4-paths.env.example"]
    assert tracked(".claude/x4-paths.env.example") == []


def test_an_X4_CONFIG_naming_a_MISSING_file_is_NOTICED_not_silent(tk, monkeypatch, tmp_path, capsys):
    """v4.0.0 review R5-6: X4_CONFIG naming a file that does not exist means NO config file is
    read -- every path then falls back (reference -> <toolkit>/reference), and nothing outside
    `x4validate --paths` said so. One stderr line, naming the variable and the path."""
    gone = tmp_path / "nope" / "x4-paths.env"
    monkeypatch.setenv("X4_CONFIG", str(gone))
    _paths.reload()
    _paths.reference()
    err = capsys.readouterr().err
    assert "X4_CONFIG" in err and str(gone) in err and "does not exist" in err, err


def test_TWIN_an_X4_CONFIG_naming_a_REAL_file_says_nothing(tk, monkeypatch, tmp_path, capsys):
    real = tmp_path / "real.env"
    real.write_text("X4_GAME=/x\n", encoding="utf-8")
    monkeypatch.setenv("X4_CONFIG", str(real))
    _paths.reload()
    _paths.reference()
    assert "X4_CONFIG" not in capsys.readouterr().err
