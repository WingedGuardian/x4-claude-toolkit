"""End-to-end checks incl. the t-file UNION regression (ATD strings in 0001.xml)."""

from pathlib import Path

from x4validate import _check, _merge


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_missing_reference_tree_is_loud_error_not_false_ok(tmp_path):
    """A mod with a real no-op sel must NOT pass just because reference is absent."""
    cfg = _merge.Config(reference=tmp_path / "does_not_exist")
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@id=\'ore\']/@x">1</replace></diff>')

    report = _check.validate(mod, cfg)
    assert report.errors, "missing reference tree must produce an error, not 'OK'"
    assert any(f.category == "reference" for f in report.errors)


def test_empty_reference_tree_is_loud_error(tmp_path):
    """Reference dir exists but has no base wares.xml -> still a loud error."""
    ref = tmp_path / "reference"
    ref.mkdir()
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@id=\'ore\']/@x">1</replace></diff>')

    report = _check.validate(mod, cfg)
    assert any(f.category == "reference" for f in report.errors)


def test_text_defs_union_across_base_dlc_mod(tmp_path):
    ref = tmp_path / "reference"
    # Base English file (would be wiped by a naive override):
    _write(ref / "t/0001-l044.xml",
           '<language id="44"><page id="1"><t id="1">base</t></page></language>')
    # DLC adds a different page via a FULL <language> file (must union, not override):
    _write(ref / "extensions/ego_dlc_x/t/0001-l044.xml",
           '<language id="44"><page id="2"><t id="2">dlc</t></page></language>')
    cfg = _merge.Config(reference=ref)

    # Mod defines its strings in the language-neutral 0001.xml via a diff:
    mod = tmp_path / "mod"
    _write(mod / "t/0001.xml",
           '<diff><add sel="/language"><page id="111204"><t id="200">x</t></page></add></diff>')

    defs = _check.collect_text_defs(cfg, [mod])
    assert ("1", "1") in defs       # base survived
    assert ("2", "2") in defs       # DLC unioned
    assert ("111204", "200") in defs  # mod's neutral-file string seen


def test_validate_no_false_dangling_when_strings_in_neutral_file(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "libraries/factions.xml", '<factions/>')
    _write(ref / "t/0001-l044.xml", '<language id="44"><page id="1"><t id="1">b</t></page></language>')
    _write(ref / "libraries/wares.xml", '<wares/>')
    cfg = _merge.Config(reference=ref)

    mod = tmp_path / "mod"
    _write(mod / "libraries/factions.xml",
           '<diff><add sel="/factions"><faction id="trust" name="{111204,200}"/></add></diff>')
    _write(mod / "t/0001.xml",
           '<diff><add sel="/language"><page id="111204"><t id="200">Trust</t></page></add></diff>')

    report = _check.validate(mod, cfg)
    ref_findings = [f for f in report.findings if f.category == "ref"]
    assert ref_findings == [], [f.message for f in ref_findings]


# --------------------------------------------------------------------------
# extensions/ego_dlc_*/... whose DLC was never unpacked into reference/.
#
# Real incident (2026-07-26): ego_dlc_mini_01 (Hyperion Pack) and ego_dlc_mini_02
# (Envoy Pack) are genuinely installed+packed in the live game but were never
# unpacked into reference/ (only the 6 DLC named in CLAUDE.md were). A patch
# targeting Hyperion content reported a hard ERROR ("no base game file"), which
# asserts the file doesn't exist — something we cannot actually know, since our
# reference simply never covered that DLC.
# --------------------------------------------------------------------------

def test_unpacked_dlc_missing_from_reference_is_info_not_error(tmp_path):
    ref = tmp_path / "reference"
    # only one DLC unpacked into reference/, mirroring the real gap
    _write(ref / "extensions/ego_dlc_split/libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / "extensions/ego_dlc_mini_01/assets/units/size_l/ship_l.xml",
           '<diff><replace sel="//ship/@id">x</replace></diff>')

    sev, cat, msg = _check._no_base_finding(
        "extensions/ego_dlc_mini_01/assets/units/size_l/ship_l.xml", cfg)
    assert sev == "info"
    assert "never unpacked" in msg and "ego_dlc_mini_01" in msg


def test_dlc_unpacked_in_reference_still_reports_real_path_mismatch(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "extensions/ego_dlc_split/libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)

    sev, cat, msg = _check._no_base_finding(
        "extensions/ego_dlc_split/libraries/nonexistent.xml", cfg)
    assert sev == "error" and cat == "path"


# --------------------------------------------------------------------------
# F19: a <diff> at a BARE mirrored path over another MOD's file is INERT — the
# engine only consults reference/ + DLC for that path and never opens the file.
# Tier B hid this completely: an installed mod's full file satisfies `base_found`,
# so the tree is non-None and the Tier A error is CURED by installing more mods.
# Measured on the live 101-mod install before the fix: Tier A 7 errors,
# Tier B 0 errors exit 0 — a false OK, in the tier used for cross-mod work.
# Population: 7 true positives in 1 mod, against 33 t/ files that must NOT flag.
# --------------------------------------------------------------------------

def _f19_world(tmp_path, *, base_file: str | None = None):
    """reference/ (+ optional base file) and one installed supplier mod.

    `libraries/wares.xml` is NOT decoration: validate() refuses to run against an
    incomplete reference tree and returns only that error. Without the sentinel these
    tests would assert "no path finding" against a check that never executed — three
    of the six failed outright and the t/ one passed VACUOUSLY when this was omitted.
    """
    ref = tmp_path / "reference"
    (ref / "extensions").mkdir(parents=True)
    _write(ref / "libraries/wares.xml", "<wares/>")
    if base_file:
        _write(ref / base_file, "<macros/>")
    supplier = tmp_path / "supplier_mod"
    _write(supplier / "content.xml", '<content id="supplier"/>')
    return ref, supplier


def test_bare_path_diff_over_a_mod_only_file_is_an_error(tmp_path):
    """The 7-file class: names the supplier and the path the file must move to."""
    ref, supplier = _f19_world(tmp_path)
    rel = "assets/units/size_s/macros/ship_x_macro.xml"
    _write(supplier / rel, '<macros><macro name="ship_x"/></macros>')
    cfg = _merge.Config(reference=ref, overlays=(supplier,))

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / rel, '<diff><replace sel="//macro/@name">y</replace></diff>')

    report = _check.validate(mod, cfg)
    paths = [f for f in report.errors if f.category == "path"]
    assert len(paths) == 1, [f.message for f in report.errors]
    assert "supplier_mod" in paths[0].message
    assert f"extensions/supplier_mod/{rel}" in paths[0].message


