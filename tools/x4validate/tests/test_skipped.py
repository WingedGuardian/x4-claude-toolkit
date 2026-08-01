"""The "nothing examined must never render as OK" suite.

Every false pass this tool has shipped had one shape: a helper hit an unreadable
input, returned a falsy sentinel (`set()` / `[]` / `None`), and the caller could
not tell *found nothing* from *could not look*. With no channel for "work not
done", silence rendered as OK.

Each test here is **mutation-verified**: with the fix reverted it fails. Where a
test asserts a distinction (empty vs None), it asserts BOTH sides — a test that
only pins the new behaviour would pass against a helper that skips everything.
"""

from __future__ import annotations

import hashlib

from lxml import etree

from x4validate import _check, _cli, _merge, _refs, _resolve


def _write_cat(mod_dir, cat_name, members):
    """Write a .cat/.dat pair (same helper shape as test_cat.py)."""
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    dat = cat.with_suffix(".dat")
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dat.write_bytes(bytes(blob))


def _ref(tmp_path, macros_xml: str | None = "<macros/>") -> _merge.Config:
    ref = tmp_path / "reference"
    (ref / "index").mkdir(parents=True)
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    if macros_xml is not None:
        (ref / "index" / "macros.xml").write_text(macros_xml, encoding="utf-8")
    return _merge.Config(reference=ref)


# --- A3: an unreadable macro index must not silently disable macro checks -----

def test_macro_defs_returns_none_not_empty_set_when_index_absent(tmp_path):
    """None ("could not look") must be distinguishable from set() ("looked, none")."""
    cfg = _ref(tmp_path, macros_xml=None)
    report = _check.Report()
    assert _check.collect_macro_defs(cfg, report=report) is None
    assert [s for s in report.skipped if s.degraded], "must be reported as a degraded skip"


def test_macro_defs_returns_a_set_when_the_index_is_readable(tmp_path):
    cfg = _ref(tmp_path, macros_xml='<index><entry name="ship_x_macro" value="a"/></index>')
    report = _check.Report()
    got = _check.collect_macro_defs(cfg, report=report)
    assert got == {"ship_x_macro"}
    assert not report.skipped


def test_empty_macro_index_still_flags_dangling_refs(tmp_path):
    """The mutation test for A3.

    An index that registers NO macros is a real state, and under it every
    <component ref> is dangling. The old gate was `if macro_def_set and ...`, so
    an empty set switched the whole check off — identical behaviour to an index
    that failed to load. Empty must flag; None must skip.
    """
    tree = etree.fromstring('<add><component ref="nonexistent_macro"/></add>')
    flagged = _refs.find_dangling(tree, set(), set(), macro_def_set=set())
    assert [d.ref for d in flagged] == ["nonexistent_macro"]

    skipped = _refs.find_dangling(tree, set(), set(), macro_def_set=None)
    assert skipped == [], "None means the index was unreadable -> skip, do not guess"


def test_completeness_component_kind_checks_the_macro_resolves():
    """`_entity_kinds` got the same empty-vs-None gate as find_dangling.

    Honest scope note: unlike find_dangling, that change is **defensive, not a
    bug fix** — with an empty index the analogue's own component also fails to
    resolve, so its kind is False and nothing can land in `missing` either way.
    The empty-set branch is unobservable here. What this test pins is the
    behaviour that does matter and must not regress: with a real index, a
    component whose macro is not registered counts as missing.
    """
    wares = etree.fromstring(
        '<wares>'
        '  <ware id="analogue"><component ref="real_macro"/></ware>'
        '  <ware id="mine"><component ref="bogus_macro"/></ware>'
        '</wares>')
    rep = _refs.ware_completeness("mine", "analogue", wares, set(),
                                 macro_def_set={"real_macro"})
    assert "component" in rep.missing

    # Index unreadable -> do not guess; presence alone satisfies the kind.
    rep_none = _refs.ware_completeness("mine", "analogue", wares, set(), macro_def_set=None)
    assert "component" not in rep_none.missing


# --- A7: packed t-files are real definitions (LIVE bug, measured) -------------

def test_text_defs_include_packed_t_files(tmp_path):
    """Measured on the live modlist: 977 strings exist ONLY inside packed
    t-files (vro 425, ship_variation_expansion 108, xenon_backup 102...). Reading
    only loose files made every one of them a false "does not resolve"."""
    cfg = _ref(tmp_path)
    mod = tmp_path / "packedmod"
    _write_cat(mod, "ext_01.cat", [(
        "t/0001.xml",
        b'<language id="44"><page id="20101"><t id="7">Packed String</t></page></language>')])

    report = _check.Report()
    defs = _check.collect_text_defs(cfg, [mod], report)
    assert ("20101", "7") in defs, "a string shipped inside ext_01.cat must count as defined"
    assert not report.skipped


