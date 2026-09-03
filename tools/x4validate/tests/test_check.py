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

def test_unpacked_dlc_missing_from_reference_is_info_not_error(tmp_path, monkeypatch):
    ref = tmp_path / "reference"
    # only one DLC unpacked into reference/, mirroring the real gap
    _write(ref / "extensions/ego_dlc_split/libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)

    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    _write(mod / "extensions/ego_dlc_mini_01/assets/units/size_l/ship_l.xml",
           '<diff><replace sel="//ship/@id">x</replace></diff>')

    # The DLC really is present in the game root — that is what makes
    # "installed but not readable from reference/" a true statement here.
    game = tmp_path / "game"
    (game / "extensions/ego_dlc_mini_01").mkdir(parents=True)
    monkeypatch.setattr(_merge, "GAME_ROOT", game)

    sev, cat, msg = _check._no_base_finding(
        "extensions/ego_dlc_mini_01/assets/units/size_l/ship_l.xml", cfg)
    assert sev == "info" and cat == "unverifiable"
    assert "is installed" in msg and "ego_dlc_mini_01" in msg


def test_dlc_absent_from_game_root_is_not_called_installed(tmp_path, monkeypatch):
    """A DLC that is not installed must never be described as installed.

    Regression for a real finding: an X Rebirth mod patching `ego_dlc_2` and
    `ego_dlc_teladi_outpost` drew 11 findings each asserting the DLC "is
    installed but was never unpacked". Neither is an X4 DLC at all. The branch
    reported an install it had never checked — and in a normally-configured run
    it is reachable ONLY when the DLC is missing, so the claim was false every
    time it could fire.
    """
    ref = tmp_path / "reference"
    _write(ref / "extensions/ego_dlc_split/libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)

    game = tmp_path / "game"
    (game / "extensions/ego_dlc_split").mkdir(parents=True)   # exists, but not ego_dlc_2
    monkeypatch.setattr(_merge, "GAME_ROOT", game)

    sev, cat, msg = _check._no_base_finding("extensions/ego_dlc_2/md/Setup_DLC2.xml", cfg)
    assert sev == "info" and cat == "inactive"
    assert "not installed" in msg
    assert "is installed but" not in msg


def test_dlc_verdict_admits_it_cannot_tell_without_a_game_root(tmp_path, monkeypatch):
    """No game root => no evidence either way, and we must say so."""
    ref = tmp_path / "reference"
    _write(ref / "extensions/ego_dlc_split/libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)
    monkeypatch.setattr(_merge, "GAME_ROOT", tmp_path / "no-such-game-root")

    sev, cat, msg = _check._no_base_finding("extensions/ego_dlc_2/md/Setup_DLC2.xml", cfg)
    assert sev == "info" and cat == "unverifiable"
    assert "not configured" in msg


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


def test_huge_op_count_is_flagged_before_the_slow_part(tmp_path):
    """A file with a pathological op count must SAY so, not just appear to hang.

    Applying a diff is O(n^2) in ops-per-file (each op re-evaluates its selector
    against a tree the previous ops grew) — inherent, not a defect to optimize
    away. What IS fixable is the silence: a 32k-op file took >900s with no
    indication that anything was wrong.
    """
    mod = tmp_path / "big"
    (mod / "libraries").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="big" name="b" version="1"/>',
                                     encoding="utf-8")
    ops = "".join(f'<add sel="//wares"><ware id="w{i}"/></add>'
                  for i in range(_check._LARGE_OP_COUNT))
    (mod / "libraries" / "wares.xml").write_text(f"<diff>{ops}</diff>", encoding="utf-8")

    report = _check.Report()
    root = _merge.parse_file(mod / "libraries" / "wares.xml")
    _check._warn_if_pathologically_large(root, "libraries/wares.xml", report)
    assert any(f.severity == "info" and "O(n^2)" in f.message for f in report.findings), \
        report.findings


def test_normal_op_count_is_not_flagged(tmp_path):
    """The largest file in a real ~120-mod install is 1,443 ops — well under the
    threshold, so ordinary content must never see this note."""
    mod = tmp_path / "normal"
    (mod / "libraries").mkdir(parents=True)
    (mod / "libraries" / "wares.xml").write_text(
        "<diff>" + "".join(f'<add sel="//wares"><ware id="w{i}"/></add>'
                           for i in range(1443)) + "</diff>", encoding="utf-8")
    report = _check.Report()
    root = _merge.parse_file(mod / "libraries" / "wares.xml")
    _check._warn_if_pathologically_large(root, "libraries/wares.xml", report)
    assert not report.findings


# --- the nested cross-mod path (mutation survivor, 2026-09-02) ----------------
#
# `nested = _merge._nested_target(vpath, config.packed_dlc_names())` -> `nested = None`
# survived the whole suite. That call is what tells a CROSS-MOD patch from a broken
# one: `extensions/<target>/<rel>` is owned by <target>, not by the base game
# (gotcha #6, and the engine never even opens the bare form). Without it, a patch
# aimed at a mod the user does not have installed -- a designed no-op -- is reported
# as a hard path error, and the two states become indistinguishable in the output.

def test_a_patch_targeting_an_UNINSTALLED_extension_is_a_designed_no_op(monkeypatch):
    from x4validate import _check as C, _merge
    monkeypatch.setattr(C, "_installed_folders", lambda: {"some_other_mod"})
    sev, code, msg = C._no_base_finding(
        "extensions/not_installed_mod/libraries/wares.xml", _merge.Config())
    assert (sev, code) == ("info", "inactive"), (sev, code, msg)
    assert "not_installed_mod" in msg, msg


def test_a_patch_targeting_an_INSTALLED_extension_is_still_a_real_error(monkeypatch):
    """The twin. Without it, a check that excused every extensions/ path would pass
    the test above while hiding genuine path mismatches -- which is the whole reason
    the cross-mod branch has to distinguish installed from not."""
    from x4validate import _check as C, _merge
    monkeypatch.setattr(C, "_installed_folders", lambda: {"target_mod"})
    sev, code, _msg = C._no_base_finding(
        "extensions/target_mod/libraries/wares.xml", _merge.Config())
    assert (sev, code) == ("error", "path"), (sev, code)


def test_a_PLAIN_vpath_is_unaffected_by_the_cross_mod_branch(monkeypatch):
    from x4validate import _check as C, _merge
    monkeypatch.setattr(C, "_installed_folders", lambda: set())
    sev, code, _msg = C._no_base_finding("libraries/wares.xml", _merge.Config())
    assert (sev, code) == ("error", "path"), (sev, code)


def test_an_UNLISTABLE_extensions_dir_says_so_rather_than_excusing_the_patch(monkeypatch):
    """'Could not check' is never 'nothing wrong': downgrading this to `inactive`
    would silently excuse a genuine path mismatch."""
    from x4validate import _check as C, _merge
    monkeypatch.setattr(C, "_installed_folders", lambda: None)
    sev, code, msg = C._no_base_finding(
        "extensions/whatever/libraries/wares.xml", _merge.Config())
    assert (sev, code) == ("info", "unverifiable"), (sev, code, msg)


# ---------------------------------------------- the completeness ORACLE (2026-09-02)
#
# `_refs` answers the `<component ref>` question with whatever set it is handed, and the
# macro INDEX alone is the wrong oracle. A ware whose component ref names a macro defined
# in an asset file but never registered in index/macros.xml was reported "missing
# 'component'" by check_completeness while check_references reported the same ref
# resolving -- two checks contradicting each other about one attribute.


def _completeness_tree(tmp_path, *, define_macro=True, register_in_index=False):
    """A reference tree with one vanilla analogue, and a mod adding one ware.

    The only variable is WHERE the mod's macro is defined: in an asset file, in the
    index, or nowhere.
    """
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml",
           '<wares>'
           '<ware id="vanilla_thing" name="{20101,101}" description="{20101,102}" '
           'group="s" transport="container" volume="1" tags="economy">'
           '<price min="1" average="2" max="3"/>'
           '<production time="1" amount="1" method="default" name="{20206,101}"/>'
           '<component ref="vanilla_macro"/>'
           '<restriction licence="generic"/>'
           '<owner faction="argon"/>'
           '</ware></wares>')
    _write(ref / "t/0001-l044.xml",
           '<language id="44">'
           '<page id="20101"><t id="101">n</t><t id="102">d</t></page>'
           '<page id="20206"><t id="101">m</t></page>'
           '<page id="30101"><t id="101">N</t><t id="102">D</t></page>'
           '</language>')
    _write(ref / "index/macros.xml",
           '<index><entry name="vanilla_macro" value="a/b"/></index>')

    mod = tmp_path / "mod"
    if register_in_index:
        _write(mod / "index/macros.xml",
               '<diff><add sel="/index"><entry name="my_macro" value="x/y"/></add></diff>')
    if define_macro:
        # An ASSET file, which is the legal-and-common case this test is about.
        _write(mod / "assets/units/size_s/macros/my_macro.xml",
               '<macros><macro name="my_macro" class="ship_s"/></macros>')
    _write(mod / "libraries/wares.xml",
           '<diff><add sel="/wares">'
           '<ware id="my_ware" name="{30101,101}" description="{30101,102}" '
           'group="s" transport="container" volume="1" tags="economy">'
           '<price min="1" average="2" max="3"/>'
           '<production time="1" amount="1" method="default" name="{20206,101}"/>'
           '<component ref="my_macro"/>'
           '<restriction licence="generic"/>'
           '<owner faction="argon"/>'
           '</ware></add></diff>')
    return ref, mod


def _completeness_component_errors(tmp_path, **kw):
    ref, mod = _completeness_tree(tmp_path, **kw)
    cfg = _merge.Config(reference=ref)
    report = _check.Report()
    _check.check_completeness(mod, cfg, report, "ware:my_ware", "ware:vanilla_thing")
    assert not report.skipped, f"the fixture degraded: {report.skipped}"
    return [e for e in report.errors if "component" in str(getattr(e, "message", e))]


def test_a_macro_defined_in_an_ASSET_file_does_not_gate_completeness(tmp_path):
    """The bug, reproduced: the macro exists, it is simply not in index/macros.xml --
    which is where a mod under development normally is."""
    assert _completeness_component_errors(tmp_path) == []


def test_a_macro_registered_in_the_INDEX_does_not_gate_either(tmp_path):
    """The half that already worked. Both routes to "this macro exists" must agree, or
    the oracle is still deciding by where the definition happens to live."""
    assert _completeness_component_errors(tmp_path, register_in_index=True) == []


def test_a_component_ref_naming_a_macro_defined_NOWHERE_still_gates(tmp_path):
    """The twin, and the reason the check exists at all. An oracle widened until it
    accepts everything would pass both tests above while checking nothing."""
    errs = _completeness_component_errors(tmp_path, define_macro=False)
    assert errs, "a ref to a macro that exists nowhere must still be reported"
    assert "missing 'component'" in str(getattr(errs[0], "message", errs[0]))


# --- the DEGRADED completeness path, which nothing reached ---------------------------
#
# `_completeness_component_errors` above asserts `not report.skipped`, so every case
# built on it is a NON-degraded one by construction. That is right for what those tests
# are about and it left the degraded branch untested: the mutation gate reported the
# None-preservation as having no test that could detect its removal.
#
#   completeness_defs = (None if macro_def_set is None else EntityDefs(...))
#
# None means "the index could not be built", and `_refs` answers that with a presence
# check alone. EntityDefs has no such state -- handed one, it reports every reference
# it cannot resolve as MISSING. So replacing None with EntityDefs turns an unreadable
# index into a wall of false "missing" errors about references that are perfectly fine.

def test_an_UNREADABLE_index_does_not_turn_real_references_into_missing_ones(
        tmp_path, monkeypatch):
    """The discriminating fixture: a macro defined NOWHERE.

    With None preserved, `_refs` checks presence alone and stays quiet. With
    EntityDefs substituted, the same reference becomes an error -- which is the
    behaviour an unreadable index must NOT produce, because the index being
    unreadable says nothing about whether the reference is real.
    """
    ref, mod = _completeness_tree(tmp_path, define_macro=False,
                                  register_in_index=False)
    # The degraded state itself: collect_macro_defs answers None when it could not
    # build the effective index. Monkeypatched rather than simulated by corrupting a
    # file, so the test pins the CONTRACT (None) instead of one way of reaching it.
    monkeypatch.setattr(_check, "collect_macro_defs",
                        lambda *a, **k: None)
    cfg = _merge.Config(reference=ref)
    report = _check.Report()
    _check.check_completeness(mod, cfg, report, "ware:my_ware", "ware:vanilla_thing")
    component_errors = [e for e in report.errors
                        if "component" in str(getattr(e, "message", e))]
    assert component_errors == [], (
        "an unreadable macro index produced 'missing component' errors; None was not "
        f"preserved: {component_errors}")


def test_the_NON_degraded_path_still_reports_a_genuinely_missing_component(tmp_path):
    """The twin that stops the test above from being satisfiable by silence.

    With a readable index, a macro defined nowhere IS an error -- so the quiet in the
    degraded case is a decision about an unreadable index, not the check being off.
    """
    ref, mod = _completeness_tree(tmp_path, define_macro=False,
                                  register_in_index=False)
    cfg = _merge.Config(reference=ref)
    report = _check.Report()
    _check.check_completeness(mod, cfg, report, "ware:my_ware", "ware:vanilla_thing")
    assert any("component" in str(getattr(e, "message", e)) for e in report.errors), (
        "a macro defined nowhere did not error even with a readable index; the "
        "degraded-path test above would then prove nothing")
