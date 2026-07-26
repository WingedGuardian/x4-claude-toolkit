"""Diff-application and effective-tree assembly."""

from lxml import etree

from x4validate import _merge, _resolve


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
