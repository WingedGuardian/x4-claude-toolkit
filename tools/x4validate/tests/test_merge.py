"""Diff-application and effective-tree assembly."""

from lxml import etree

from x4validate import _merge, _resolve
from x4validate._provenance import Recorder


def _wares():
    return etree.fromstring(b"""<wares>
  <ware id="ore" price_average="120"><price min="80" average="120" max="160"/></ware>
  <ware id="gone"/>
</wares>""")


def _diff(body: bytes):
    return etree.fromstring(b"<diff>" + body + b"</diff>")


def test_add_append():
    tree = _wares()
    _merge.apply_diff(tree, _diff(b'<add sel="//wares"><ware id="new"/></add>'))
    assert tree.xpath("//ware[@id='new']")
    assert tree.xpath("//wares/ware[last()][@id='new']")  # appended last


def test_add_prepend():
    tree = _wares()
    _merge.apply_diff(tree, _diff(b'<add sel="//wares" pos="prepend"><ware id="first"/></add>'))
    assert tree.xpath("//wares/ware[1][@id='first']")


def test_add_before_after():
    tree = _wares()
    _merge.apply_diff(tree, _diff(
        b'<add sel="//ware[@id=\'ore\']" pos="before"><ware id="b4"/></add>'))
    ids = tree.xpath("//ware/@id")
    assert ids.index("b4") < ids.index("ore")


def test_replace_attribute():
    tree = _wares()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/@price_average">500</replace>'))
    assert tree.xpath("//ware[@id='ore']/@price_average") == ["500"]


def test_replace_element():
    tree = _wares()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/price"><price min="1" average="2" max="3"/></replace>'))
    assert tree.xpath("//ware[@id='ore']/price/@average") == ["2"]


def test_remove():
    tree = _wares()
    _merge.apply_diff(tree, _diff(b'<remove sel="//ware[@id=\'gone\']"/>'))
    assert not tree.xpath("//ware[@id='gone']")


def test_if_false_skips():
    tree = _wares()
    applied = _merge.apply_diff(tree, _diff(
        b'<add sel="//wares" if="//ware[@id=\'absent\']"><ware id="cond"/></add>'))
    assert not tree.xpath("//ware[@id='cond']")
    assert applied[0].skipped_if


def test_if_true_applies():
    tree = _wares()
    _merge.apply_diff(tree, _diff(
        b'<add sel="//wares" if="//ware[@id=\'ore\']"><ware id="cond"/></add>'))
    assert tree.xpath("//ware[@id='cond']")


def test_unmatched_sel_records_failure_without_crashing():
    tree = _wares()
    applied = _merge.apply_diff(tree, _diff(b'<replace sel="//ware[@id=\'nope\']/@x">1</replace>'))
    assert applied[0].ok is False and "nothing" in applied[0].detail


# --- Effective-tree assembly through the real pipeline (tmp reference) --------


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_build_effective_dlc_diff_and_mod(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml",
           '<wares><ware id="ore" price_average="120"/></wares>')
    # A DLC adds a ware via diff:
    _write(ref / "extensions/ego_dlc_x/libraries/wares.xml",
           '<diff><add sel="//wares"><ware id="boronfuel" price_average="9"/></add></diff>')
    cfg = _merge.Config(reference=ref)

    base_plus_dlc = _merge.build_effective("libraries/wares.xml", cfg)
    # A sel that ONLY matches post-DLC state must resolve under Tier A:
    assert base_plus_dlc.tree.xpath("//ware[@id='boronfuel']")
    assert "ego_dlc_x:diff" in base_plus_dlc.sources

    # A mod overlay applied on top:
    mod = tmp_path / "mymod"
    _write(mod / "libraries/wares.xml",
           '<diff><replace sel="//ware[@id=\'ore\']/@price_average">999</replace></diff>')
    with_mod = _merge.build_effective("libraries/wares.xml", cfg, extra_overlays=[mod])
    assert with_mod.tree.xpath("//ware[@id='ore']/@price_average") == ["999"]


def test_full_file_override_asset(tmp_path):
    # Asset files (outside libraries/index/t) keep full-override semantics.
    ref = tmp_path / "reference"
    _write(ref / "assets/props/x/macros/bar_macro.xml", '<macros><macro name="a"/></macros>')
    _write(ref / "extensions/ego_dlc_x/assets/props/x/macros/bar_macro.xml",
           '<macros><macro name="b"/></macros>')  # full file, not a diff
    cfg = _merge.Config(reference=ref)
    merged = _merge.build_effective("assets/props/x/macros/bar_macro.xml", cfg)
    assert merged.tree.xpath("//macro/@name") == ["b"]  # DLC fully overrode base


