"""F27: the engine registers MD scripts by FILENAME, so a duplicate is INERT.

ENGINE-PROVEN 2026-08-22 by a controlled pair differing in exactly one variable --
same cue structure, same actions, same load position, and both script `name=`
differing from vanilla's `Setup`, so the script name is not the discriminator:

    md/setup_moona_central.xml (new vpath)     -> registers, its cues run
    md/setup.xml               (vanilla vpath) -> never takes effect, silently

Modelling the second as a full-file override made `x4effective dump md/setup.xml`
return a mod's 44-line file while the engine was demonstrably running vanilla's
1,795-line `Setup`.

The scope limit is pinned here too: `aiscripts/` is NOT included, because there are
zero complete-file-at-a-vanilla-vpath instances in the corpus to verify it against.
"""

from lxml import etree

from x4validate import _merge


def _root(xml: str) -> etree._Element:
    return etree.fromstring(xml)


VANILLA_SETUP = '<mdscript name="Setup"><cues><cue name="Start"/></cues></mdscript>'
MOD_SETUP = '<mdscript name="Setup_Mod"><cues><cue name="Start"/></cues></mdscript>'


def test_a_complete_mdscript_at_an_ALREADY_SUPPLIED_vpath_is_inert():
    base = _root(VANILLA_SETUP)
    tree, mode = _merge.apply_overlay(base, _root(MOD_SETUP), "md/setup.xml", "amod")
    assert mode == "script(inert)"
    assert tree is base, "the base document must be untouched"
    assert tree.get("name") == "Setup", "vanilla's script must still be the live one"


def test_the_same_script_at_a_NEW_vpath_is_LIVE():
    """The other half of the controlled pair — this is what makes it a mechanism
    rather than 'mod scripts do not work'."""
    oroot = _root(MOD_SETUP)
    tree, mode = _merge.apply_overlay(None, oroot, "md/setup_mod_unique.xml", "amod")
    assert mode == "full"
    assert tree is oroot


def test_a_DIFF_at_a_vanilla_script_vpath_still_APPLIES():
    """263 of 264 script-path collisions are diffs, including 59 of 59 of Egosoft's
    own. Breaking those would be catastrophic and is the main regression risk."""
    base = _root(VANILLA_SETUP)
    diff = _root('<diff><add sel="/mdscript/cues">'
                 '<cue name="Added"/></add></diff>')
    tree, mode = _merge.apply_overlay(base, diff, "md/setup.xml", "amod")
    assert mode == "diff"
    assert tree.find("cues/cue[@name='Added']") is not None


def test_aiscripts_are_DELIBERATELY_out_of_scope():
    """Pins the scope limit so widening it becomes a conscious, tested act.

    MEASURED over 115 installed mods / 4,391 XML files: zero complete-file-at-a-
    vanilla-vpath instances under aiscripts/. With nothing to verify against,
    including it would encode an inference as a fact. gates/tool_properties.py
    trips the moment a real instance appears."""
    base = _root("<aiscript name='order.move.recon'/>")
    oroot = _root("<aiscript name='order.move.recon'/>")
    tree, mode = _merge.apply_overlay(base, oroot, "aiscripts/order.move.recon.xml", "amod")
    assert mode == "full", "aiscripts/ must keep full-override semantics for now"
    assert tree is oroot


def test_asset_full_file_override_is_unaffected():
    """The rule must not leak outside md/ — asset macros override wholesale, and
    `cpsdo_vro` clobbering another mod's weapon-fx macros is live proof."""
    base = _root("<macros><macro name='a'/></macros>")
    oroot = _root("<macros><macro name='b'/></macros>")
    tree, mode = _merge.apply_overlay(base, oroot, "assets/props/x/macros/a_macro.xml", "amod")
    assert mode == "full"
    assert tree is oroot


def test_libraries_union_is_unaffected():
    base = _root("<wares><ware id='ore'/></wares>")
    oroot = _root("<wares><ware id='new'/></wares>")
    tree, mode = _merge.apply_overlay(base, oroot, "libraries/wares.xml", "amod")
    assert mode == "union"
    assert {w.get("id") for w in tree} == {"ore", "new"}
