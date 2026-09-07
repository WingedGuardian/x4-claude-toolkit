"""Tests for _stats.py — advisory numeric comparison."""

from __future__ import annotations

import ast

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
    # effective_wares now returns the TREE alongside the dict: candidate_wares has to
    # resolve a `sel=` against something, and rebuilding it there would merge the
    # whole corpus twice.
    eff, eff_tree = _stats.effective_wares(ext, cfg)
    assert eff_tree is not None
    assert "ore" in eff and "newware" in eff
    assert eff["newware"].price_avg == 999.0


# --------------------------------------------------------------------------
# Ungrouped wares must never be compared as if they were peers.
#
# Real incident (2026-07-26): group="" was used as a real dict key, so all 1386
# ungrouped wares in the game (paint mods, cosmetic props) were bucketed together.
# A candidate priced 1 was reported "~0th percentile" against a pool with median
# 51,696 — a comparison as meaningless as it looks.
# --------------------------------------------------------------------------

def test_ungrouped_ware_is_not_comparable_not_measured_against_junk_bucket():
    candidate = {"cpsdo_paintmod_01": _stats.Ware(
        id="cpsdo_paintmod_01", group="", transport="", volume=0, tags="",
        price_avg=1.0, price_min=1.0, price_max=1.0)}
    effective = {
        "cpsdo_paintmod_01": candidate["cpsdo_paintmod_01"],
        # another ungrouped ware with a wildly different price — must NEVER become a peer
        "some_other_cosmetic": _stats.Ware(
            id="some_other_cosmetic", group="", transport="", volume=0, tags="",
            price_avg=450_000_000.0, price_min=1.0, price_max=1.0),
        "ore": _stats.Ware(id="ore", group="minerals", transport="", volume=0, tags="",
                           price_avg=500.0, price_min=1.0, price_max=1.0),
    }
    out = _stats.compare_wares(candidate, effective)
    assert len(out) == 1
    cmp = out[0]
    assert cmp.peer_count == 0
    assert "not comparable" in cmp.note
    assert "percentile" not in cmp.note


def test_grouped_ware_comparison_still_works():
    candidate = {"newweap": _stats.Ware(id="newweap", group="weapons", transport="",
                                    volume=0, tags="", price_avg=1000.0,
                                    price_min=1.0, price_max=1.0)}
    effective = {
        "newweap": candidate["newweap"],
        "w1": _stats.Ware(id="w1", group="weapons", transport="", volume=0, tags="",
                          price_avg=500.0, price_min=1.0, price_max=1.0),
        "w2": _stats.Ware(id="w2", group="weapons", transport="", volume=0, tags="",
                          price_avg=2000.0, price_min=1.0, price_max=1.0),
    }
    out = _stats.compare_wares(candidate, effective)
    assert out[0].peer_count == 2
    assert "percentile" in out[0].note


# --- an ABSENCE and a NON-ANSWER must not print the same sentence -------------
#
# `candidate_wares` reads a ware only from a <ware> ELEMENT, so `<replace sel=...>`
# and `<remove sel=...>` -- the DEFAULT X4 patch idiom, and the example in the
# project's own CLAUDE.md -- are invisible to it. `render_wares` then printed
# "candidate introduces/changes no wares." over them.
#
# MEASURED over the live install: 125 mods scanned, 37 supply libraries/wares.xml,
# 5 reported "no wares", all 5 wrong. The largest hid 1,443 ops (1,067 replace,
# 132 add, 244 remove) -- a whole-economy rewrite. Two skills route the balance
# question through this output.
#
# The wares are NOT recovered here: attributing a sel= to a ware needs the selector
# resolved against the merged tree, which is a feature and is recorded separately.
# What is fixed is that a non-answer stops wearing the grammar of an absence.

_REPLACE_ONLY = (
    '<diff>'
    '<replace sel="//ware[@id=\'ore\']/@price_average">500</replace>'
    '<replace sel="//ware[@id=\'silicon\']/@price_average">600</replace>'
    '<remove sel="//ware[@id=\'energycells\']"/>'
    '</diff>')


def test_replace_and_remove_ops_are_COUNTED_even_though_unattributable(tmp_path):
    """WITHOUT a base_tree -- the degraded path, and it is deliberately unchanged.

    Resolving a `sel=` needs a tree to resolve it against. A caller that has none
    still gets an honest partial answer ("N ops I could not attribute") rather than
    a wrong one ("changes no wares"). The attributed path is tested below.
    """
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml", _REPLACE_ONLY)
    assert _stats.candidate_wares(cand) == {}, \
        "premise of this test: with no tree, these ops are invisible"
    assert _stats.unattributed_ware_ops(cand) == 3


