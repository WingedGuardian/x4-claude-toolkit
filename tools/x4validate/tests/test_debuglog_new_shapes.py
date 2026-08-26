r"""The 2026-08-25 classifier extension, pinned by verbatim engine lines.

MEASURED against `debug-2026-08-24T1935.txt` (2,490 `[=ERROR=]` lines, NEW GAME,
429 s): the residue was **263 unclassified (10.6%)** spread over **114 distinct
shapes** - a long tail, not six big ones. Adding the head of that tail took it to
**60 (2.4%)**, and the move is fully accounted:

    263 - 60 = 203 reclassified
              =  29 into the SCRIPT bucket  (subtotal 602 -> 631)
              + 174 into SUBSYSTEM buckets  (subtotal 783 -> 957)

The 29 are the `Context:md.X.Y:` prefix, which the engine uses interchangeably with
`Error in MD cue md.X.Y:`. They belong in the script bucket because routing them to
a subsystem bucket would throw away the mod attribution that makes them actionable.
28 are FinaliseStations, 1 is FactionLogic - counted directly from the log, so the
delta has no unexplained remainder.

WHY EVERY SAMPLE HERE IS VERBATIM: a regex written against a remembered message
shape is a checker bug waiting to happen. Each string below was lifted from a real
log line, so if the engine's wording changes these go red instead of silently
reclassifying to `unclassified`.

Two rows carry a deliberately EMPTY `entity` group (`npcblackboard`, `sectioncurve`):
those messages contain no id at all, and an empty identity is the honest rendering.
Inventing one would be worse than admitting there is none.
"""

BS = chr(92)   # a literal backslash, built at runtime - see the module
               # docstring: escaping layers eat these, four times so far.

import pytest

from x4validate import _debuglog


def _one(line: str):
    """Classify a single verbatim [=ERROR=] line."""
    result = _debuglog.parse_log_text("[=ERROR=] 0.00 " + line)
    assert result.total == 1
    assert len(result.entries) == 1
    return result.entries[0]


# (verbatim message, expected ident_kind, expected identity fragment)
SAMPLES = [
    ("Error in context race: Property lookup failed: central",
     "contextrace", "central"),
    ("Property lookup failed: roomtype.bar2", "roomtype", "bar2"),
    ("Property lookup failed: roomtype.infrastructure2", "roomtype", "infrastructure2"),
    ("JobClass::ResolveReferences(): job loanshark_patrol_l_cluster_2 references "
     "non-subordinate job loanshark_escort_common_chaos_l as a subordinate. "
     "Missing 'subordinate' modifier flag?", "jobclass", "loanshark_patrol_l_cluster_2"),
    ("Unable to resolve subordinate job ID: 'central_miningfleet_m_solid_small'",
     "jobclass", "central_miningfleet_m_solid_small"),
    ("Non-virtual module 'dockarea_cpsdo_m_ship_right_01_macro' does not have a "
     "wreck geometry defined", "wreckgeometry", "dockarea_cpsdo_m_ship_right_01_macro"),
    ("'landmarks_asteroid_01' has only turrets in group '1'! @Artists",
     "turretgroup", "landmarks_asteroid_01"),
    ("Error in default context: Evaluated EquipmentModsDefinition ware "
     "'mod_shield_rechargedelay_01_mk1' cannot be applied to any shield group",
     "equipmentmod", "mod_shield_rechargedelay_01_mk1"),
    ("template 'ship_xenon_battleship_e' does not have any countermeasure connection!",
     "countermeasure", "ship_xenon_battleship_e"),
    ("StockData: Invalid ware 'cpsdo_paintmod' referenced for stock id "
     "'default_trader', skipping entry.", "stockdata", "cpsdo_paintmod"),
    ("GroupDB::ImportDB(): Duplicate definition of 'yak_destroyer_l' in file "
     "'libraries" + BS + "shipgroups'", "groupdb", "yak_destroyer_l"),
    ("Faction import: Duplicate named licence of type 'capitalequipment' for "
     "faction 'yaki'", "factionimport", "yaki"),
    ("EffectProperties: MaxScale 0.500000 is less than MinScale 1.000000 in effect "
     "'impact_cpsdo_xl_beam_01_mk6_base' element 1! MaxScale will revert to MinScale.",
     "effectproperties", "impact_cpsdo_xl_beam_01_mk6_base"),
    ("[XLib::TextDB::ConvertTextDBString] Found newline in text: 999443-3",
     "textdb", "999443-3"),
    ("GetText(pageid=20202, textid=3903) TextID not found!", "textpage", "20202"),
]


