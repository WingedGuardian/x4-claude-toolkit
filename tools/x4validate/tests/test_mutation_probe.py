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


def test_every_target_has_tests_that_exist():
    root = Path(__file__).resolve().parent.parent
    for target, tests in mp.TARGETS.items():
        assert (root / "x4validate" / target).is_file(), target
        assert any((root / t).exists() for t in tests), f"{target} has no runnable tests"


def test_every_mutant_names_a_target_with_a_test_scope():
    for m in mp.MUTANTS:
        assert m.target in mp.TARGETS, f"{m.target} has no entry in TARGETS"


def test_the_uniqueness_check_can_actually_fail():
    """Falsification twin. Without this, 'all anchors unique' would be
    indistinguishable from 'the check never looked'."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "x4validate" / "_merge.py").read_text(encoding="utf-8")
    assert text.count("def ") > 1, "a planted non-unique anchor must be detectable"
