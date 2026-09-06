"""Every gate must be able to report a failure.

`scripts/run-gates.sh` judges a gate purely on its exit code -- `0) ok`, anything else
FAIL -- so a gate that cannot return non-zero is printed `ok` whatever it found, forever.

MEASURED 2026-09-02 by an AST census over all 29 gates: `oracle.py` and `regress.py`
had zero `raise`, zero `assert`, zero `sys.exit` and zero non-zero `return`. The oracle
is the gate the README cites for "234/234 ops agree, 0 FALSE OK"; it computed the
false-OK count, printed it with a marker, and stopped. Over an empty log it printed a
table of zeroes and exited 0, which is indistinguishable from a clean run.

This is the structural half of the fix: the two gates were repaired, and this stops a
third being added without a reachable failing branch. It is deliberately an AST check
rather than a run -- most gates need a configured X4 install, and a test that skipped on
this machine would be exactly the kind of green that cannot go red.
"""
import ast
import pathlib
import re

import pytest

GATES = pathlib.Path(__file__).resolve().parents[1] / "gates"

#: Not a gate -- the package marker. Named rather than pattern-matched, so a real gate
#: cannot be excused by accident.
NOT_A_GATE = {"__init__.py"}


def _failure_paths(tree: ast.AST) -> int:
    """How many ways this module can end non-zero."""
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Raise, ast.Assert)):
            n += 1
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("exit", "SystemExit", "_exit"):
                n += 1
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, int) and node.value.value not in (0, False):
                n += 1
    return n


def _gate_files():
    return [p for p in sorted(GATES.glob("*.py")) if p.name not in NOT_A_GATE]


def test_there_are_gates_to_check():
    """The denominator. A glob that matched nothing would make every assertion below
    vacuously true, which is the failure this file exists to stop."""
    assert len(_gate_files()) >= 20, [p.name for p in _gate_files()]


@pytest.mark.parametrize("path", _gate_files(), ids=lambda p: p.name)
def test_the_gate_can_report_a_failure(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert _failure_paths(tree) > 0, (
        f"{path.name} has no raise, assert, exit or non-zero return, so run-gates.sh "
        f"will print `ok {path.stem}` whatever it finds")


def test_the_detector_itself_can_go_red():
    """The twin. A counter that always returned 1 would pass every case above."""
    assert _failure_paths(ast.parse("print('hi')\n")) == 0
    assert _failure_paths(ast.parse("raise SystemExit(2)\n")) > 0
    assert _failure_paths(ast.parse("import sys\nsys.exit(1)\n")) > 0
    assert _failure_paths(ast.parse("assert x\n")) > 0
    assert _failure_paths(ast.parse("def f():\n    return 3\n")) > 0
    assert _failure_paths(ast.parse("def f():\n    return 0\n")) == 0


#: Any refusal that happens BEFORE the empty log can be reached. Kept as one pattern
#: so a new wording is added in one place rather than discovered in CI.
_CANNOT_REACH_THE_EMPTY_LOG = re.compile(
    r"no mod source directory|needs a configured|no installed extension set"
    r"|no reference tree|^SKIP:", re.M)


def test_the_oracle_REFUSES_an_empty_log_when_it_is_RUN(tmp_path):
    """The twin the AST check structurally cannot be.

    Counting `raise` nodes says nothing about whether they execute. MEASURED
    2026-09-02: the refusal added to `oracle.py` referenced `sys.stderr` in a module
    that never imported `sys`, so it raised NameError -- and the parametrised AST test
    above was GREEN over it, because the `raise SystemExit(2)` node was right there.

    Running the gate is the only thing that could have caught that, so one gate is
    actually run. An empty log is the cheapest input that must reach the refusal.
    """
    import os
    import subprocess
    import sys as _sys

    log = tmp_path / "empty.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ, X4_ORACLE_LOG=str(log))
    r = subprocess.run([_sys.executable, "gates/oracle.py"], cwd=str(GATES.parent),
                       capture_output=True, text=True, env=env)
    # These two hold in EVERY environment, so they are asserted BEFORE the skip.
    # The original order skipped first, which meant that on a machine with no X4 --
    # most machines, and every CI runner -- this test could not have caught the
    # NameError it exists for. A crash on the refusal path is still a crash whether
    # the gate refuses for want of a log or for want of an install.
    assert "NameError" not in r.stderr, r.stderr[-400:]
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])

    # A PATTERN, not a hand-listed pair. The guard named two cold messages and the
    # real one on a clean runner is a third -- "SKIP: no installed extension set" --
    # so the assertion below ran against it and demanded the word REFUSING of a
    # message that says SKIP. Both are refusals; only the wording differed.
    if _CANNOT_REACH_THE_EMPTY_LOG.search(r.stderr):
        pytest.skip("gates/oracle.py refuses earlier without a configured X4 install, "
                    "so the empty-log branch is unreachable here; rc and the crash "
                    "check above still ran, and the AST census covers the rest")
    assert "REFUSING" in r.stderr, r.stderr[-400:]


