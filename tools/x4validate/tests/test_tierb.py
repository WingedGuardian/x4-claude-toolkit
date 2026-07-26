"""Tier B (installed-set merge) + if= guard awareness.

Both behaviours come from one real incident (2026-07-25):

  * `xspvro` ships index/macros.xml as a <diff> that <remove>s
    `turret_xen_m_beam_02_mk1_macro` and never re-adds it. Six other mods still
    reference that vanilla macro, producing 415 engine errors. Tier A (base+DLC)
    cannot see the removal at all, so it reported the macro as defined — a false OK.

  * The overlay written to repair it uses if= guards so it no-ops when xspvro is
    absent. The sel-checker did not know if= existed and reported those
    deliberately-guarded ops as hard ERRORs — a false alarm.
"""

from pathlib import Path

from x4validate import _check, _merge


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _ref_with_wares(tmp_path: Path) -> Path:
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml", '<wares><ware id="ore"/></wares>')
    return ref


# --------------------------------------------------------------------------
# if= guard awareness
# --------------------------------------------------------------------------

def test_if_false_guard_is_info_not_error(tmp_path):
    """A guarded op whose guard is false is a DESIGNED no-op, not a failure."""
    ref = _ref_with_wares(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff>'
           '<replace sel="//ware[@id=\'nosuch\']/@price" if="//ware[@id=\'nosuch\']">5</replace>'
           '</diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    sel = [f for f in report.findings if f.category == "sel"]
    assert not [f for f in sel if f.severity == "error"], \
        "if=-guarded no-op must not be an error"
    assert any(f.severity == "info" and "if= is false" in f.message for f in sel)


def test_if_open_but_sel_misses_is_still_error(tmp_path):
    """Guard passes -> the author asserted the target exists -> a miss is real."""
    ref = _ref_with_wares(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff>'
           # guard is TRUE (ore exists) but sel targets a node that does not
           '<replace sel="//ware[@id=\'ore\']/@nosuchattr" if="//ware[@id=\'ore\']">5</replace>'
           '</diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    errs = [f for f in report.errors if f.category == "sel"]
    assert errs, "an open guard with a missing sel target must still error"
    assert "if= passed" in errs[0].message


def test_invalid_if_xpath_is_error(tmp_path):
    ref = _ref_with_wares(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware" if="//[[[">5</replace></diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    assert any("invalid if=" in f.message for f in report.errors)


def test_guarded_op_order_matches_merge_engine(tmp_path):
    """if= is evaluated BEFORE sel= — an invalid sel behind a false guard is
    unreachable in _merge, so the checker must not evaluate it either."""
    ref = _ref_with_wares(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//[[[" if="//ware[@id=\'nosuch\']">5</replace></diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    assert not report.errors, "false guard must short-circuit before sel= is parsed"


# --------------------------------------------------------------------------
# Tier B: the installed set participates in the merge
# --------------------------------------------------------------------------

def test_tier_b_resolves_node_added_by_another_mod(tmp_path):
    """Tier A false-alarms on a sel targeting a node another mod adds; Tier B resolves it."""
    ref = _ref_with_wares(tmp_path)
    other = tmp_path / "other_mod"
    _write(other / "libraries/wares.xml",
           '<diff><add sel="/wares"><ware id="frommod" price="1"/></add></diff>')

    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@id=\'frommod\']/@price">7</replace></diff>')

    tier_a = _check.validate(mod, _merge.Config(reference=ref))
    assert any(f.category == "sel" for f in tier_a.errors), \
        "Tier A cannot see another mod's node — expected the false alarm"

    tier_b = _check.validate(mod, _merge.Config(reference=ref, overlays=(other,)))
    assert not [f for f in tier_b.errors if f.category == "sel"], \
        "Tier B must resolve a node contributed by another installed mod"


def test_macro_defs_honor_remove_by_another_mod(tmp_path):
    """THE xspvro REGRESSION: a macro removed from the effective index is NOT defined.

    A naive per-directory union of index/macros.xml sees the base entry and
    reports the macro as defined, missing that a later mod deleted it.
    """
    ref = tmp_path / "reference"
    _write(ref / "index/macros.xml",
           '<index>'
           '<entry name="turret_keep_macro" value="a\\b\\turret_keep_macro"/>'
           '<entry name="turret_doomed_macro" value="a\\b\\turret_doomed_macro"/>'
           '</index>')

    remover = tmp_path / "remover_mod"
    _write(remover / "index/macros.xml",
           '<diff><remove sel="//index/entry[@name=\'turret_doomed_macro\']"/></diff>')

    base_only = _check.collect_macro_defs(_merge.Config(reference=ref))
    assert "turret_doomed_macro" in base_only, "sanity: defined before the remover loads"

    with_remover = _check.collect_macro_defs(
        _merge.Config(reference=ref, overlays=(remover,)))
    assert "turret_keep_macro" in with_remover, "untouched entry must survive"
    assert "turret_doomed_macro" not in with_remover, \
        "a macro removed by another mod must NOT count as defined"


def test_macro_defs_see_entries_added_by_another_mod(tmp_path):
    """The other direction: an entry a mod registers IS defined under Tier B."""
    ref = tmp_path / "reference"
    _write(ref / "index/macros.xml", '<index><entry name="base_macro" value="x"/></index>')
    adder = tmp_path / "adder_mod"
    _write(adder / "index/macros.xml",
           '<index><entry name="mod_macro" value="extensions\\adder\\y"/></index>')

    defs = _check.collect_macro_defs(_merge.Config(reference=ref, overlays=(adder,)))
    assert {"base_macro", "mod_macro"} <= defs


def test_tier_b_overlays_excludes_mod_under_test_by_folder(tmp_path, monkeypatch):
    """The dev folder is usually ALSO deployed; merging that copy would pre-apply
    the mod's own ops and mask real misses."""
    installed = tmp_path / "extensions"
    for name in ("aaa_other", "zzz_target"):
        _write(installed / name / "content.xml", f'<content id="{name}_id"/>')
    dev = tmp_path / "dev" / "zzz_target"
    _write(dev / "content.xml", '<content id="zzz_target_id"/>')

    monkeypatch.setattr("x4validate._registry.default_installed_dirs", lambda: [installed])

    overlays, notes = _check.tier_b_overlays(dev)
    names = [p.name for p in overlays]
    assert "zzz_target" not in names, "mod under test must be excluded"
    assert "aaa_other" in names
    assert any("excluded the mod under test" in n for n in notes)


def test_tier_b_excludes_mod_under_test_by_content_id(tmp_path, monkeypatch):
    """Folder name may differ from the manifest id — exclusion must match on id too."""
    installed = tmp_path / "extensions"
    _write(installed / "deployed_folder_name" / "content.xml", '<content id="shared_id"/>')
    dev = tmp_path / "dev" / "different_dev_folder"
    _write(dev / "content.xml", '<content id="shared_id"/>')

    monkeypatch.setattr("x4validate._registry.default_installed_dirs", lambda: [installed])

    overlays, _notes = _check.tier_b_overlays(dev)
    assert [p.name for p in overlays] == [], "same content id must be excluded"


# --------------------------------------------------------------------------
# Load-order truncation: a mod's selectors only see mods that load BEFORE it.
#
# Real incident (2026-07-26): `cpsdo_vro` <add>s ishield_cpsdo_* wares and loads
# AFTER `cpsdo_faction`, which patches them. The engine runs the patch first and
# skips it (27 "No matching node" ops). Merging *all* other mods made those ops
# look fine — 27 FALSE OKs. Truncating at the mod's own position took the oracle
# from 165/192 to 192/192 agreement with the engine.
# --------------------------------------------------------------------------

def test_tier_b_truncates_at_mod_load_order_position(tmp_path, monkeypatch):
    installed = tmp_path / "extensions"
    for name in ("aaa_earlier", "mmm_target", "zzz_later"):
        _write(installed / name / "content.xml", f'<content id="{name}_id"/>')
    dev = tmp_path / "dev" / "mmm_target"
    _write(dev / "content.xml", '<content id="mmm_target_id"/>')

    monkeypatch.setattr("x4validate._registry.default_installed_dirs", lambda: [installed])

    overlays, notes = _check.tier_b_overlays(dev)
    names = [p.name for p in overlays]
    assert names == ["aaa_earlier"], (
        "only mods loading BEFORE the target may be merged — including a later mod "
        "builds a tree that never exists when this mod is patched")
    assert "zzz_later" not in names
    assert any("load BEFORE this mod" in n for n in notes)


def test_tier_b_uninstalled_mod_says_it_assumes_last(tmp_path, monkeypatch):
    """A dev-only mod has no knowable position. Falling back to 'last' is the
    optimistic tree, so the note must SAY so rather than imply the tree is exact."""
    installed = tmp_path / "extensions"
    for name in ("aaa_earlier", "zzz_later"):
        _write(installed / name / "content.xml", f'<content id="{name}_id"/>')
    dev = tmp_path / "dev" / "never_deployed"
    _write(dev / "content.xml", '<content id="never_deployed_id"/>')

    monkeypatch.setattr("x4validate._registry.default_installed_dirs", lambda: [installed])

    overlays, notes = _check.tier_b_overlays(dev)
    assert len(overlays) == 2, "unknown position -> assume last, merge everything"
    assert any("NOT installed" in n and "assumed to load LAST" in n for n in notes)


def test_op_targeting_a_later_mods_node_fails_like_the_engine(tmp_path, monkeypatch):
    """The ishield_cpsdo_* shape, end to end: a LATER mod adds the ware, we patch it.

    The engine skips this op. Before the truncation fix our tree already contained
    the ware, so the op applied cleanly and we reported OK.
    """
    ref = _ref_with_wares(tmp_path)
    installed = tmp_path / "extensions"
    _write(installed / "mmm_target" / "content.xml", '<content id="mmm_target_id"/>')
    # loads AFTER the target, and is the only source of the ware being patched
    _write(installed / "zzz_adder" / "content.xml", '<content id="zzz_adder_id"/>')
    _write(installed / "zzz_adder" / "libraries/wares.xml",
           '<diff><add sel="/wares"><ware id="late_ware"><owner faction="argon"/>'
           '</ware></add></diff>')

    dev = tmp_path / "dev" / "mmm_target"
    _write(dev / "content.xml", '<content id="mmm_target_id"/>')
    _write(dev / "libraries/wares.xml",
           '<diff><replace sel="//wares/ware[@id=\'late_ware\']/owner/@faction">'
           'teladi</replace></diff>')

    monkeypatch.setattr("x4validate._registry.default_installed_dirs", lambda: [installed])

    overlays, _notes = _check.tier_b_overlays(dev)
    assert [p.name for p in overlays] == [], "zzz_adder loads later -> not visible"

    cfg = _merge.Config(reference=ref, overlays=overlays)
    res = _merge.build_effective("libraries/wares.xml", cfg)
    applied = _merge.apply_diff(res.tree, _merge.parse_file(dev / "libraries/wares.xml"))
    assert applied and not applied[0].ok, (
        "patching a ware only a LATER mod adds must fail, exactly as the engine does")

def test_multi_match_sel_is_error_not_silent_pass(tmp_path):
    """A sel matching >1 node is a SILENT no-op in X4 — must be flagged.

    Real case: the 'stars' mod adds two map materials with
    sel="/materiallibrary/collection[@name='map']", but two collections carry
    that name, so the engine logs "Multiple matching nodes ... Skipping node"
    and the materials never install. 236 such ops were skipped across one modlist.
    """
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml",
           '<wares><ware id="a" group="g"/><ware id="b" group="g"/></wares>')
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@group=\'g\']/@group">h</replace></diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    errs = [f for f in report.errors if f.category == "sel"]
    assert errs, "an ambiguous sel must be an error, not a silent pass"
    assert "matched 2 nodes" in errs[0].message
    assert "SKIPS" in errs[0].message


def test_single_match_sel_still_passes(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml",
           '<wares><ware id="a" group="g"/><ware id="b" group="other"/></wares>')
    mod = tmp_path / "mod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@group=\'g\']/@group">h</replace></diff>')

    report = _check.validate(mod, _merge.Config(reference=ref))
    assert not [f for f in report.errors if f.category == "sel"]


def test_merge_skips_ambiguous_op_like_the_engine(tmp_path):
    """_merge must APPLY NOTHING on a multi-match sel — not apply to every match.

    Applying to all matches would build an effective tree the game never has
    (e.g. a material duplicated into both collections named 'map').
    """
    from lxml import etree as _et
    tree = _et.fromstring('<root><c n="x"/><c n="x"/></root>')
    diff = _et.fromstring('<diff><add sel="//c[@n=\'x\']"><m/></add></diff>')

    applied = _merge.apply_diff(tree, diff)

    assert len(tree.xpath('//m')) == 0, "ambiguous add must apply to NOTHING"
    assert applied and applied[0].ambiguous
    assert not applied[0].ok


def test_merge_applies_unambiguous_op(tmp_path):
    from lxml import etree as _et
    tree = _et.fromstring('<root><c n="x"/><c n="y"/></root>')
    diff = _et.fromstring('<diff><add sel="//c[@n=\'x\']"><m/></add></diff>')

    applied = _merge.apply_diff(tree, diff)

    assert len(tree.xpath('//m')) == 1
    assert applied[0].ok and not applied[0].ambiguous


# --------------------------------------------------------------------------
# Cross-mod nesting: <mymod>/extensions/<target>/<rel> patches <target>'s <rel>
# --------------------------------------------------------------------------

def test_nested_cross_mod_patch_resolves_against_owner(tmp_path):
    """The base for extensions/<target>/<rel> lives inside <target>, not reference/.

    Real case: ship_variation_expansion_vro patches ship_variation_expansion this
    way; its ops demonstrably apply in-game, yet every one reported
    "no base game file" because the owner was never consulted.
    """
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml", "<wares/>")           # unrelated base
    owner = tmp_path / "ship_variation_expansion"
    _write(owner / "assets/units/size_l/macros/drake_macro.xml",
           '<macros><macro name="drake"><properties>'
           '<explosiondamage value="10000"/></properties></macro></macros>')

    mod = tmp_path / "mod"
    _write(mod / "extensions/ship_variation_expansion/assets/units/size_l/macros/drake_macro.xml",
           '<diff><replace sel="//macros/macro/properties/explosiondamage">'
           '<explosiondamage value="1000" shield="5000"/></replace></diff>')

    cfg = _merge.Config(reference=ref, overlays=(owner,))
    report = _check.validate(mod, cfg)
    assert not [f for f in report.errors if f.category == "path"], \
        "owner-owned base must be found, not reported as missing"
    assert not [f for f in report.errors if f.category == "sel"]

    res = _merge.build_effective(
        "extensions/ship_variation_expansion/assets/units/size_l/macros/drake_macro.xml",
        cfg, extra_overlays=[mod])
    nd = res.tree.xpath("//explosiondamage")[0]
    assert nd.get("shield") == "5000" and nd.get("value") == "1000"


def test_nested_helper_ignores_dlc_paths():
    """ego_dlc_* live under reference/extensions and are ordinary base content."""
    assert _merge._nested_target("extensions/ego_dlc_terran/libraries/wares.xml") is None
    assert _merge._nested_target("libraries/wares.xml") is None
    assert _merge._nested_target("extensions/somemod/libraries/wares.xml") == \
        ("somemod", "libraries/wares.xml")
