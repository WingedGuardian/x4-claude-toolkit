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
    # Hermetic for the CONFIG too: since the v4.0.0 B2 fix a script binds to its OWN toolkit,
    # so with X4_* stripped _paths still finds this checkout's real x4-paths.env and its
    # X4_PROFILE. An X4_CONFIG naming a missing file means "read NO config" (_paths rule).
    env["X4_CONFIG"] = str(tmp_path / "no-such-x4-paths.env")
    env.update(extra)
    return env


def _repo(tmp_path: Path, body: str) -> Path:
    # v4.0.0 delta review: this was an unconditional skip calling the script "dev-only". It
    # is tracked, not export-ignored, and copied by both installers, so it ships in every
    # layout: a missing one must FAIL.
    assert SCRIPT.is_file(), f"{SCRIPT} is missing -- it ships in every layout"
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


def test_a_MISSING_scan_identifiers_script_FAILS_rather_than_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", tmp_path / "scan-identifiers.py")
    with pytest.raises(AssertionError, match="ships in every layout"):
        _repo(tmp_path, "x")


# --- FX-G3 (v4.0.0 delta review): EVERY occurrence on a line, not the first ------------------- #
# account_match used `search`, so a placeholder EARLIER on a line hid a real identifier LATER on
# the same line. MEASURED before the fix: account_match(...) -> None. Names are ASSEMBLED.
REAL_USER = "dev" + "user"


def test_a_placeholder_EARLIER_on_the_line_does_not_hide_a_real_user_path_LATER(tmp_path):
    repo = _repo(tmp_path, "cp C:/Users/tester/a C:/Users/%s/Desktop/b\n" % REAL_USER)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1 and "a.txt" in r.stdout, r.stdout + r.stderr


def test_a_placeholder_profile_id_EARLIER_does_not_hide_a_real_one_LATER(tmp_path):
    repo = _repo(tmp_path, "Egosoft/X4/12345678 vs Egosoft/X4/%s\n" % OTHER)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1 and "a.txt" in r.stdout, r.stdout + r.stderr


def test_TWIN_two_placeholders_on_one_line_are_still_clean(tmp_path):
    repo = _repo(tmp_path, "cp C:/Users/tester/a C:/Users/youruser/b Egosoft/X4/12345678\n")
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_TWIN_the_real_path_ALONE_is_caught_too(tmp_path):
    """Control: without the placeholder in front, the same line was caught before the fix as well --
    so the two tests above fail ONLY because of what precedes the identifier."""
    repo = _repo(tmp_path, "cp C:/Users/%s/Desktop/b\n" % REAL_USER)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr


# --- FX-B2 (delta review): the walk covers Linux, and says when it was PARTIAL --------------

def _linux_profile(tmp_path: Path, pid: str) -> Path:
    d = tmp_path / "home" / ".config" / "EgoSoft" / "X4" / pid
    d.mkdir(parents=True)
    return d


def test_FXB2_a_LINUX_profile_folder_is_derived_too(tmp_path):
    """The native Linux client keeps profiles under ~/.config/EgoSoft/X4/<id>; the walk read
    only the two Windows Documents locations, so a Linux machine derived nothing."""
    repo = _repo(tmp_path, "see profile %s for the save\n" % FAKE_ID)
    _linux_profile(tmp_path, FAKE_ID)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "1 X4 profile id(s) derived" in r.stdout, r.stdout
    assert FAKE_ID not in r.stdout + r.stderr
    assert "profile-id walk: 1 of 3 known profile location(s)" in r.stdout, r.stdout