def test_a_mod_that_only_REPLACES_is_not_reported_as_changing_nothing(tmp_path):
    """The defect, at the surface the user actually reads."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml", _REPLACE_ONLY)
    out = _stats.render_wares(
        _stats.compare_wares(_stats.candidate_wares(cand), {}),
        _stats.unattributed_ware_ops(cand))
    assert "introduces/changes no wares" not in out, (
        "a mod with 3 ops on libraries/wares.xml was reported as changing nothing")
    assert "NOT CHECKED" in out
    assert "3 op(s)" in out


def test_an_ADDED_ware_is_still_attributed_and_not_counted_as_unchecked(tmp_path):
    """The falsification twin. A counter that called everything unattributable
    would pass the two tests above while making the working case report NOT
    CHECKED alongside its own results."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml",
       '<diff><add sel="/wares">'
       '<ware id="new1" group="weapons"><price average="500"/></ware>'
       '</add></diff>')
    assert set(_stats.candidate_wares(cand)) == {"new1"}
    assert _stats.unattributed_ware_ops(cand) == 0


def test_a_mod_with_NO_wares_file_still_says_it_changes_no_wares(tmp_path):
    """The other twin, and the reason the two messages stay distinct: a mod that
    genuinely touches no wares must keep saying so. Turning every empty result
    into NOT CHECKED would be the same conflation in the opposite direction."""
    cand = tmp_path / "mod"
    _w(cand / "content.xml", '<content id="m"/>')
    assert _stats.unattributed_ware_ops(cand) == 0
    out = _stats.render_wares([], _stats.unattributed_ware_ops(cand))
    assert out == "candidate introduces/changes no wares."


def test_a_MIXED_diff_counts_only_the_unattributable_ops(tmp_path):
    """Both shapes in one file: the <add>ed ware is found, the two <replace> ops
    are counted. A counter that returned the op TOTAL would say 3 here."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml",
       '<diff>'
       '<add sel="/wares"><ware id="new1" group="weapons">'
       '<price average="500"/></ware></add>'
       '<replace sel="//ware[@id=\'ore\']/@price_average">500</replace>'
       '<remove sel="//ware[@id=\'silicon\']"/>'
       '</diff>')
    assert set(_stats.candidate_wares(cand)) == {"new1"}
    assert _stats.unattributed_ware_ops(cand) == 2


# ------------------------------------------- RESERVED-A: sel= resolved to its ware
# `candidate_wares` used to find a ware only when a <ware> ELEMENT was present as an
# op payload, so it saw nothing for the DEFAULT X4 idiom -- the one in this project's
# own CLAUDE.md. MEASURED over the live install: of 37 mods supplying
# libraries/wares.xml, 5 reported "introduces/changes no wares" and all five zeros
# were wrong; the largest hid 1,443 ops. With attribution: zeros 5 -> 1, unattributed
# ops 3,414 -> 190, and mlog_deadair_eco_no_da_wares went 0 -> 350 wares.

SQ = chr(39)


def _base_tree():
    return etree.fromstring(
        '<wares>'
        '<ware id="ore" group="minerals"><price average="100"/></ware>'
        '<ware id="silicon" group="minerals"><price average="200"/></ware>'
        '<ware id="energycells" group="energy"><price average="16"/></ware>'
        '</wares>')


#: Targets `<price average=>`, which is what _ware_from_el actually READS. The older
#: _REPLACE_ONLY fixture targets `@price_average` on the ware -- a shape the parser
#: does not read, so it can prove attribution but not the resulting value.
_REPLACE_PRICES = (
    '<diff>'
    '<replace sel="//ware[@id=' + chr(39) + 'ore' + chr(39) + ']/price/@average">500</replace>'
    '<replace sel="//ware[@id=' + chr(39) + 'silicon' + chr(39) + ']/price/@average">600</replace>'
    '<remove sel="//ware[@id=' + chr(39) + 'energycells' + chr(39) + ']"/>'
    '</diff>')


def test_a_replace_on_an_ATTRIBUTE_is_attributed_to_its_ware(tmp_path):
    """The idiom that was invisible. The ware is named only in the SELECTOR, so no
    amount of reading the op payload can find it."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml", _REPLACE_PRICES)
    got = _stats.candidate_wares(cand, _base_tree())
    # `energycells` is REMOVED by this diff, so it is ATTRIBUTED (it does not count as
    # unattributed below) but has no post-state to compare a price against -- there is
    # no ware left in the merged tree. Those are two different questions and the split
    # is deliberate: the op is accounted for, and the comparison has nothing to say.
    assert set(got) == {"ore", "silicon"}, got
    assert _stats.unattributed_ware_ops(cand, _base_tree()) == 0


