"""Provenance capture through _merge: chains, inheritance, union, override."""

from lxml import etree

from x4validate import _merge
from x4validate._provenance import Origin, Recorder


def _wares():
    return etree.fromstring(b"""<wares>
  <ware id="ore" price_average="120"><price min="80" average="120" max="160"/></ware>
  <ware id="gone"/>
</wares>""")


def _diff(body: bytes):
    return etree.fromstring(b"<diff>" + body + b"</diff>")


def test_replace_attr_chain_winner_and_history():
    tree, rec = _wares(), Recorder()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/@price_average">500</replace>'),
        recorder=rec, source="modA")
    ore = tree.xpath("//ware[@id='ore']")[0]
    chain = rec.attr_chain(ore, "price_average")
    assert chain[-1].source == "modA" and chain[-1].op == "replace-attr"
    assert chain[0] == rec.default_origin          # history starts at base
    assert rec.is_base(ore, "volume")              # untouched attr stays base
    assert not rec.is_base(ore, "price_average")


def test_two_mods_stack_three_entry_chain():
    tree, rec = _wares(), Recorder()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/@price_average">300</replace>'),
        recorder=rec, source="modA")
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/@price_average">999</replace>'),
        recorder=rec, source="modB")
    ore = tree.xpath("//ware[@id='ore']")[0]
    chain = rec.attr_chain(ore, "price_average")
    assert [o.source for o in chain] == ["base", "modA", "modB"]
    assert rec.winner(ore, "price_average").source == "modB"


def test_add_subtree_inherits_from_added_root():
    tree, rec = _wares(), Recorder()
    _merge.apply_diff(tree, _diff(
        b'<add sel="//wares"><ware id="new"><price average="7"/></ware></add>'),
        recorder=rec, source="modA")
    price = tree.xpath("//ware[@id='new']/price")[0]
    # descendant of an added subtree inherits the add origin via ancestor walk
    assert rec.winner(price, "average").source == "modA"
    assert rec.winner(price).op == "add"


def test_element_replace_carries_prior_lineage():
    tree, rec = _wares(), Recorder()
    _merge.apply_diff(tree, _diff(
        b'<replace sel="//ware[@id=\'ore\']/price"><price min="1" average="2" max="3"/></replace>'),
        recorder=rec, source="modA")
    price = tree.xpath("//ware[@id='ore']/price")[0]
    chain = rec.elem_chain(price)
    assert [o.source for o in chain] == ["base", "modA"]
    assert chain[-1].op == "replace"


def test_union_replace_carries_entity_chain():
    tree, rec = _wares(), Recorder()
    overlay = etree.fromstring(
        b'<wares><ware id="ore" price_average="777"/><ware id="fresh"/></wares>')
    _merge._union_children(tree, overlay, recorder=rec, source="vro")
    ore = tree.xpath("//ware[@id='ore']")[0]
    assert [o.source for o in rec.elem_chain(ore)] == ["base", "vro"]
    assert rec.elem_chain(ore)[-1].op == "union-replace"
    fresh = tree.xpath("//ware[@id='fresh']")[0]
    assert rec.elem_chain(fresh) == [Origin("vro", "union-add")]
    # attr under a union-replaced entity restarts at the entity chain
    assert rec.winner(ore, "price_average").source == "vro"


def test_remove_recorded_with_path():
    tree, rec = _wares(), Recorder()
    _merge.apply_diff(tree, _diff(b'<remove sel="//ware[@id=\'gone\']"/>'),
                      recorder=rec, source="modA")
    assert not tree.xpath("//ware[@id='gone']")
    (path, origin), = rec.removed
    assert "ware" in path and origin.source == "modA" and origin.op == "remove"


def test_full_override_resets_default():
    rec = Recorder()
    rec.attr_set(etree.Element("x"), "a", Origin("modA", "replace-attr"))
    rec.full_override(Origin("modB", "full-override"))
    el = etree.Element("y")
    assert rec.elem_chain(el) == [Origin("modB", "full-override")]
    assert rec.default_origin.source == "modB"


