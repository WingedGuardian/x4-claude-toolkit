"""Mutation-campaign gaps in `_compat` AN-5 (removals decided per op at its own load
position) and AN-10 (order misses) -- campaign 2, 2026-09-26. Each test names the
surviving mutant(s) it was written to kill and was verified to FAIL with them applied
and PASS without. Everything runs for real over tiny loose mods; nothing is stubbed.
"""
from __future__ import annotations

from x4validate import _compat, _merge


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mod(ext, folder, wares_diff):
    root = ext / folder
    _w(root / "content.xml", f'<content id="{folder}" name="{folder}" version="1"/>')
    _w(root / "libraries/wares.xml", wares_diff)


def _world(tmp_path, mods):
    ref = tmp_path / "reference"
    _w(ref / "libraries/wares.xml",
       '<wares><ware id="ore"><price average="100"/></ware>'
       '<ware id="ice"><price average="50"/></ware></wares>')
    ext = tmp_path / "extensions"
    for folder, body in mods:
        _mod(ext, folder, body)
    return _compat.analyze(ext, config=_merge.Config(reference=ref))


_REP_ORE = ('<diff><replace sel="//ware[@id=\'ore\']"><ware id="ore">'
            '<price average="7"/></ware></replace></diff>')
_REP_ORE_NO_PRICE = ('<diff><replace sel="//ware[@id=\'ore\']"><ware id="ore"/>'
                     '</replace></diff>')
_RM_ORE = '<diff><remove sel="//ware[@id=\'ore\']"/></diff>'
_RM_ORE_PRICE = '<diff><remove sel="//ware[@id=\'ore\']/price"/></diff>'
_READD_ORE = ('<diff><add sel="/wares"><ware id="ore"><price average="55"/></ware>'
              '</add></diff>')
_EDIT_IN_ORE = '<diff><replace sel="//ware[@id=\'ore\']/price/@average">9</replace></diff>'
_ADD_Z = '<diff><add sel="/wares"><ware id="zware"><price average="1"/></ware></add></diff>'
_RM_Z = '<diff><remove sel="//ware[@id=\'zware\']"/></diff>'
_PATCH_Z = '<diff><replace sel="//ware[@id=\'zware\']/price/@average">5</replace></diff>'


def _hard_on(rep, mods):
    return [c for c in rep.by_kind("HARD") if set(c.mods) == set(mods)]


def test_a_remove_between_two_replaces_is_live_and_names_its_remover(tmp_path):
    """CA9 (ops judged on the tree AFTER their own mod applies) and CA6 (removed_by
    blanked): a replaces ore, b removes it, c's replace then matches nothing. The
    removal is live, b is the winner, and `removed_by` names b."""
    rep = _world(tmp_path, [("a_rep", _REP_ORE), ("b_rm", _RM_ORE), ("c_rep", _REP_ORE)])
    hard = _hard_on(rep, ["a_rep", "b_rm", "c_rep"])
    assert len(hard) == 1, hard
    assert hard[0].winner == "b_rm" and hard[0].removed_by == "b_rm"
    assert "'c_rep'" in hard[0].detail


def test_an_op_dead_BEFORE_the_winner_is_not_called_a_later_op(tmp_path):
    """CA5b: a removes ore, b's replace then matches nothing, c re-adds ore, d's
    replace applies and wins. b loads BEFORE the winner; 'later op(s) ... match
    nothing' must not name it."""
    rep = _world(tmp_path, [("a_rm", _RM_ORE), ("b_rep", _REP_ORE),
                            ("c_readd", _READD_ORE), ("d_rep", _REP_ORE)])
    hard = _hard_on(rep, ["a_rm", "b_rep", "d_rep"])
    assert len(hard) == 1, hard
    assert hard[0].winner == "d_rep" and not hard[0].removed_by
    assert "match nothing" not in hard[0].detail, hard[0].detail


def test_an_edit_BEFORE_the_remover_is_never_attributed_to_it(tmp_path):
    """CA7: z removes ore, but b's edit inside ore loads EARLIER. Whatever made b's op
    miss (here a's replace dropped the price), it was not z -- the removed-first
    disclosure must not name a remover that loads after the editor."""
    rep = _world(tmp_path, [("a_rep", _REP_ORE_NO_PRICE), ("b_edit", _EDIT_IN_ORE),
                            ("z_rm", _RM_ORE)])
    assert [m for m in rep.removed_first if m.removed_by == "z_rm"] == []


def test_one_skipped_op_inside_two_removed_ancestors_is_disclosed_once(tmp_path):
    """CA8b: a removes ore, b removes ore/price; c's edit inside both is ONE op the
    engine skips, and is disclosed once, naming the first remover. (b's own remove is
    inside a's removed node too, so it is disclosed as well -- once.)"""
    rep = _world(tmp_path, [("a_rm", _RM_ORE), ("b_rm", _RM_ORE_PRICE),
                            ("c_edit", _EDIT_IN_ORE)])
    assert sorted((m.mod, m.removed_by) for m in rep.removed_first) == [
        ("b_rm", "a_rm"), ("c_edit", "a_rm")]


def test_a_remove_of_a_node_an_EARLIER_mod_added_is_not_an_order_miss(tmp_path):
    """CA13: b's remove misses the base but matches when b loads (a added zware). It is
    supplied in time -- not a miss -- even though b's own remove makes it vanish and c
    re-adds it later."""
    rep = _world(tmp_path, [("a_add", _ADD_Z), ("b_rm", _RM_Z), ("c_add", _ADD_Z)])
    assert rep.order_misses == []


def test_an_op_dead_in_the_FINISHED_tree_is_not_named_as_an_order_miss(tmp_path):
    """CA16: the fast pass's stated limit, shared with the rebuild form -- a node a
    later mod adds and a still-later mod removes again is filtered as dead, so both
    forms give one answer."""
    rep = _world(tmp_path, [("a_patch", _PATCH_Z), ("b_add", _ADD_Z), ("c_rm", _RM_Z)])
    assert rep.order_misses == []
