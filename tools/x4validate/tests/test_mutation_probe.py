r"""The mutation probe must not lie, and must not leave the tree poisoned.

TWO THINGS ARE UNDER TEST, and the second is the one that nearly cost a release.

1. VERDICT HONESTY. A mutant that makes the suite HANG is not a pass. Before
   2026-08-26 the probe had no hang verdict at all and a 1800s timeout, so one
   hanging mutant cost half an hour and then reported as a survivor -- two
   different findings collapsed into one word.

2. CRASH SAFETY. Restore lived only in a `finally:`, and `finally` does not run
   on SIGKILL. A killed probe therefore left a MUTATED SOURCE on disk, and that
   file is TRACKED, so `git status` looks like an ordinary modification. v2.5.0
   shipped exactly that way once -- `> 99999` instead of `> 1`, ambiguous-`sel`
   detection silently off in a public release. MEASURED 2026-08-25: a TaskStop
   that reported success but did not stop left three gate sweeps racing, so the
   "never run a mutating gate against a tree in use" rule can be broken BY
   ACCIDENT, not only by choice.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
import mutation_probe as mp  # noqa: E402


# --- verdict honesty ---------------------------------------------------------

def test_a_timeout_is_HANG_not_a_pass(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=mp.TEST_TIMEOUT)
    monkeypatch.setattr(mp.subprocess, "run", boom)
    monkeypatch.setattr(mp, "ROOT", Path(__file__).resolve().parent.parent)
    assert mp.run_tests(["tests"]) == "hang"


def test_a_nonzero_exit_is_a_KILL(monkeypatch):
    monkeypatch.setattr(mp.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    assert mp.run_tests(["tests"]) == "fail"


def test_a_zero_exit_means_the_mutant_SURVIVED(monkeypatch):
    monkeypatch.setattr(mp.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert mp.run_tests(["tests"]) == "pass"


def test_running_NO_tests_is_never_a_pass(monkeypatch, tmp_path):
    """A target whose test files have all been renamed away must not read as
    'nothing objected'. Nothing was asked -- that is the absence-vs-non-answer
    distinction this whole register exists for."""
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    assert mp.run_tests(["tests/does_not_exist.py"]) != "pass"


def test_the_timeout_is_not_the_old_half_hour():
    assert mp.TEST_TIMEOUT <= 300, (
        "1800s meant a single hanging mutant cost 30 minutes, which is what made "
        "widening this gate unaffordable")


# --- crash safety ------------------------------------------------------------

@pytest.fixture
def fake_tree(tmp_path, monkeypatch):
    """A miniature package with one target, wired into the probe's constants."""
    pkg = tmp_path / "x4validate"; pkg.mkdir()
    (pkg / "_merge.py").write_text("GOOD\n", encoding="utf-8")
    monkeypatch.setattr(mp, "PKG", pkg)
    monkeypatch.setattr(mp, "MARKER", tmp_path / ".mutation-probe-active")
    monkeypatch.setattr(mp, "PRISTINE", tmp_path / ".mutation-probe-pristine")
    monkeypatch.setattr(mp, "MUTANTS", [
        mp.Mutant("_merge.py", "x", "GOOD", "BROKEN", "y")])
    return tmp_path, pkg


def test_a_killed_probe_leaves_recoverable_state(fake_tree):
    """The whole point: simulate SIGKILL by never running the finally block."""
    tmp, pkg = fake_tree
    mp.take_pristine()
    (pkg / "_merge.py").write_text("BROKEN\n", encoding="utf-8")   # mid-mutation death
    assert mp.MARKER.is_file(), "the marker must survive to announce the window"
    assert (pkg / "_merge.py").read_text() == "BROKEN\n"

    assert mp.recover() == 0
    assert (pkg / "_merge.py").read_text() == "GOOD\n", "recovery must restore the bytes"
    assert not mp.MARKER.exists(), "a completed recovery must clear the marker"


def test_recovery_reports_WHICH_file_was_mutated(fake_tree, capsys):
    tmp, pkg = fake_tree
    mp.take_pristine()
    (pkg / "_merge.py").write_text("BROKEN\n", encoding="utf-8")
    mp.recover()
    out = capsys.readouterr().out
    assert "_merge.py" in out and "RESTORED" in out, (
        "a silent recovery is worse than none -- the reader must learn the tree "
        "WAS poisoned, not just that it is fine now")


