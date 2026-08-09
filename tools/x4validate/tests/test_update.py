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
    advs = {f.vpath for f in rep.findings if f.severity == "info"}
    assert any("req.xml" in e for e in errs)     # required-attr breakage gates
    assert any("elem.xml" in e for e in errs)    # removed/unknown element gates
    # F7 (2026-08-02): attribute-not-allowed is STILL advisory on the MD side, but
    # a pair vanilla never uses now carries its own category, `xsd-unknown-attr`
    # (here the tmp reference uses (root, extra) nowhere). Severity unchanged —
    # that is the ATD-protection asymmetry pinned in test_effective_schema.
    assert any("extra.xml" in f.vpath for f in rep.findings
               if f.severity == "info" and f.category == "xsd-unknown-attr")
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


# --------------------------------------------------------------------------
# Engine-verified md.xsd element-model gaps.
#
# `check_xsd` GATES "element not expected" on the deliberate reasoning that a
# removed/renamed action is safer flagged than missed. That policy produced 9
# false ERRORs on a working mod using <ammunition> inside <create_ship>.
# Settled 2026-08-09 by the engine itself, not by judgement: a live debug.txt
# shows the engine parsing those same files to LINE granularity (expression
# warnings at specific lines) while raising no objection at any of the 9
# <ammunition> sites -- and common.xsd:11738 defines exactly that nested shape.
# --------------------------------------------------------------------------

_AMMO_MSG = ("Element 'ammunition': This element is not expected. "
             "Expected is one of ( orientation, position, safepos, rotation ).")


def test_known_schema_gap_is_recognized():
    reason = _xsd.schema_element_gap(_AMMO_MSG)
    assert reason and "create_ship" in reason
    assert "debug.txt" in reason, "an entry must carry its engine evidence"


def test_an_unknown_element_is_NOT_excused():
    """The whole risk of an allowlist is becoming a place real breaks hide.
    A different element, and the same element in a different parent context,
    must both still gate."""
    other = ("Element 'no_such_action': This element is not expected. "
             "Expected is one of ( orientation, position, safepos, rotation ).")
    assert _xsd.schema_element_gap(other) is None
    # same element, different expected-set => different parent => not excused
    elsewhere = ("Element 'ammunition': This element is not expected. "
                 "Expected is one of ( alpha, beta ).")
    assert _xsd.schema_element_gap(elsewhere) is None
    # a required-attr message is a different class entirely
    assert _xsd.schema_element_gap(
        "Element 'find_ship': The attribute 'space' is required but missing.") is None


def test_gap_is_reported_as_advisory_not_dropped(tmp_path, monkeypatch):
    """Demoted, never hidden -- and it must say why."""
    report = _check.Report()
    monkeypatch.setattr(_xsd, "validate_mod",
                        lambda *a, **k: ([_xsd.XsdFinding("md/x.xml", 32, _AMMO_MSG)], 1, 0))
    _check.check_xsd(tmp_path, _merge.Config(reference=tmp_path), report)
    ammo = [f for f in report.findings if "ammunition" in f.message]
    assert len(ammo) == 1
    assert ammo[0].severity == "info"
    assert ammo[0].category == "xsd-schema-gap"
    assert "create_ship" in ammo[0].message      # the reason travels with it


def test_a_real_removed_element_still_gates(tmp_path, monkeypatch):
    """Both sides asserted: the demotion must not have opened the floodgates."""
    msg = ("Element 'gone_in_9': This element is not expected. "
           "Expected is one of ( orientation, position ).")
    report = _check.Report()
    monkeypatch.setattr(_xsd, "validate_mod",
                        lambda *a, **k: ([_xsd.XsdFinding("md/x.xml", 1, msg)], 1, 0))
    _check.check_xsd(tmp_path, _merge.Config(reference=tmp_path), report)
    assert [f.severity for f in report.findings if "gone_in_9" in f.message] == ["error"]


# --------------------------------------------------------------------------
# Fast required-attribute path (no schema compilation).
#
# Compiling md.xsd costs 98.5s and aiscripts.xsd 122s, and the compiled object
# is not picklable so it cannot be cached between runs. Measured 2026-08-09 the
# cost is NOT "they include the 40k-line common.xsd" (that compiles in 0.03s) --
# it is the recursive `actions` content model. But the gating class,
# "attribute X is required but missing", is a flat fact per element and needs
# none of that: extracting it by plain parsing takes ~0.05s.
#
# Equivalence with libxml2 is proven corpus-wide by gates/xsd_fast_parity.py.
# These tests pin the extractor's own rules.
# --------------------------------------------------------------------------

_SCHEMA_HEAD = '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'


def _lib(tmp_path, body: str, name: str = "probe.xsd") -> str:
    """Write a one-file schema and return ITS PATH.

    The table is scoped to the schema a document declares (plus its includes),
    not to a fixed set of files -- see `_schema_closure`.
    """
    lib = tmp_path / "libraries"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / name).write_text(f"{_SCHEMA_HEAD}{body}</xs:schema>", encoding="utf-8")
    _xsd.required_attr_table.cache_clear()
    return str(lib / name)


