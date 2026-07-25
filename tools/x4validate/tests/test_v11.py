"""v1.1 checks: file-existence, page-collision, connection-validation, variant-set, sel-only."""

from pathlib import Path
import hashlib

from x4validate import _check, _merge


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- file existence (macro -> component -> file) ---

def test_file_existence_flags_registered_but_missing_macro_file(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "index/macros.xml", '<index><entry name="badfile_macro" value="assets/m/badfile_macro"/></index>')
    _w(ref / "index/components.xml", "<index/>")
    mod = tmp_path / "mod"
    _w(mod / "libraries/wares.xml",
       '<diff><add sel="//wares"><ware id="s"><component ref="badfile_macro"/></ware></add></diff>')
    rep = _check.Report()
    _check.check_file_existence(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "file" and "file missing" in f.message for f in rep.findings)


def test_file_existence_clean_full_chain(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "index/macros.xml", '<index><entry name="good_macro" value="assets/m/good_macro"/></index>')
    _w(ref / "index/components.xml", '<index><entry name="good_comp" value="assets/c/good_comp"/></index>')
    _w(ref / "assets/m/good_macro.xml", '<macros><macro name="good_macro"><component ref="good_comp"/></macro></macros>')
    _w(ref / "assets/c/good_comp.xml", "<components/>")
    mod = tmp_path / "mod"
    _w(mod / "libraries/wares.xml",
       '<diff><add sel="//wares"><ware id="s"><component ref="good_macro"/></ware></add></diff>')
    rep = _check.Report()
    _check.check_file_existence(mod, _merge.Config(reference=ref), rep)
    assert [f for f in rep.findings if f.category == "file"] == []


# --- page-id collision ---

def test_page_collision_warns(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "t/0001-l044.xml", '<language id="44"><page id="1"><t id="1">x</t></page></language>')
    mod = tmp_path / "mod"
    _w(mod / "t/0001.xml", '<diff><add sel="/language"><page id="1"><t id="1">y</t></page></add></diff>')
    rep = _check.Report()
    _check.check_page_collisions(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "text" for f in rep.findings)


# --- connection validation (loadout path -> component connection) ---

def test_connection_flags_bad_path_passes_good(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "index/macros.xml", "<index/>")
    _w(ref / "index/components.xml", '<index><entry name="ship_x" value="assets/u/ship_x"/></index>')
    _w(ref / "assets/u/ship_x.xml",
       '<components><component name="ship_x"><connections><connection name="con_engine_01"/></connections></component></components>')
    mod = tmp_path / "mod"
    _w(mod / "assets/u/ship_new_macro.xml",
       '<macros><macro name="ship_new_macro"><component ref="ship_x"/>'
       '<loadouts><loadout id="default"><macros>'
       '<engine macro="e" path="../con_engine_01"/>'
       '<engine macro="e2" path="../con_engine_BAD"/>'
       '</macros></loadout></loadouts></macro></macros>')
    rep = _check.Report()
    _check.check_connections(mod, _merge.Config(reference=ref), rep)
    msgs = [f.message for f in rep.findings if f.category == "connection"]
    assert any("con_engine_BAD" in m for m in msgs)
    assert not any("con_engine_01" in m for m in msgs)


# --- variant-set diff-coverage ---

def test_variant_warns_when_sibling_untouched(tmp_path):
    ref = tmp_path / "reference"
    d = "assets/units/size_l/macros"
    _w(ref / d / "ship_v_01_a_macro.xml", "<macros/>")
    _w(ref / d / "ship_v_01_b_macro.xml", "<macros/>")
    mod = tmp_path / "mod"
    _w(mod / d / "ship_v_01_a_macro.xml", "<diff/>")  # only _a patched
    rep = _check.Report()
    _check.check_variant_consistency(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "variant" and "ship_v_01_b_macro.xml" in f.message for f in rep.findings)


def test_variant_clean_when_both_touched(tmp_path):
    ref = tmp_path / "reference"
    d = "assets/units/size_l/macros"
    _w(ref / d / "ship_v_01_a_macro.xml", "<macros/>")
    _w(ref / d / "ship_v_01_b_macro.xml", "<macros/>")
    mod = tmp_path / "mod"
    _w(mod / d / "ship_v_01_a_macro.xml", "<diff/>")
    _w(mod / d / "ship_v_01_b_macro.xml", "<diff/>")
    rep = _check.Report()
    _check.check_variant_consistency(mod, _merge.Config(reference=ref), rep)
    assert [f for f in rep.findings if f.category == "variant"] == []


# --- sel-only fast path ---

