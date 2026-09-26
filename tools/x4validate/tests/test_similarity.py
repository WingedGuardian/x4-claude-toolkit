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


def test_threshold_rejects_values_outside_0_1():
    """A similarity score is a ratio. `--threshold -1` used to match every pair
    with every other and emit 1.7 MB of meaningless 'findings'."""
    import argparse
    import pytest

    for bad in ("-1", "9", "1.5"):
        with pytest.raises(argparse.ArgumentTypeError):
            _similarity._threshold(bad)
    for good in ("0", "0.85", "1"):
        assert 0.0 <= _similarity._threshold(good) <= 1.0


# --- AN-6: ships are scored at their EFFECTIVE values ---------------------------

_BASE_SHIP = ('<macros><macro name="ship_a_macro" class="ship_s"><properties>'
              '<purpose primary="fight"/><hull max="1000"/><people capacity="2"/>'
              '<storage missile="10" unit="0"/><secrecy level="1"/>'
              '</properties></macro></macros>')
_SHIP_VPATH = "assets/units/size_s/macros/ship_a_macro.xml"


def _an6_world(tmp_path, monkeypatch, patch: str, enabled: bool = True):
    from x4validate import _registry
    prof = tmp_path / "profile_content.xml"
    prof.write_text('<content><extension id="patch_mod" enabled="%s"/></content>'
                    % ("true" if enabled else "false"), encoding="utf-8")
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", prof)
    ref = tmp_path / "reference"
    (ref / _SHIP_VPATH).parent.mkdir(parents=True)
    (ref / _SHIP_VPATH).write_text(_BASE_SHIP, encoding="utf-8")
    ext = tmp_path / "extensions"
    mod = ext / "patch_mod"
    (mod / _SHIP_VPATH).parent.mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="patch_mod" name="p" version="1"/>',
                                     encoding="utf-8")
    (mod / _SHIP_VPATH).write_text(patch, encoding="utf-8")
    return [v for v in _similarity._collect_all(ref, ext, [], dlc_dirs=[])
            if v.macro_name == "ship_a_macro"]


def test_a_root_replace_patch_is_scored_at_its_replacement(tmp_path, monkeypatch):
    """VRO's idiom (CLAUDE.md #10): `<replace sel="//macros">` with a whole new
    document. The raw reader saw a <diff> root and scored vanilla."""
    vecs = _an6_world(tmp_path, monkeypatch,
                      '<diff><replace sel="//macros">'
                      + _BASE_SHIP.replace('max="1000"', 'max="7777"') + '</replace></diff>')
    assert [(v.source, v.stats.get("hull.max")) for v in vecs] == [("base", 7777.0)]


def test_a_patch_in_a_DISABLED_mod_does_not_change_the_score(tmp_path, monkeypatch):
    """The twin: the effective tree is the ENGINE's, so a disabled mod's patch is
    not applied (and the ship is still reported once, as base)."""
    vecs = _an6_world(tmp_path, monkeypatch,
                      '<diff><replace sel="//macro/properties/hull/@max">5000</replace>'
                      '</diff>', enabled=False)
    assert [(v.source, v.stats.get("hull.max")) for v in vecs] == [("base", 1000.0)]


def test_unscorable_ships_are_counted_not_dropped():
    few = _similarity.ShipVector("x", "base", "v", "ship_s", "fight",
                                 stats={"hull.max": 1.0, "secrecy.level": 1.0})
    enough = _similarity.ShipVector("y", "base", "v", "ship_s", "fight",
                                    stats={k: 1.0 for k in list(_similarity._WEIGHTS)[:4]})
    assert _similarity.unscorable([few, enough]) == [few]


def test_a_candidate_whose_ship_file_a_LATER_mod_also_ships_stays_visible(
        tmp_path, monkeypatch, capsys):
    """Review of AN-6: one vector per merged file, labelled by the last full-file
    supplier, made a candidate vanish from --candidate when a later mod ships the
    same file. Every contributor is tracked, so the candidate's ship is still found."""
    from x4validate import _registry
    monkeypatch.setattr(_registry, "ingest_content_xml", lambda *a, **k: [])
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", None)
    ref = tmp_path / "reference"
    (ref / "assets" / "units").mkdir(parents=True)
    peer = ref / "assets/units/size_s/macros/ship_peer_macro.xml"
    peer.parent.mkdir(parents=True)
    peer.write_text(_BASE_SHIP.replace("ship_a_macro", "ship_peer_macro"), encoding="utf-8")
    ext = tmp_path / "extensions"
    vp = "assets/units/size_s/macros/ship_new_macro.xml"
    for folder in ("a_cand", "z_later"):
        (ext / folder / vp).parent.mkdir(parents=True)
        (ext / folder / "content.xml").write_text(
            f'<content id="{folder}" name="{folder}" version="1"/>', encoding="utf-8")
        (ext / folder / vp).write_text(_BASE_SHIP.replace("ship_a_macro", "ship_new_macro"),
                                       encoding="utf-8")
    rc = _similarity.main(["--reference", str(ref), "--ext-dir", str(ext),
                           "--candidate", "a_cand"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ship_new_macro" in out and "ship_peer_macro" in out, out
    assert "a_cand, z_later" in out, out
