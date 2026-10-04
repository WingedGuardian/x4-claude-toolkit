"""A BARE X4 profile id is an account identifier too (v4.0.0 review, R6-02/R7-1 follow-up).

`scan-identifiers.py` caught a profile id only INSIDE an `egosoft/x4/<id>` path -- keyed on
the path on purpose, because a bare 8-digit number is everywhere (hashes, sizes, times) and
a check that floods is ignored. So a test that wrote the id bare ("profile <id>") shipped,
and had to be scrubbed from history.

The fix keeps the no-flood property by NOT banning a shape: it derives the ACTUAL id(s) on
the machine where it runs -- the configured X4_PROFILE's last component and every
`Documents/Egosoft/X4/<digits>` folder that exists locally -- and bans those values, bare.
Nothing is hardcoded in the repo and the id is never printed. In CI no profile exists, so
nothing is derived and nothing changes.

Every run here is HERMETIC: `X4_SCAN_HOME` points the folder walk at the sandbox and the
developer's X4_* variables are removed, so the real machine's id is never derived, used or
printed by this file. The synthetic id is ASSEMBLED, so no line here carries it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "scan-identifiers.py"
FAKE_ID = "4" + "2424" + "242"        # 8 digits, not a PLACEHOLDER_IDS entry
OTHER = "7" + "1717" + "171"          # an unrelated 8-digit number


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _env(tmp_path: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("X4_")}
    env.pop("EXTRA_FORBIDDEN", None)
    env["X4_SCAN_HOME"] = str(tmp_path / "home")
    env.update(extra)
    return env


def _repo(tmp_path: Path, body: str) -> Path:
    if not SCRIPT.is_file():
        pytest.skip("no scripts/scan-identifiers.py (dev-only script) -- not checked")
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, r / "scripts" / SCRIPT.name)
    _git(r, "init", "-q", ".")
    _git(r, "config", "user.name", "Testy McTest")
    _git(r, "config", "user.email", "testy@example.invalid")
    (r / "LICENSE").write_text("Copyright (c) 2026 The Project Authors\n", encoding="utf-8")
    _git(r, "add", "LICENSE", "scripts")
    _git(r, "commit", "-qm", "base")      # TWO commits: one visible commit is refused (rc 2)
    (r / "a.txt").write_text(body, encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "body")
    return r


def _scan(repo: Path, env: dict):
    return subprocess.run([sys.executable, str(repo / "scripts" / SCRIPT.name)], cwd=str(repo),
                          capture_output=True, text=True, env=env, timeout=120)


def _local_profile(tmp_path: Path, pid: str) -> Path:
    d = tmp_path / "home" / "Documents" / "Egosoft" / "X4" / pid
    d.mkdir(parents=True)
    return d


def test_a_BARE_locally_derived_profile_id_is_caught_and_never_printed(tmp_path):
    repo = _repo(tmp_path, "see profile %s for the save\n" % FAKE_ID)
    _local_profile(tmp_path, FAKE_ID)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "a.txt" in r.stdout and "profile id" in r.stdout
    assert FAKE_ID not in r.stdout + r.stderr, "the scanner PRINTED the id it exists to suppress"
    assert "1 X4 profile id(s) derived" in r.stdout


def test_the_configured_X4_PROFILE_is_a_source_too(tmp_path):
    repo = _repo(tmp_path, "id %s\n" % FAKE_ID)
    prof = tmp_path / "elsewhere" / FAKE_ID
    prof.mkdir(parents=True)
    r = _scan(repo, _env(tmp_path, X4_PROFILE=str(prof)))
    assert r.returncode == 1, r.stdout + r.stderr
    assert FAKE_ID not in r.stdout + r.stderr


def test_TWIN_an_UNRELATED_8_digit_number_is_NOT_caught(tmp_path):
    """The no-flood property: only a DERIVED id is banned, never the 8-digit shape."""
    repo = _repo(tmp_path, "blob size %s bytes\n" % OTHER)
    _local_profile(tmp_path, FAKE_ID)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_TWIN_the_id_as_a_SUBSTRING_of_a_longer_number_is_NOT_caught(tmp_path):
    repo = _repo(tmp_path, "sha 9%s9\n" % FAKE_ID)
    _local_profile(tmp_path, FAKE_ID)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_TWIN_with_NO_profile_on_the_machine_nothing_is_derived(tmp_path):
    """CI: no profile exists, so the bare value is unknown and passes -- and the run SAYS
    that it derived none, rather than implying the axis was checked."""
    repo = _repo(tmp_path, "see profile %s\n" % FAKE_ID)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 X4 profile id(s) derived" in r.stdout


def test_a_PLACEHOLDER_named_folder_is_never_banned(tmp_path):
    repo = _repo(tmp_path, "fixture 12345678\n")
    _local_profile(tmp_path, "12345678")
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_HISTORY_mode_catches_a_committed_and_removed_bare_id(tmp_path):
    repo = _repo(tmp_path, "clean\n")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "a.txt").write_text("profile %s\n" % FAKE_ID, encoding="utf-8")
    _git(repo, "commit", "-qam", "leak")
    (repo / "a.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "fix")
    _local_profile(tmp_path, FAKE_ID)
    r = subprocess.run([sys.executable, str(repo / "scripts" / SCRIPT.name), "--history",
                        base + "..HEAD"], cwd=str(repo), capture_output=True, text=True,
                       env=_env(tmp_path), timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert FAKE_ID not in r.stdout + r.stderr


def test_the_selftest_covers_the_bare_id_both_ways():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout
    assert "DERIVED profile id" in r.stdout and "unrelated 8-digit" in r.stdout
