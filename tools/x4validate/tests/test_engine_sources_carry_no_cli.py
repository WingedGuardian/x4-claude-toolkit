"""An ENGINE_SOURCE must contain no CLI surface (F69).

The `engine` freshness axis hashes the whole BYTES of every `ENGINE_SOURCES`
file. That coarseness is deliberate and safe -- it survives a dirty tree where a
commit hash would not -- but it cannot tell *merge semantics changed* from *an
error message changed*, and the banner it produces asserts the former:

    engine changed: the merge code that produced this has been edited, so the
    SAME inputs would now merge differently

MEASURED 2026-08-27, twice in one session, both times FALSE. Wiring a guard into
`x4effective attr` (CLI text only) moved the hash 40b64b579f2e07ab ->
caef9277b49246c4; adding a DOCSTRING to `_registry.mods()` (10 lines added, 0
removed, 0 executable) moved it again to e3c5f4d5536d239d. Each invalidated the
effective store AND BaseX `x4eff`, requiring rebuilds that could not change one
row. That is the shape that trains you to ignore a banner.

The fix is to make the POPULATION right, not the hash clever: a semantic hash
that missed one real merge change would fail in the UNSAFE direction, and that
is the 2026-08-13 defect where a design decision recorded vanilla engine values
as VRO's (140 of 194 rows, 72%, moved on rebuild with no input file changed).

The target state was already proven achievable when this was written: 5 of the 7
engine sources had zero prints and zero argparse. Only `_effective.py` (42
prints, 1 argparse) and `_diff.py` (9 prints, 1 argparse) carried a CLI.
"""

import ast
from pathlib import Path

from x4validate import _freshness

PKG = Path(_freshness.__file__).resolve().parent

#: print() calls permitted inside an engine source, as a LITERAL with a reason.
#: Not a grandfather clause: growth is a FINDING. These are library-level refusal
#: messages on the unconfigured-install path, not a presentation surface -- they
#: are edited approximately never, and moving them would mean `require()` could
#: no longer explain itself at the point it refuses.
PRINT_ALLOWANCE = {
    "_registry.py": (2, "require(): the unconfigured-install refusal message"),
}


def _tree(name: str) -> ast.Module:
    return ast.parse((PKG / name).read_text(encoding="utf-8"))


def _defs(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _imports(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def _prints(tree: ast.Module) -> int:
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "print")


def test_the_population_is_what_we_think_it_is():
    """Denominator first: a vacuous pass over an empty tuple proves nothing."""
    assert len(_freshness.ENGINE_SOURCES) >= 5, "engine source list looks truncated"
    for name in _freshness.ENGINE_SOURCES:
        assert (PKG / name).is_file(), f"{name} is listed but does not exist"


def test_no_engine_source_parses_command_line_arguments():
    offenders = {n for n in _freshness.ENGINE_SOURCES if "argparse" in _imports(_tree(n))}
    assert not offenders, (
        f"argparse in an engine source: {sorted(offenders)} — a CLI edit there "
        f"invalidates the effective store and BaseX x4eff for nothing")


def test_no_engine_source_defines_a_cli_entry_point():
    bad = {}
    for name in _freshness.ENGINE_SOURCES:
        names = _defs(_tree(name))
        hits = [d for d in names if d == "main" or d.startswith("_cmd_")]
        if hits:
            bad[name] = sorted(hits)
    assert not bad, f"CLI entry points inside engine sources: {bad}"


def test_print_calls_in_engine_sources_stay_within_the_stated_allowance():
    over = {}
    for name in _freshness.ENGINE_SOURCES:
        n = _prints(_tree(name))
        cap = PRINT_ALLOWANCE.get(name, (0, ""))[0]
        if n > cap:
            over[name] = (n, cap)
    assert not over, (
        f"print() beyond the stated allowance {over} — add a reason to "
        f"PRINT_ALLOWANCE only if the call genuinely cannot live in a CLI module")


def test_the_allowance_itself_is_not_stale():
    """An allowance larger than reality is how a cap silently stops binding."""
    for name, (cap, reason) in PRINT_ALLOWANCE.items():
        assert name in _freshness.ENGINE_SOURCES, f"{name} is not an engine source"
        assert reason, f"{name} allowance carries no reason"
        actual = _prints(_tree(name))
        assert actual == cap, (
            f"{name}: allowance says {cap} print(s), file has {actual} — "
            f"tighten the number rather than leaving slack")


def test_the_detector_can_actually_fail(tmp_path):
    """Prove the checks have a reachable failing branch (CLAUDE.md #26)."""
    planted = tmp_path / "_fake_engine.py"
    planted.write_text(
        "import argparse\n"
        "def main():\n"
        "    print('hi')\n"
        "def _cmd_thing():\n"
        "    print('there')\n", encoding="utf-8")
    tree = ast.parse(planted.read_text(encoding="utf-8"))
    assert "argparse" in _imports(tree)
    assert sorted(d for d in _defs(tree) if d == "main" or d.startswith("_cmd_")) == \
        ["_cmd_thing", "main"]
    assert _prints(tree) == 2
