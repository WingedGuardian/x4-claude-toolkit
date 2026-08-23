r"""F8: x4similar's score and its ORACLE must weight the same axes.

F8 is closed as consciously WONTFIX, not fixed. x4similar's score deliberately
ignores the flight model: a ship macro exposes 34 numeric axes and only 8 are
scored. That is defensible because the score is advisory by design and
`_similarity.difference_profile` renders the unscored axes on EVERY reported
pair -- MEASURED top axes `physics.drag.forward` (624), `physics.mass` (514),
`physics.inertia.pitch/yaw` (497). Re-weighting would break score continuity with
every historical comparison, for a number that was never meant to be a verdict.

WHAT IS ACTUALLY FIXED HERE is a different, real hazard. `gates/similar_audit.py`
carries a HAND-DUPLICATED copy of the weights. The duplication is correct and
must stay -- an oracle that imported the implementation's constants would be
checking the code against itself, and would have agreed with any bug in it. But
nothing tied the two tables together, so editing one alone would produce a gate
failure that looks like a scoring defect and is really a stale oracle.

Read by AST, never imported: `similar_audit.py` resolves the game install at
module scope, so importing it fails on a machine with no X4 -- which is every CI
runner and every fresh clone.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMPL = ROOT / "x4validate" / "_similarity.py"
ORACLE = ROOT / "gates" / "similar_audit.py"


def _literal_dict(path: Path, name: str) -> dict:
    """The value of a module-level `name = {...}` literal, without importing."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no module-level `{name}` literal in {path.name} -- it was "
                         f"renamed or made dynamic, and this guard has gone blind")


def test_both_tables_are_found_at_all():
    """Denominator guard: an empty dict equals an empty dict, so the equality
    below would pass vacuously if either lookup silently returned nothing."""
    for path, name in ((IMPL, "_WEIGHTS"), (ORACLE, "WEIGHTS")):
        table = _literal_dict(path, name)
        assert table, f"{path.name}:{name} parsed as empty"
        assert len(table) >= 5, f"{path.name}:{name} has only {len(table)} axes"


def test_the_oracle_weights_the_same_axes_as_the_implementation():
    """THE GATE. Independent computation, identical inputs -- that is what makes
    the oracle an oracle rather than a second opinion about a different question."""
    impl = _literal_dict(IMPL, "_WEIGHTS")
    oracle = _literal_dict(ORACLE, "WEIGHTS")
    assert impl == oracle, (
        f"x4similar and gates/similar_audit.py disagree about the scored axes.\n"
        f"  only in _similarity._WEIGHTS: {sorted(set(impl) - set(oracle))}\n"
        f"  only in similar_audit.WEIGHTS: {sorted(set(oracle) - set(impl))}\n"
        f"  differing values: "
        f"{ {k: (impl[k], oracle[k]) for k in set(impl) & set(oracle) if impl[k] != oracle[k]} }\n"
        f"Keep the oracle's copy INDEPENDENT (do not import the constant) -- but "
        f"update both together, or the gate reports a scoring defect that is really "
        f"a stale oracle.")


def test_this_guard_would_notice_a_perturbed_weight(tmp_path):
    """Proven to fail. A guard nobody has seen fail is a guard nobody knows works."""
    impl = _literal_dict(IMPL, "_WEIGHTS")
    fake = tmp_path / "fake.py"
    perturbed = dict(impl)
    key = sorted(perturbed)[0]
    perturbed[key] = perturbed[key] + 1.0
    fake.write_text(f"WEIGHTS = {perturbed!r}\n", encoding="utf-8")
    assert _literal_dict(fake, "WEIGHTS") != impl