def test_required_attr_inline_and_via_attributegroup(tmp_path):
    lib = _lib(tmp_path, '''
      <xs:attributeGroup name="grp">
        <xs:attribute name="fromgroup" use="required"/>
      </xs:attributeGroup>
      <xs:element name="probe">
        <xs:complexType>
          <xs:attribute name="inline" use="required"/>
          <xs:attribute name="optional"/>
          <xs:attributeGroup ref="grp"/>
        </xs:complexType>
      </xs:element>''')
    assert _xsd.required_attr_table(lib)["probe"] == ("fromgroup", "inline")


def test_required_attr_via_extension_base(tmp_path):
    """The spike missed this hop; only under-reporting, but parity demands it."""
    lib = _lib(tmp_path, '''
      <xs:complexType name="basetype">
        <xs:attribute name="frombase" use="required"/>
      </xs:complexType>
      <xs:element name="probe">
        <xs:complexType>
          <xs:complexContent>
            <xs:extension base="basetype">
              <xs:attribute name="own" use="required"/>
            </xs:extension>
          </xs:complexContent>
        </xs:complexType>
      </xs:element>''')
    assert _xsd.required_attr_table(lib)["probe"] == ("frombase", "own")


def test_attributegroup_cycle_does_not_hang(tmp_path):
    lib = _lib(tmp_path, '''
      <xs:attributeGroup name="a">
        <xs:attribute name="fa" use="required"/><xs:attributeGroup ref="b"/>
      </xs:attributeGroup>
      <xs:attributeGroup name="b">
        <xs:attribute name="fb" use="required"/><xs:attributeGroup ref="a"/>
      </xs:attributeGroup>
      <xs:element name="probe">
        <xs:complexType><xs:attributeGroup ref="a"/></xs:complexType>
      </xs:element>''')
    assert _xsd.required_attr_table(lib)["probe"] == ("fa", "fb")


def test_nested_child_requirements_are_not_attributed_to_the_parent(tmp_path):
    """A plain node.iter() walks into CHILD element declarations and would invent
    requirements on the parent -- i.e. false gating ERRORs, the one outcome this
    path must never produce."""
    lib = _lib(tmp_path, '''
      <xs:element name="parent">
        <xs:complexType>
          <xs:sequence>
            <xs:element name="child">
              <xs:complexType><xs:attribute name="childreq" use="required"/></xs:complexType>
            </xs:element>
          </xs:sequence>
        </xs:complexType>
      </xs:element>''')
    table = _xsd.required_attr_table(lib)
    assert "parent" not in table          # parent itself requires nothing
    assert table["child"] == ("childreq",)


def test_conflicting_declarations_use_the_intersection(tmp_path):
    """24 real element names are declared with different required sets. Taking the
    intersection means such a name can only under-report, never false-positive."""
    lib = _lib(tmp_path, '''
      <xs:element name="dual">
        <xs:complexType>
          <xs:attribute name="both" use="required"/>
          <xs:attribute name="onlyhere" use="required"/>
        </xs:complexType>
      </xs:element>
      <xs:element name="dual">
        <xs:complexType><xs:attribute name="both" use="required"/></xs:complexType>
      </xs:element>''')
    assert _xsd.required_attr_table(lib)["dual"] == ("both",)
    assert _xsd.ambiguous_element_names(lib) == 1


def test_a_diff_document_yields_no_required_attr_findings(tmp_path):
    """Regression: the first parity run produced 226 false positives by walking
    <diff> files and matching their `<replace sel=...>` ops against the schema's
    unrelated `replace` element. libxml2 never validates a diff either."""
    from lxml import etree
    lib = _lib(tmp_path, '''
      <xs:element name="replace">
        <xs:complexType><xs:attribute name="string" use="required"/></xs:complexType>
      </xs:element>''', name="md.xsd")
    diff = etree.fromstring('<diff><replace sel="//x/@y">1</replace></diff>')
    # No <diff> root in ROOT_TO_SCHEMA and no xsi declaration -> no schema -> no findings.
    assert _xsd.required_attr_findings(diff, "md/x.xml", Path(lib).parent) == []


def test_findings_message_matches_libxml2_wording(tmp_path):
    """Byte-identical wording is what lets the two paths de-duplicate and lets the
    parity gate compare them as sets."""
    from lxml import etree
    lib = _lib(tmp_path, '''
      <xs:element name="mdscript">
        <xs:complexType><xs:sequence>
          <xs:element name="find_ship">
            <xs:complexType><xs:attribute name="space" use="required"/></xs:complexType>
          </xs:element>
        </xs:sequence></xs:complexType>
      </xs:element>''', name="md.xsd")
    doc = etree.fromstring('<mdscript name="x"><find_ship name="$s"/></mdscript>')
    got = _xsd.required_attr_findings(doc, "md/x.xml", Path(lib).parent)
    assert len(got) == 1
    assert got[0].message == (
        "Element 'find_ship': The attribute 'space' is required but missing.")
    assert "is required but missing" in got[0].message   # the gating classifier's key
