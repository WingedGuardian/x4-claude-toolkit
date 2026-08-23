"""Per-kind collision semantics in gates/cross_tool.py.

The gate itself only exercises these against the CURRENT modlist, so its "0
disagreements" is a fact about today's 115 mods, not a guarantee about the logic.
These tests pin the logic itself.

Background: BLIND-SPOTS F25/F26, KB 2026-08-13d, CLAUDE.md gotcha #18.
`Collision.winner` means a different thing per kind, and asserting one blanket
rule produced 6 false HARD disagreements + 6 false SUBTREE alarms — both of them
the CHECKER's bug, not x4compat's.
"""

import sys
from pathlib import Path

from conftest import import_gate  # noqa: E402

# Module-scope import of a gate exits the whole pytest session on a machine
# with no X4 install -- see tests/conftest.py. Skip, do not abort.
cross_tool = import_gate("cross_tool")


# --- SUBTREE targets are NODE-scoped, not file-scoped -------------------------

def test_document_root_replace_is_a_whole_file_wipe():
    """`/macros` is the document-root override idiom (gotcha #10) — 140 of 148
    SUBTREE rows on the measured install. The victim must be gone entirely."""
    assert cross_tool._subtree_scope("/macros") == ("file", None)


def test_whole_macro_element_replace_is_also_file_wide():
    assert cross_tool._subtree_scope("/macros/macro") == ("file", None)


def test_node_scoped_wipe_maps_to_a_property_prefix():
    """A wipe of ONE node must NOT assert file-wide absence: the victim keeps its
    other attributes in the same document. This is the exact shape that produced
    6 false alarms."""
    mode, prop = cross_tool._subtree_scope("/macros/macro/properties/explosiondamage")
    assert (mode, prop) == ("node", "explosiondamage")


def test_deeper_node_scope_keeps_the_dotted_grammar():
    mode, prop = cross_tool._subtree_scope("/macros/macro/properties/hull/max")
    assert (mode, prop) == ("node", "hull.max")


def test_bare_properties_is_a_whole_entity_wipe():
    assert cross_tool._subtree_scope("/macros/macro/properties") == ("file", None)


def test_predicated_target_is_unmapped_not_guessed():
    """A predicate cannot be mapped onto a flattened prop key. Report it as
    unmapped so it is COUNTED, never silently treated as clean."""
    mode, prop = cross_tool._subtree_scope(
        "/macros/macro/connections/connection[@ref='con_cockpit_01']")
    assert mode == "unmapped" and prop is None


def test_unknown_anchor_is_unmapped():
    assert cross_tool._subtree_scope("/components/component/source")[0] == "unmapped"


# --- nested mod-on-mod paths --------------------------------------------------

def test_nested_patch_path_also_offers_the_owners_logical_path():
    """`build_touch_map` rewrites extensions/<owner>/<rel> to <rel>. A lookup that
    only tries the literal spelling finds nothing — that is how 6 of 148 rows went
    unresolvable and nearly became a bogus x4compat finding."""
    literal, stripped = cross_tool._vpath_forms(
        "extensions/some_mod/assets/units/size_l/macros/x_macro.xml")
    assert literal == "extensions/some_mod/assets/units/size_l/macros/x_macro.xml"
    assert stripped == "assets/units/size_l/macros/x_macro.xml"


def test_plain_path_is_unchanged_by_stripping():
    literal, stripped = cross_tool._vpath_forms("libraries/wares.xml")
    assert literal == stripped == "libraries/wares.xml"


def test_dlc_paths_are_not_treated_as_mod_nesting():
    """Unpacked ego_dlc_* content genuinely lives under extensions/ — stripping it
    would invent a vpath the game does not have."""
    _, stripped = cross_tool._vpath_forms(
        "extensions/ego_dlc_terran/libraries/modulegroups.xml")
    assert stripped.startswith("extensions/ego_dlc_terran/")


# --- Collision.live_value_owner(): the one definition of "whose value is live" ---

from x4validate import _compat  # noqa: E402


def _c(kind, winner="w_mod", wiped_by=""):
    return _compat.Collision("v.xml", kind, "t", ["a_mod", "w_mod"], winner,
                             wiped_by=wiped_by)


def test_kinds_that_really_do_have_a_live_winner_report_it():
    for kind in ("FULL-OVERRIDE", "HARD", "UNION-KEY"):
        assert _c(kind).live_value_owner() == "w_mod", kind


def test_subtree_refuses_to_name_a_live_owner():
    """`winner` was the WIPER; a later mod can re-supply what was wiped
    (MEASURED 3 of 148 on the live install), so there is no answer to give."""
    c = _c("SUBTREE", winner="", wiped_by="w_mod")
    assert c.live_value_owner() is None
    assert c.wiped_by == "w_mod", "the wiper is still reported, under its own name"


def test_name_clash_refuses_too():
    assert _c("NAME-CLASH", winner="").live_value_owner() is None


def test_soft_has_no_winner_to_claim():
    assert _c("SOFT", winner="").live_value_owner() is None


def test_an_empty_winner_never_renders_as_a_mod_name():
    """Guards the failure this replaced: '' must not read as an answer."""
    assert _c("HARD", winner="").live_value_owner() is None