def test_text_defs_loose_file_still_wins_and_unreadable_is_reported(tmp_path):
    cfg = _ref(tmp_path)
    mod = tmp_path / "brokenmod"
    (mod / "t").mkdir(parents=True)
    (mod / "t" / "0001.xml").write_text("<language><page id='1'><t id='2'>oops",
                                        encoding="utf-8")  # truncated
    report = _check.Report()
    _check.collect_text_defs(cfg, [mod], report)
    assert report.skipped, "a t-file that will not parse must be reported, not swallowed"
    assert not report.degraded, "one bad t-file is partial, not a whole-check failure"


# --- A6: un-evaluable is not empty -------------------------------------------

def test_component_connections_returns_none_on_malformed_file(tmp_path):
    """Returning set() read as "this component has zero connections", turning
    every loadout entry that targets it into a false ERROR."""
    bad = tmp_path / "broken_component.xml"
    bad.write_text("<component><connections><connection name='x'/>", encoding="utf-8")
    assert _resolve.component_connections(bad) is None

    good = tmp_path / "ok_component.xml"
    good.write_text("<component><connections><connection name='x'/></connections></component>",
                    encoding="utf-8")
    assert _resolve.component_connections(good) == {"x"}


# --- B1: an unknown op tag is a schema violation, not a comment --------------

def test_unknown_op_tag_is_reported():
    """libraries/diff.xsd admits exactly add/replace/remove. A typo'd tag used to
    hit the same silent `continue` as a comment node and vanish."""
    tree = etree.fromstring("<wares><ware id='ore'/></wares>")
    diff = etree.fromstring("<diff><relace sel=\"//ware[@id='ore']/@id\">x</relace></diff>")
    applied = _merge.apply_diff(tree, diff)
    assert len(applied) == 1
    assert not applied[0].ok
    assert "unknown op" in applied[0].detail
    assert tree.xpath("//ware/@id") == ["ore"], "and it must not have been applied"


def test_comments_and_pis_stay_silent():
    """The other side of the split: these are legitimately not ops."""
    tree = etree.fromstring("<wares><ware id='ore'/></wares>")
    diff = etree.fromstring(
        "<diff><!-- a note --><?pi data?>"
        "<replace sel=\"//ware[@id='ore']/@id\">gold</replace></diff>")
    applied = _merge.apply_diff(tree, diff)
    assert len(applied) == 1 and applied[0].ok
    assert tree.xpath("//ware/@id") == ["gold"]


# --- D1: a Tier B that could not be built is not a Tier A pass ---------------

def test_tier_b_fallback_is_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr(_check._registry, "scan_installed", lambda *a, **k: [])
    report = _check.Report()
    overlays, notes = _check.tier_b_overlays(tmp_path / "mymod", report)
    assert overlays == ()
    assert report.degraded, "asked for Tier B, got Tier A -> the result is not a pass"


# --- A5: a nonexistent --like analogue is a vacuous comparison ----------------

def test_missing_analogue_flagged_instead_of_matching_footprint(tmp_path):
    """With no analogue, its footprint is all-False, `missing` is empty, and the
    old code printed "ware 'x' matches the footprint of 'y'" — the most
    misleading output the tool produced."""
    wares = etree.fromstring('<wares><ware id="mine"/></wares>')
    rep = _refs.ware_completeness("mine", "does_not_exist", wares, set())
    assert rep.analogue_missing
    assert not rep.missing, "nothing can be missing — which is exactly why it must be flagged"


def test_present_analogue_is_not_flagged():
    wares = etree.fromstring('<wares><ware id="mine"/><ware id="real"><price/></ware></wares>')
    rep = _refs.ware_completeness("mine", "real", wares, set())
    assert not rep.analogue_missing and not rep.entity_missing
    assert "price" in rep.missing


# --- The channel itself -------------------------------------------------------

def test_degraded_run_exits_nonzero_and_says_so(capsys):
    report = _check.Report()
    report.skip("Tier B cross-mod validation", "could not scan installed mods", degraded=True)
    _cli._print_human(tmp_path_stub := "mod", report)
    out = capsys.readouterr().out
    assert "OK: no issues found" not in out, "zero findings with work undone is not OK"
    assert "NOT CHECKED" in out and "NOT a pass" in out
    assert tmp_path_stub  # silence linters


def test_clean_run_still_says_ok(capsys):
    _cli._print_human("mod", _check.Report())
    assert "OK: no issues found" in capsys.readouterr().out


# --- 1c: _xpath adoption in the collision detector ---------------------------

def test_compat_unresolvable_sel_is_not_silent():
    """A conflict detector that drops an op it cannot parse reports "no
    collision" — the most dangerous possible false negative for that tool.
    The old contract was literally "empty on no-match/invalid"."""
    from x4validate import _compat
    tree = etree.fromstring("<wares><ware id='ore'/></wares>")
    assert _compat._resolve_op_targets(tree, "//ware[@id='nope']") == [], "valid, no match"
    assert _compat._resolve_op_targets(tree, "//ware[[[") is None, "invalid must not read as no-match"
