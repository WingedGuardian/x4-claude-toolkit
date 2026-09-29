r"""scan-identifiers.py must REFUSE, not hang, when TMP/TEMP is long enough to
trigger the Windows CreateProcessW hang the fu-hang investigation measured.

MEASURED (reproduced twice): a native Windows process whose TMP env var is
longer than 260 characters (and exists on disk) spins forever inside
CreateProcessW the first time it starts a child of its own. `scan-identifiers.py`
is the exact script this happened to in a real run -- it is the first native
process `scripts/test-hooks.sh` spawns that itself spawns a child (`git`), and
it hung for 15 hours.

A `subprocess.run(..., timeout=...)` around the CALL does NOT help: the hang is
INSIDE `CreateProcessW` before the child is even reported started, so no
timeout on the caller's side is ever reached (the task brief this test was
written against says so explicitly, and it matches the observed 15-hour spin
rather than a bounded one). The only correct move is to never spawn in the
first place, which is what `_tmp_hang_risk` + the `main()` guard do.

This test NEVER actually sets a real 261-character TMP and runs a subprocess
under it -- doing so would reproduce the hang this file exists to prevent, in
the test suite. Everything here monkeypatches the environ dict `_tmp_hang_risk`
is handed, or the `os.environ.get` scan-identifiers.py reads FROM, and calls
`main()` with `git` never actually reachable (the refusal must fire before any
`git` invocation is attempted).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "scan-identifiers.py"

_spec = importlib.util.spec_from_file_location("scan_identifiers_under_test", SCRIPT)
si = importlib.util.module_from_spec(_spec)
sys.modules["scan_identifiers_under_test"] = si
_spec.loader.exec_module(si)


# --------------------------------------------------------------------------
# _tmp_hang_risk: the pure predicate, parameterised so no real long path or
# real Windows machine is needed to exercise either branch.
# --------------------------------------------------------------------------

def test_a_long_tmp_on_windows_is_flagged():
    env = {"TMP": "C:/x/" + "a" * 260}
    assert len(env["TMP"]) > si.TMP_HANG_THRESHOLD
    risk = si._tmp_hang_risk(env, is_windows=True)
    assert risk is not None
    var, length = risk
    assert var == "TMP"
    assert length == len(env["TMP"])


def test_a_long_temp_on_windows_is_ALSO_flagged():
    """TWIN: the task brief says "len(TMP or TEMP)" -- both names, not just one."""
    env = {"TEMP": "C:/x/" + "b" * 300}
    risk = si._tmp_hang_risk(env, is_windows=True)
    assert risk is not None
    assert risk[0] == "TEMP"


def test_exactly_at_the_threshold_is_NOT_flagged():
    """Falsification twin: MEASURED 260 is fine, 261 hangs -- the boundary must
    sit exactly there, not one character either side of where it was measured."""
    env = {"TMP": "x" * si.TMP_HANG_THRESHOLD}
    assert si._tmp_hang_risk(env, is_windows=True) is None


def test_one_over_the_threshold_IS_flagged():
    env = {"TMP": "x" * (si.TMP_HANG_THRESHOLD + 1)}
    assert si._tmp_hang_risk(env, is_windows=True) is not None


def test_a_long_tmp_on_a_NON_windows_platform_is_not_flagged():
    """The hang is CreateProcessW-specific; POSIX exec has no equivalent defect,
    and flagging it there would refuse a scan for no reason on Linux CI."""
    env = {"TMP": "x" * 500}
    assert si._tmp_hang_risk(env, is_windows=False) is None


def test_a_short_tmp_is_not_flagged():
    env = {"TMP": "/tmp/short"}
    assert si._tmp_hang_risk(env, is_windows=True) is None


def test_tmpdir_is_deliberately_not_checked():
    """TMPDIR is the POSIX name and irrelevant to this Windows-only hang; see
    the module's own docstring for why checking it would be a false-refusal risk."""
    env = {"TMPDIR": "x" * 500}
    assert si._tmp_hang_risk(env, is_windows=True) is None


def test_an_absent_var_is_not_flagged():
    assert si._tmp_hang_risk({}, is_windows=True) is None


# --------------------------------------------------------------------------
# main(): the guard must actually fire, exit 2, and refuse BEFORE anything
# that would spawn git. No real long-path fixture, no real subprocess.
# --------------------------------------------------------------------------

def test_main_refuses_with_exit_2_when_tmp_is_long(monkeypatch, capsys):
    # setenv/delenv, never a wholesale replacement of os.environ: `si.os` IS the
    # real `os` module (this is an exec'd script, not a copy), so a full
    # replacement would blow away every other variable in the process
    # environment for the duration of the test.
    monkeypatch.setattr(si.os, "name", "nt")
    monkeypatch.setenv("TMP", "C:/x/" + "a" * 300)
    # If the guard did NOT fire first, this would raise -- proving the refusal
    # really does come before any git invocation, not just before a check that
    # happens to run early for some unrelated reason.
    monkeypatch.setattr(si, "_git", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("git was invoked -- the TMP-hang guard did not refuse first")))
    monkeypatch.setattr(sys, "argv", ["scan-identifiers.py"])
    rc = si.main()
    assert rc == 2
    out = capsys.readouterr().out
    assert "::error::" in out
    assert "TMP" in out


def test_main_refuses_even_in_selftest_mode(monkeypatch, capsys):
    """The guard runs before the --selftest branch too -- refusing on-purpose in
    fewer places is what makes the refusal predictable rather than mode-dependent."""
    monkeypatch.setattr(si.os, "name", "nt")
    monkeypatch.setenv("TMP", "C:/x/" + "a" * 300)
    monkeypatch.setattr(sys, "argv", ["scan-identifiers.py", "--selftest"])
    rc = si.main()
    assert rc == 2


def test_main_does_not_refuse_on_a_normal_environment(monkeypatch):
    """Falsification twin: a real, short TMP must not be caught in the net.

    The guard is asked as WINDOWS directly. Faking `os.name = "nt"` process-wide (the first
    version) made pathlib build a WindowsPath on Linux and crash -- CI ubuntu, v3.3.0."""
    monkeypatch.setenv("TMP", "C:/Users/x/AppData/Local/Temp")
    assert si._tmp_hang_risk({"TMP": "C:/Users/x/AppData/Local/Temp"}, True) is None
    monkeypatch.setattr(sys, "argv", ["scan-identifiers.py", "--selftest"])
    rc = si.main()
    assert rc == 0, "a short, ordinary TMP must not trip the hang guard"
