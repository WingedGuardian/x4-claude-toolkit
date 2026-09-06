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


# --- a <t> added INTO an existing page was invisible --------------------------
#
# `text_defs` walked `//page[@id]` and then `.//t[@id]`. A diff that adds strings
# into a page the base game already defines has NO <page> element in its payload --
# the page id exists only in the selector -- so the walk could not reach it.
#
# That is the ordinary way to touch existing text, and the ONLY way to clobber a
# base string. MEASURED with two fixtures differing only in the depth of one
# selector: byte-identical mods referencing {1001,900001}/{1001,900002} gave
# "OK: no issues found" (rc 0) in the page-element form and TWO gating
# "introduced text reference does not resolve" errors (rc 1) in the into-page
# form -- while the same run's sel-resolution pass certified the selector as
# resolving. The collision half failed the other way: a real clobber of base
# string {1001,1} printed "OK: no issues found" with nothing in NOT CHECKED.
#
# Corpus, MEASURED over 125 extensions / 4,629 documents / 86 t-files: 30 <t id>
# definitions invisible, all cpsdo_faction, from one
# <add sel="/language[@id='44']/page[@id='20005']"> carrying 16 <t> children.

def _t(xml: bytes):
    return _refs.text_defs(etree.fromstring(xml))


def test_a_t_added_INTO_an_existing_page_is_a_definition():
    """The defect. No <page> element anywhere in the payload."""
    assert _t(b'<diff><add sel="//page[@id=\'20101\']">'
              b'<t id="1">x</t></add></diff>') == {("20101", "1")}


def test_the_corpus_form_with_a_language_prefixed_selector():
    """The shape actually present in the installed set, and with more than one
    child, so a reader that stopped at the first <t> would be caught."""
    assert _t(b'<diff><add sel="/language[@id=\'44\']/page[@id=\'20005\']">'
              b'<t id="7">x</t><t id="8">y</t></add></diff>') == {
        ("20005", "7"), ("20005", "8")}


def test_a_replace_into_a_page_also_defines():
    """`<replace>` is the other way to put strings in a page -- and the other way
    to clobber one -- so it must count exactly as `<add>` does."""
    assert _t(b'<diff><replace sel="//page[@id=\'1001\']">'
              b'<t id="1">clobbered</t></replace></diff>') == {("1001", "1")}


def test_the_page_ELEMENT_form_still_works(  ):
    """Twin: the shape that always worked must be untouched by the new branch."""
    assert _t(b'<diff><add sel="/language"><page id="20101">'
              b'<t id="1">x</t></page></add></diff>') == {("20101", "1")}


def test_a_full_language_file_still_works():
    """Twin: not a diff at all."""
    assert _t(b'<language id="44"><page id="1001"><t id="1">x</t>'
              b'<t id="2">y</t></page></language>') == {("1001", "1"), ("1001", "2")}


def test_an_op_whose_selector_names_NO_page_defines_nothing():
    """Twin, and the one that matters most: the new branch reads a page id out of a
    SELECTOR, so it must not invent one. An op with no page in its sel contributes
    nothing, however many <t> elements happen to be under it."""
    assert _t(b'<diff><add sel="/wares"><ware id="w"><t id="9">x</t>'
              b'</ware></add></diff>') == set()


def test_an_op_with_a_page_selector_but_no_t_defines_nothing():
    """The other clause, alone: a page-scoped op that carries no <t> is not a text
    definition. Tested separately so the <t> clause cannot be shadowed by the
    selector clause in front of it."""
    assert _t(b'<diff><add sel="//page[@id=\'20101\']">'
              b'<something id="1"/></add></diff>') == set()