def test_bare_path_diff_over_a_real_base_file_is_fine(tmp_path):
    """The ~1,510-vpath majority. Also covers a DLC-supplied base, which reaches
    base_from_game through the overlay loop rather than the reference/ branch."""
    rel = "libraries/shipsizes.xml"
    ref, supplier = _f19_world(tmp_path, base_file=rel)
    cfg = _merge.Config(reference=ref, overlays=(supplier,))
    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / rel, '<diff><add sel="//macros"><macro name="q"/></add></diff>')
    assert not [f for f in _check.validate(mod, cfg).errors if f.category == "path"]

    # DLC layer supplies it, reference/ does not.
    dlc_rel = "libraries/dlconly.xml"
    _write(ref / "extensions/ego_dlc_split" / dlc_rel, "<macros/>")
    mod2 = tmp_path / "mod2"
    _write(mod2 / "content.xml", '<content id="mod2"/>')
    _write(mod2 / dlc_rel, '<diff><add sel="//macros"><macro name="q"/></add></diff>')
    assert not [f for f in _check.validate(mod2, cfg).errors if f.category == "path"]


def test_t_file_diff_with_only_mod_suppliers_is_not_flagged(tmp_path):
    """The 33 false positives this check had to avoid. t/*.xml has no single base
    file; build_effective synthesizes a <language> root because the ENGINE supplies
    one, so a t/ diff is well-founded even when only mods ship that path."""
    ref, supplier = _f19_world(tmp_path)
    _write(supplier / "t/0001.xml", '<language id="44"><page id="1"/></language>')
    cfg = _merge.Config(reference=ref, overlays=(supplier,))

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / "t/0001.xml",
           '<diff><add sel="/language"><page id="99"><t id="1">x</t></page></add></diff>')
    assert not [f for f in _check.validate(mod, cfg).errors if f.category == "path"]


def test_nested_form_is_never_flagged_inert(tmp_path):
    """The CORRECT idiom must stay silent — it is what the finding tells you to do."""
    ref, supplier = _f19_world(tmp_path)
    rel = "assets/units/size_s/macros/ship_x_macro.xml"
    _write(supplier / rel, '<macros><macro name="ship_x"/></macros>')
    cfg = _merge.Config(reference=ref, overlays=(supplier,))

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / f"extensions/supplier_mod/{rel}",
           '<diff><replace sel="//macro/@name">y</replace></diff>')
    assert not [f for f in _check.validate(mod, cfg).errors if f.category == "path"]


def test_no_source_anywhere_still_reports_no_base_finding(tmp_path):
    """No double-report with the existing 16-file 'nobody supplies it' class:
    that one leaves tree None, so the inert branch is never reached."""
    ref, supplier = _f19_world(tmp_path)
    cfg = _merge.Config(reference=ref, overlays=(supplier,))
    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / "libraries/nobody_has_this.xml",
           '<diff><replace sel="//x/@y">1</replace></diff>')

    paths = [f for f in _check.validate(mod, cfg).errors if f.category == "path"]
    assert len(paths) == 1
    assert "no base game file" in paths[0].message
    assert "engine never loads it" not in paths[0].message


def test_inert_bare_path_skips_op_checking(tmp_path):
    """A sel that would FAIL against the supplier's tree must not add a second
    finding: op verdicts on a file the engine never opens are noise, and a
    PASSING one would be the false reassurance this whole check exists to kill."""
    ref, supplier = _f19_world(tmp_path)
    rel = "assets/units/size_s/macros/ship_x_macro.xml"
    _write(supplier / rel, '<macros><macro name="ship_x"/></macros>')
    cfg = _merge.Config(reference=ref, overlays=(supplier,))

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / rel, '<diff><replace sel="//nope/@gone">1</replace></diff>')

    report = _check.validate(mod, cfg)
    assert len([f for f in report.errors if f.category == "path"]) == 1
    assert not [f for f in report.errors if f.category == "sel"]


def test_only_file_missing_reports_instead_of_raising(tmp_path):
    """A typo'd --file must be a finding, not a traceback.

    `_merge.parse_file` raises OSError for a missing path, but the handler only
    caught XMLSyntaxError — so `x4validate --file no/such.xml` crashed with a raw
    lxml OSError instead of telling the user the path was wrong.
    """
    mod = tmp_path / "mod"
    mod.mkdir()
    report = _check.Report()
    _check.check_sel_resolution_one(mod / "nope.xml", mod, _merge.Config(), report)
    assert any(f.category == "path" and "cannot read file" in f.message
               for f in report.findings), report.findings
