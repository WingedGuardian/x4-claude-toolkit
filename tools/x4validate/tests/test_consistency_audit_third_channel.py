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

from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[1] / "gates"


@pytest.fixture()
def ca(gate_install):
    """A FRESH copy of the gate, imported against conftest's fake install. It used to
    import against the real one and SKIP without it, so on a machine with no X4 (CI)
    none of these ran -- the gate's logic under test needs no install at all."""
    return gate_install.load("consistency_audit")


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
    """The defect itself: no counter meant no floor could exist.

    ⚠ The FIRST version of this test asserted only that the names appear ANYWHERE in
    the module -- and removing their initialisation left it GREEN, because the
    increments and the print still mention them. A test that cannot fail is worse than
    no test: it reads as coverage. Caught by the red-then-green, which is the only
    reason it is not still sitting here passing.

    So: assert they are ASSIGNED (an initialisation, not a mention), and that the
    FLOOR keyed on `dump_checked` reaches a `return 3`.
    """
    import ast
    tree = ast.parse((GATES / "consistency_audit.py").read_text(encoding="utf-8"))
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
    for want in ("dump_checked", "dump_degraded", "dump_unusable"):
        assert want in assigned, (
            "%s must be INITIALISED, not merely mentioned -- without an initial value "
            "there is no counter and no floor can key on it" % want)

    # the floor: `if not dump_checked:` ... `return 3`
    floors = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "dump_checked" not in names:
            continue
        returns = [r for r in ast.walk(node) if isinstance(r, ast.Return)
                   and isinstance(r.value, ast.Constant) and r.value.value == 3]
        if returns:
            floors.append(node.lineno)
    assert floors, (
        "no branch tests dump_checked and returns 3 -- the third channel can still "
        "contribute nothing while the gate reports a clean three-way agreement")


# --- release review 2026-09-26 (pre-arc): a FINDING outranks the dump-channel refusal ----

def _one_row(ca, monkeypatch, merged):
    monkeypatch.setattr(ca._env, "stale_store_refusal", lambda db, who: None)
    monkeypatch.setattr(ca, "store_rows",
                        lambda *a, **k: [("ship_a_macro", "assets/x.xml", "hull.max", "100",
                                          "modA")])
    monkeypatch.setattr(ca, "from_merge", lambda vpath, name, prop: merged)
    monkeypatch.setattr(ca, "from_dump", lambda vpath, name, prop: None)   # dump unusable


def test_a_store_vs_merge_disagreement_is_rc1_even_when_dump_contributed_nothing(
        ca, monkeypatch, capsys):
    """The rc-3 branch returned BEFORE the disagreements were printed, so a real
    store-vs-merge disagreement read as 'dump degraded' whenever the dump channel was
    down."""
    _one_row(ca, monkeypatch, merged="999")
    assert ca.main() == 1
    got = capsys.readouterr()
    assert "store vs merge" in got.out and "ship_a_macro" in got.out
    assert "DEGRADED" in got.err                    # the refusal is still stated


def test_TWIN_no_disagreement_and_no_dump_is_still_rc3(ca, monkeypatch, capsys):
    _one_row(ca, monkeypatch, merged="100")
    assert ca.main() == 3
