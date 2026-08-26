r"""W3.1 — schema-validate the EFFECTIVE merged tree for data files, differentially.

Every number in this file was measured over the 102 installed non-DLC mods on
2026-07-29 BEFORE the check was written, and the implementation was then required to
reproduce it. That order matters: a rule tuned until its own output looks clean
proves nothing.

The measurement is also what shaped the design, twice:

1. **Absolute validation cannot ship.** Egosoft's own base+DLC data fails Egosoft's
   own bundled schemas — 66 errors across 6 files. Hence `introduced`.
2. **Multiset differencing cannot ship either.** The first implementation credited a
   mod for each of its own copies of a construct, which flagged 31 entries in
   `ebi_pirate_chaos_conflict` and 15 in `vro` purely for following vanilla's idiom.
   Vanilla exhibiting a construct IS the evidence the engine tolerates it.

Both are pinned below, because both would silently come back as an "optimisation".
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from x4validate import _check, _merge, _xsd


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- the two differencing rules -------------------------------------------------

def test_a_message_the_baseline_already_has_is_not_the_mods_fault():
    """The 66-vanilla-errors case. Without this the check opens with false positives."""
    base = ["Element 'category': content not allowed", "Element 'limits': not expected"]
    assert _xsd.introduced(base, list(base)) == []


def test_repeating_a_vanilla_construct_is_not_a_finding():
    """MULTISET REGRESSION PIN.

    Measured: counting per-copy produced 50 findings whose entire content was
    "this mod added more entries in the same shape vanilla itself uses".
    """
    base = ["Element 'category': content not allowed"]
    with_mod = base + ["Element 'category': content not allowed"] * 30
    assert _xsd.introduced(base, with_mod) == [], (
        "vanilla already exhibits this construct, so the engine tolerates it; "
        "a mod reusing it 30 more times is not 30 findings")


def test_a_genuinely_new_message_survives():
    """The other side — differencing must not be a way of reporting nothing."""
    base = ["Element 'category': content not allowed"]
    got = _xsd.introduced(base, base + ["Element 'filter': This element is not expected."])
    assert got == ["Element 'filter': This element is not expected."]


def test_the_four_known_real_defects_carry_their_value_in_the_message():
    """Why set-differencing is safe for the real findings, stated as a property.

    Each real defect's message embeds the offending value, so it cannot collide
    with a baseline message about a different value.
    """
    base = ["Element 'set', attribute 'race': [facet 'enumeration'] "
            "The value 'argon' is not an element of the set {a}"]
    new = ["Element 'set', attribute 'race': [facet 'enumeration'] "
           "The value 'central' is not an element of the set {a}"]
    assert _xsd.introduced(base, new) == new


# --- eligibility ----------------------------------------------------------------

def test_script_dirs_are_left_to_the_file_by_file_check():
    assert not _xsd.eligible("md/foo.xml")
    assert not _xsd.eligible("aiscripts/foo.xml")
    assert not _xsd.eligible("t/0001.xml")
    assert _xsd.eligible("libraries/jobs.xml")


def test_a_cross_mod_nested_script_is_also_excluded():
    r"""NESTED-PATH PIN.

    `<mymod>/extensions/<target>/md/foo.xml` does not START with `md/`. A prefix
    test let 5 real MD scripts through (4 `vro`, 1 `kuertee_emergent_missions`) to
    be validated against md.xsd — double-covered and stricter than the engine.
    """
    assert not _xsd.eligible("extensions/ego_dlc_split/md/story_split.xml")
    assert not _xsd.eligible(r"extensions\ego_dlc_split\aiscripts\x.xml")
    assert _xsd.eligible("extensions/ego_dlc_boron/libraries/rooms.xml"), \
        "a nested DATA file is still eligible — only the script dirs are excluded"


# --- open lookups ---------------------------------------------------------------

_ENUM_MSG = ("Element 'set', attribute 'race': [facet 'enumeration'] "
             "The value '{}' is not an element of the set {{argon, xenon}}")


def test_a_mod_defined_race_is_suppressed():
    """`xenon_backup` defines `tfdrones` in its own libraries/races.xml diff."""
    assert _xsd.open_lookup_ok(_ENUM_MSG.format("tfdrones"), {"race": {"tfdrones"}})


def test_a_race_nothing_defines_is_still_reported():
    """`cpsdo_faction` uses race='central'; the effective race list has 10 entries
    and 'central' is not one. Same message shape, opposite answer — which is the
    whole reason the XSD list alone cannot decide."""
    assert not _xsd.open_lookup_ok(_ENUM_MSG.format("central"), {"race": {"tfdrones"}})


def test_a_closed_enum_is_never_suppressed():
    """Only race/faction attributes are open. `station type='fortress'` is not a
    lookup a mod can extend by defining something, so it must not be waved through."""
    msg = ("Element 'station', attribute 'type': [facet 'enumeration'] "
           "The value 'fortress' is not an element of the set {shipyard}")
    assert not _xsd.open_lookup_ok(msg, {"race": {"fortress"}, "faction": {"fortress"}})


def test_a_non_enumeration_message_is_never_suppressed():
    assert not _xsd.open_lookup_ok("Element 'filter': This element is not expected.", {})


# --- an unbundled schema must be a SKIP, never silence ---------------------------

def test_an_unbundled_schema_is_reported_not_swallowed(tmp_path):
    """30 real cases (`coreaddon.xsd`) plus `shadergl.xsd`. A file we could not
    check must never be indistinguishable from a file we checked and liked."""
    root = etree.fromstring(
        '<x xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="nope.xsd"/>')
    path, why = _xsd.schema_of(root, tmp_path)
    assert path is None and why and "nope.xsd" in why


def test_no_declared_schema_is_not_a_finding(tmp_path):
    """Macros, components and libraries/wares.xml declare none. Silence is correct
    here — there is nothing to check against, and no coverage was lost."""
    assert _xsd.schema_of(etree.fromstring("<x/>"), tmp_path) == (None, None)


# --- end-to-end wiring ----------------------------------------------------------
#
# The mechanism tests above all stay green if `check_effective_schema` is never
# called. W1 proved that the hard way: reverting one wiring line in validate() left
# 226 mechanism tests passing while the bug was fully restored.

_XSD = """<?xml version="1.0" encoding="utf-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="things">
    <xs:complexType><xs:sequence>
      <xs:element name="thing" minOccurs="0" maxOccurs="unbounded">
        <xs:complexType>
          <xs:sequence><xs:element name="production" minOccurs="0"/></xs:sequence>
          <xs:attribute name="id" use="required"/>
          <xs:attribute name="race">
            <xs:simpleType><xs:restriction base="xs:string">
              <xs:enumeration value="argon"/>
            </xs:restriction></xs:simpleType>
          </xs:attribute>
          <xs:attribute name="tag">
            <xs:simpleType><xs:restriction base="xs:string">
              <xs:pattern value="ego_.+"/>
            </xs:restriction></xs:simpleType>
          </xs:attribute>
        </xs:complexType>
      </xs:element>
    </xs:sequence></xs:complexType>
  </xs:element>