def test_build_effective_records_file_chain(tmp_path):
    ref = tmp_path / "ref"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(
        b'<wares><ware id="ore" price_average="120"/></wares>')
    mod = tmp_path / "modA"
    (mod / "libraries").mkdir(parents=True)
    (mod / "libraries" / "wares.xml").write_bytes(
        b'<diff><replace sel="//ware[@id=\'ore\']/@price_average">500</replace></diff>')
    rec = Recorder()
    res = _merge.build_effective("libraries/wares.xml", _merge.Config(reference=ref),
                                 extra_overlays=[mod], recorder=rec)
    ore = res.tree.xpath("//ware[@id='ore']")[0]
    assert rec.winner(ore, "price_average").source == "modA"
    assert [o.source for o in rec.file_chain] == ["modA"]


def test_recorder_none_is_noop_regression():
    # identical behavior with and without a recorder
    t1, t2 = _wares(), _wares()
    ops = _diff(b'<replace sel="//ware[@id=\'ore\']/@price_average">500</replace>'
                b'<add sel="//wares"><ware id="n"/></add>'
                b'<remove sel="//ware[@id=\'gone\']"/>')
    a1 = _merge.apply_diff(t1, ops)
    a2 = _merge.apply_diff(t2, ops, recorder=Recorder(), source="m")
    assert etree.tostring(t1) == etree.tostring(t2)
    assert [(o.tag, o.ok) for o in a1] == [(o.tag, o.ok) for o in a2]


import json


# --- F64: provenance reports WHO WON, never WHO INTRODUCED --------------------
#
# A root `<replace sel="//macros">` swaps the whole document, so base contributes
# NO chain entry -- and that is VRO's dominant idiom (848 root-replaces, CLAUDE.md
# #10). A single-entry chain then reads as "this mod introduced this" when it
# usually means "this mod re-supplied what vanilla already had".
#
# PEER-MEASURED: of 35,423 single-op root-replace attributes, 23,182 (65.4%) also
# exist in vanilla with the chain hiding it; only 39 vpaths are truly mod-added.
# It cost a real design conclusion ("VRO added Kha'ak shield disruption" -- false).
#
# Scope is deliberately EXISTENCE, not the vanilla value: extracting the value
# means re-deriving the flatten, and a second implementation of a normaliser is
# exactly what made a peer's check report 2.6% where the answer was 65.4%.

def test_note_fires_for_a_single_non_base_chain_over_a_vanilla_vpath(monkeypatch):
    """The F64 case itself."""
    from x4validate import _effective
    monkeypatch.setattr(_effective, "base_has", lambda cfg, vp, owner=None: True)
    note = _effective._winner_not_origin_note(
        "assets/props/x_macro.xml", json.dumps([["vro", "replace-root", 3]]), cfg=object())
    assert note and "WON" in note.upper(), note


def test_note_is_SILENT_when_base_does_not_ship_the_vpath(monkeypatch):
    """The 39 genuinely mod-added vpaths must not be slandered as re-supplies."""
    from x4validate import _effective
    monkeypatch.setattr(_effective, "base_has", lambda cfg, vp, owner=None: False)
    assert _effective._winner_not_origin_note(
        "assets/props/modonly_macro.xml", json.dumps([["vro", "replace-root", 3]]),
        cfg=object()) is None


def test_note_is_SILENT_for_a_pure_base_value(monkeypatch):
    """`chain` is None for a pure-default value -- there is no winner to disclaim."""
    from x4validate import _effective
    monkeypatch.setattr(_effective, "base_has", lambda cfg, vp, owner=None: True)
    assert _effective._winner_not_origin_note("libraries/wares.xml", None, cfg=object()) is None


def test_note_is_SILENT_when_the_chain_ALREADY_shows_base(monkeypatch):
    """A multi-entry chain that names base is not hiding anything, so annotating it
    would be noise -- and a note that fires on the 99% trains you to ignore it."""
    from x4validate import _effective
    monkeypatch.setattr(_effective, "base_has", lambda cfg, vp, owner=None: True)
    assert _effective._winner_not_origin_note(
        "libraries/wares.xml",
        json.dumps([["base", "full", 0], ["vro", "replace", 7]]), cfg=object()) is None
