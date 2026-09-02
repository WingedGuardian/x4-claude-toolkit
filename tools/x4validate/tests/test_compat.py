"""Tests for _compat.py — cross-mod collision detection."""

from __future__ import annotations

from x4validate import _compat, _merge


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mod(ext, folder, files, mod_id=None, deps=()):
    """Create a loose mod folder with a content.xml + given {vpath: text}."""
    root = ext / folder
    dep_xml = "".join(f'<dependency id="{d}"/>' for d in deps)
    _w(root / "content.xml",
       f'<content id="{mod_id or folder}" name="{folder}" version="1">{dep_xml}</content>')
    for vpath, text in files.items():
        _w(root / vpath, text)
    return root


def _setup_ref(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries" / "wares.xml",
       '<wares><ware id="ore"><price average="100"/></ware>'
       '<ware id="ice"><price average="50"/></ware></wares>')
    _w(ref / "aiscripts" / "order.fight.xml",
       '<aiscript name="order.fight"><actions><label name="start"/></actions></aiscript>')
    _w(ref / "assets" / "props" / "mat.xml", "<materials><m id='a'/></materials>")
    return _merge.Config(reference=ref)


def test_hard_two_mods_replace_same_node(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">200</replace></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">300</replace></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    hard = rep.by_kind("HARD")
    assert len(hard) == 1
    assert hard[0].mods == ["a_mod", "b_mod"]
    assert hard[0].winner == "b_mod"  # loads last alphabetically


def test_soft_two_mods_add_under_same_parent(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="a_extra"/></add></diff>'})
    _mod(ext, "b_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="b_extra"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.hard
    assert len(rep.by_kind("SOFT")) == 1


def test_dup_add_same_key_escalates_to_hard(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # Both add a label with the SAME name under the same parent -> duplicate.
    _mod(ext, "a_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="dup"/></add></diff>'})
    _mod(ext, "b_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="dup"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert len(rep.by_kind("HARD")) == 1
    assert "duplicate" in rep.by_kind("HARD")[0].detail


def test_union_key_two_mods_define_same_ware_id(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # Full-file (non-diff) libraries/wares.xml from two mods, both defining ware 'newore'.
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<wares><ware id="newore"><price average="1"/></ware></wares>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<wares><ware id="newore"><price average="2"/></ware></wares>'})
    rep = _compat.analyze(ext, config=cfg)
    uk = rep.by_kind("UNION-KEY")
    assert len(uk) == 1
    assert "newore" in uk[0].target
    assert uk[0].winner == "b_mod"


def test_union_different_ids_no_collision(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<wares><ware id="ware_a"><price average="1"/></ware></wares>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<wares><ware id="ware_b"><price average="2"/></ware></wares>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.collisions  # distinct ids coexist in a union dir


def test_full_override_two_mods_same_asset(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"assets/props/mat.xml": "<materials><m id='x'/></materials>"})
    _mod(ext, "b_mod", {"assets/props/mat.xml": "<materials><m id='y'/></materials>"})
    rep = _compat.analyze(ext, config=cfg)
    fo = rep.by_kind("FULL-OVERRIDE")
    assert len(fo) == 1
    assert fo[0].winner == "b_mod"


def test_ui_xml_not_flagged_as_override(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"ui.xml": "<wm><add><ui/></add></wm>"})
    _mod(ext, "b_mod", {"ui.xml": "<wm><add><ui/></add></wm>"})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.by_kind("FULL-OVERRIDE")  # per-extension manifest, never overrides


def test_load_order_dependency_forces_earlier(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # z_mod depends on a_mod's id -> but also they collide; dependency doesn't change
    # who-wins here (dep loads FIRST, so the dependent z_mod still wins as it loads later).
    _mod(ext, "z_first_alpha", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">1</replace></diff>'},
         mod_id="ZID")
    _mod(ext, "a_dependent", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">2</replace></diff>'},
         deps=["ZID"])
    rep = _compat.analyze(ext, config=cfg)
    order = rep.load_order
    # dependency ZID(z_first_alpha) must come before its dependent a_dependent,
    # overriding the alphabetical (a before z) default.
    assert order.index("z_first_alpha") < order.index("a_dependent")
    assert rep.by_kind("HARD")[0].winner == "a_dependent"


def test_candidate_mode_only_reports_candidate_collisions(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">1</replace></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ice\']/price/@average">1</replace></diff>'})
    # candidate collides only with a_mod (both touch 'ore')
    cand = _mod(ext, "cand_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">9</replace></diff>'})
    rep = _compat.analyze(ext, candidate=cand, config=cfg)
    assert all("cand_mod" in c.mods for c in rep.collisions)
    assert any(set(c.mods) == {"a_mod", "cand_mod"} for c in rep.by_kind("HARD"))
    assert not any("b_mod" in c.mods for c in rep.collisions)


# --- cross-mod NESTED patches (audit 2026-08-01, finding F10) ------------------
#
# A mod that exists purely to patch ANOTHER mod ships extensions/<target>/<rel>
# while the target itself ships <rel>. Keyed on the raw vpath those never meet,
# so x4compat reported "0 shared files examined … no collisions", exit 0 — blind
# to the most collision-prone construct in X4 modding.

def test_nested_patch_collides_with_its_target(tmp_path, case_insensitive_fs):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "target_mod", {"md/Thing.xml": '<mdscript name="Thing"><cues/></mdscript>'})
    _mod(ext, "zzz_patcher", {"extensions/target_mod/md/thing.xml":
         '<diff><add sel="//cues"><cue name="Extra"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert rep.files_examined >= 1, "the patch and its target must share a file"


def test_nested_patch_matches_target_case_insensitively(tmp_path, case_insensitive_fs):
    """The live case differed in BOTH prefix and case: the overlay shipped
    .../md/morerooms.xml while moreroomsforships ships md/MoreRooms.xml."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "Target_Mod", {"md/MixedCase.xml": '<mdscript name="M"><cues/></mdscript>'})
    _mod(ext, "zzz_patcher", {"extensions/target_mod/md/mixedcase.xml":
         '<diff><add sel="//cues"><cue name="Extra"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert rep.files_examined >= 1


def test_two_nested_patches_on_one_target_still_collide(tmp_path, case_insensitive_fs):
    """The alias must not lose the ordinary patcher-vs-patcher HARD case.

    The owner must be reachable through the config, exactly as it is in a real
    run: `build_effective` resolves extensions/<owner>/<rel> by finding <owner>
    among the overlay dirs. Without that the base tree is None and _analyze_vpath
    reports nothing at all — see the note on that branch.
    """
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    target = _mod(ext, "target_mod", {"md/Thing.xml":
                  '<mdscript name="Thing"><cues><cue name="C"/></cues></mdscript>'})
    for p in ("y_patch", "z_patch"):
        _mod(ext, p, {"extensions/target_mod/md/thing.xml":
             '<diff><replace sel="//cue[@name=\'C\']/@name">' + p + '</replace></diff>'})
    cfg = _merge.replace(cfg, overlays=[target])
    rep = _compat.analyze(ext, config=cfg)
    hard = rep.by_kind("HARD")
    assert hard and hard[0].winner == "z_patch"


def test_unrelated_mods_are_not_aliased_together(tmp_path):
    """Both sides asserted: the alias must not invent shared files."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"md/OwnA.xml": "<mdscript name='A'/>"})
    _mod(ext, "b_mod", {"md/OwnB.xml": "<mdscript name='B'/>"})
    rep = _compat.analyze(ext, config=cfg)
    assert rep.files_examined == 0


# --- F17: the owner mod must be found without the caller staging it ------------

def test_nested_patch_collides_without_a_manually_staged_owner(tmp_path, case_insensitive_fs):
    """The F17 regression test.

    `test_two_nested_patches_on_one_target_still_collide` above only passes
    because it hand-stages the owner via `_merge.replace(cfg, overlays=[target])`.
    A real x4compat run cannot do that: `analyze()` is handed one Config for the
    whole sweep and the owner differs per vpath. So `_build_owned` never found the
    owner, the base tree was None, and every mod on the file was dropped by a bare
    `continue` — measured at 140 of 523 examined files on the live 101-mod install,
    silently discarding 144 <diff> mods.

    Same fixture, WITHOUT the staging line. It must still find the collision.
    """
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "target_mod", {"md/Thing.xml":
         '<mdscript name="Thing"><cues><cue name="C"/></cues></mdscript>'})
    for p in ("y_patch", "z_patch"):
        _mod(ext, p, {"extensions/target_mod/md/thing.xml":
             '<diff><replace sel="//cue[@name=\'C\']/@name">' + p + '</replace></diff>'})

    rep = _compat.analyze(ext, config=cfg)          # <- no overlays= staging

    hard = rep.by_kind("HARD")
    assert hard, f"nested collision missed; skipped={[s.why for s in rep.skipped]}"
    assert hard[0].winner == "z_patch"
    assert not rep.degraded, "a resolvable file must not be reported as degraded"


def test_owner_overlay_does_not_apply_the_other_patchers(tmp_path, case_insensitive_fs):
    """The base must stay UNPATCHED, or one mod's <remove> hides another's target.

    y_patch removes the very cue z_patch replaces. Both must still be seen to
    resolve against the same pristine owner tree and collide; if the fix folded
    every patcher into the base, z_patch's sel would match nothing and the
    collision would vanish — a false clean.

    Both ops target the cue ELEMENT deliberately. An earlier draft had z_patch
    target `.../@name`, which does not collide here — `_canonical` keys an
    attribute as `<elem path>/@name`, a different string from the element's own
    path, so an element-vs-its-own-attribute overlap is invisible to the detector.
    That is a real gap (logged as F18) but a separate one; pulling it into this
    test would have hidden the thing this test exists to prove.
    """
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "target_mod", {"md/Thing.xml":
         '<mdscript name="Thing"><cues><cue name="C"/></cues></mdscript>'})
    _mod(ext, "y_patch", {"extensions/target_mod/md/thing.xml":
         '<diff><remove sel="//cue[@name=\'C\']"/></diff>'})
    _mod(ext, "z_patch", {"extensions/target_mod/md/thing.xml":
         '<diff><replace sel="//cue[@name=\'C\']"><cue name="zz"/></replace></diff>'})

    rep = _compat.analyze(ext, config=cfg)

    hard = rep.by_kind("HARD")
    assert hard, "a remove-vs-replace on one node is the canonical HARD case"
    assert set(hard[0].mods) == {"y_patch", "z_patch"}


# --- F17: a file that yields no comparison must SAY so -------------------------

def test_missing_owner_is_a_degraded_skip_not_silence(tmp_path):
    """No owner installed => no base => no comparison. That must not read as OK."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    for p in ("y_patch", "z_patch"):
        _mod(ext, p, {"extensions/ghost_mod/md/thing.xml":
             '<diff><replace sel="//cue[@name=\'C\']/@name">' + p + '</replace></diff>'})

    rep = _compat.analyze(ext, config=cfg)

    assert not rep.collisions
    assert rep.degraded, "silently contributing nothing is the F4 failure mode"
    assert "ghost_mod" in rep.degraded[0].why
    assert "not installed" in rep.degraded[0].why


def test_no_base_reason_is_computed_not_guessed(tmp_path):
    """An owner that ships its own <diff> is a DIFFERENT cause from a missing one.

    A draft of this fix hard-coded "the owning mod is not installed" for every
    nested path. A wrong reason is worse than none — it is what stops the next
    person checking (the F1 lesson).
    """
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "target_mod", {"md/thing.xml":
         '<diff><replace sel="//x/@y">1</replace></diff>'})   # a patch, not a base
    _mod(ext, "z_patch", {"extensions/target_mod/md/thing.xml":
         '<diff><replace sel="//cue/@name">z</replace></diff>'})

    rep = _compat.analyze(ext, config=cfg)

    assert rep.degraded
    why = rep.degraded[0].why
    assert "<diff> itself" in why, why
    assert "not installed" not in why, "target_mod IS installed — do not guess"


def test_clean_run_reports_no_skips(tmp_path):
    """The channel must stay quiet when everything really was compared."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">200</replace></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">300</replace></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert rep.by_kind("HARD")
    assert rep.skipped == []


def test_cli_exits_3_when_degraded_without_hard_collisions(tmp_path, capsys):
    """Exit-code contract, mirrored from x4validate: 1 findings > 3 degraded > 0."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    for p in ("y_patch", "z_patch"):
        _mod(ext, p, {"extensions/ghost_mod/md/thing.xml":
             '<diff><replace sel="//cue/@name">' + p + '</replace></diff>'})

    code = _compat.main(["check", "--all", "--ext-dir", str(ext),
                         "--reference", str(cfg.reference)])

    assert code == 3, "a run that compared nothing must not exit 0"
    out = capsys.readouterr().out
    assert "NOT ANALYSED" in out
    assert "DEGRADED" in out


# --------------------------------------------------------------------------
# F12 (2026-08-02): registry uniqueness is per-DOCUMENT, and identity is @id.
# Both engine-confirmed duplicates (WareDB shield_xen_xl_standard_02_mk1,
# GroupDB yak_destroyer_l) shaped these rules; mod-vs-base duplication was
# measured (476 tolerated instances incl. VRO/SVE) and deliberately DROPPED.
# --------------------------------------------------------------------------

def test_added_child_keys_prefer_id_over_name():
    """A ware's name= is a localized {page,t} TEXT REFERENCE, not identity.
    Keying by name hid the engine-confirmed shield duplicate and compared
    unrelated jobs by display name."""
    from lxml import etree
    op = etree.fromstring('<add sel="/wares">'
                          '<ware id="shield_x" name="{20204,1}"/></add>')
    assert _compat._added_child_keys(op) == ["ware#shield_x"]


def test_docwide_duplicate_add_different_anchors_is_union_key(tmp_path):
    """The shield_xen_xl_standard_02_mk1 shape: two mods add the same ware id
    anchored at DIFFERENT siblings — same-anchor HARD never compares them, and
    before 2026-08-02 nothing else did either."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ore\']" pos="after">'
         '<ware id="dupware" name="{20204,9}"/></add></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ice\']" pos="after">'
         '<ware id="dupware" name="{20204,9}"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    uk = [c for c in rep.by_kind("UNION-KEY") if c.target == "ware#dupware"]
    assert len(uk) == 1 and set(uk[0].mods) == {"a_mod", "b_mod"}


def test_same_anchor_duplicate_stays_hard_only(tmp_path):
    """One fact, one finding: a same-anchor duplicate is already HARD, so the
    document-wide pass must not report it a second time as UNION-KEY."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    body = ('<diff><add sel="/wares"><ware id="dupware"/></add></diff>')
    _mod(ext, "a_mod", {"libraries/wares.xml": body})
    _mod(ext, "b_mod", {"libraries/wares.xml": body})
    rep = _compat.analyze(ext, config=cfg)
    assert [c for c in rep.by_kind("HARD") if "dupware" in c.detail]
    assert not [c for c in rep.by_kind("UNION-KEY") if "dupware" in c.target]


def test_wildcard_and_guarded_adds_do_not_join_the_docwide_pass(tmp_path):
    """icon#upgrade_* style wildcard entries are the generic-icon idiom (32 of
    37 measured document-wide duplicates, zero engine complaints), and an
    if=-guarded add is a designed conditional."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><add sel="/wares"><ware id="upgrade_*"/></add>'
         '<add sel="//ware[@id=\'ore\']" pos="after" if="not(//ware[@id=\'g\'])">'
         '<ware id="guarded_ware"/></add></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ice\']" pos="after"><ware id="upgrade_*"/></add>'
         '<add sel="/wares" if="not(//ware[@id=\'g\'])">'
         '<ware id="guarded_ware"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not [c for c in rep.by_kind("UNION-KEY")
                if "upgrade" in c.target or "guarded" in c.target]


# --------------------------------------------------------------------------
# F18 (2026-08-02): a later mod replace/removing an ELEMENT wipes an earlier
# mod's change INSIDE it — _canonical gave the two unrelated ids. Order-aware:
# 184 measured pair-hits -> 165 real clobbers; the filter correctly cleared
# ebi_m0_vro, whose ws_ dependency on VRO orders it after the wipe.
# --------------------------------------------------------------------------

def test_later_element_replace_wiping_earlier_inner_edit_is_subtree(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">7</replace></diff>'})
    _mod(ext, "z_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']">'
         '<ware id="ore"><price average="1"/></ware></replace></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    st = rep.by_kind("SUBTREE")
    assert len(st) == 1
    assert st[0].mods == ["a_mod", "z_mod"]
    # The wiper goes in its OWN field, and `winner` is deliberately empty: for a
    # SUBTREE the load-order winner is the mod that WIPED, not the owner of the
    # final value, and a later mod can re-supply what was wiped (MEASURED: 3 of
    # 148 on the live install). Reporting the wiper as `winner` is what made an
    # inbound report conclude x4compat was wrong. Same precedent as NAME-CLASH.
    assert st[0].wiped_by == "z_mod", "the wiper must still be reported"
    assert st[0].winner == "", "a SUBTREE has no live-value winner"
    assert st[0].live_value_owner() is None, "and must refuse to name one"
    assert st[0] in rep.hard, "SUBTREE gates hard-ish by user decision"
    assert "advisory" in st[0].detail, "the load-order caveat must ride every row"


def test_element_replace_loading_before_the_inner_edit_is_not_subtree(tmp_path):
    """A wipe that loads FIRST merely changes what the victim's sel sees —
    the Tier B sel check covers that; nothing is destroyed."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']">'
         '<ware id="ore"><price average="1"/></ware></replace></diff>'})
    _mod(ext, "z_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">7</replace></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.by_kind("SUBTREE")


def test_add_on_the_ancestor_does_not_wipe(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">7</replace></diff>'})
    _mod(ext, "z_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ore\']"><production time="1"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.by_kind("SUBTREE")


def test_textref_keys_never_join_the_docwide_pass(tmp_path):
    """A {page,text} key is localized display text (a <production>'s name=),
    not identity — keying on it matched production stages of UNRELATED wares."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ore\']"><production name="{20206,601}"/></add></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><add sel="//ware[@id=\'ice\']"><production name="{20206,601}"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not [c for c in rep.by_kind("UNION-KEY") if "20206" in c.target]


def test_union_key_row_survives_when_it_names_mods_the_hard_row_missed(tmp_path):
    """Subset-fold semantics: a same-anchor HARD duplicate between a and b must
    not swallow the fact that FULL-FILE shipper c also defines the key — the
    real-world case is icon#upgrade_*, where the full-file shippers are
    entirely different mods from the same-anchor adders."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    body = '<diff><add sel="/wares"><ware id="dupware"/></add></diff>'
    _mod(ext, "a_mod", {"libraries/wares.xml": body})
    _mod(ext, "b_mod", {"libraries/wares.xml": body})
    _mod(ext, "c_mod", {"libraries/wares.xml":
         '<wares><ware id="dupware"/></wares>'})   # full union file
    rep = _compat.analyze(ext, config=cfg)
    assert [c for c in rep.by_kind("HARD") if "dupware" in c.detail]
    uk = [c for c in rep.by_kind("UNION-KEY") if c.target == "ware#dupware"]
    assert len(uk) == 1 and "c_mod" in uk[0].mods


def test_by_kind_order_is_stable():
    """Two identical runs must emit collisions in the same order.

    An upstream `for k in <set>` leaked hash-randomized iteration order into the
    report, so two identical runs produced the same 419 collisions in different
    orders. Content was never wrong — but a baseline diff became noise, which is
    how a real change hides.
    """
    import random
    from x4validate._compat import Collision, CompatReport

    rows = [Collision(vpath=f"libraries/f{i % 3}.xml", kind="UNION-KEY",
                      target=f"entry#e{i}", mods=[f"mod_{i%2}", f"mod_{(i+1)%2}"],
                      winner=f"mod_{i%2}")
            for i in range(50)]

    first = None
    for _ in range(5):
        shuffled = rows[:]
        random.shuffle(shuffled)              # simulate a different discovery order
        rep = CompatReport(collisions=shuffled)
        order = [(c.vpath, c.target, tuple(c.mods)) for c in rep.by_kind("UNION-KEY")]
        if first is None:
            first = order
        assert order == first, "by_kind order depends on insertion order"


# --------------------------------------------------------------------------
# NAME-CLASH: the same macro NAME defined by two mods in DIFFERENT files.
#
# Structurally invisible to the per-vpath scan (the two mods never share a
# path), yet X4 resolves macros by NAME via index/macros.xml, so only one
# definition is ever loaded and the other is dead content the author cannot
# tell is dead. Found 2026-08-09 re-deriving the missile roster:
# `missile_flagship_light_mk1_macro` is defined by two mods at different paths
# and the effective index points at only one of them.
# --------------------------------------------------------------------------

_MACROS = ('<macros><macro name="ship_probe_macro" class="ship_s">'
           "<properties/></macro></macros>")


def _clashes(report):
    return [c for c in report.collisions if c.kind == "NAME-CLASH"]


def test_same_macro_name_in_different_files_is_reported(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "amod", {"assets/units/size_s/macros/ship_probe_macro.xml": _MACROS})
    _mod(ext, "bmod", {"assets/units/other/macros/ship_probe_macro.xml": _MACROS})
    rep = _compat.analyze(ext, config=cfg)
    cl = _clashes(rep)
    assert len(cl) == 1, [c.target for c in cl]
    assert cl[0].target == "ship_probe_macro"
    assert sorted(cl[0].mods) == ["amod", "bmod"]
    # index/macros.xml decides, NOT load order -- so no winner may be claimed.
    assert cl[0].winner == ""
    assert "index/macros.xml" in cl[0].detail


def test_same_macro_name_in_the_SAME_file_is_not_a_name_clash(tmp_path):
    """That is a plain file-level collision; reporting it twice is noise."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    same = "assets/units/size_s/macros/ship_probe_macro.xml"
    _mod(ext, "amod", {same: _MACROS})
    _mod(ext, "bmod", {same: _MACROS})
    assert _clashes(_compat.analyze(ext, config=cfg)) == []


def test_nested_cross_mod_patch_is_the_same_logical_file(tmp_path):
    """`extensions/<owner>/<rel>` is a patch INTO <owner>'s file, not a rival
    definition. Measured: without this, 35 of 57 reported rows were this case."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    rel = "assets/units/size_s/macros/ship_probe_macro.xml"
    _mod(ext, "amod", {rel: _MACROS})
    _mod(ext, "bmod", {f"extensions/amod/{rel}": _MACROS})
    assert _clashes(_compat.analyze(ext, config=cfg)) == []


def test_a_macro_defined_inside_a_diff_still_counts(tmp_path):
    """`<replace sel="//macros">` with a fresh payload is the standard whole-file
    override idiom. Skipping all <diff> roots missed the very case this check was
    built for, because that is exactly how the overhaul mod ships its macros."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "amod", {"assets/units/size_s/macros/ship_probe_macro.xml": _MACROS})
    _mod(ext, "bmod", {"assets/units/other/macros/ship_probe_macro.xml":
                       f'<diff><replace sel="//macros">{_MACROS}</replace></diff>'})
    cl = _clashes(_compat.analyze(ext, config=cfg))
    assert len(cl) == 1 and cl[0].target == "ship_probe_macro"


def test_a_diff_that_defines_no_macro_is_not_a_definition(tmp_path):
    """A bare attribute tweak names no macro and must not count as defining one."""
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "amod", {"assets/units/size_s/macros/ship_probe_macro.xml": _MACROS})
    _mod(ext, "bmod", {"assets/units/other/macros/ship_probe_macro.xml":
                       '<diff><replace sel="//macro/@class">ship_m</replace></diff>'})
    assert _clashes(_compat.analyze(ext, config=cfg)) == []


# --- the precondition guard itself ------------------------------------------

def test_case_probe_detects_this_filesystem(tmp_path):
    """The probe must return a real answer, and both branches must be reachable.

    Five tests above stage `md/Thing.xml` and patch `md/thing.xml`. That is one
    file under X4's Windows VFS and two on a case-sensitive filesystem, so on
    Linux they were failing for a reason that says nothing about the code. They
    now declare the precondition instead — but a guard nobody can make flip is
    not a guard, so both outcomes are exercised here.

    Asserting `is True` was wrong, and contradicted the paragraph above it: on
    Linux the honest answer is False, and demanding True made this guard the only
    thing in the file that FAILED there rather than skipped. What actually needs
    pinning is that the probe reports the truth about whatever filesystem it is
    handed — so it is checked against an INDEPENDENT mechanism. The probe asks
    "does the other casing exist?"; `os.path.samefile` asks "are these the same
    file?" — different syscalls, so agreement is evidence rather than tautology.
    """
    import os.path

    from conftest import fs_is_case_insensitive

    probe = fs_is_case_insensitive(tmp_path)
    assert isinstance(probe, bool), "the probe must give a real answer, not None"

    original = tmp_path / "SameFileProbe.tmp"
    original.write_text("x", encoding="utf-8")
    other_casing = tmp_path / "samefileprobe.tmp"
    try:
        independently_same = os.path.samefile(original, other_casing)
    except (FileNotFoundError, OSError):
        independently_same = False

    assert probe == independently_same, (
        f"the case probe says folds={probe} but os.path.samefile says "
        f"{independently_same}; one of them is lying about this filesystem, and "
        f"five nested-patch tests decide whether to run based on the first")


def test_case_probe_reports_false_on_a_case_sensitive_filesystem(tmp_path, monkeypatch):
    """Simulate the Linux answer — the branch this machine can never take."""
    from pathlib import Path

    import conftest
    real_exists = Path.exists
    monkeypatch.setattr(
        Path, "exists",
        lambda self: False if self.name == "caseprobe.tmp" else real_exists(self))
    assert conftest.fs_is_case_insensitive(tmp_path) is False


# --- live_value_owner must REFUSE for the kinds it cannot know (survivor) -----
#
# Narrowing the guard to `("SOFT",)` survived the whole suite, and it is exactly the
# conflation CLAUDE.md #18 exists to prevent: for SUBTREE, `winner` is the mod that did
# the WIPING -- not the owner of the final value, because a later mod can re-supply it
# (MEASURED: 3 of 148 SUBTREE rows, 2.0%) -- and for NAME-CLASH nothing in load order
# decides at all, index/macros.xml does. An inbound report once called x4compat "wrong"
# by reading `winner` as the live owner; x4compat was right, the reading was not.


def _collision(kind, winner="modB"):
    from x4validate._compat import Collision
    return Collision(vpath="libraries/wares.xml", kind=kind, target="t",
                     mods=["modA", "modB"], winner=winner)


def test_live_value_owner_is_NONE_for_the_kinds_it_cannot_know():
    for kind in ("SUBTREE", "NAME-CLASH", "SOFT"):
        assert _collision(kind).live_value_owner() is None, (
            f"{kind} named a live owner it has no way to know")


def test_live_value_owner_DOES_name_one_when_it_can():
    """The twin. A method that returned None for everything would pass the test
    above while destroying the answer for the three kinds that do have one."""
    for kind in ("FULL-OVERRIDE", "HARD", "UNION-KEY"):
        assert _collision(kind).live_value_owner() == "modB", kind