</xs:schema>
"""

_BASE = ('<things xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
         'xsi:noNamespaceSchemaLocation="things.xsd">'
         '<thing id="a"><production/></thing></things>')


def _world(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "libraries" / "things.xsd", _XSD)
    _write(ref / "libraries" / "things.xml", _BASE)
    _write(ref / "libraries" / "races.xml", "<races><race id='argon'/></races>")
    _write(ref / "libraries" / "factions.xml", "<factions/>")
    _write(ref / "index" / "macros.xml", "<index/>")
    # reference_ready() gates the whole of validate() on this file existing — it is
    # always present in the real base game, so its absence means an empty tree.
    _write(ref / "libraries" / "wares.xml", "<wares/>")
    return ref, _merge.Config(reference=ref, include_packed_dlc=False)


def test_a_diff_that_keeps_the_document_valid_reports_nothing(tmp_path):
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b'><production/></thing></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    assert report.findings == []
    assert any("1 merged data file" in n for n in report.notes), \
        "a check that ran must say so, or 'no findings' cannot be told from 'never ran'"


def test_a_diff_that_breaks_the_merged_document_gates(tmp_path):
    """The `mlog_deadair_eco_no_da_wares` case in miniature: the patch itself is
    well-formed and its selector matches; only the MERGED document is broken. No
    other check in this package can see that."""
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel=\"/things/thing[@id='a']\">"
           "<unexpected/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    errs = [f for f in report.findings if f.severity == "error"]
    assert errs and "unexpected" in errs[0].message
    assert errs[0].vpath == "libraries/things.xml"


def test_a_facet_failure_is_advisory_not_a_gate(tmp_path):
    """The bundled XSDs lag the engine on value facets, so those inform, never gate.

    RE-POINTED for F14 (2026-08-02): this test used `race='klingon'` — an
    open-lookup value defined nowhere, which is exactly what F14 now GATES. The
    still-advisory class is a pattern facet (the `ego_.+` naming convention every
    third-party UI mod harmlessly violates), so that is what this test pins now;
    the klingon fixture moved to `test_an_undefined_open_lookup_value_gates`.
    """
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b' tag='not_ego_prefixed'/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    assert not [f for f in report.findings if f.severity == "error"]
    assert [f for f in report.findings if f.category == "schema-strict"]


# --- F7 + F14: what has no excuse, gates (measured 2026-08-02: 15 findings move,
# --- all individually verified real — see gates/schema_sweep.py) -----------------

def test_an_undefined_open_lookup_value_gates(tmp_path):
    """F14: race='klingon' with NO definition anywhere — not the XSD floor, not
    the effective tree. 'The schema lags the engine' cannot excuse a value that
    nothing defines. The real instance is cpsdo_faction's race='central' x7."""
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b' race='klingon'/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    errs = [f for f in report.findings if f.severity == "error"]
    assert errs and errs[0].category == "schema-enum-undefined"