def test_sel_only_one_file_runs_only_sel(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries/wares.xml", '<wares><ware id="ore"/></wares>')
    mod = tmp_path / "mod"
    f = mod / "libraries/wares.xml"
    _w(f, '<diff><replace sel="//ware[@id=\'nope\']/@x">1</replace></diff>')
    rep = _check.validate(mod, _merge.Config(reference=ref), only_file=f)
    assert rep.findings and all(c.category in ("sel", "path") for c in rep.findings)
    assert any(c.category == "sel" for c in rep.findings)


# --- loader-sanity checks found from live debug logs ---

def _write_cat(mod_dir, cat_name, members):
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    dat = cat.with_suffix(".dat")
    lines = []
    blob = bytearray()
    for vpath, data in members:
        md5 = hashlib.md5(data).hexdigest()
        lines.append(f"{vpath} {len(data)} 1700000000 {md5}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dat.write_bytes(bytes(blob))


def test_text_sanity_warns_on_literal_newline(tmp_path):
    ref = tmp_path / "reference"
    mod = tmp_path / "mod"
    _w(mod / "t/0001.xml",
       '<language><page id="9"><t id="3">one\ntwo</t><t id="4">ok</t></page></language>')
    rep = _check.Report()
    _check.check_text_sanity(mod, _merge.Config(reference=ref), rep)
    msgs = [f.message for f in rep.findings if f.category == "text"]
    assert any("{9,3}" in m and "literal newline" in m for m in msgs)
    assert not any("{9,4}" in m for m in msgs)


def test_identity_values_flags_faction_as_makerrace(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries/races.xml", '<races><race id="argon"/></races>')
    mod = tmp_path / "mod"
    _w(mod / "assets/m/macros/weapon.xml",
       '<macros><macro name="weapon"><properties>'
       '<identification makerrace="loanshark"/>'
       '</properties></macro></macros>')
    rep = _check.Report()
    _check.check_identity_values(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "identity" and f.severity == "error" and "loanshark" in f.message
               for f in rep.findings)


def test_identity_values_accepts_real_race(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries/races.xml", '<races><race id="argon"/></races>')
    mod = tmp_path / "mod"
    _w(mod / "assets/m/macros/weapon.xml",
       '<macros><macro name="weapon"><properties>'
       '<identification makerrace="argon"/>'
       '</properties></macro></macros>')
    rep = _check.Report()
    _check.check_identity_values(mod, _merge.Config(reference=ref), rep)
    assert [f for f in rep.findings if f.category == "identity"] == []


def test_identity_values_accepts_mod_added_race(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries/races.xml", '<races><race id="argon"/></races>')
    mod = tmp_path / "mod"
    _w(mod / "libraries/races.xml",
       '<diff><add sel="/races"><race id="customrace"/></add></diff>')
    _w(mod / "assets/m/macros/weapon.xml",
       '<macros><macro name="weapon"><properties>'
       '<identification makerrace="customrace"/>'
       '</properties></macro></macros>')
    rep = _check.Report()
    _check.check_identity_values(mod, _merge.Config(reference=ref), rep)
    assert [f for f in rep.findings if f.category == "identity"] == []


def test_engine_connection_tags_flag_mismatch_and_normalize_order(tmp_path):
    ref = tmp_path / "reference"
    mod = tmp_path / "mod"
    _w(mod / "assets/units/ship.xml",
       '<components><component name="ship">'
       '<connections>'
       '<connection name="con_engine_01" tags="advanced engine medium platformcollision"/>'
       '<connection name="con_engine_02" tags="medium advanced engine"/>'
       '</connections>'
       '</component></components>')
    rep = _check.Report()
    _check.check_engine_connection_tags(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "connection" and "non-identical engine connection tags" in f.message
               for f in rep.findings)


def test_engine_connection_tags_clean_when_sets_match(tmp_path):
    ref = tmp_path / "reference"
    mod = tmp_path / "mod"
    _w(mod / "assets/units/ship.xml",
       '<components><component name="ship">'
       '<connections>'
       '<connection name="con_engine_01" tags="advanced engine medium"/>'
       '<connection name="con_engine_02" tags="medium advanced engine"/>'
       '</connections>'
       '</component></components>')
    rep = _check.Report()
    _check.check_engine_connection_tags(mod, _merge.Config(reference=ref), rep)
    assert [f for f in rep.findings if f.category == "connection"] == []


def test_loader_sanity_scans_packed_xml(tmp_path):
    ref = tmp_path / "reference"
    _w(ref / "libraries/races.xml", '<races><race id="argon"/></races>')
    mod = tmp_path / "packed"
    _write_cat(mod, "ext_01.cat", [
        ("t/0001.xml", b'<language><page id="99"><t id="3">packed\ntext</t></page></language>'),
        ("assets/m/macros/weapon.xml", b'<macros><macro name="weapon"><properties><identification makerrace="loanshark"/></properties></macro></macros>'),
    ])
    rep = _check.Report()
    _check.check_text_sanity(mod, _merge.Config(reference=ref), rep)
    _check.check_identity_values(mod, _merge.Config(reference=ref), rep)
    assert any(f.category == "text" and "{99,3}" in f.message for f in rep.findings)
    assert any(f.category == "identity" and "loanshark" in f.message for f in rep.findings)