def test_full_file_registry_union(tmp_path):
    # Shared-registry files (libraries/, index/, t/) UNION entries — base must NOT be
    # clobbered by a DLC's full file. This is the clobber-bug regression test.
    ref = tmp_path / "reference"
    _write(ref / "libraries/ships.xml", '<ships><ship id="base_ship"/></ships>')
    _write(ref / "extensions/ego_dlc_x/libraries/ships.xml",
           '<ships><ship id="dlc_ship"/></ships>')  # full file, not a diff
    cfg = _merge.Config(reference=ref)
    merged = _merge.build_effective("libraries/ships.xml", cfg)
    assert set(merged.tree.xpath("//ship/@id")) == {"base_ship", "dlc_ship"}
    assert "ego_dlc_x:union" in merged.sources


def test_full_file_registry_union_same_id_overrides(tmp_path):
    # Same id across base + overlay -> later-overlay-wins (replaced, not duplicated).
    ref = tmp_path / "reference"
    _write(ref / "libraries/ships.xml", '<ships><ship id="dup" hull="1"/></ships>')
    _write(ref / "extensions/ego_dlc_x/libraries/ships.xml",
           '<ships><ship id="dup" hull="2"/></ships>')
    cfg = _merge.Config(reference=ref)
    merged = _merge.build_effective("libraries/ships.xml", cfg)
    assert merged.tree.xpath("//ship[@id='dup']/@hull") == ["2"]
    assert len(merged.tree.xpath("//ship[@id='dup']")) == 1


def test_textfile_synthetic_language_base(tmp_path):
    # t/0001.xml has no single base file in reference (real base t-files are
    # 0001-lNNN.xml); build_effective synthesizes a <language> root so a mod's
    # <add sel="/language"> resolves instead of "no base game file".
    cfg = _merge.Config(reference=tmp_path / "reference")
    merged = _merge.build_effective("t/0001.xml", cfg)
    assert merged.tree is not None and merged.tree.tag == "language"


def test_strip_mod_index_prefix():
    # Mod index values are written game-root-relative (extensions/<mod>/...) but
    # resolve relative to the mod root here -> the prefix must be stripped, else
    # the path doubles into a spurious 'file missing'.
    assert _resolve._strip_mod_index_prefix(
        r"extensions\mymod\assets\props\x_macro") == "assets/props/x_macro"
    # No prefix -> unchanged (mod-relative style).
    assert _resolve._strip_mod_index_prefix(r"assets\props\x_macro") == r"assets\props\x_macro"


# --- RFC 5261 attribute-add ---------------------------------------------------
# Regression: <add type="@attr"> fell through to the append-children branch and,
# with no element children, reported "1 target(s)" while mutating nothing. Found
# while repairing higher_dimensional_space, where a whole-node <replace> would have
# baked in another mod's @radius.

def _apply(base_xml: str, diff_xml: str):
    tree = _merge.parse_bytes(base_xml.encode())
    ops = _merge.apply_diff(tree, _merge.parse_bytes(diff_xml.encode()))
    return tree, ops


def test_add_type_attr_sets_the_attribute():
    tree, ops = _apply(
        "<r><safepos x='1' radius='21km'/></r>",
        '<diff><add sel="//safepos" type="@value">$Position</add></diff>')
    assert [o.ok for o in ops] == [True]
    sp = tree.find("safepos")
    assert sp.get("value") == "$Position"
    assert sp.get("radius") == "21km", "sibling attributes must survive"


def test_add_type_attr_overwrites_existing_value():
    tree, _ = _apply(
        "<r><safepos value='old'/></r>",
        '<diff><add sel="//safepos" type="@value">new</add></diff>')
    assert tree.find("safepos").get("value") == "new"


def test_add_with_unsupported_type_is_reported_not_silently_ok():
    _, ops = _apply(
        "<r><safepos/></r>",
        '<diff><add sel="//safepos" type="namespace">urn:x</add></diff>')
    assert [o.ok for o in ops] == [False]
    assert "unsupported add type" in ops[0].detail


def test_plain_add_still_appends_children():
    tree, ops = _apply(
        "<r><a/></r>", '<diff><add sel="//a"><b/></add></diff>')
    assert [o.ok for o in ops] == [True]
    assert tree.find("a/b") is not None


