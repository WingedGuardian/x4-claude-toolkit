"""A mod shipping md/ or aiscripts/ must not read as a clean pass in default mode.

Reported from real use 2026-08-27: an additive-only `<mdscript>` with three
`md.xsd` violations returned **"OK: no issues found"**, exit 0. Confirmed here, and
the reporter's falsification test was sound -- reintroducing one violation kept
the clean result.

⚠ BUT THE DIAGNOSIS "x4validate does not schema-validate MD" IS WRONG, and the
distinction decides the fix. MEASURED against the same fixtures:

    `<loadout level="1.0"/>`      --update -> [INFO] xsd-strict, rc 0
    `<conditions>` after `<delay>` --update -> [ERROR] xsd,       rc 1

So the tool catches all three; two of them GATE. What it does not do is run any
script check by default, and that is deliberate and documented -- `md.xsd` takes
~102s to compile, so `check_xsd` and the fast `check_required_attrs` pass both sit
behind `--update`.

The defect is therefore narrower than reported and entirely real: **for a mod whose
payload is script files, no applicable check runs at all, and the tool still prints
"OK: no issues found"** -- the sentence the skipped channel exists to prevent. The
same tool already refuses to call a content.xml-only folder a pass.

MEASURED blast radius, and why this is a disclosure rather than a degraded exit:
**79 of 125 installed mods ship script XML and 18 are script-only.** An exit 3 on
18 mods, permanently, clearable only by paying the ~102s compile every run, would
train you to ignore the output.

⚠ The first version of this file said **77 of 124 / 17**. Those figures came from a
plain-prefix test that missed every cross-mod patch at
`extensions/<target>/md/...` — **15 files across 7 mods**, the exact trap
`_xsd.eligible`'s own docstring records having fixed once already. The strip is now
a single shared helper, `_xsd.strip_nesting`.
"""

from pathlib import Path

from x4validate import _check, _merge, _xsd


def _script_mod(tmp_path: Path, body: str, rel: str = "md/probe.xml") -> Path:
    d = tmp_path / "scriptmod"
    (d / Path(rel).parent).mkdir(parents=True)
    (d / rel).write_text(body, encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?>"
        "<content id='scriptmod' name='s' version='100'/>", encoding="utf-8")
    return d


MD = ("<?xml version='1.0' encoding='utf-8'?>"
      "<mdscript name='Probe' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance' "
      "xsi:noNamespaceSchemaLocation='md.xsd'><cues><cue name='C'>"
      "<actions><debug_text text=\"'x'\"/></actions></cue></cues></mdscript>")


def _run(mod: Path):
    report = _check.Report()
    _check.check_script_validation_scope(mod, _merge.Config(), report)
    return report


def test_a_script_file_is_disclosed_as_unvalidated(tmp_path):
    mod = _script_mod(tmp_path, MD)
    report = _run(mod)
    assert report.skipped, "shipping md/ with no script check must not be silent"
    why = " ".join(s.why for s in report.skipped)
    assert "--update" in why, "the disclosure must name the flag that runs the check"
    assert "1" in why, "state HOW MANY files went unvalidated"


def test_the_disclosure_does_NOT_degrade_the_run(tmp_path):
    """Disclosure, not a false exit-3 across most of a real modlist.

    MEASURED over the installed set with the CORRECTED predicate: 79 of 125 mods
    ship script XML and 18 are script-only. An exit 3 firing on 18 mods
    permanently -- clearable only by paying the ~102s compile every run -- converts
    it from "investigate" into "ignore", which is the workspace's own "a check that
    floods is worse than no check".

    Exit 3 stays reserved for a run where something that COULD have been checked
    could not be. Superseded design note: an earlier pass degraded the script-only
    case; it was never committed, because the better answer is to RUN the cheap
    check rather than escalate the exit code.
    """
    mod = _script_mod(tmp_path, MD)
    report = _run(mod)
    assert report.skipped, "still disclosed"
    assert not report.degraded, "disclosure, not a false exit-3 across most of the corpus"