def test_an_attr_vanilla_never_uses_gates(tmp_path):
    """F7: attribute unknown to the schema AND absent from vanilla at
    (element, attribute) granularity. Real instances: category/@matchextension
    (a real attribute on the WRONG element — vanilla's 140 uses are all on
    <location>) and element/@forkmaterial (invented by VRO, read by nothing)."""
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b' bogusattr='1'/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    errs = [f for f in report.findings if f.severity == "error"]
    assert errs and errs[0].category == "schema-dead-attr"


def test_an_attr_vanilla_uses_elsewhere_stays_advisory(tmp_path):
    """The other half of F7's pair check: vanilla uses (thing, legacyattr) in a
    DIFFERENT file, so the schema plausibly lags the engine — advisory. This is
    also why the check is per-PAIR and cross-file: per-file differencing alone
    cannot see a use in another document."""
    ref, cfg = _world(tmp_path)
    # vanilla usage of the pair, in a file the mod does not touch
    _write(ref / "libraries" / "other.xml", "<other><thing legacyattr='x'/></other>")
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b' legacyattr='1'/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    assert not [f for f in report.findings if f.severity == "error"]
    assert [f for f in report.findings if f.category == "schema-strict"]


def test_md_side_dead_attr_is_categorized_but_never_gates(tmp_path, monkeypatch):
    """ATD-PROTECTION PIN (audit F8). The same F7 rule on the MD side must change
    the CATEGORY only, never the severity: MD attributes can be spawn-time engine
    features no static pass or debug.txt can settle, and the user explicitly left
    kuertee_atd's four unresolved. If this test fails because check_xsd started
    emitting errors for attribute-not-allowed, that is a decision to re-litigate
    with the user, not a code cleanup."""
    from x4validate import _xsd
    ref, cfg = _world(tmp_path)
    findings = [
        _xsd.XsdFinding("md/x.xml", 1,
                        "Element 'create_ship', attribute 'position': "
                        "The attribute 'position' is not allowed."),
        _xsd.XsdFinding("md/x.xml", 2,
                        "Element 'thing', attribute 'race': [facet 'enumeration'] "
                        "The value 'z' is not an element of the set {'argon'}."),
    ]
    monkeypatch.setattr(_xsd, "validate_mod", lambda mod_dir, config: (findings, 1, 0))
    report = _check.Report()
    _check.check_xsd(tmp_path / "mod", cfg, report)
    assert not [f for f in report.findings if f.severity == "error"]
    cats = sorted(f.category for f in report.findings)
    assert cats == ["xsd-strict", "xsd-unknown-attr"]


def test_a_mod_defined_race_is_suppressed_end_to_end(tmp_path):
    """Union with the EFFECTIVE definitions, not the XSD's vanilla floor —
    the mod adds the race in the same breath as using it."""
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "races.xml",
           "<diff><add sel='/races'><race id='klingon'/></add></diff>")
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b' race='klingon'/></add></diff>")
    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    assert report.findings == []
    assert any("suppressed as mod-defined" in n for n in report.notes), \
        "suppression must be disclosed — a silent one is indistinguishable from a miss"


def test_a_mod_that_validated_SOMETHING_still_says_what_it_SKIPPED(tmp_path):
    """F52. The note used to go silent about skips as soon as it validated one file.

    MEASURED 2026-08-25 on three mods deployed the same day: one correctly said
    "0 validated — 2 declaring no schema", while `Synthetium_Music` said "1
    validated" and stayed silent about its other two eligible files. Attributing a
    `schema_sweep` pairs delta then had to be re-derived by hand.

    The rule this restores is the register's founding one: a step that NARROWS the
    data announces it even when it also succeeded at something.
    """
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    # one file that CAN be schema-checked (things.xsd exists beside things.xml)...
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel='/things'><thing id='b'><production/></thing></add></diff>")
    # ...and one at a base path with no declared schema, which is silently skipped
    _write(mod / "libraries" / "factions.xml",
           "<diff><add sel='/factions'><faction id='x'/></add></diff>")

    report = _check.Report()
    _check.check_effective_schema(mod, cfg, report)
    note = next(n for n in report.notes if n.startswith("effective-schema:"))

    assert "1 merged data file" in note, "the positive half must still be reported"
    assert "declaring no schema" in note, (
        "a file that was NOT checked must be disclosed even though another file "
        "WAS -- silent-on-any-success is the F52 defect")

    # The gate parses this note positionally; the detail must stay a SUFFIX.
    assert note.split()[1] == "1", (
        "gates/schema_sweep.py reads the pair count as note.split()[1] -- moving "
        "the leading tokens would silently break the sweep's totals")


def test_validate_actually_runs_the_check_under_update(tmp_path):
    """WIRING PIN. Everything above passes with the check unreachable from validate()."""
    ref, cfg = _world(tmp_path)
    mod = tmp_path / "mod"
    _write(mod / "libraries" / "things.xml",
           "<diff><add sel=\"/things/thing[@id='a']\"><unexpected/></add></diff>")
    assert not [f for f in _check.validate(mod, cfg).findings if f.category == "schema"], \
        "the effective-schema check is --update only; it must not run on the default path"
    report = _check.validate(mod, cfg, update=True)
    assert [f for f in report.findings if f.category == "schema"], \
        "validate(update=True) must reach check_effective_schema"
