r"""A test must never bail with a bare `return`. It counts as a PASS.

MEASURED 2026-09-04: `test_merge.py` had two load-order invariants that bailed with
`return` when no reference tree was available. Both reported GREEN while asserting
nothing -- in the CI step literally named "Run the suite with NO game installed", which
is the release gate. `test_effective_scope.py` had a third whose assertion had never
executed in this checkout at all.

`X4_MAX_SKIPS` exists to catch exactly this failure -- 125 tests going silently dormant
-- and is STRUCTURALLY BLIND to it, because nothing is skipped. A skip is counted and
named; a return is invisible.

So the rule is mechanical: inside a `def test_*`, a `return` with no value is banned.
`pytest.skip(reason)` says what happened and gets counted. A `return <value>` is left
alone -- pytest warns about those itself -- and helper functions nested inside a test
are exempt, because a bare return is ordinary control flow there.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent.parent.parent   # the repository root


def _bare_returns_in_tests(tree: ast.AST):
    """Every bare `return` whose nearest enclosing function is a test."""
    out = []

    def walk(node, in_test):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # A nested helper is NOT a test, even inside one: its bare return is
                # ordinary control flow and says nothing about the assertion.
                walk(child, child.name.startswith("test_"))
                continue
            if isinstance(child, ast.Lambda):
                continue
            if in_test and isinstance(child, ast.Return) and child.value is None:
                out.append(child.lineno)
            walk(child, in_test)

    walk(tree, False)
    return out


def test_no_test_function_bails_with_a_bare_return():
    offenders = []
    scanned = 0
    # EVERY test file the repo ships, not just this directory. `TESTS.glob` is
    # non-recursive and scoped to `tools/x4validate/tests/`, so it missed SEVEN:
    # the six under `tools/basex/` and `.claude/hooks/test_hook_facts.py`.
    # MEASURED 2026-09-07 by the release reviewer: 113 scanned, 7 unscanned, cost
    # today 0 -- recorded and fixed anyway, because "the cost is zero" is the line
    # nobody re-checks (gotcha #23), and a bare `return` in one of those seven is
    # exactly as invisible as in one of the 113.
    #
    # `X4_MAX_SKIPS` is the check this one backs up: a bare return counts as a
    # PASS and is invisible to the skip ceiling, so a file outside this glob had
    # NEITHER guard.
    roots = [TESTS,
             REPO / "tools" / "basex",
             REPO / ".claude" / "hooks"]
    files = sorted({f for r in roots for f in r.glob("test_*.py") if f.is_file()})
    for path in files:
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line in _bare_returns_in_tests(tree):
            offenders.append("%s:%d" % (path.name, line))
    assert scanned > 100, (
        "only %d test files were scanned -- this guard would be vacuous, and the floor is now 100 because the population is the whole repo" % scanned)
    assert not offenders, (
        "a bare `return` inside a test is counted as a PASS. Use "
        "`pytest.skip(reason)` so it is counted and named:\n  "
        + "\n  ".join(offenders))


def test_the_guard_itself_can_go_red():
    """Without this, a walker that found nothing would look identical to a clean tree."""
    planted = ast.parse(
        "def test_x():\n"
        "    if cond:\n"
        "        return\n"
        "    assert True\n")
    assert _bare_returns_in_tests(planted) == [3]


def test_a_nested_helper_is_not_a_test():
    exempt = ast.parse(
        "def test_x():\n"
        "    def helper(v):\n"
        "        if not v:\n"
        "            return\n"
        "        return v\n"
        "    assert helper(1) == 1\n")
    assert _bare_returns_in_tests(exempt) == []


def test_a_return_WITH_a_value_is_not_the_shape_this_bans():
    """pytest warns about those itself; conflating them would make this noisy."""
    other = ast.parse("def test_x():\n    return 5\n")
    assert _bare_returns_in_tests(other) == []