def test_a_mod_with_scripts_AND_other_payload_does_NOT_degrade(tmp_path):
    """The line between disclosure and degradation, and why it is drawn here.

    MEASURED over the installed set: 79 of 125 mods ship script XML but only 18 are
    script-ONLY. Degrading all 77 would fire on most of a real modlist by default,
    and a check that floods is worse than no check -- it trains you to ignore the
    output. The 17 are different in kind: for them the run examined nothing.
    """
    mod = _script_mod(tmp_path, MD)
    (mod / "libraries").mkdir()
    (mod / "libraries" / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    report = _run(mod)
    assert report.skipped, "still disclosed"
    assert not report.degraded, "something else WAS examinable, so this is a real pass"


def test_a_mod_with_NO_script_files_says_nothing(tmp_path):
    """Falsification twin: the disclosure must be about script files, not about
    every mod. Without this the check could 'pass' by always firing."""
    d = tmp_path / "plain"
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='p' version='100'/>",
        encoding="utf-8")
    report = _run(d)
    assert not report.skipped, f"nothing to disclose here: {report.skipped}"


def test_a_script_only_mod_is_no_longer_told_nothing_was_examined(tmp_path):
    """Was `test_a_script_only_mod_says_so_explicitly`, and the change is the point.

    While no script check ran by default, a script-only mod genuinely examined
    nothing that could fail, and the disclosure said so. The required-attribute
    class now runs in every mode (parity-proven, ~0.1s worst case), so that
    sentence would be FALSE -- the run does examine something, and it is complete
    for its class.

    What replaces it is a statement of what is STILL missing, by name: the
    'element not expected' class, where element-ORDERING errors live. Two of the
    three violations in the report that started this work were exactly that class.
    """
    mod = _script_mod(tmp_path, MD)
    why = " ".join(s.why for s in _run(mod).skipped)
    assert "element not expected" in why, why


def test_the_script_dirs_come_from_the_xsd_module(tmp_path):
    """Not a second hard-coded list -- one implementation, asked for by everyone."""
    assert _xsd.SCRIPT_DIRS, "the shared list must be non-empty or the check is vacuous"
    mod = _script_mod(tmp_path, MD, rel=f"{sorted(_xsd.SCRIPT_DIRS)[0]}/probe.xml")
    assert _run(mod).skipped


# --- found by SWEEPING for the shape, not by tripping over it ---------------------

def test_a_schema_declaring_data_file_is_also_disclosed(tmp_path):
    """The same gap, one surface along, found by asking what ELSE is gated.

    `check_effective_schema` validates merged data files against the schema they
    declare, and sits behind `--update` exactly like the script pass. MEASURED: a
    mod patching `libraries/audiologs.xml` (which declares `audiologs.xsd`)
    returned "OK: no issues found" with no mention that the schema pass had not run.

    Weaker than the script-only case -- sel-resolution genuinely examined the diff,
    so exit 0 is defensible -- but the schema claim was still never made and never
    disclosed. Disclosure costs nothing and is the difference between "checked" and
    "not checked".
    """
    d = tmp_path / "datamod"
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "audiologs.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff>"
        "<add sel='/audiologs'><audiolog id='probe'/></add></diff>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='d' version='100'/>",
        encoding="utf-8")
    report = _run(d)
    why = " ".join(s.why for s in report.skipped)
    assert report.skipped, "a schema-declaring data file must not silently go unvalidated"
    assert "--update" in why
    assert not report.degraded, "disclosure only; the diff itself WAS examined"


def test_a_data_file_that_declares_NO_schema_is_not_disclosed(tmp_path):
    """Falsification twin: the disclosure is about files with a schema to check.

    Without this the check could pass by firing on every mod that ships any
    library file at all -- which would flood, and mean nothing.
    """
    d = tmp_path / "plainlib"
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "zzz_not_a_vanilla_file.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='p' version='100'/>",
        encoding="utf-8")
    report = _run(d)
    assert not report.skipped, f"nothing declares a schema here: {report.skipped}"


# --- red-teaming the disclosure found a defect IN IT ------------------------------