# --- a mutation harness must not be judged by a STALE .pyc --------------------------

def test_both_mutation_harnesses_disable_bytecode_caching():
    """CPython invalidates a cached .pyc on (source mtime in SECONDS, source size).

    Mutants are written to the same path within the same second, so two of them that
    leave the file the SAME SIZE make the second run import the first one's bytecode --
    and the mutant is then judged by the previous mutant's failures.
    `verify-hook-tests.py` records the measurement: 2 of 54 mutants reported "NOT
    CAUGHT" while each, reproduced by hand, turned its target test red.

    It bites the RESTORE harder, and that direction was measured on 2026-09-03: a
    mutant turning `return 2` into `return 0` is identical in LENGTH, so after
    restoring the pristine source -- byte-identical by sha256 -- the stale .pyc was
    still imported and every later test ran the MUTANT while the file on disk was
    correct. A byte-identity check cannot see it; the defect is in the cache.

    Pinned for BOTH harnesses because only one of them had the fix.
    """
    root = GATES.parent.parent.parent
    files = {
        "scripts/verify-hook-tests.py": root / "scripts" / "verify-hook-tests.py",
        "gates/mutation_probe.py": GATES / "mutation_probe.py",
    }
    for label, path in files.items():
        if not path.is_file():
            pytest.skip(f"{label} is not present -- NOT CHECKED")
        text = path.read_text(encoding="utf-8", errors="replace")
        # STRUCTURAL, not a substring. Both files also NAME the variable in a comment
        # explaining why it is there, so `"PYTHONDONTWRITEBYTECODE" in text` was
        # satisfied by the prose -- deleting the mechanism left the comment and this
        # assertion still passed. Prose satisfies substrings; it does not satisfy an
        # AST node.
        tree = ast.parse(text)
        kwargs = {k.arg for n in ast.walk(tree) if isinstance(n, ast.Call)
                  for k in n.keywords if k.arg}
        assert "PYTHONDONTWRITEBYTECODE" in kwargs, (
            f"{label} does not PASS PYTHONDONTWRITEBYTECODE to a child process (the "
            "name may appear in a comment, which is not the mechanism); a same-length "
            "mutant will be judged by the previous mutant's bytecode")
        purges = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "rglob"
                  and n.args and isinstance(n.args[0], ast.Constant)
                  and n.args[0].value == "__pycache__"]
        assert purges, (
            f"{label} does not walk for __pycache__ to purge it between mutants")


