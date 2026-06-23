"""9.0 mechanical-port checks: XSD schema validation + runtime migration heuristic.

Uses a tiny synthetic schema so tests stay fast (the real md.xsd/common.xsd take
~100s to compile — that path is integration-validated against ATD instead)."""

from pathlib import Path

from x4validate import _check, _merge, _migration, _xsd

_TINY_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="root">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="allowed" minOccurs="0"/>
      </xs:sequence>
      <xs:attribute name="req" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>'''

_HDR = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="test.xsd"'


def test_xsd_flags_missing_required_attr_passes_valid(tmp_path):
    lib = tmp_path / "reference" / "libraries"
    lib.mkdir(parents=True)
    (lib / "test.xsd").write_text(_TINY_XSD, encoding="utf-8")
    mod = tmp_path / "mod" / "md"
    mod.mkdir(parents=True)
    (mod / "good.xml").write_text(f'<root {_HDR} req="x"/>', encoding="utf-8")
    (mod / "bad.xml").write_text(f'<root {_HDR}/>', encoding="utf-8")  # missing req

    cfg = _merge.Config(reference=tmp_path / "reference")
    findings, checked, skipped = _xsd.validate_mod(tmp_path / "mod", cfg)
    assert checked == 2
    bad = [f for f in findings if "bad.xml" in f.file]
    assert bad and "req" in " ".join(f.message for f in bad)
    assert not any("good.xml" in f.file for f in findings)  # valid file clean


def test_xsd_skips_unknown_root(tmp_path):
    lib = tmp_path / "reference" / "libraries"
    lib.mkdir(parents=True)
    mod = tmp_path / "mod" / "md"
    mod.mkdir(parents=True)
    (mod / "x.xml").write_text("<whatever/>", encoding="utf-8")  # no schema, no decl
    cfg = _merge.Config(reference=tmp_path / "reference")
    findings, checked, skipped = _xsd.validate_mod(tmp_path / "mod", cfg)
    assert skipped == 1 and findings == []


def test_check_xsd_categorizes_required_vs_strict(tmp_path):
    # md.xsd is stricter than the engine, so only "required but missing" is an error;
    # "not allowed" is a schema-strict advisory.
    lib = tmp_path / "reference" / "libraries"
    lib.mkdir(parents=True)
    (lib / "test.xsd").write_text(_TINY_XSD, encoding="utf-8")
    mod = tmp_path / "mod" / "md"
    mod.mkdir(parents=True)
    (mod / "req.xml").write_text(f'<root {_HDR}/>', encoding="utf-8")              # required missing -> GATE
    (mod / "elem.xml").write_text(f'<root {_HDR} req="x"><surprise/></root>', encoding="utf-8")  # element not expected -> GATE
    (mod / "extra.xml").write_text(f'<root {_HDR} req="x" extra="y"/>', encoding="utf-8")  # attr not allowed -> advisory
    cfg = _merge.Config(reference=tmp_path / "reference")
    rep = _check.Report()
    _check.check_xsd(tmp_path / "mod", cfg, rep)
    errs = {f.vpath for f in rep.findings if f.severity == "error" and f.category == "xsd"}
    advs = {f.vpath for f in rep.findings if f.severity == "info" and f.category == "xsd-strict"}
    assert any("req.xml" in e for e in errs)     # required-attr breakage gates
    assert any("elem.xml" in e for e in errs)    # removed/unknown element gates
    assert any("extra.xml" in a for a in advs)   # attribute-not-allowed is advisory
    assert not any("extra.xml" in e for e in errs)


def test_migration_flags_dead_apis_only(tmp_path):
    mod = tmp_path / "mod"
    (mod / "md").mkdir(parents=True)
    (mod / "md" / "s.xml").write_text(
        "<x><raise_lua_event name=\"'Lua_Loader.Load'\"/><a>$t.keys.list.clone</a></x>",
        encoding="utf-8")
    (mod / "ok.lua").write_text("local n = foo.keys.list  -- plain, no .clone", encoding="utf-8")
    out = _migration.scan_mod(mod)
    assert any("Lua_Loader" in m.note for m in out)
    clone = [m for m in out if "use .keys.list" in m.note]
    assert len(clone) == 1  # only the .clone, not the plain .keys.list in ok.lua
