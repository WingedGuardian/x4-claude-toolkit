"""No statement may sit after an unconditional exit in the same block.

WHY THIS EXISTS. `_effective._extract_registry` carried SEVEN unreachable statements
after an unconditional `return out` -- a superseded copy of the block above it, left
behind when its reporting moved to the call site. Dead code is usually harmless; this
was not, for two reasons that generalise:

  1. It called `rec.note(...)`, and `Recorder` has no `note` method anywhere in the
     package. A guaranteed AttributeError, invisible only because nothing could reach
     it. Un-delete one `return` and the module raises.
  2. It was the RICHER of the two copies -- it carried a denominator report the live
     block does not. So reading the function told you the denominator was handled
     THERE, when in fact it is handled at the call site. Dead code does not just fail
     to run; it misinforms the next reader about where behaviour lives.

Found by the v3.1.0 release review by reading. Reading does not scale, so this is the
mechanised form: the whole package, every function, every block.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "x4validate"
#: `raise` and `return` end a block unconditionally. `continue`/`break` do too, but
#: only inside a loop, and pinning those needs loop context -- deliberately out of
#: scope rather than half-checked.
_TERMINAL = (ast.Return, ast.Raise)


def _unreachable_in(src: str, label: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(src)):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body):
            if isinstance(stmt, _TERMINAL) and i < len(body) - 1:
                dead = body[i + 1:]
                out.append("%s: %s at line %d, then %d unreachable statement(s) "
                           "starting line %d" % (label, type(stmt).__name__.lower(),
                                                 stmt.lineno, len(dead), dead[0].lineno))
    return out


def test_the_detector_actually_detects():
    """The twin, first. Without it a bug in `_unreachable_in` reports the package
    clean and the real test below passes over an empty measurement -- a verdict
    reachable from an input the instrument failed to read."""
    planted = "def f():\n    return 1\n    x = 2\n    y = 3\n"
    hits = _unreachable_in(planted, "<planted>")
    assert len(hits) == 1, hits
    assert "2 unreachable" in hits[0], hits


def test_the_detector_does_not_cry_wolf():
    """The second twin: a `return` that legitimately ENDS a block, and one inside an
    `if`, must not register. Otherwise the test above passes for a detector that
    flags everything."""
    clean = ("def f(a):\n"
             "    if a:\n"
             "        return 1\n"
             "    return 2\n"
             "\n"
             "def g():\n"
             "    for i in range(3):\n"
             "        if i:\n"
             "            return i\n"
             "    raise ValueError('none')\n")
    assert _unreachable_in(clean, "<clean>") == []


def test_no_module_in_the_package_carries_unreachable_code():
    mods = sorted(PKG.glob("*.py"))
    assert len(mods) > 10, (
        "expected the whole package; %d files is not a measurement" % len(mods))
    findings = []
    for p in mods:
        findings += _unreachable_in(p.read_text(encoding="utf-8"), p.name)
    assert not findings, (
        "unreachable code (it cannot run, and it misinforms the reader about where "
        "behaviour lives):\n  " + "\n  ".join(findings))
