r"""A killed scanner must not be reported as a leaked identifier.

MEASURED (the fu-hang investigation): a `scan-identifiers.py` hung by the
TMP-length bug (see `test_shell_scripts_never_reassign_tmp.py`) and then ended
with `taskkill /F` exits 1 with NO stdout at all. `scripts/test-hooks.sh` used
to read rc==1 alone as "a personal identifier reached a tracked file" -- the
SAME rc `scan-identifiers.py` uses for a real finding (its `main()` prints one
or more `::error file=<path>,line=<n>::` lines and then returns 1). So a kill
was misattributed as a leak, and the suite reported a FAIL that named the
wrong cause entirely.

`scripts/_scan-classify.sh::classify_scan_result` is the fix: it requires
POSITIVE evidence (an `::error file=` line) before calling the result "leak",
and reports "unknown" -- a scanner failure/cannot-confirm, not a finding -- for
any other non-zero rc. This is the ONE implementation `test-hooks.sh` sources,
so this test exercises the real shell function rather than a re-implementation
that could only ever prove two copies agree with each other and not with
reality (`scripts/scan-identifiers.py`'s own docstring makes exactly this
argument for why it exposes one `account_match` rather than two).
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HELPER = REPO / "scripts" / "_scan-classify.sh"


def _find_bash() -> str | None:
    """The bash this repo's scripts actually run under.

    MEASURED: plain `subprocess.run(["bash", ...])` on this machine resolved to
    `C:\\Windows\\System32\\bash.exe` -- the WSL launcher stub -- ahead of Git
    Bash on PATH, and it fails outright with no WSL distro installed
    (`execvpe(/bin/bash) failed`). Every other script and hook in this repo
    runs under Git Bash, so a test that silently picked a different one would
    not be testing the same interpreter as production.
    """
    if platform.system() == "Windows":
        for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                          r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(candidate).is_file():
                return candidate
    return shutil.which("bash")


def _classify(rc: str, out: str) -> str:
    """Call the REAL shell function, passed as argv so quoting never matters --
    `out` can contain anything (newlines, quotes, `::error` text) without any
    shell re-interpreting it."""
    if not HELPER.is_file():
        pytest.skip(f"{HELPER} not present in this tree")
    bash = _find_bash()
    if not bash:
        pytest.skip("no usable bash found on this machine")
    r = subprocess.run(
        [bash, "-c", 'source "$1"; classify_scan_result "$2" "$3"',
         "bash", str(HELPER), rc, out],
        capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_rc_zero_is_clean_regardless_of_output():
    assert _classify("0", "") == "clean"
    assert _classify("0", "scanning 42 tracked file(s) ... clean") == "clean"


def test_a_real_finding_with_error_file_evidence_is_a_leak():
    out = ("  scanning 42 tracked file(s) against 3 identifier(s)\n"
           "::error file=tests/fixture.py,line=7::a contributor identifier "
           "appears here; replace it with a generic description\n"
           "::error::1 line(s) contain a contributor identifier.\n")
    assert _classify("1", out) == "leak"


def test_a_killed_scanner_rc_1_with_no_output_is_NOT_a_leak():
    """THE regression case: taskkill'd hang, exit 1, zero bytes of stdout."""
    assert _classify("1", "") == "unknown"


def test_rc_1_with_unrelated_output_and_no_error_file_is_NOT_a_leak():
    """A crash that happens to print something, but never an ::error file= line,
    is still not evidence of a finding -- the check is on the MARKER, not on rc."""
    assert _classify("1", "Traceback (most recent call last):\n"
                          "  File \"scan-identifiers.py\", line 1\nSomeError\n") == "unknown"


def test_rc_2_cannot_run_is_unknown_not_leak():
    assert _classify("2", "::error::cannot run the identifier scan: ...") == "unknown"


def test_the_helper_is_the_one_sourced_by_test_hooks_sh():
    """One implementation, asked for by everyone -- if test-hooks.sh ever stops
    sourcing this file, this test cannot see it, so pin the reference too."""
    text = (REPO / "scripts" / "test-hooks.sh").read_text(encoding="utf-8")
    assert "scripts/_scan-classify.sh" in text, (
        "test-hooks.sh no longer sources the shared classifier -- the "
        "misattribution fix and this test would have silently diverged")
    assert "classify_scan_result" in text
