"""The cheap script check must run in a DEFAULT run, not only under --update.

`check_required_attrs` needs no schema compile and its corpus-wide parity with
libxml2 is proven by `gates/xsd_fast_parity.py` (MEASURED 2026-08-27: 555 script
files, 0 false positives, 0 misses). It sat behind `--update` only by association
with `check_xsd`, which costs ~102s to compile `md.xsd`.

MEASURED before making this change:

    check_required_attrs over all 125 installed mods : 6.3s total
    slowest single mod                               : 0.100s
    mods that newly report an ERROR (per-mod census)  : 1  <- a TRUE POSITIVE

`xenon e class ship` has `find_ship` missing its required `space` attribute -- a
real 9.0 breakage the default run could not see before. An earlier measurement
said 0 and was WRONG: it filtered on `f.level` where the field is `f.severity`,
and `getattr(f, 'level', '')` returns '' instead of raising. Use `Report.errors`.

So the exit codes of a real modlist do not move, and a script-only mod stops
being a run where nothing that can fail was examined -- which is the honest way
to satisfy README's "0 = clean AND something was actually examined", rather than
escalating those mods to exit 3 permanently.

⚠ Superseded design: an earlier pass degraded script-only mods to exit 3. It was
never committed. Firing on 18 of 125 mods, clearable only by paying 102s every
run, turns exit 3 from "investigate" into "ignore".
"""

from pathlib import Path

import pytest

from x4validate import _check, _merge, _paths

#: These exercise paths that need a REAL reference tree: `validate()` refuses via
#: `reference_ready` when `libraries/wares.xml` cannot be resolved, and the
#: effective-schema disclosure calls `_merge.build_effective`. conftest supplies an
#: EMPTY reference on a machine with no X4, which is right for tests that only need
#: a Config -- but it makes these return an empty report.
#:
#: A SKIP, never a silent pass: without this they failed on every fresh clone and
#: every CI runner while passing here (F63's shape, and gotcha #26 -- "cold is the
#: check that lies most"). `scripts/verify-cold.sh` is the instrument that catches
#: it; I did not run it on these before pushing, and public CI went red.
needs_reference = pytest.mark.skipif(
    _paths.reference() is None,
    reason="needs a real reference tree (no X4 installed on this machine)")



def _script_mod(tmp_path: Path) -> Path:
    d = tmp_path / "fastmod"
    (d / "md").mkdir(parents=True)
    (d / "md" / "probe.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        "<mdscript name='Probe' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance' "
        "xsi:noNamespaceSchemaLocation='md.xsd'><cues><cue name='C'>"
        "<actions><debug_text text=\"'x'\"/></actions></cue></cues></mdscript>",
        encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='fastmod' version='100'/>",
        encoding="utf-8")
    return d


@needs_reference
def test_the_fast_pass_runs_without_update(tmp_path):
    report = _check.validate(_script_mod(tmp_path), _merge.Config())
    notes = " ".join(report.notes)
    assert "required-attrs" in notes, (
        f"the cheap script check must run by default; notes were: {report.notes}")


@needs_reference
def test_it_reports_how_many_script_files_it_checked(tmp_path):
    """A denominator, not a bare 'checked'. 'checked 1 file, all fine' and
    'checked 14 files, all fine' must not print the same way."""
    report = _check.validate(_script_mod(tmp_path), _merge.Config())
    note = next(n for n in report.notes if "required-attrs" in n)
    assert "1 script file" in note, note


@needs_reference
def test_the_disclosure_no_longer_claims_nothing_was_examined(tmp_path):
    """Once the fast pass runs, that sentence stops being true for a script-only mod."""
    report = _check.validate(_script_mod(tmp_path), _merge.Config())
    why = " ".join(s.why for s in report.skipped)
    assert "nothing that can fail was examined" not in why, why
    assert "element not expected" in why, (
        "state what IS still unchecked, by name: " + why)


@needs_reference
def test_a_mod_with_no_script_files_gets_no_such_note(tmp_path):
    """Twin: without this the check could 'pass' by always emitting the note."""
    d = tmp_path / "plain"
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='p' version='100'/>",
        encoding="utf-8")
    report = _check.validate(d, _merge.Config())
    assert not any("required-attrs" in n for n in report.notes), report.notes


def test_the_fast_pass_is_not_run_TWICE_under_update():
    """Moving the call must not leave a second one in the `--update` branch.

    Duplicate findings are the failure mode `already` exists to prevent.

    Checked STRUCTURALLY, by AST over `validate`, rather than by invoking
    `--update` -- that path compiles md.xsd and costs ~102s, which is not a price
    a unit suite should pay on every run. The invariant is "exactly one call
    site", and that is exactly what this asserts.
    """
    import ast
    from pathlib import Path
    src = Path(_check.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "validate")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "check_required_attrs"]
    assert len(calls) == 1, f"expected exactly one call site, found {len(calls)}"
