r"""The BaseX tests must actually RUN, not merely exist.

THE GAP THIS CLOSES (MEASURED 2026-08-22). `tools/basex/` ships `test_ask.py` and
`test_staleness.py` — **23 tests that pass** — and `pyproject.toml` sets
`testpaths = ["tests"]`, so the main suite never collected one of them. It
reported "593 passed" and said nothing whatsoever about 23 tests it had not
looked at.

That is this register's founding shape, in the test runner itself: a step that
narrows the population and reports success anyway. And the two files are not
incidental — `ask.py` is what REFUSES to render a zero-result as a finding
without a coverage denominator, and `staleness.py` is the freshness contract.
A silent regression in either would remove a guard while every gate stayed green.

Why a subprocess rather than adding `../basex` to `testpaths`: BaseX is
deliberately dev-only and is NOT part of the public bundle (it needs a JVM and a
36M-node corpus). A hard testpath would make `pytest` fail on a fresh public
clone, which is the first thing a new user runs. Present → run it; absent → SKIP
with a reason, so "not checked here" can never read as "checked and fine".
"""

import subprocess
import sys
from pathlib import Path

import pytest

BASEX = Path(__file__).resolve().parent.parent.parent / "basex"
TEST_FILES = ("test_ask.py", "test_staleness.py")


def test_the_basex_tests_pass():
    if not BASEX.is_dir():
        pytest.skip(f"no BaseX tooling at {BASEX} (dev-only, not in the public bundle)")
    present = [f for f in TEST_FILES if (BASEX / f).is_file()]
    if not present:
        pytest.skip(f"BaseX tooling present at {BASEX} but ships no test files")

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *present],
        cwd=BASEX, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, (
        f"the BaseX test suite FAILED ({' '.join(present)}). It is not collected by "
        f"this suite's `testpaths`, so nothing else would have told you.\n\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-1500:]}")


def test_the_expected_basex_test_files_still_exist():
    """Tripwire against the check above quietly becoming a no-op: if a file is
    renamed, the runner would pass over a shrinking set and report green."""
    if not BASEX.is_dir():
        pytest.skip(f"no BaseX tooling at {BASEX} (dev-only)")
    missing = [f for f in TEST_FILES if not (BASEX / f).is_file()]
    assert not missing, (
        f"expected BaseX test file(s) are gone: {missing}. Either they were renamed "
        f"(update TEST_FILES) or deleted (say so deliberately) — but a shrinking test "
        f"set must never be silent.")
