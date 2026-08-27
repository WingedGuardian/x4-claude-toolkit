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

MEASURED blast radius, which is why this is a disclosure and not a degraded exit:
**77 of 124 installed mods ship script XML and 17 are script-only.** Degrading 17
in default mode is a behaviour change for a released tool, so it is left as a
decision rather than taken here.
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
    """77 of 124 installed mods ship script XML; degrading them all would flood.

    A check that floods is worse than no check -- it trains you to ignore output.
    """
    mod = _script_mod(tmp_path, MD)
    report = _run(mod)
    assert not report.degraded, "disclosure, not a false exit-3 across most of the corpus"


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


def test_a_script_only_mod_says_so_explicitly(tmp_path):
    """The sharpest case: every other check is vacuous, so 'OK' means 'examined
    nothing that could fail'. MEASURED: 17 of 124 installed mods are script-only."""
    mod = _script_mod(tmp_path, MD)
    report = _run(mod)
    why = " ".join(s.why for s in report.skipped)
    assert "only" in why.lower(), why


def test_the_script_dirs_come_from_the_xsd_module(tmp_path):
    """Not a second hard-coded list -- one implementation, asked for by everyone."""
    assert _xsd.SCRIPT_DIRS, "the shared list must be non-empty or the check is vacuous"
    mod = _script_mod(tmp_path, MD, rel=f"{sorted(_xsd.SCRIPT_DIRS)[0]}/probe.xml")
    assert _run(mod).skipped
