r"""An ADDITIVE vpath must union regardless of how the mod spelled its case.

X4 vpaths are case-insensitive to the engine -- the corpus genuinely mixes case
(`Cluster_104` vs `cluster_104`, `SurfaceElements` vs `surfaceelements`) and Windows
resolves either spelling to the same file. `_merge` tested the additive prefix with a
case-SENSITIVE `startswith`, so a mod that wrote `Index/macros.xml` took a different
merge path from one that wrote `index/macros.xml`.

MEASURED 2026-09-04 on the live corpus, and the damage is in the DLC layering rather
than the mod's own patch:

    Index/components.xml   8 DLC layers merge as `full`  ->    10 entries
    index/components.xml   8 DLC layers merge as `union` ->  3,986 entries

Every DLC ships an `<index>` root at that path. With the union test failing, each DLC
REPLACES the previous one and only the last survives, so a mod patching the index sees
a tree missing ~99.7% of the game's entries. Exactly 2 of 4,629 documents across 125
installed mods spell it that way -- a small population and a large per-item cost.

The adjacent `_SCRIPT_REGISTRY_DIRS` test one line below already lowercased. One line
had it right and its neighbour did not.
"""

from __future__ import annotations

from lxml import etree

from x4validate import _merge


def _index(*names):
    root = etree.Element("index")
    for n in names:
        etree.SubElement(root, "entry", name=n)
    return root


CASES = ["index/macros.xml", "Index/macros.xml", "INDEX/macros.xml",
         "libraries/wares.xml", "Libraries/wares.xml",
         "t/0001.xml", "T/0001.xml"]


def test_an_additive_vpath_unions_in_every_spelling():
    for vpath in CASES:
        base = _index("a", "b")
        overlay = _index("c")
        tree, mode = _merge.apply_overlay(base, overlay, vpath, source="m")
        assert mode == "union", "%s merged as %r, not union" % (vpath, mode)
        assert len(tree) == 3, "%s lost entries: %d" % (vpath, len(tree))


def test_the_control_a_NON_additive_vpath_still_full_overrides():
    """Without this the test above would pass on a change that unions everything."""
    base = _index("a", "b")
    overlay = _index("c")
    tree, mode = _merge.apply_overlay(base, overlay, "assets/units/size_s/ship.xml",
                                      source="m")
    assert mode != "union", "a non-additive path must NOT union"


def test_a_diff_root_is_unaffected_by_case():
    """A <diff> returns from the first branch and never reaches the prefix test; this
    pins that the fix did not move that boundary."""
    for vpath in ("index/macros.xml", "Index/macros.xml"):
        base = _index("a")
        overlay = etree.fromstring(
            b'<diff><add sel="/index"><entry name="z"/></add></diff>')
        tree, mode = _merge.apply_overlay(base, overlay, vpath, source="m")
        assert mode == "diff", "%s -> %r" % (vpath, mode)
        assert len(tree) == 2


def test_the_language_file_test_is_also_case_insensitive():
    """`t/` decides `is_text_file`, which is what makes a language diff well-founded
    even when no base file was found. On Linux the case is not forgiven by the
    filesystem either, so a `T/` spelling there is a hard failure rather than a
    quiet one."""
    assert _merge._is_text_vpath("t/0001-l044.xml")
    assert _merge._is_text_vpath("T/0001-l044.xml")
    assert not _merge._is_text_vpath("libraries/wares.xml")
    assert not _merge._is_text_vpath("t/notxml.txt")


# --------------------------------------------------------------------------- #
# THE OTHER HALF OF THE SAME BRANCH. The tests above vary the CASE of the vpath;
# nothing varied the PREFIX. `_ADDITIVE_DIRS` are paths inside the extension that
# OWNS the document, and two of apply_overlay's three call sites pass a vpath that
# still carries `extensions/<owner>/` -- which does not start with `libraries/`.
#
# MEASURED 2026-09-05 on the live corpus: 6 shared registry files full-overridden
# instead of unioned, 99 base entries discarded from the effective tree. Same
# branch and same consequence as d368bf3 ("a mixed-case additive vpath made every
# DLC layer REPLACE instead of union"), one variant away, and that fix's test
# pinned case rather than prefix.
# --------------------------------------------------------------------------- #

NESTED = ["extensions/ego_dlc_boron/libraries/rooms.xml",
          "extensions/ego_dlc_split/index/macros.xml",
          "extensions/EGO_DLC_TERRAN/Libraries/wares.xml",   # prefix AND case
          "extensions/some_mod/t/0001.xml"]


def test_an_OWNER_NESTED_additive_vpath_still_unions():
    for vpath in NESTED:
        base = _index("a", "b")
        overlay = _index("c")
        tree, mode = _merge.apply_overlay(base, overlay, vpath, source="m")
        assert mode == "union", "%s merged as %r, not union" % (vpath, mode)
        assert len(tree) == 3, "%s lost base entries: %d of 3" % (vpath, len(tree))


def test_the_control_a_nested_NON_additive_vpath_still_full_overrides():
    """Without this, a fix that stripped the prefix and unioned EVERYTHING nested
    would look identical to one that only fixed the registry dirs."""
    base = _index("a", "b")
    overlay = _index("c")
    tree, mode = _merge.apply_overlay(
        base, overlay, "extensions/ego_dlc_boron/assets/units/size_s/ship.xml", source="m")
    assert mode != "union", "a nested NON-additive path must NOT union"


def test_a_bare_prefix_lookalike_is_not_stripped():
    """`extensions` as a top-level FILE name, or a two-segment path, must not be
    mistaken for an owner prefix -- the strip requires at least three segments."""
    assert _merge._registry_rel("libraries/wares.xml") == "libraries/wares.xml"
    assert _merge._registry_rel("extensions/wares.xml") == "extensions/wares.xml"
    assert _merge._registry_rel("extensions/m/libraries/w.xml") == "libraries/w.xml"