@pytest.mark.parametrize("line,kind,identity", SAMPLES)
def test_a_known_shape_is_classified_not_left_as_residue(line, kind, identity):
    entry = _one(line)
    assert entry.ident_kind == "subsystem", (
        f"expected a subsystem entry, got {entry.ident_kind!r} for: {line[:80]}")
    assert entry.subsystem == kind, (
        f"expected bucket {kind!r}, got {entry.subsystem!r} for: {line[:80]}")
    assert identity in (entry.entity or ""), (
        f"expected entity containing {identity!r}, got {entry.entity!r}")


@pytest.mark.parametrize("line,kind", [
    ("C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations/.../(): "
     "GetNPCBlackboard(): Component 0 does not exist any more", "npcblackboard"),
    ("[SectionCurve::Import] A curve was defined with exactly two points with the "
     "same value: 1.000000. Use 'default' attribute instead.", "sectioncurve"),
])
def test_a_shape_with_NO_id_is_classified_with_an_EMPTY_identity(line, kind):
    """Admitting there is no id beats inventing one."""
    entry = _one(line)
    assert entry.ident_kind == "subsystem"
    assert entry.subsystem == kind
    assert entry.entity == "", "these messages carry no id; the entity must be empty"


def test_the_merge_patch_PAIR_keeps_its_two_DIFFERENT_names():
    """CLAUDE.md #28b: the engine's skip vocabulary names an inconsistent object.

    One line names the merge TARGET, the other names the PATCH file, and they are
    the same failure. Collapsing them into one bucket would make "which file is
    actually broken?" unanswerable - so they stay two rows.
    """
    win = BS.join(["extensions", "amphitrite", "assets", "units", "size_l",
                   "macros", "ship_l_arethusa_raider_macro"])
    target = _one("Error loading from XML merge/patch file " + "'" + win + "'"
                  ". Check the log for further information. Skipping file.")
    patch = _one("LIBXML2: file:///extensions/amphitrite_vro/extensions/amphitrite/"
                 "assets/units/size_l/macros/ship_l_arethusa_raider_macro"
                 "?ext=xml%20xml.gz line 75, error 76: Opening and ending tag "
                 "mismatch: connections line 50 and replace")
    assert target.subsystem == "mergepatch"
    assert patch.subsystem == "libxml2"
    assert "amphitrite_vro" not in target.entity, (
        "the merge/patch line names the TARGET (amphitrite), not the mod that broke it")
    assert "amphitrite_vro" in patch.entity, (
        "the LIBXML2 line is the one that names the PATCHING mod")


@pytest.mark.parametrize("prefix", ["Error in MD cue md.", "Context:md."])
def test_BOTH_md_prefixes_land_in_the_SCRIPT_bucket(prefix):
    """29 lines in the 08-24 log used the second prefix and were residue.

    Routing them to a subsystem bucket would have classified them while LOSING the
    script name - a silent downgrade that still looks like progress.
    """
    entry = _one(prefix + "FinaliseStations.ConstructionSequenceCompleted<inst:4e6e3>: "
                 "Automatic station generation was not able to find any 'sensible' "
                 "wares for use in loadouts")
    assert entry.ident_kind == "script"
    assert entry.script_name == "FinaliseStations"


def test_an_UNKNOWN_shape_is_still_residue_not_swept_into_a_new_bucket():
    """The falsification twin for this whole file: adding buckets must not make the
    parser claim shapes it does not know. If this ever goes green-by-absorption, the
    new rows are too greedy."""
    entry = _one("SaveList::TriggerUpdate() - We are already processing the "
                 "savegame directory. Call will be skipped.")
    assert entry.ident_kind == "unclassified"
