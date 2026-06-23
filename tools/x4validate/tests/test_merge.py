"""Diff-application and effective-tree assembly."""

from lxml import etree

from x4validate import _merge


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


def test_full_file_override(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "index/macros.xml", '<index><entry name="a"/></index>')
    _write(ref / "extensions/ego_dlc_x/index/macros.xml",
           '<index><entry name="b"/></index>')  # full file, not a diff
    cfg = _merge.Config(reference=ref)
    merged = _merge.build_effective("index/macros.xml", cfg)
    assert merged.tree.xpath("//entry/@name") == ["b"]  # DLC fully overrode base
