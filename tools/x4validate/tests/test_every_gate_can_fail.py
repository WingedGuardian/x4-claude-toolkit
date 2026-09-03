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
    if "no mod source directory" in r.stderr or "needs a configured" in r.stderr:
        pytest.skip("gates/oracle.py needs a configured X4 install to reach its own "
                    "refusal; the AST check above still covers it")
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])
    assert "REFUSING" in r.stderr, r.stderr[-400:]
    assert "NameError" not in r.stderr, r.stderr[-400:]