# --------------------------------------------------------------------------
# F19 phase 2: the engine only loads a bare-path <diff> when the GAME supplies
# the file — over another mod's file it never opens it. build_effective must
# refuse such a diff (sources records ':diff(inert)') or the effective tree
# carries values the engine never sees (measured: 14 lied attribute values
# before this landed). Full non-diff files keep overriding cross-mod — the
# engine's VFS honours those (cpsdo_vro clobbering cpsdo_zb_modpack, live).
# --------------------------------------------------------------------------


def _f19p2_world(tmp_path):
    """A reference tree with one real base file, plus a supplier mod that owns
    an asset file the base game does not have."""
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml", '<wares><ware id="ore"/></wares>')
    supplier = tmp_path / "supplier_mod"
    _write(supplier / "assets/units/size_s/macros/ship_x_macro.xml",
           '<macros><macro name="ship_x"><properties hull="100"/></macro></macros>')
    return _merge.Config(reference=ref), supplier


def test_bare_diff_over_mod_only_file_is_refused(tmp_path):
    from x4validate._provenance import Recorder
    cfg, supplier = _f19p2_world(tmp_path)
    patcher = tmp_path / "patcher_mod"
    _write(patcher / "assets/units/size_s/macros/ship_x_macro.xml",
           '<diff><replace sel="//properties/@hull">9999</replace></diff>')

    rec = Recorder()
    res = _merge.build_effective("assets/units/size_s/macros/ship_x_macro.xml", cfg,
                                 extra_overlays=[supplier, patcher], recorder=rec)
    # Supplier's file, UNMODIFIED — the engine never opens the patcher's diff.
    assert res.tree.xpath("//properties/@hull") == ["100"]
    assert "patcher_mod:diff(inert)" in res.sources
    assert not res.base_from_game
    # No provenance entry for a file that contributed nothing.
    assert all(o.source != "patcher_mod" for o in rec.file_chain)


def test_bare_diff_over_reference_base_still_applies(tmp_path):
    cfg, supplier = _f19p2_world(tmp_path)
    patcher = tmp_path / "patcher_mod"
    _write(patcher / "libraries/wares.xml",
           '<diff><add sel="//wares"><ware id="newware"/></add></diff>')
    res = _merge.build_effective("libraries/wares.xml", cfg,
                                 extra_overlays=[supplier, patcher])
    assert res.tree.xpath("//ware[@id='newware']")
    assert "patcher_mod:diff" in res.sources


def test_bare_diff_over_dlc_supplied_base_still_applies(tmp_path):
    # reference/ lacks the file; a DLC layer supplies it -> from_game via the loop.
    cfg, supplier = _f19p2_world(tmp_path)
    _write(cfg.reference / "extensions/ego_dlc_x/assets/props/y/macros/gun_macro.xml",
           '<macros><macro name="gun"><properties damage="5"/></macro></macros>')
    patcher = tmp_path / "patcher_mod"
    _write(patcher / "assets/props/y/macros/gun_macro.xml",
           '<diff><replace sel="//properties/@damage">7</replace></diff>')
    res = _merge.build_effective("assets/props/y/macros/gun_macro.xml", cfg,
                                 extra_overlays=[patcher])
    assert res.tree.xpath("//properties/@damage") == ["7"]
    assert res.base_from_game


def test_t_diff_with_only_mod_suppliers_still_applies(tmp_path):
    # The 33-file class, phase-2 edition: the ENGINE supplies the language tree,
    # so a t/ diff is never inert no matter who else ships the path.
    cfg, supplier = _f19p2_world(tmp_path)
    _write(supplier / "t/0001.xml", '<language id="44"><page id="1"/></language>')
    patcher = tmp_path / "patcher_mod"
    _write(patcher / "t/0001.xml",
           '<diff><add sel="/language"><page id="99"/></add></diff>')
    res = _merge.build_effective("t/0001.xml", cfg,
                                 extra_overlays=[supplier, patcher])
    assert res.tree.xpath("//page[@id='99']")
    assert "patcher_mod:diff" in res.sources


def test_diff_mod_loading_before_supplier_is_still_refused(tmp_path):
    # Order-independence: the engine's decision does not depend on load order
    # (the file is not base-game content, full stop), and neither may ours —
    # from_game is final before ANY mod overlay is processed.
    cfg, supplier = _f19p2_world(tmp_path)
    patcher = tmp_path / "patcher_mod"
    _write(patcher / "assets/units/size_s/macros/ship_x_macro.xml",
           '<diff><replace sel="//properties/@hull">9999</replace></diff>')
    res = _merge.build_effective("assets/units/size_s/macros/ship_x_macro.xml", cfg,
                                 extra_overlays=[patcher, supplier])  # patcher FIRST
    assert res.tree.xpath("//properties/@hull") == ["100"]
    assert "patcher_mod:diff(inert)" in res.sources


