"""A property that could not be checked must not print `ok` and return 0.

`gates/tool_properties.py` had three sites calling `note(True, ..., "SKIPPED: ...")`.
`note()` prints an `ok` line and only appends to `failures` when its first argument is
False -- so a SKIP rendered as a pass, the gate printed "All properties hold." and
returned 0 over checks that never executed.

The file already STATED the rule, at the store-vs-x4eff manifest branch: "A SKIP IS NOT
A PASS ... that is a could-not-check, and it now FAILS rather than printing ok -- the
same rule this file applies to everything else it measures." It did not apply it in
three places. The prose was true and the code was not, which is the same shape as
`_merge.overlay_root` swallowing four lines above the branch forbidding it.

rc 3 rather than rc 1 because these are ENVIRONMENTAL (a CI runner has no effective
store), not defects. `scripts/run-gates.sh` already buckets could-not-run separately
and reports NOT A CLEAN SWEEP.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[1] / "gates"


@pytest.fixture()
def tp(monkeypatch):
    """A fresh import, so the module-level `failures`/`skips` lists start empty."""
    sys.path.insert(0, str(GATES))
    spec = importlib.util.spec_from_file_location(
        "tool_properties_under_test", GATES / "tool_properties.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit as exc:               # unconfigured machine: not this test's subject
        pytest.skip(f"gates/_env refused to resolve: {exc}")
    finally:
        sys.path.remove(str(GATES))
    mod.failures.clear()
    mod.skips.clear()
    return mod


def test_a_skip_is_recorded_separately_from_a_pass(tp):
    tp.skip("some property", "no artifact on this machine")
    assert tp.skips, "a skip must be recorded"
    assert not tp.failures, "a skip is not a FAILURE either -- it is a third state"


def test_a_skip_does_NOT_reach_the_failures_list(tp):
    """The twin against over-correction: turning skips into failures would make every
    CI runner red for an environmental absence, which is why rc 3 exists."""
    tp.skip("some property", "no artifact")
    assert tp.failures == []


def test_note_still_records_a_real_failure(tp):
    """The twin against under-correction: if `note` stopped recording, the skip test
    above would pass over a gate that can no longer fail at all."""
    tp.note(False, "a real violation", "two rows where one was expected")
    assert len(tp.failures) == 1, tp.failures
    assert not tp.skips


def test_no_site_still_launders_a_SKIP_through_note(tp):
    """The defect itself, asserted structurally over the SOURCE.

    A substring check on the rendered output would be satisfied by the word SKIPPED
    appearing in a comment, so this reads the call sites: no `note(` may carry a detail
    string announcing a skip.
    """
    import ast
    src = (GATES / "tool_properties.py").read_text(encoding="utf-8")
    bad = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "note"):
            continue
        for arg in node.args:
            text = ""
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = "".join(v.value for v in arg.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if "SKIP" in text.upper():
                bad.append("tool_properties.py:%d" % node.lineno)
    assert not bad, (
        "these call `note()` with a SKIP message, so a check that could not run "
        "renders as `ok` and the gate returns 0: " + ", ".join(bad))
