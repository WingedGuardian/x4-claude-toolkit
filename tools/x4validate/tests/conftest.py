"""Shared test helpers.

`import_gate` exists because of a real CI failure on the v2.4.0 push: a gate
module imported at test-module scope KILLED THE WHOLE RUN on a machine with no X4
installed.

Every module under `gates/` resolves its paths at IMPORT time (`EXT = _env.extensions()`
and friends — MEASURED: 13 of them do), and `gates/_env.py::skip` reports a missing
install by `raise SystemExit(2)`. That is correct for a gate, which is a script.
But a `SystemExit` during pytest COLLECTION is an INTERNALERROR: pytest aborts the
entire session with exit 3 rather than failing one module. Three test files import
gate modules, so all three were affected; only the first showed up, because
collection stops at the first internal error.

It was invisible locally because unsetting `$X4_*` is NOT the same as having no
game installed — `_paths` still resolved through `.claude/x4-paths.env` and the
real install. Only a genuinely clean machine (CI) could surface it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parent.parent / "gates"


def import_gate(name: str, *, module_level: bool = True):
    """Import a module from `gates/`, or SKIP.

    At module scope::

        cross_tool = import_gate("cross_tool")

    Inside a test, where only that test depends on the gate::

        qa_sweep = import_gate("qa_sweep", module_level=False)

    `module_level` must be False inside a function -- `allow_module_level=True` is
    only legal during collection. Importing inside the test body does NOT avoid the
    problem, it just moves it: the SystemExit becomes a test FAILURE instead of a
    collection abort, and a machine with no X4 install is not a broken toolkit.

    A skip, never a silent pass: pytest reports it distinctly, so "this machine has
    no X4 install" can never read as "the invariants hold".
    """
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    try:
        return importlib.import_module(name)
    except (SystemExit, TypeError, OSError) as exc:
        # A gate can fail to import for TWO reasons on an unconfigured machine, and
        # only one of them is a SystemExit:
        #   gates/_env.py::skip          -> SystemExit(2)      (the documented path)
        #   Path(_paths.<thing>())       -> TypeError          (None is not a PathLike)
        # `gates/claims_audit.py` does the latter at module scope, and CI caught it
        # one push after the SystemExit case was fixed.
        #
        # The skip is CONDITIONED on the environment actually being unresolvable, not
        # on the exception type. A blanket catch would silently swallow a real
        # TypeError in a gate on a properly configured machine -- turning a defect
        # into a green skip, which is the exact inversion this suite exists to stop.
        if not _environment_is_unresolvable():
            raise
        reason = (f"gates/{name}.py needs a configured X4 install "
                  f"({type(exc).__name__} at import: {exc}). "
                  f"Set $X4_GAME / $X4_EXTENSIONS, or see .claude/x4-paths.env.")
        if module_level:
            pytest.skip(reason, allow_module_level=True)
        pytest.skip(reason)


@pytest.fixture(scope="session", autouse=True)
def _reference_for_unit_tests(tmp_path_factory):
    """Give `_merge` an empty reference directory when the machine has no X4.

    Since 2.5.0 `_merge.Config()` REFUSES when no reference tree is configured,
    rather than falling back to a CWD-relative guess (F39). That is right for the
    CLIs — an unconfigured toolkit must not invent an answer — but it changed the
    result of the SUITE depending on the machine it ran on: 15 unit tests that
    construct a Config only to exercise overlay merging, TierB shape or archive
    metadata began failing on a fresh clone with no X4 installed. A new user's
    first `pytest` would have shown 15 errors about their own machine.

    So the tests that do not care about a reference tree are given one that is
    empty, and ONLY when the machine cannot resolve a real one. On a configured
    machine this is inert.

    It does not weaken anything. The refusal is pinned directly by
    `tests/test_unconfigured_refusal.py`, which sets `_merge.REFERENCE = None`
    itself and is unaffected by a default; and the real proof lives in
    `scripts/verify-cold.sh`, which runs the actual EXECUTABLES on a cold
    checkout and requires exit 2. What this fixture buys is that a test result
    means the same thing on every machine — which is the property a suite is for.
    """
    from x4validate import _merge, _paths
    if _paths.reference() is not None:
        yield
        return
    previous = _merge.REFERENCE
    _merge.REFERENCE = tmp_path_factory.mktemp("empty-reference")
    try:
        yield
    finally:
        _merge.REFERENCE = previous


@pytest.fixture
def case_insensitive_fs(tmp_path):
    """Skip unless the filesystem treats `Thing.xml` and `thing.xml` as one file.

    X4 is a Windows game and its VFS is case-insensitive: a mod patching
    `md/thing.xml` reaches a file shipped as `md/Thing.xml`, and the toolkit
    models that. Tests that stage one case and patch the other are therefore
    asserting real engine behaviour — but on a case-sensitive filesystem they
    stage two DIFFERENT files, so the scenario they describe cannot be built and
    the failure says nothing about the code.

    DETECTED, not assumed from `sys.platform`. macOS defaults to
    case-insensitive and Linux does not, but either can be configured the other
    way, and a platform guess would then skip a test that would have run (or run
    one that cannot pass). The precondition is a property of the filesystem, so
    it is measured on the filesystem.
    """
    if not fs_is_case_insensitive(tmp_path):
        pytest.skip("needs a case-insensitive filesystem: this test stages one "
                    "case and patches another, which is a single file under "
                    "X4's Windows VFS but two files here")


def fs_is_case_insensitive(directory) -> bool:
    """Does *directory*'s filesystem fold case? Probed, never assumed.

    Split out of the fixture so both branches are reachable from a test. A
    precondition check that can only ever return one answer on the machine you
    are sitting at is not verified — it is merely unexercised.
    """
    probe = directory / "CaseProbe.tmp"
    probe.write_text("x", encoding="utf-8")
    try:
        return (directory / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


def _environment_is_unresolvable() -> bool:
    """True when this machine has no usable X4 configuration.

    Deliberately checks the THREE things the gates actually need, rather than
    trusting any single one: a machine can have a reference tree but no registry,
    and the failure mode differs per gate.
    """
    try:
        from x4validate import _paths
    except ImportError:
        return True
    return (_paths.registry() is None
            or _paths.game_extensions() is None
            or _paths.reference() is None)


# --------------------------------------------------------------- skip accounting
#
# A skip is a test that did NOT run, and pytest hides them by default: the summary
# says "1159 passed, 14 skipped" and never says WHICH 14 or WHY. That is how 125 tests
# sat skipped for weeks behind a lookup that could not succeed in the public tree --
# a green tick over untested code, guarding a Lua contract whose violation hangs X4.
#
# Two things here, and neither can produce a false failure:
#   * `-rs` in addopts, so every skip is always NAMED with its reason.
#   * a count printed in the summary, plus an OPT-IN ceiling via X4_MAX_SKIPS for a
#     caller that knows its environment (CI). A fixed ceiling would be wrong: a cold
#     machine legitimately skips more than a configured one, and a check that cries
#     wolf is one people learn to ignore.
import os as _os


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    skipped = terminalreporter.stats.get("skipped", [])
    n = len(skipped)
    terminalreporter.write_line("")
    terminalreporter.write_line(
        "skip accounting: %d test(s) did not run. A skip is not a pass; the reasons are "
        "listed above (-rs)." % n)
    cap = _os.environ.get("X4_MAX_SKIPS")
    if cap is None:
        return
    try:
        cap_n = int(cap)
    except ValueError:
        terminalreporter.write_line(
            "  X4_MAX_SKIPS=%r is not a number, so no ceiling was applied. That is a "
            "NON-ANSWER, not a pass." % cap)
        return
    if n > cap_n:
        terminalreporter.write_line(
            "  FAIL: %d skips exceeds X4_MAX_SKIPS=%d. A test that stopped running is "
            "indistinguishable from one that passed unless something counts them." % (n, cap_n))
        terminalreporter._session.exitstatus = 1