def _load_scanner():
    import importlib.util
    assert SCRIPT.is_file(), "scripts/scan-identifiers.py ships in every layout: %s is missing" % SCRIPT
    spec = importlib.util.spec_from_file_location("scan_identifiers_fxb2", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_FXB2_an_UNREADABLE_location_makes_the_walk_say_PARTIAL(tmp_path, monkeypatch):
    m = _load_scanner()
    home = tmp_path / "home"
    (home / "Documents" / "Egosoft").mkdir(parents=True)
    (home / "Documents" / "Egosoft" / "X4").write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv("X4_SCAN_HOME", str(home))
    bad = []
    m.profile_ids_from([], m._profile_docs_dirs(), bad)
    note = m.profile_walk_note(bad)
    assert "PARTIAL" in note and "1 could not be read" in note, note


def test_FXB2_TWIN_absent_locations_are_not_PARTIAL(tmp_path, monkeypatch):
    m = _load_scanner()
    monkeypatch.setenv("X4_SCAN_HOME", str(tmp_path / "home"))
    bad = []
    m.profile_ids_from([], m._profile_docs_dirs(), bad)
    note = m.profile_walk_note(bad)
    assert "PARTIAL" not in note and "0 of 3" in note, note


# ------------------ FX-B3 (reviewer F M7): PARTIAL is not clean; the unreadable list is per call

def _unreadable_home(tmp_path: Path) -> None:
    """A known profile location that EXISTS and cannot be listed: a FILE where the folder is."""
    (tmp_path / "home" / "Documents" / "Egosoft").mkdir(parents=True)
    (tmp_path / "home" / "Documents" / "Egosoft" / "X4").write_text("x", encoding="utf-8")


def test_FXB3_a_PARTIAL_walk_with_nothing_found_EXITS_3_not_0(tmp_path):
    """It was a note and exit 0: a scan that could not look where an id lives read clean."""
    repo = _repo(tmp_path, "nothing to see\n")
    _unreadable_home(tmp_path)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "PARTIAL" in r.stdout and "NOT a clean result" in r.stdout, r.stdout
    assert "clean - no contributor" not in r.stdout, r.stdout


def test_FXB3_TWIN_the_same_scan_with_the_location_ABSENT_is_clean(tmp_path):
    repo = _repo(tmp_path, "nothing to see\n")
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 0 and "clean - no contributor" in r.stdout, r.stdout + r.stderr


def test_FXB3_TWIN_a_FINDING_still_wins_over_PARTIAL(tmp_path):
    """1 (found) outranks 3: a partial walk must not hide what the scan DID find."""
    repo = _repo(tmp_path, "C:/Users/someone/Documents/Egosoft/X4/%s/save\n" % FAKE_ID)
    _unreadable_home(tmp_path)
    r = _scan(repo, _env(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr


def test_FXB3_the_HISTORY_mode_with_a_PARTIAL_walk_EXITS_3(tmp_path):
    repo = _repo(tmp_path, "clean\n")
    base = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
    _unreadable_home(tmp_path)
    r = subprocess.run([sys.executable, str(repo / "scripts" / SCRIPT.name), "--history",
                        base + "..HEAD"], cwd=str(repo), capture_output=True, text=True,
                       env=_env(tmp_path), timeout=120)
    assert r.returncode == 3, r.stdout + r.stderr


def test_FXB3_the_unreadable_list_is_PER_CALL_not_module_global(tmp_path, monkeypatch):
    """It was a module-global list appended on every call: a second walk over a HEALTHY
    machine still reported the first walk's failure."""
    m = _load_scanner()
    _unreadable_home(tmp_path)
    monkeypatch.setenv("X4_SCAN_HOME", str(tmp_path / "home"))
    first, second = [], []
    m.profile_ids_from([], m._profile_docs_dirs(), first)
    monkeypatch.setenv("X4_SCAN_HOME", str(tmp_path / "healthy-home"))
    m.profile_ids_from([], m._profile_docs_dirs(), second)
    assert len(first) == 1 and second == [], (first, second)
    assert "PARTIAL" not in m.profile_walk_note(second)
    assert not hasattr(m, "_UNREADABLE"), "the module-global list is back"


# ------------------ FX-B4 (reviewer I): the PARTIAL advice must be true; the note must count
#                    an unreadable location as one that EXISTS

def test_FXB4_the_PARTIAL_verdict_does_not_advise_X4_PROFILE_which_cannot_lift_it(tmp_path):
    """It said "or name the id through X4_PROFILE, and re-run" -- and a re-run with X4_PROFILE
    naming an id still exits 3: naming ONE id says nothing about the others an unreadable
    location may hold, so the walk stays PARTIAL. The advice was false; the exit was right."""
    repo = _repo(tmp_path, "nothing to see\n")
    _unreadable_home(tmp_path)
    r = _scan(repo, _env(tmp_path, X4_PROFILE=str(tmp_path / "prof" / FAKE_ID)))
    assert r.returncode == 3, r.stdout + r.stderr          # still not clean: fail closed
    verdict = [ln for ln in r.stdout.splitlines() if ln.startswith("::error::")]
    assert verdict and "PARTIAL" in verdict[-1], r.stdout
    assert "X4_PROFILE" not in verdict[-1], verdict[-1]
    assert "name the id through X4_PROFILE" not in _load_scanner().__doc__, "the docstring advises it"


def test_FXB4_the_note_counts_an_UNREADABLE_location_as_one_that_EXISTS(tmp_path, monkeypatch):
    """It read "0 of 3 known profile location(s) exist here; PARTIAL -- 1 could not be read":
    the count used is_dir() (False for the unreadable one) and the PARTIAL clause the walk's
    own list. One classification now feeds both."""
    m = _load_scanner()
    _unreadable_home(tmp_path)
    monkeypatch.setenv("X4_SCAN_HOME", str(tmp_path / "home"))
    bad = []
    m.profile_ids_from([], m._profile_docs_dirs(), bad)
    note = m.profile_walk_note(bad)
    assert "1 of 3 known profile location(s) exist" in note and "1 could not be read" in note, note


def test_FXB4_TWIN_a_READABLE_location_still_counts_and_is_not_PARTIAL(tmp_path, monkeypatch):
    m = _load_scanner()
    (tmp_path / "home" / "Documents" / "Egosoft" / "X4").mkdir(parents=True)
    monkeypatch.setenv("X4_SCAN_HOME", str(tmp_path / "home"))
    bad = []
    m.profile_ids_from([], m._profile_docs_dirs(), bad)
    note = m.profile_walk_note(bad)
    assert bad == [] and "1 of 3" in note and "PARTIAL" not in note, note


def test_FXB4_a_PERMISSION_refusal_like_macOS_privacy_is_PARTIAL_and_never_crashes(tmp_path, monkeypatch):
    """macOS refuses a read under a privacy-protected ~/Documents with EPERM. pathlib's
    is_dir() re-raises EPERM (it ignores only ENOENT/ENOTDIR/EBADF/ELOOP), so the note --
    which asked is_dir() -- CRASHED the scan where the walk had recorded PARTIAL. Simulated:
    both the listing and the stat of the location are refused."""
    import errno
    import pathlib
    m = _load_scanner()
    home = tmp_path / "home"
    monkeypatch.setenv("X4_SCAN_HOME", str(home))
    target = home / "Documents" / "Egosoft" / "X4"
    real_iterdir, real_stat = pathlib.Path.iterdir, pathlib.Path.stat

    def deny(p):
        return str(p) == str(target)

    def iterdir(self):
        if deny(self):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(self))
        return real_iterdir(self)

    def stat(self, *a, **kw):
        if deny(self):
            raise PermissionError(errno.EPERM, "Operation not permitted", str(self))
        return real_stat(self, *a, **kw)
    monkeypatch.setattr(pathlib.Path, "iterdir", iterdir)
    monkeypatch.setattr(pathlib.Path, "stat", stat)
    bad = []
    m.profile_ids_from([], m._profile_docs_dirs(), bad)
    assert [str(d) for d in bad] == [str(target)], bad          # fail closed: PARTIAL
    note = m.profile_walk_note(bad)                            # and no crash
    assert "1 of 3" in note and "PARTIAL" in note, note
