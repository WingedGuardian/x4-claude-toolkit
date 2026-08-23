"""`<module group="X">` must name a group libraries/modulegroups.xml defines.

The engine rejects a dangling one at station-generation time:
``FactoryGenerator::GetAllPossibleMacros(): Station group reference 'X' not found or
does not contain any macros``. x4validate could not see this at all until 2026-08-21 —
`modulegroups` was not an indexed registry — so the engine caught a real defect
(cpsdo_faction: 3 entries, 43 engine errors) that we reported clean.

MEASURED before gating, over the installed corpus: 115 mods, 4,391 XML files parsed,
0 scan failures, 22 `<module group=>` references, and exactly ONE mod carrying a
dangling one. No flood, so this gates as an error rather than starting life as INFO.
"""

from pathlib import Path

from x4validate import _check, _merge


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _setup(tmp_path, groups_xml: str, mod_xml: str):
    ref = tmp_path / "reference"
    _write(ref / "libraries/modulegroups.xml", groups_xml)
    mod = tmp_path / "mod"
    _write(mod / "libraries/modules.xml", mod_xml)
    report = _check.Report()
    _check.check_module_groups(mod, _merge.Config(reference=ref), report)
    return report


_ONE_GROUP = '<groups><group name="dockarea_ter"><select macro="m"/></group></groups>'


def test_a_resolving_group_reference_is_clean(tmp_path):
    report = _setup(
        tmp_path, _ONE_GROUP,
        '<diff><add sel="/modules">'
        '<module id="dockarea_central" group="dockarea_ter"/>'
        '</add></diff>')
    assert not report.errors


def test_a_dangling_group_reference_is_an_error_naming_the_group(tmp_path):
    """The real cpsdo_faction shape: the Argon/Paranid hightech-lowtech dockarea split
    copied onto Terran, which is the one race that does not have it."""
    report = _setup(
        tmp_path, _ONE_GROUP,
        '<diff><add sel="/modules">'
        '<module id="dockarea_ter_hightech" group="dockarea_ter_hightech"/>'
        '</add></diff>')
    [err] = report.errors
    assert err.category == "ref"
    assert "dockarea_ter_hightech" in err.message
    assert "modulegroups" in err.message


def test_it_finds_them_in_a_full_file_too_not_only_in_a_diff(tmp_path):
    report = _setup(
        tmp_path, _ONE_GROUP,
        '<modules><module id="x" group="nope"/></modules>')
    assert len(report.errors) == 1


def test_a_group_defined_only_by_a_DLC_still_resolves(tmp_path):
    """Definitions must be the UNION across base + DLC, not the base file alone —
    dockarea_ter is Terran-DLC-defined, so a base-only check would flag every
    Terran module as dangling."""
    ref = tmp_path / "reference"
    _write(ref / "libraries/modulegroups.xml", '<groups><group name="dockarea_arg"/></groups>')
    _write(ref / "extensions/ego_dlc_terran/libraries/modulegroups.xml",
           '<diff><add sel="/groups"><group name="dockarea_ter"/></add></diff>')
    mod = tmp_path / "mod"
    _write(mod / "libraries/modules.xml",
           '<diff><add sel="/modules">'
           '<module id="dockarea_central" group="dockarea_ter"/></add></diff>')
    report = _check.Report()
    _check.check_module_groups(mod, _merge.Config(reference=ref), report)
    assert not report.errors


def test_NO_definitions_is_a_non_answer_and_must_SKIP_not_flag_everything(tmp_path):
    """The load-bearing guard. If modulegroups.xml is missing or defines nothing, every
    reference looks dangling — that is an absent oracle, not 22 findings. A check that
    cannot tell 'no groups defined' from 'group undefined' is the narrowing-step defect
    this codebase keeps re-learning (docs/BLIND-SPOTS.md)."""
    ref = tmp_path / "reference"
    ref.mkdir()
    mod = tmp_path / "mod"
    _write(mod / "libraries/modules.xml",
           '<diff><add sel="/modules"><module id="x" group="anything"/></add></diff>')
    report = _check.Report()
    _check.check_module_groups(mod, _merge.Config(reference=ref), report)
    assert not report.errors, "an absent oracle must not manufacture findings"
    assert report.skipped, "and it must SAY it could not answer"