def test_the_attributed_ware_carries_the_value_the_MOD_LEAVES(tmp_path):
    """Read back out of the MUTATED copy, because the price comparison is about the
    value after the candidate applies, not the value it patched over."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml", _REPLACE_PRICES)
    got = _stats.candidate_wares(cand, _base_tree())
    assert got["ore"].price_avg == 500.0
    assert got["silicon"].price_avg == 600.0


def test_a_REMOVE_of_a_whole_ware_is_attributed_before_it_is_detached():
    """A <remove> whose target CARRIES @id. Kept, but it does NOT test the ordering:
    _id_key returns on its first iteration and never climbs, so it passes whether the
    capture happens before or after the helper. The real ordering test is below."""
    ops = _merge.apply_diff(
        _base_tree(),
        etree.fromstring('<diff><remove sel="//ware[@id=' + SQ + 'energycells'
                         + SQ + ']"/></diff>'),
        want_targets=True)
    assert ops[0].ok
    assert ops[0].target_keys == (("ware", "energycells"),)


def test_a_target_WITHOUT_its_own_id_is_captured_BEFORE_the_helper_detaches_it():
    """THE ordering test, and the one the release reviewer showed was missing.

    `_do_remove` detaches its target; a detached node has no ancestor chain left to
    climb, so `_id_key` must run BEFORE the helper. The test above cannot show that,
    because its target has an `@id` of its own.

    MEASURED by the reviewer per op shape: moving the capture after the helpers is
    load-bearing for 3 of 6 -- exactly the shapes whose target lacks an id and gets
    detached. These are the live shapes: one real mod carries 51 `<price>` replaces.
    """
    for sel in ("//ware[@id=" + SQ + "ore" + SQ + "]/price",
                "//ware[@id=" + SQ + "ore" + SQ + "]/production/primary"):
        ops = _merge.apply_diff(
            _base_tree(),
            etree.fromstring('<diff><remove sel="' + sel + '"/></diff>'),
            want_targets=True)
        if not ops[0].ok:
            continue                      # shape absent from the fixture; try the next
        assert ops[0].target_keys == (("ware", "ore"),), (sel, ops[0].target_keys)
        break
    else:
        raise AssertionError("neither id-less remove shape resolved against the fixture")


def test_a_REPLACE_of_an_id_less_element_is_also_captured_before_the_swap():
    """The other detaching helper. `_do_replace` swaps the node out, so an element
    payload replacing an id-less child has the same ordering requirement."""
    ops = _merge.apply_diff(
        _base_tree(),
        etree.fromstring('<diff><replace sel="//ware[@id=' + SQ + 'ore' + SQ
                         + ']/price"><price average="7"/></replace></diff>'),
        want_targets=True)
    assert ops[0].ok
    assert ops[0].target_keys == (("ware", "ore"),), ops[0].target_keys


def test_target_keys_are_EMPTY_unless_asked_for(tmp_path):
    """The opt-in is the point: the corpus-wide store build never asks, so it pays
    nothing. A change that made every merge do this work would be a guard with an
    unwatched second output (gotcha #35)."""
    diff = etree.fromstring(
        '<diff><replace sel="//ware[@id=' + chr(39) + 'ore' + chr(39)
        + ']/price/@average">500</replace></diff>')
    assert _merge.apply_diff(_base_tree(), diff)[0].target_keys == ()
    assert _merge.apply_diff(_base_tree(), diff, want_targets=True)[0].target_keys != ()


def test_an_op_that_the_ENGINE_would_skip_is_NOT_attributed(tmp_path):
    """The honest residue. An ambiguous selector is one X4 itself refuses (RFC 5261:
    "Multiple matching nodes ... Skipping node"), so attributing it would claim a
    change the game never makes. MEASURED over the live install, 189 of the 192
    residual ops are exactly this or a selector matching nothing."""
    tree = etree.fromstring(
        '<wares><ware id="a"><price average="1"/></ware>'
        '<ware id="b"><price average="2"/></ware></wares>')
    diff = etree.fromstring(
        '<diff><replace sel="//price/@average">9</replace></diff>')
    ops = _merge.apply_diff(tree, diff, want_targets=True)
    assert ops[0].ok is False and ops[0].ambiguous
    assert ops[0].target_keys == ()


def test_a_sel_that_matches_NOTHING_is_still_counted_not_silently_dropped(tmp_path):
    """A step that narrows data must announce it. An unresolvable op stays in the
    unattributed count rather than vanishing into a clean-looking zero."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml",
       '<diff><replace sel="//ware[@id=' + chr(39) + 'nosuchware' + chr(39)
       + ']/@price_average">1</replace></diff>')
    assert _stats.candidate_wares(cand, _base_tree()) == {}
    assert _stats.unattributed_ware_ops(cand, _base_tree()) == 1


# ---------------- the v3.1.0 release review, group B2 ------------------------------
# Two IMPORTANT findings, both IN-ARC, both in the sel=-to-ware feature itself. The
# existing tests could not have caught either: the value test used a diff with NO
# <ware> payload (so `out` was empty when setdefault ran and it behaved like `[]=`),
# and both render_wares call sites passed an EMPTY comparison list.


def test_a_ware_ADDED_then_REPLACED_reports_the_value_the_MOD_LEAVES(tmp_path):
    """Finding 1. setdefault let the PAYLOAD win over the MUTATED tree, so the
    X4_Customizer chaining idiom (add, then replace the same ware -- gotcha #17)
    reported the INTERMEDIATE price. The reviewer measured an add at 50 followed by a
    replace to 500000 reporting 50: "~33th percentile" where the truth is "PRICIER
    than every same-group peer"."""
    cand = tmp_path / "mod"
    _w(cand / "libraries" / "wares.xml",
       '<diff>'
       '<add sel="/wares"><ware id="newware" group="minerals">'
       '<price average="50"/></ware></add>'
       '<replace sel="//ware[@id=' + chr(39) + 'newware' + chr(39)
       + ']/price/@average">500000</replace>'
       '</diff>')
    got = _stats.candidate_wares(cand, _base_tree())
    assert "newware" in got
    assert got["newware"].price_avg == 500000.0, (
        "reported %r -- the pre-modification value, not what the mod leaves"
        % got["newware"].price_avg)


def test_the_NOT_CHECKED_disclosure_survives_a_NON_EMPTY_comparison():
    """Finding 2. The disclosure was gated on `not comparisons`, which was true when
    an unattributable mod produced no comparisons at all. Resolving sel= made
    comparisons non-empty for exactly those mods -- zeros 5 -> 1 while FIVE still
    carry residue -- so 4 of 5 lost the disclosure to the fix meant to answer them."""
    c = _stats.WareComparison(
        ware=_stats.Ware(id="ore", group="minerals", transport="container",
                         volume=1, price_min=90.0, price_avg=100.0,
                         price_max=110.0),
        peer_group="minerals", peer_count=3, peer_price_min=40.0,
        peer_price_median=100.0, peer_price_max=200.0, percentile=50.0)
    out = _stats.render_wares([c], unattributed=7)
    assert "NOT CHECKED" in out, "the residue vanished once there were results to show"
    assert "7 op(s)" in out
    assert "ore" in out, "and the comparison itself must still be rendered"


def test_an_empty_comparison_with_no_residue_still_says_it_changes_nothing():
    """The twin. A genuine absence must keep reading as one -- turning every empty
    result into NOT CHECKED is the same conflation in the other direction."""
    assert _stats.render_wares([], 0) == "candidate introduces/changes no wares."


def test_the_disclosure_no_longer_claims_replace_and_remove_are_invisible():
    """Finding 3. The message still told users this tool reads a ware only from an
    <add>ed <ware> element, which stopped being true when the feature landed."""
    out = _stats.render_wares([], unattributed=3)
    assert "NOT CHECKED" in out
    assert "invisible" not in out, "the message outlived the limitation it described"
    assert "ambiguous selector" in out or "Skipping node" in out


def test_the_RESOLUTION_tree_takes_the_ACTIVE_set_not_the_installed_one():
    """Finding 4, asserted STRUCTURALLY (gotcha #37) rather than by installing a
    disabled mod: the CLI must ask for scope="active" when building the tree a
    candidate's selectors resolve against, because that models what the ENGINE loads
    (CLAUDE.md #24), while the comparison POOL stays "installed"."""
    import inspect
    src = inspect.getsource(_stats.main)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "effective_wares"]
    assert len(calls) == 2, "expected a pool build and a resolution build"
    scopes = []
    for c in calls:
        kw = {k.arg: k for k in c.keywords}
        scopes.append(kw["scope"].value.value if "scope" in kw else "installed")
    assert scopes == ["installed", "active"], scopes
