"""Tests for _stats.py — advisory numeric comparison."""

from __future__ import annotations

from lxml import etree

from x4validate import _stats, _merge


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_ware_extraction():
    el = etree.fromstring(
        '<ware id="w1" group="weapons" transport="equipment" volume="2" tags="a b">'
        '<price min="10" average="20" max="30"/></ware>')
    w = _stats._ware_from_el(el)
    assert w.id == "w1" and w.group == "weapons" and w.volume == 2.0
    assert (w.price_min, w.price_avg, w.price_max) == (10.0, 20.0, 30.0)


def test_candidate_wares_from_diff(tmp_path):
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml",
       '<diff><add sel="/wares">'
       '<ware id="new1" group="weapons"><price average="500"/></ware>'
       '</add></diff>')
    cw = _stats.candidate_wares(cand)
    assert set(cw) == {"new1"}
    assert cw["new1"].price_avg == 500.0


def test_compare_wares_percentile():
    cand = {"c": _stats.Ware("c", "weapons", "equipment", 1, 0, 500, 0)}
    eff = {
        "c": cand["c"],  # candidate present in effective too — must be excluded from peers
        "p1": _stats.Ware("p1", "weapons", "equipment", 1, 0, 100, 0),
        "p2": _stats.Ware("p2", "weapons", "equipment", 1, 0, 300, 0),
        "p3": _stats.Ware("p3", "weapons", "equipment", 1, 0, 900, 0),
        "other": _stats.Ware("other", "shields", "equipment", 1, 0, 999, 0),
    }
    [cmp] = _stats.compare_wares(cand, eff)
    assert cmp.peer_group == "weapons"
    assert cmp.peer_count == 3            # p1,p2,p3 — candidate + other-group excluded
    assert cmp.peer_price_median == 300.0
    # 500 is above p1(100),p2(300) but below p3(900) -> 2/3 = ~67th percentile
    assert 60 < cmp.percentile < 70


def test_compare_wares_pricier_than_all():
    cand = {"c": _stats.Ware("c", "weapons", "e", 1, 0, 5000, 0)}
    eff = {"p1": _stats.Ware("p1", "weapons", "e", 1, 0, 100, 0)}
    [cmp] = _stats.compare_wares(cand, eff)
    assert "PRICIER than every" in cmp.note


def test_compare_wares_no_peers():
    cand = {"c": _stats.Ware("c", "exotica", "e", 1, 0, 5000, 0)}
    [cmp] = _stats.compare_wares(cand, {})
    assert "no same-group" in cmp.note


def test_flatten_macro_props():
    root = etree.fromstring(
        '<macros><macro name="m" class="weapon"><properties>'
        '<hull max="10000"/><rotationspeed max="20"/>'
        '<bullet class="bullet_x_macro"/><heat overheat="9000" coolrate="1160"/>'
        '</properties></macro></macros>')
    v = _stats.flatten_macro_props(root)
    assert v["class"] == "weapon"
    assert v["hull.max"] == 10000.0
    assert v["rotationspeed.max"] == 20.0
    assert v["heat.overheat"] == 9000.0
    assert v["bullet.class"] == "bullet_x_macro"  # kept as string for peer chasing


def test_effective_wares_reads_installed_overlay(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries" / "wares.xml",
       '<wares><ware id="ore" group="minerals"><price average="100"/></ware></wares>')
    ext = tmp_path / "extensions"
    mod = ext / "z_mod"
    _w(mod / "content.xml", '<content id="z_mod" name="z" version="1"/>')
    _w(mod / "libraries" / "wares.xml",
       '<diff><add sel="/wares"><ware id="newware" group="weapons">'
       '<price average="999"/></ware></add></diff>')
    cfg = _merge.Config(reference=ref)
    eff = _stats.effective_wares(ext, cfg)
    assert "ore" in eff and "newware" in eff
    assert eff["newware"].price_avg == 999.0