def test_mod_full_file_over_mod_only_base_still_overrides(tmp_path):
    # The cpsdo_vro idiom: a full (non-diff) file at a bare path DOES override
    # another mod's file — the engine's VFS chain honours it. Refusing diffs
    # must not leak into refusing full files.
    cfg, supplier = _f19p2_world(tmp_path)
    clobberer = tmp_path / "clobber_mod"
    _write(clobberer / "assets/units/size_s/macros/ship_x_macro.xml",
           '<macros><macro name="ship_x"><properties hull="777"/></macro></macros>')
    res = _merge.build_effective("assets/units/size_s/macros/ship_x_macro.xml", cfg,
                                 extra_overlays=[supplier, clobberer])
    assert res.tree.xpath("//properties/@hull") == ["777"]
    assert "clobber_mod:full" in res.sources


# --- <replace> targeting the document ROOT -----------------------------------
# Regression guard for the defect that silently dropped 858 installed-mod ops
# (VRO alone ships 848 `<replace sel="//macros">` whole-file overrides). The op
# was discarded because a root has no parent to swap it through, yet apply_diff
# still reported applied=True. The engine applies these — it logs every other
# patch failure and never one of these.

def _macros(hull="100"):
    return etree.fromstring(
        f'<macros><macro name="m"><properties hull="{hull}"/></macro></macros>'.encode())


def test_replace_document_root_applies():
    tree = _macros()
    ops = _merge.apply_diff(tree, _diff(
        b'<replace sel="//macros">'
        b'<macros><macro name="m"><properties hull="999"/></macro></macros>'
        b'</replace>'))
    assert tree.xpath("//properties/@hull") == ["999"]
    assert tree.tag == "macros"          # still a well-formed document
    assert [o.ok for o in ops] == [True]


def test_replace_document_root_absolute_and_components_selectors():
    for sel, root in ((b"/macros", b"macros"), (b"//components", b"components"),
                      (b"/components", b"components")):
        tree = etree.fromstring(b"<" + root + b'><c hull="1"/></' + root + b">")
        _merge.apply_diff(tree, _diff(
            b'<replace sel="' + sel + b'"><' + root + b'><c hull="2"/></' + root + b"></replace>"))
        assert tree.xpath("//c/@hull") == ["2"], sel


def test_replace_document_root_multi_element_payload_reports_not_applied():
    tree = _macros()
    ops = _merge.apply_diff(tree, _diff(
        b'<replace sel="//macros"><macros/><macros/></replace>'))
    assert [o.ok for o in ops] == [False]
    assert "one payload element" in ops[0].detail
    assert tree.xpath("//properties/@hull") == ["100"]   # unchanged


def test_replace_document_root_records_provenance():
    tree = _macros()
    rec = Recorder()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//macros">'
        b'<macros><macro name="m"><properties hull="999"/></macro></macros>'
        b'</replace>'), recorder=rec, source="vro")
    # A root replace is a whole-file override: every node's origin is the mod.
    assert rec.default_origin.source == "vro"
    assert [o.source for o in rec.file_chain] == ["vro"]


def test_remove_document_root_reports_not_applied():
    tree = _macros()
    ops = _merge.apply_diff(tree, _diff(b'<remove sel="//macros"/>'))
    assert [o.ok for o in ops] == [False]
    assert "document root" in ops[0].detail


def test_apply_diff_never_reports_ok_for_a_noop():
    """The contract that makes the whole class visible: if the tree did not
    change, the op must not be reported as applied."""
    cases = [
        b'<replace sel="//macros"><macros/><macros/></replace>',   # multi-root payload
        b'<remove sel="//macros"/>',                                # root removal
        b'<add sel="//macros" type="@"/>',                          # unnamed attribute
        b'<add sel="//macros" pos="after"><macro/></add>',          # sibling of a root
    ]
    for body in cases:
        tree = _macros()
        before = etree.tostring(tree)
        ops = _merge.apply_diff(tree, _diff(body))
        unchanged = etree.tostring(tree) == before
        if unchanged:
            assert all(not o.ok for o in ops), f"silent no-op reported as applied: {body}"
            assert all(o.detail for o in ops)