def test_a_nested_script_file_is_counted(tmp_path):
    """MEASURED: the shipped plain-prefix test missed 15 files across 7 mods.

    A cross-mod patch lives at `<mymod>/extensions/<target>/md/foo.xml`, which does
    not START with `md/`. `_xsd.eligible`'s own docstring records this exact trap
    ("a plain prefix test let 5 MD scripts through"), and the disclosure added
    hours earlier walked straight into it.

    Real owners of the 15: vro (4), kuertee_additional_agent_actions (3),
    ship_variation_expansion_vro (3), kuertee_npc_reactions (2), and one each from
    atd_ejection_router, kuertee_emergent_missions, zzz_moona_morerooms_fixes.
    All 15 are `<diff>`, none a complete <mdscript>.
    """
    d = tmp_path / "nested"
    inner = d / "extensions" / "someothermod" / "md"
    inner.mkdir(parents=True)
    (inner / "patch.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='n' version='100'/>",
        encoding="utf-8")
    report = _run(d)
    why = " ".join(s.why for s in report.skipped)
    assert report.skipped, "a nested script patch is a script file and must be counted"
    assert "nested" in why.lower(), why


def test_a_nested_file_is_NOT_advertised_as_fixable_by_update(tmp_path):
    """The reason the naive count-them fix would have been WORSE than the bug.

    Both halves of `_xsd.validate_mod` filter `count("/") != 1` -- direct children
    only, deliberately, so the loose and packed halves check the same population.
    So `--update` does NOT validate a nested script file either. Counting nested
    files into a message that says "runs only under `--update`" would have made the
    count complete and the ADVICE false.
    """
    d = tmp_path / "nested2"
    inner = d / "extensions" / "someothermod" / "md"
    inner.mkdir(parents=True)
    (inner / "patch.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='n' version='100'/>",
        encoding="utf-8")
    nested = [s for s in _run(d).skipped if "nested" in s.why.lower()]
    assert nested, "expected a nested-specific disclosure"
    assert "not validated by anything" in nested[0].why.lower(), nested[0].why


def test_a_TOP_LEVEL_script_file_still_says_run_update(tmp_path):
    """Twin: the depth-1 population IS fixable by --update and must keep saying so."""
    mod = _script_mod(tmp_path, MD)
    top = [s for s in _run(mod).skipped if "nested" not in s.why.lower()]
    assert top, "top-level script files must still be disclosed"
    assert "--update" in top[0].why


def test_the_nesting_strip_is_SHARED_not_reimplemented():
    """One implementation, asked for by everyone else (CLAUDE.md: written 7 times).

    The measurement that FOUND this bug re-implemented the strip rather than
    calling it -- the same trap, one level up. `_xsd.eligible` and the disclosure
    must agree by construction, not by both being edited correctly.
    """
    assert hasattr(_xsd, "strip_nesting"), "the strip must be a shared helper"
    assert _xsd.strip_nesting("extensions/vro/md/foo.xml") == "md/foo.xml"
    assert _xsd.strip_nesting("md/foo.xml") == "md/foo.xml"
    assert _xsd.strip_nesting("Extensions/VRO/MD/Foo.xml") == "md/foo.xml", "case-folded"
    # a two-segment path must not be mangled into nothing
    assert _xsd.strip_nesting("extensions/vro") == "extensions/vro"


def test_a_NESTED_ONLY_mod_is_told_nothing_was_examined(tmp_path):
    """A mod whose sole payload is a nested patch never reaches the top-level branch.

    Without the clause on BOTH branches it is never told that nothing was examined
    -- and it is the stronger case, because not even `--update` would examine it.

    Caught by a prediction that disagreed: the corrected tool reported 17
    script-only mods where 18 were predicted, and the missing one
    (`zzz_moona_morerooms_fixes`) ships exactly one nested patch and nothing else.
    """
    d = tmp_path / "nestonly"
    inner = d / "extensions" / "someothermod" / "md"
    inner.mkdir(parents=True)
    (inner / "patch.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='n' version='100'/>",
        encoding="utf-8")
    why = " ".join(s.why for s in _run(d).skipped)
    assert "only payload" in why, why
    assert "nothing that can fail was examined" in why, why


def test_a_nested_patch_ALONGSIDE_other_payload_does_not_claim_that(tmp_path):
    """Twin: the clause must not fire when something else WAS examinable."""
    d = tmp_path / "nestplus"
    inner = d / "extensions" / "someothermod" / "md"
    inner.mkdir(parents=True)
    (inner / "patch.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "libraries").mkdir()
    (d / "libraries" / "wares.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><diff/>", encoding="utf-8")
    (d / "content.xml").write_text(
        "<?xml version='1.0' encoding='utf-8'?><content id='n' version='100'/>",
        encoding="utf-8")
    why = " ".join(s.why for s in _run(d).skipped)
    assert "only payload" not in why, why
