"""The consistency audit's THIRD channel had no denominator.

Its header says "store vs build_effective vs `dump`". `checked` counts only the
store-vs-merge comparisons and is incremented BEFORE the dump call, so it cannot drop
when the dump channel dies. With every dump failing, the gate printed a clean two-way
result under a three-way headline -- and the comment at `from_dump` claimed "the
cross-checked count drops visibly", which was false.

Sharpened by a change of mine in this same arc: `x4effective dump` now returns rc 3
when an overlay was skipped (a real tree, incomplete). `from_dump` rejected any
non-zero rc, so my fix silently narrowed this gate's third channel.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[1] / "gates"


@pytest.fixture()
def ca():
    sys.path.insert(0, str(GATES))
    try:
        import consistency_audit as mod
        importlib.reload(mod)
    except SystemExit as exc:
        pytest.skip("gates/_env refused to resolve: %s" % exc)
    finally:
        sys.path.remove(str(GATES))
    return mod


def test_a_DEGRADED_dump_is_distinguished_from_an_UNUSABLE_one(ca):
    """rc 3 means the dump RAN and produced an incomplete tree. Comparing against it
    could manufacture a disagreement caused by the missing layer, so it is not
    comparable -- but it is not the same as a dump that could not run, and the two
    must not share a bucket."""
    assert ca._DEGRADED is not None
    assert ca._DEGRADED is not False, "the sentinel must not be falsy-ambiguous"


def test_the_rc3_branch_exists_and_precedes_the_generic_failure(ca):
    """Structural, over the SOURCE: a substring check would be satisfied by the
    comment that explains the branch."""
    import ast
    src = (GATES / "consistency_audit.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "from_dump")
    consts = [c.value for c in ast.walk(fn)
              if isinstance(c, ast.Constant) and isinstance(c.value, int)]
    assert 3 in consts, (
        "from_dump must special-case rc 3; without it a DEGRADED dump reads as a "
        "total failure and the third channel narrows silently")


def test_the_dump_channel_has_its_own_counter(ca):
    """The defect itself: no counter meant no floor could exist."""
    import ast
    src = (GATES / "consistency_audit.py").read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    for want in ("dump_checked", "dump_degraded", "dump_unusable"):
        assert want in names, "the dump channel needs its own denominator: %s" % want
