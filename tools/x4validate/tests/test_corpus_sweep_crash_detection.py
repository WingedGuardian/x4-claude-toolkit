r"""A crash that prints no traceback must still be a crash (F55).

MEASURED 2026-08-25, from the gate's own log on a real run:

    tier a  exit 0: 51 | exit 1: 18 | exit 3221225794: 52
    tier b  exit 3221225794: 121
    CRASHES/HANGS: 0            <-- and the gate returned 0

3221225794 is 0xC0000142, STATUS_DLL_INIT_FAILED: the Windows loader killed the
process before Python started, so it printed nothing at all. Detection was
`"Traceback (most recent call last)" in out` plus a subprocess timeout, and
neither can fire on a process that never ran. **173 of 242 invocations (71.5%)
died and the gate passed.**

The shape is this register's founding one with a twist: not a step that narrows
the data silently, but one that PRINTS THE EVIDENCE AND THEN IGNORES IT IN THE
VERDICT. The exit codes were right there in the distribution block; only the
pass/fail path never consulted them.
"""
from __future__ import annotations

import pytest

from conftest import import_gate


@pytest.fixture
def corpus_sweep():
    """Import the gate PER TEST, never at module scope.

    `corpus_sweep.py` resolves the extensions directory at import time, so on a
    machine with no X4 install the import raises SystemExit. A module-level skip
    would collapse all five tests below into ONE skipped line -- the exact defect
    recorded as F42, where 24 tests vanished behind a single skip and the summary
    said nothing about them. As a fixture, each test is collected and skips on its
    own, so cold and warm collection counts stay equal (they are checked).
    """
    return import_gate("corpus_sweep", module_level=False)

TRACEBACK = "Traceback (most recent call last):\n  File x\nValueError: boom"
LOADER_FAILURE = 3221225794  # 0xC0000142


def test_a_traceback_is_a_crash(corpus_sweep):
    assert corpus_sweep.crash_reason(1, TRACEBACK) is not None


def test_a_loader_failure_with_NO_output_is_a_crash(corpus_sweep):
    """The F55 case. No traceback, no output, no timeout -- the process never ran."""
    reason = corpus_sweep.crash_reason(LOADER_FAILURE, "")
    assert reason is not None, (
        "a process killed by the OS loader prints nothing; if only a traceback counts, "
        "173 of 242 dead runs report as a clean sweep")
    assert str(LOADER_FAILURE) in reason


def test_the_documented_exit_codes_are_NOT_crashes(corpus_sweep):
    """0 clean, 1 findings, 3 skipped-work. A mod with errors is the tool working;
    flagging those would make the gate fire on every run and get ignored."""
    for rc in (0, 1, 3):
        assert corpus_sweep.crash_reason(rc, "some ordinary output") is None, rc


def test_an_undocumented_exit_code_is_a_crash_even_if_it_looks_harmless(corpus_sweep):
    """2 is 'not configured' -- legitimate for a CLI, but never for a sweep that
    just configured it. Anything outside the documented set means the run did not
    reach a verdict, and 'did not reach a verdict' is not 'passed'."""
    assert corpus_sweep.crash_reason(2, "") is not None
    assert corpus_sweep.crash_reason(-1073741819, "") is not None  # 0xC0000005 access violation


def test_the_check_can_actually_fail(corpus_sweep):
    """Falsification twin. If crash_reason ever returned None unconditionally every
    test above would still pass except this one -- a guard you cannot make fail on
    purpose is not verification (#26)."""
    assert corpus_sweep.crash_reason(0, "") is None
    assert corpus_sweep.crash_reason(LOADER_FAILURE, "") is not None