# --- FOUR MORE gates that returned a clean 0 over nothing examined -----------------
#
# The AST census above proves a gate CAN end non-zero. It cannot prove the gate does
# so when it examined nothing -- that is a different question, and four gates answered
# it wrongly. Each now carries the floor `gates/oracle.py` states in its own words:
# "NOTHING EXAMINED IS REFUSED, NOT PASSED ... rc 2 is the NON-ANSWER, rc 1 is
# 'there are findings'."
#
# MEASURED before the fix, through the real gates:
#   claims_audit with no CLAIMS.tsv   -> rc 0, printed by run-gates.sh as `ok claims_audit`
#   consistency_audit --samples=0     -> rc 0, having cross-checked nothing
# and by reading: oracle_reverse printed "We agree with the engine on every checkable
# complaint in this log" over a log with no complaints, and fuzz_diff returned the same
# verdict whether the merge engine applied 58 of 300 structural ops or none.

def _run_gate(name, *args, env_extra=None):
    import os
    import subprocess
    import sys as _sys
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run([_sys.executable, "gates/" + name, *args],
                          cwd=str(GATES.parent), capture_output=True, text=True, env=env)


def test_claims_audit_REFUSES_a_missing_claims_file_rather_than_passing(tmp_path):
    """Both of this gate's non-answers were backwards: an absent claims file returned
    0 (so losing CLAIMS.tsv silently switched the gate off, printed `ok` by
    run-gates.sh), and an absent STORE raised out of sqlite3.connect as an uncaught
    traceback -- rc 1, which reads as FINDINGS."""
    empty = tmp_path / "mods"
    (empty / "_registry").mkdir(parents=True)
    r = _run_gate("claims_audit.py", env_extra={"X4_MODS": str(empty)})
    assert "Traceback" not in r.stderr, r.stderr[-400:]
    assert r.returncode == 2, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert "REFUSING" in r.stderr, r.stderr[-400:]


def test_consistency_audit_REFUSES_when_it_cross_checked_NOTHING():
    """`--samples=0` is the cheapest reachable form; the same state arises whenever
    every sampled value has no merged counterpart (`if merged is None: continue`,
    which has no counter at all)."""
    r = _run_gate("consistency_audit.py", "--samples=0")
    assert "Traceback" not in r.stderr, r.stderr[-400:]
    if r.returncode == 2 and "REFUSING" not in r.stderr:
        pytest.skip("the gate refused earlier for want of a configured store; the rc "
                    "and crash checks above still ran")
    assert r.returncode == 2, (r.returncode, r.stdout[-400:])
    assert "cross-checked" in (r.stdout + r.stderr)


def test_the_four_floors_are_REACHABLE_not_just_present():
    r"""The twin for the AST census, one level up.

    `test_the_gate_can_report_a_failure` counts failure NODES; it was green over a
    refusal that raised NameError because `sys` was never imported. A floor that
    references `sys.stderr` in a module without `import sys` is the same trap, so
    every gate given one is checked for the import.
    """
    import ast as _ast
    for name in ("oracle_reverse.py", "consistency_audit.py", "fuzz_diff.py",
                 "claims_audit.py"):
        src = (GATES / name).read_text(encoding="utf-8")
        tree = _ast.parse(src)
        uses_sys_stderr = any(
            isinstance(n, _ast.Attribute) and n.attr == "stderr"
            and isinstance(n.value, _ast.Name) and n.value.id == "sys"
            for n in _ast.walk(tree))
        imports_sys = any(
            (isinstance(n, _ast.Import) and any(a.name == "sys" for a in n.names))
            or (isinstance(n, _ast.ImportFrom) and n.module == "sys")
            for n in _ast.walk(tree))
        assert not uses_sys_stderr or imports_sys, (
            "%s writes to sys.stderr without importing sys, so its refusal raises "
            "NameError -- the exact defect the oracle refusal shipped with" % name)
        returns_two = any(
            isinstance(n, _ast.Return) and isinstance(n.value, _ast.Constant)
            and n.value.value == 2
            for n in _ast.walk(tree))
        raises_two = any(
            isinstance(n, _ast.Raise) and isinstance(n.exc, _ast.Call)
            and getattr(n.exc.func, "id", "") == "SystemExit"
            for n in _ast.walk(tree))
        assert returns_two or raises_two, (
            "%s has no rc-2 path, so it cannot say 'could not check'" % name)
