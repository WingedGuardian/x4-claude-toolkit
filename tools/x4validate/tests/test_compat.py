"""Tests for _compat.py — cross-mod collision detection."""

from __future__ import annotations

from x4validate import _compat, _merge


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mod(ext, folder, files, mod_id=None, deps=()):
    """Create a loose mod folder with a content.xml + given {vpath: text}."""
    root = ext / folder
    dep_xml = "".join(f'<dependency id="{d}"/>' for d in deps)
    _w(root / "content.xml",
       f'<content id="{mod_id or folder}" name="{folder}" version="1">{dep_xml}</content>')
    for vpath, text in files.items():
        _w(root / vpath, text)
    return root


def _setup_ref(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries" / "wares.xml",
       '<wares><ware id="ore"><price average="100"/></ware>'
       '<ware id="ice"><price average="50"/></ware></wares>')
    _w(ref / "aiscripts" / "order.fight.xml",
       '<aiscript name="order.fight"><actions><label name="start"/></actions></aiscript>')
    _w(ref / "assets" / "props" / "mat.xml", "<materials><m id='a'/></materials>")
    return _merge.Config(reference=ref)


def test_hard_two_mods_replace_same_node(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">200</replace></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">300</replace></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    hard = rep.by_kind("HARD")
    assert len(hard) == 1
    assert hard[0].mods == ["a_mod", "b_mod"]
    assert hard[0].winner == "b_mod"  # loads last alphabetically


def test_soft_two_mods_add_under_same_parent(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="a_extra"/></add></diff>'})
    _mod(ext, "b_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="b_extra"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.hard
    assert len(rep.by_kind("SOFT")) == 1


def test_dup_add_same_key_escalates_to_hard(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # Both add a label with the SAME name under the same parent -> duplicate.
    _mod(ext, "a_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="dup"/></add></diff>'})
    _mod(ext, "b_mod", {"aiscripts/order.fight.xml":
         '<diff><add sel="//actions"><label name="dup"/></add></diff>'})
    rep = _compat.analyze(ext, config=cfg)
    assert len(rep.by_kind("HARD")) == 1
    assert "duplicate" in rep.by_kind("HARD")[0].detail


def test_union_key_two_mods_define_same_ware_id(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # Full-file (non-diff) libraries/wares.xml from two mods, both defining ware 'newore'.
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<wares><ware id="newore"><price average="1"/></ware></wares>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<wares><ware id="newore"><price average="2"/></ware></wares>'})
    rep = _compat.analyze(ext, config=cfg)
    uk = rep.by_kind("UNION-KEY")
    assert len(uk) == 1
    assert "newore" in uk[0].target
    assert uk[0].winner == "b_mod"


def test_union_different_ids_no_collision(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<wares><ware id="ware_a"><price average="1"/></ware></wares>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<wares><ware id="ware_b"><price average="2"/></ware></wares>'})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.collisions  # distinct ids coexist in a union dir


def test_full_override_two_mods_same_asset(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"assets/props/mat.xml": "<materials><m id='x'/></materials>"})
    _mod(ext, "b_mod", {"assets/props/mat.xml": "<materials><m id='y'/></materials>"})
    rep = _compat.analyze(ext, config=cfg)
    fo = rep.by_kind("FULL-OVERRIDE")
    assert len(fo) == 1
    assert fo[0].winner == "b_mod"


def test_ui_xml_not_flagged_as_override(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"ui.xml": "<wm><add><ui/></add></wm>"})
    _mod(ext, "b_mod", {"ui.xml": "<wm><add><ui/></add></wm>"})
    rep = _compat.analyze(ext, config=cfg)
    assert not rep.by_kind("FULL-OVERRIDE")  # per-extension manifest, never overrides


def test_load_order_dependency_forces_earlier(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    # z_mod depends on a_mod's id -> but also they collide; dependency doesn't change
    # who-wins here (dep loads FIRST, so the dependent z_mod still wins as it loads later).
    _mod(ext, "z_first_alpha", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">1</replace></diff>'},
         mod_id="ZID")
    _mod(ext, "a_dependent", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">2</replace></diff>'},
         deps=["ZID"])
    rep = _compat.analyze(ext, config=cfg)
    order = rep.load_order
    # dependency ZID(z_first_alpha) must come before its dependent a_dependent,
    # overriding the alphabetical (a before z) default.
    assert order.index("z_first_alpha") < order.index("a_dependent")
    assert rep.by_kind("HARD")[0].winner == "a_dependent"


def test_candidate_mode_only_reports_candidate_collisions(tmp_path):
    cfg = _setup_ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">1</replace></diff>'})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ice\']/price/@average">1</replace></diff>'})
    # candidate collides only with a_mod (both touch 'ore')
    cand = _mod(ext, "cand_mod", {"libraries/wares.xml":
         '<diff><replace sel="//ware[@id=\'ore\']/price/@average">9</replace></diff>'})
    rep = _compat.analyze(ext, candidate=cand, config=cfg)
    assert all("cand_mod" in c.mods for c in rep.collisions)
    assert any(set(c.mods) == {"a_mod", "cand_mod"} for c in rep.by_kind("HARD"))
    assert not any("b_mod" in c.mods for c in rep.collisions)