def test_a_marker_makes_the_probe_REFUSE_with_2(fake_tree, monkeypatch, capsys):
    tmp, pkg = fake_tree
    mp.MARKER.write_text(json.dumps({"pid": 1, "targets": {}}), encoding="utf-8")
    monkeypatch.setattr(mp, "RECOVER", False)
    rc = mp.main()
    assert rc == 2, "cannot-run is exit 2, never 1 (which means 'your code has findings')"
    assert "--recover" in capsys.readouterr().err


def test_recover_on_a_clean_tree_is_a_no_op(fake_tree):
    assert mp.recover() == 0


def test_restore_RAISES_if_it_did_not_actually_restore(fake_tree, monkeypatch):
    """A restore that silently failed to restore is the exact failure this
    section exists to prevent, so it must be loud."""
    tmp, pkg = fake_tree
    mp.take_pristine()
    monkeypatch.setattr(mp.shutil, "copy2", lambda *a, **k: None)  # pretend-copy
    (pkg / "_merge.py").write_text("STILL BROKEN\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        mp.restore_all()


# --- the probe can still aim -------------------------------------------------

def test_every_anchor_is_unique_in_its_real_target():
    """Against the REAL sources, not a fixture. A non-unique anchor means the
    probe mutates the wrong site and every verdict from it is meaningless."""
    root = Path(__file__).resolve().parent.parent
    for m in mp.MUTANTS:
        text = (root / "x4validate" / m.target).read_text(encoding="utf-8")
        assert text.count(m.old) == 1, f"{m.target} :: {m.name} anchor is not unique"


def mp_scope_gaps(root: Path, targets: dict) -> dict:
    """{target: [scoped test paths that do not exist]}, omitting complete targets.

    Extracted so the check itself can be tested. Named gaps beat a bare boolean:
    F62 was invisible for exactly as long as this answered yes/no.
    """
    gaps = {}
    for target, tests in targets.items():
        missing = [t for t in tests if not (root / t).exists()]
        if missing:
            gaps[target] = missing
    return gaps


def test_every_target_has_tests_that_exist():
    """ALL of them, not `any` of them -- see test_the_scope_check_can_actually_fail.

    `run_tests` drops a missing path from the scope, so a test file that was never
    ported does not error, it just quietly stops being run. This is the only thing
    standing between that and a gate reporting 11/11 over a partial scope.
    """
    root = Path(__file__).resolve().parent.parent
    for target in mp.TARGETS:
        assert (root / "x4validate" / target).is_file(), target
    gaps = mp_scope_gaps(root, mp.TARGETS)
    assert gaps == {}, f"scoped test file(s) missing, so the probe measures less than it claims: {gaps}"


def test_every_mutant_names_a_target_with_a_test_scope():
    for m in mp.MUTANTS:
        assert m.target in mp.TARGETS, f"{m.target} has no entry in TARGETS"


def test_the_uniqueness_check_can_actually_fail():
    """Falsification twin. Without this, 'all anchors unique' would be
    indistinguishable from 'the check never looked'."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "x4validate" / "_merge.py").read_text(encoding="utf-8")
    assert text.count("def ") > 1, "a planted non-unique anchor must be detectable"


def test_a_hang_is_re_run_before_being_reported(fake_tree, monkeypatch):
    """A suspend fires `subprocess.run(timeout=)` on wall clock while no CPU time
    passed. MEASURED 2026-08-26: corpus_sweep reported a 20-minute HANG for a mod
    that re-ran in 13s, after the machine slept mid-sweep. Same rule as
    perf_guard (F50) -- confirm before reporting."""
    calls = []

    def flaky(tests):
        # call 1 is the BASELINE (must pass), call 2 is the mutant (hangs),
        # call 3 is the re-run that decides it.
        calls.append(tests)
        return {1: "pass", 2: "hang"}.get(len(calls), "fail")

    monkeypatch.setattr(mp, "run_tests", flaky)
    monkeypatch.setattr(mp, "RECOVER", False)
    rc = mp.main()
    assert len(calls) >= 3, "baseline + first attempt + a re-run after the hang"
    assert rc == 0, "a hang that does not reproduce must not be reported as a finding"


# --- a narrowed scope must announce itself (F62) ------------------------------
#
# `run_tests` filters missing paths out of its scope before invoking pytest. That
# is the right thing to DO and the wrong thing to do SILENTLY: the public copy of
# this gate ran 3 of the 4 `_registry` test files -- because the fourth was never
# ported -- and printed the identical "killed" line. A step that narrows the data
# must announce it, and an empty scope is a non-answer, not a timeout.

def test_a_PARTIALLY_missing_scope_says_which_files_it_skipped(monkeypatch, capsys, tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_real.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))

    mp.run_tests(["tests/test_real.py", "tests/test_vanished.py"])

    out = capsys.readouterr().out
    assert "test_vanished.py" in out, (
        "a silently narrowed scope is the defect this test exists for; "
        f"nothing named the missing file. Got: {out!r}")
    assert "test_real.py" not in out, "only the MISSING files are news"


def test_an_EMPTY_scope_is_its_own_verdict_not_a_hang(monkeypatch, tmp_path):
    """'I had no tests to run' and 'the tests did not finish in 120s' are
    different findings. Reporting the first as the second asserts a timeout that
    was never measured -- and the caller then re-runs it as if confirming a hang."""
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    assert mp.run_tests(["tests/gone.py"]) == "noscope"


def test_an_empty_scope_FAILS_the_gate(monkeypatch, tmp_path, capsys):
    """noscope must not be quietly tolerated either: it is a failure, like
    corpus_sweep's UNCONFIRMED. 'Could not check' is never 'nothing wrong'."""
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    assert mp.run_tests(["tests/gone.py"]) in mp.FAILING_VERDICTS


def test_main_reports_an_empty_scope_SEPARATELY_and_fails(fake_tree, monkeypatch, capsys):
    """A mutant whose scope was empty was never challenged, so it is not a kill.
    Counting it as one is how a gate reports 11/11 while measuring 3 of 4 files."""
    calls = []

    def scoped(tests):
        calls.append(tests)          # call 1 is the BASELINE and must pass
        return "pass" if len(calls) == 1 else "noscope"

    monkeypatch.setattr(mp, "run_tests", scoped)
    monkeypatch.setattr(mp, "RECOVER", False)
    rc = mp.main()
    out = capsys.readouterr().out

    assert rc != 0, "an unchallenged mutant must not make the gate pass"
    assert "NOSCOPE" in out, f"the empty scope was not reported as such:\n{out}"
    assert "killed 0/" in out, f"an unchallenged mutant was counted as killed:\n{out}"


def test_main_REFUSES_when_the_BASELINE_scope_is_empty(fake_tree, monkeypatch, capsys):
    """rc 2 = could not run, never rc 1 = has findings. The F39/F47 distinction."""
    monkeypatch.setattr(mp, "run_tests", lambda tests: "noscope")
    monkeypatch.setattr(mp, "RECOVER", False)
    assert mp.main() == 2


def test_the_scope_check_can_actually_fail(tmp_path):
    """Falsification twin for `all` vs `any`, and the reason F62 went unseen.

    `test_every_target_has_tests_that_exist` used to assert `any(... exists ...)`.
    Its NAME promises every file; its ASSERTION accepted one. Three of four present
    passed -- which is exactly how the public copy of the gate ran 3 of the 4
    `_registry` test files and printed the same `killed` line as a full scope.
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_present.py").write_text("", encoding="utf-8")
    targets = {"_x.py": ["tests/test_present.py", "tests/test_absent.py"]}

    assert any((tmp_path / t).exists() for t in targets["_x.py"]), \
        "precondition: the OLD any() predicate is satisfied by this tree"
    assert mp_scope_gaps(tmp_path, targets) == {"_x.py": ["tests/test_absent.py"]}, \
        "the check must NAME the missing file, not merely fail"

    whole = {"_x.py": ["tests/test_present.py"]}
    assert mp_scope_gaps(tmp_path, whole) == {}, "a complete scope must be clean"
