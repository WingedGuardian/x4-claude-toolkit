"""Tests for _similarity.py — fuzzy same-ship detection."""

from __future__ import annotations

from lxml import etree

from x4validate import _similarity


SHIP_TEMPLATE = """
<macros><macro name="{name}" class="{cls}">
  <properties>
    <purpose primary="{purpose}"/>
    <people capacity="{people}"/>
    <storage missile="{missile}"/>
    <hull max="{hull}"/>
    <secrecy level="2"/>
    <rotationspeed max="{rot}"/>
    <rotationacceleration max="1000"/>
  </properties>
</macro></macros>
"""


def _ship(name, cls="ship_s", purpose="fight", people=3, missile=2, hull=3100, rot=1000):
    xml = SHIP_TEMPLATE.format(name=name, cls=cls, purpose=purpose, people=people,
                               missile=missile, hull=hull, rot=rot)
    return _similarity.extract_ship_vector(etree.fromstring(xml), "src", "v/path.xml")


def test_extract_ship_vector_basics():
    v = _ship("ship_arg_s_fighter_01_a_macro")
    assert v.ship_class == "ship_s"
    assert v.purpose == "fight"
    assert v.stats["hull.max"] == 3100.0


def test_non_ship_macro_returns_none():
    xml = '<macros><macro name="x" class="dock_gen_xs"><properties/></macro></macros>'
    assert _similarity.extract_ship_vector(etree.fromstring(xml), "src", "v") is None


def test_near_identical_ships_score_high():
    a = _ship("ship_a", hull=3100)
    b = _ship("ship_b", hull=3050)  # ~1.6% rescale, VRO-style
    pair = _similarity.similarity(a, b)
    assert pair is not None
    assert pair.score > 0.95


def test_different_class_never_compared():
    a = _ship("ship_a", cls="ship_s")
    b = _ship("ship_b", cls="ship_xl")
    assert _similarity.similarity(a, b) is None


def test_different_purpose_never_compared():
    a = _ship("ship_a", purpose="fight")
    b = _ship("ship_b", purpose="mine")
    assert _similarity.similarity(a, b) is None


def test_too_few_shared_keys_not_comparable():
    a = _similarity.ShipVector("a", "s", "v", "ship_s", "fight",
                               {"hull.max": 100.0, "people.capacity": 1.0})
    b = _similarity.ShipVector("b", "s", "v", "ship_s", "fight",
                               {"hull.max": 100.0, "people.capacity": 1.0})
    assert _similarity.similarity(a, b) is None  # only 2 shared keys, below min-4


def test_wildly_different_stats_score_low():
    a = _ship("ship_a", hull=3100, people=3, missile=2)
    b = _ship("ship_b", hull=200000, people=50, missile=500)  # capital-scale numbers
    pair = _similarity.similarity(a, b)
    assert pair is not None
    assert pair.score < 0.3


def test_find_similar_excludes_below_threshold():
    vecs = [_ship("ship_a", hull=3100), _ship("ship_b", hull=3105),  # near-dup
            _ship("ship_c", hull=50000)]                            # very different
    pairs = _similarity.find_similar(vecs, threshold=0.85)
    names = {(p.a.macro_name, p.b.macro_name) for p in pairs}
    assert ("ship_a", "ship_b") in names
    assert not any("ship_c" in n for n in names)


def test_find_similar_skips_identical_macro_name():
    """Same macro name = a UNION-KEY collision (x4compat's job), not this tool's."""
    vecs = [_ship("dup_name", hull=3100), _ship("dup_name", hull=3100)]
    assert _similarity.find_similar(vecs, threshold=0.85) == []


def test_exclude_same_source():
    a = _similarity.ShipVector("a", "mod_x", "v", "ship_s", "fight",
                               {"hull.max": 100.0, "people.capacity": 1.0,
                                "storage.missile": 2.0, "secrecy.level": 2.0})
    b = _similarity.ShipVector("b", "mod_x", "v", "ship_s", "fight",
                               {"hull.max": 100.0, "people.capacity": 1.0,
                                "storage.missile": 2.0, "secrecy.level": 2.0})
    assert _similarity.find_similar([a, b], threshold=0.85) != []
    assert _similarity.find_similar([a, b], threshold=0.85, exclude_same_source=True) == []
