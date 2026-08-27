"""C1: index <component> identity + connection slots (docs/BLIND-SPOTS.md F11).

Components are what a macro's <connections> point AT -- the slots that hold a
cockpit, turret, shield or engine. `connections` only became visible on
2026-08-12 (0 -> 19,994 rows); without components the join has one half.

SCOPED DELIBERATELY. A component file is a 3D structure definition: MEASURED,
flattening 5,011 of them wholesale yields 33,131,780 attribute rows -- 148x the
entire store. Identity + connections/connection measures ~204k rows (+91%), which
is the half that answers "what is installed in this slot".
"""

from lxml import etree

from x4validate import _effective, _effectivecli
from x4validate._provenance import Origin, Recorder


COMP = ('<components><component name="ship_x" class="ship_s">'
        '<source geometry="assets/x"/>'
        '<layers><layer><lod index="0"><materials><material id="1"/></materials></lod></layer></layers>'
        '<connections>'
        '<connection name="con_shield_01" tags="shield standard"/>'
        '<connection name="con_turret_01" tags="turret weapon"/>'
        '</connections>'
        '</component></components>')


def _extract(xml, vpath="assets/units/size_s/ship_x.xml"):
    root = etree.fromstring(xml)
    return _effective.extract_components(root, vpath, Recorder())


def test_component_identity_is_indexed_keyed_by_name():
    [e] = _extract(COMP)
    assert e.kind == "component"
    assert e.name == "ship_x"        # keyed by @name, NOT @id
    assert e.klass == "ship_s"


def test_connection_slots_are_indexed_with_their_tags():
    [e] = _extract(COMP)
    props = {p: v for p, v, _n, _c in e.attrs}
    assert props["connection[con_shield_01].tags"] == "shield standard"
    assert props["connection[con_turret_01].tags"] == "turret weapon"


def test_geometry_subtrees_are_NOT_indexed():
    """The scope decision, pinned: layers/source are 3D data. Indexing them
    measured 33.1M rows, 148x the store."""
    [e] = _extract(COMP)
    keys = {p for p, _v, _n, _c in e.attrs}
    assert not [k for k in keys if k.startswith("layers")], "layers must stay out"
    assert not [k for k in keys if k.startswith("source")], "source/geometry must stay out"
    assert not [k for k in keys if "material" in k or "lod" in k]


def test_duplicate_slot_names_do_not_collide_silently():
    """MEASURED: 11 of 5,011 components repeat a connection name. Two slots must
    not collapse into one row -- that would be the silent-narrowing defect again."""
    xml = ('<components><component name="c"><connections>'
           '<connection name="dup" tags="a"/><connection name="dup" tags="b"/>'
           '</connections></component></components>')
    [e] = _extract(xml)
    vals = sorted(v for p, v, _n, _c in e.attrs if p.endswith(".tags"))
    assert vals == ["a", "b"], f"both slots must survive, got {vals}"


def test_a_component_an_overlay_patched_carries_that_overlay_as_origin():
    root = etree.fromstring(COMP)
    rec = Recorder()
    conn = root.find(".//connection")

    rec.attr_set(conn, "tags", Origin("somemod", "replace", 7))
    [e] = _effective.extract_components(root, "assets/x.xml", rec)
    origins = {p: c[-1].source for p, _v, _n, c in e.attrs if p.endswith(".tags")}
    assert origins["connection[con_shield_01].tags"] == "somemod"


def test_build_default_kinds_cannot_drift_from_BUILDABLE_KINDS():
    """The CLI default was hardcoded "ware,macro,job", so adding `component` to
    BUILDABLE_KINDS built nothing and said nothing -- caught only because the
    entity count did not move. One list, one source."""
    import argparse
    from unittest.mock import patch
    captured = {}
    real = argparse.ArgumentParser.add_argument

    def spy(self, *a, **k):
        if a and a[0] == "--kinds":
            captured["default"] = k.get("default")
        return real(self, *a, **k)

    with patch.object(argparse.ArgumentParser, "add_argument", spy):
        try:
            _effectivecli.main(["--help"])
        except SystemExit:
            pass
    assert captured.get("default") == ",".join(_effective.BUILDABLE_KINDS)
