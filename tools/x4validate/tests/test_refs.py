"""Reference graph, dangling-reference detection, and completeness."""

from lxml import etree

from x4validate import _refs


def test_text_ref_parsing():
    assert _refs.text_refs_in("name {20101, 1001} desc") == [("20101", "1001")]
    assert _refs.text_refs_in(None) == []


def test_ware_defs_and_refs():
    tree = etree.fromstring(b"""<wares>
      <ware id="ore"><production><primary><ware ware="energycells" amount="2"/></primary></production></ware>
    </wares>""")
    assert _refs.ware_defs(tree) == {"ore"}
    assert ("energycells", _refs.ware_refs(tree)[0][1]) == _refs.ware_refs(tree)[0]


def test_find_dangling_flags_unresolved():
    introduced = etree.fromstring(
        b'<_added><ware id="x" name="{9,9}"><primary><ware ware="missing"/></primary></ware></_added>')
    dangling = _refs.find_dangling(introduced, ware_def_set={"ore"}, text_def_set={("1", "1")})
    kinds = {(d.kind, d.ref) for d in dangling}
    assert ("ware", "missing") in kinds
    assert ("text", "{9,9}") in kinds


def test_find_dangling_passes_resolved():
    introduced = etree.fromstring(
        b'<_added><thing ware="ore" name="{1,1}"/></_added>')
    assert _refs.find_dangling(introduced, ware_def_set={"ore"}, text_def_set={("1", "1")}) == []


def test_ware_completeness_reports_missing_kinds():
    wares = etree.fromstring(b"""<wares>
      <ware id="ore" name="{1,1}" description="{1,2}"><price min="1" average="2" max="3"/>
        <production/></ware>
      <ware id="newware"/>
    </wares>""")
    text_defs = {("1", "1"), ("1", "2")}
    rep = _refs.ware_completeness("newware", "ore", wares, text_defs)
    assert set(rep.missing) == {"name_string", "description_string", "price", "production"}
    assert "definition" not in rep.missing  # newware IS defined


def test_ship_completeness_flags_missing_component_owner_restriction():
    wares = etree.fromstring(b"""<wares>
      <ware id="ship_ref" name="{1,1}"><price min="1" average="2" max="3"/>
        <production/><component ref="ship_ref_macro"/>
        <owner faction="argon"/><restriction licence="capitalship"/></ware>
      <ware id="ship_new" name="{1,2}"><price min="1" average="2" max="3"/><production/></ware>
    </wares>""")
    rep = _refs.ware_completeness("ship_new", "ship_ref", wares,
                                 {("1", "1"), ("1", "2")}, {"ship_ref_macro"})
    assert set(rep.missing) == {"component", "owner", "restriction"}


def test_ship_completeness_flags_unregistered_macro():
    wares = etree.fromstring(b"""<wares>
      <ware id="ship_ref"><component ref="ship_ref_macro"/></ware>
      <ware id="ship_new"><component ref="ship_new_macro"/></ware>
    </wares>""")
    # ship_new's macro is NOT registered in the index -> component kind fails.
    rep = _refs.ware_completeness("ship_new", "ship_ref", wares, set(), {"ship_ref_macro"})
    assert "component" in rep.missing


def test_find_dangling_flags_unregistered_macro():
    introduced = etree.fromstring(b'<_added><ware id="s"><component ref="ghost_macro"/></ware></_added>')
    d = _refs.find_dangling(introduced, set(), set(), macro_def_set={"real_macro"})
    assert any(x.kind == "macro" and x.ref == "ghost_macro" for x in d)


def test_find_dangling_macro_ok_when_registered():
    introduced = etree.fromstring(b'<_added><ware id="s"><component ref="real_macro"/></ware></_added>')
    assert _refs.find_dangling(introduced, set(), set(), macro_def_set={"real_macro"}) == []


def test_ware_completeness_clean_when_matched():
    wares = etree.fromstring(b"""<wares>
      <ware id="ore" name="{1,1}"><price min="1" average="2" max="3"/></ware>
      <ware id="newware" name="{1,3}"><price min="1" average="2" max="3"/></ware>
    </wares>""")
    text_defs = {("1", "1"), ("1", "3")}
    rep = _refs.ware_completeness("newware", "ore", wares, text_defs)
    assert rep.missing == []
