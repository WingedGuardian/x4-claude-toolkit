"""Referencing something the game defines but cannot SELL.

MEASURED 2026-08-28 over the effective tree (125 active mods), and the measurement
is why this check is NARROW:

    indexed macros : 5559
      live          1575  (28.3%)
      deprecated      39  ( 0.7%)     <- this check
      no ware       3945  (71.0%)     <- deliberately NOT checked

⚠ The proposal that reached me was "flag macros with no ware", from a 1-in-5 figure
measured on MISSILES. Corpus-wide that is **71%** and it is the NORMAL state:
`bullet` is 170 of 170 no-ware (weapons reference bullets, nobody sells them),
scenery/story macros 89.5%, `storage` 80.6%, `dock` 78.3%. Shipping it would fire on
3,945 macros that are correctly-by-design and train everyone to ignore the channel.
Doing that half properly needs a per-class expectation model, which is not a join
over indexes already in memory.

`deprecated` is the half that IS clean: 39 macros, every one a missile (21) or a
missile launcher (18) from the pre-rework generic line, each verified by hand before
this shipped.

INFO, never a gate: an author may reference deprecated content deliberately, and
CLAUDE.md's rule is that a check which floods is worse than no check.
"""
from pathlib import Path

from lxml import etree

from x4validate import _refs

WARES = """<wares>
  <ware id="live_ware" tags="equipment">
    <component ref="live_macro"/>
  </ware>
  <ware id="dead_ware" tags="missile deprecated">
    <component ref="dead_macro"/>
  </ware>
  <ware id="old_supplier" tags="deprecated">
    <component ref="both_macro"/>
  </ware>
  <ware id="new_supplier" tags="equipment">
    <component ref="both_macro"/>
  </ware>
  <ware id="no_component" tags="equipment"/>
</wares>"""


def _tree(xml: str):
    return etree.fromstring(xml.encode("utf-8"))


def test_a_macro_whose_only_supplier_is_deprecated_is_reported():
    got = _refs.deprecated_only_macros(_tree(WARES))
    assert "dead_macro" in got
    assert got["dead_macro"] == ["dead_ware"]


def test_a_macro_with_a_LIVE_supplier_too_is_NOT_reported():
    """The falsification twin, and it can ONLY be synthetic: MEASURED on the live
    corpus there are **0** such macros, so real data cannot exercise this clause.
    Without it, `any(deprecated)` and `all(deprecated)` are indistinguishable."""
    got = _refs.deprecated_only_macros(_tree(WARES))
    assert "both_macro" not in got, (
        "a macro still sold by a live ware is obtainable; flagging it would be a "
        "false positive that no real-corpus run could have revealed")


def test_a_live_macro_is_not_reported():
    assert "live_macro" not in _refs.deprecated_only_macros(_tree(WARES))


def test_a_ware_with_no_component_ref_contributes_nothing():
    got = _refs.deprecated_only_macros(_tree(WARES))
    assert all(v for v in got.values()), "an empty supplier list must never be emitted"
    assert len(got) == 1


def test_no_wares_tree_is_an_empty_answer_not_a_crash():
    assert _refs.deprecated_only_macros(None) == {}


def test_finding_references_matches_only_WHOLE_attribute_values():
    """`dead_macro_mk2` is a different macro. A substring match would invent findings."""
    doc = _tree('<root><a ref="dead_macro"/><b ref="dead_macro_mk2"/>'
                '<c ref="live_macro"/><d note="mentions dead_macro in prose"/></root>')
    hits = _refs.unobtainable_refs(doc, {"dead_macro": ["dead_ware"]})
    assert [h.ref for h in hits] == ["dead_macro"]
    assert hits[0].wares == ["dead_ware"]


def test_the_finding_is_INFO_so_it_can_never_gate_a_build(tmp_path):
    """Severity is load-bearing and nothing else pinned it.

    Referencing deprecated content is a fact worth surfacing, not a defect: an author
    may do it deliberately, and the reference DOES resolve. Promoting this to `error`
    would start failing builds on 6 of 126 installed mods (MEASURED) for something
    they may have chosen. Without this test that promotion is a one-word edit no
    other test would notice.
    """
    from x4validate import _check, _merge

    ref = tmp_path / "reference" / "libraries"
    ref.mkdir(parents=True)
    (ref / "wares.xml").write_text(
        '<wares><ware id="dead_ware" tags="missile deprecated">'
        '<component ref="dead_macro"/></ware></wares>', encoding="utf-8")
    mod = tmp_path / "mod"
    (mod / "assets").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="m" version="1"/>', encoding="utf-8")
    (mod / "assets" / "t.xml").write_text(
        '<macros><macro name="t"><ammunition ref="dead_macro"/></macro></macros>',
        encoding="utf-8")

    report = _check.Report()
    _check.check_references(mod, _merge.Config(reference=tmp_path / "reference"), report)

    found = [f for f in report.findings if f.category == "unobtainable"]
    assert len(found) == 1, f"expected exactly 1 unobtainable finding, got {len(found)}"
    assert found[0].severity == "info", (
        f"severity is {found[0].severity!r}; an INFO promoted to error here would gate "
        "builds on deliberate references to deprecated content")
    assert report.errors == [], "this check must contribute no errors"
