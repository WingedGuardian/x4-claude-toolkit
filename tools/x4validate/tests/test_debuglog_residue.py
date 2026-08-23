r"""A log parser must say what it did NOT parse.

The register's rule is that a step which narrows the data has to announce it.
`parse_debug` was the sixth occurrence of the opposite: it walked every
`[=ERROR=]` line, matched six regexes, and `continue`d past anything else
without a word. MEASURED against the 2026-08-13 log: **1,067 of 2,430 lines
(43.9%) were dropped in silence** — and `check_debug_correlation` then printed
"(of 1363 total in the log)", asserting a denominator it had never measured.

What was in the missing 44% is the point. The most consequential finding of that
day's triage — 22 jobs added by a mod whose `ship.select.tags` no ship in the
effective tree carries, so they can never spawn — is a `[JobEngine]` /
`ShipGenerator` line, and every one of those was invisible.

So the contract here is: **every `[=ERROR=]` line is accounted for.** Lines the
parser cannot classify are labelled `unclassified` and counted, never dropped.
An unclassified line is an honest account; a missing line is not.
"""

import pytest

from x4validate import _debuglog

# Verbatim from a real engine debug.txt (2026-08-13), captured from the X4 user
# profile directory. The path is deliberately NOT written out: it embeds a personal
# Steam profile id, and this file is a candidate for the public bundle.
SUBSYSTEM_SAMPLE = "\n".join([
    r"[=ERROR=] 0.00 [JobEngine] No ship generated for JobID: 'argon_heavyfrigate_patrol_l_sector'. Probably invalid ship macro/group/ref definition.",
    r"[=ERROR=] 0.00 Error in default context: No suitable ShipGenerator found with tags=[tag.military,tag.heavyfrigate], size=class.ship_l, factions=faction.argon",
    r"[=ERROR=] 0.00 FactoryGenerator::GetAllPossibleMacros(): Station group reference 'dockarea_ter_hightech' not found or does not contain any macros.",
    r"[=ERROR=] 0.00 ShipGenerator::GetAllPossibleMacros(): Ship group reference 'sca_heavyfrigate_plunderer_l' not found or does not contain any macros.",
    r"[=ERROR=] 0.00 Cannot find referenced part template XML file from index 'thruster_ship_l_00' in file 'index\components', referenced from component template 'ship_shadow' connection 'connectionforanim_thruster_01001'",
    r"[=ERROR=] 0.00 WareDB::Import(): ware 'ship_cpsdo_l_ninghai' has blueprint owners set but does not specify a required trade licence so owners are ignored!",
    r"[=ERROR=] 0.00 [God Engine] God Entry ID: 'yaki_shipyard' no sectors in galaxy found, error in map?",
    r"[=ERROR=] 0.00 EffectLibrary::GetDefinition() Effect 'impact_cpsdo_s_laser_01_mk4_inside' not found",
])


def test_parse_log_reports_a_total_it_actually_measured():
    """The false-denominator bug, stated as a test: the reported total must be the
    number of [=ERROR=] lines READ, never the number successfully classified."""
    result = _debuglog.parse_log_text(SUBSYSTEM_SAMPLE)
    assert result.total == 8, "total must count every [=ERROR=] line in the input"
    assert result.total == len(result.entries), (
        "every line must be accounted for — a classified entry or an unclassified one, "
        "never dropped")


def test_an_unclassifiable_line_is_LABELLED_not_dropped():
    """The whole contract. A shape we have never seen must survive as evidence."""
    text = r"[=ERROR=] 0.00 SomeFutureSubsystem::Explode(): a shape nobody has parsed yet"
    result = _debuglog.parse_log_text(text)
    assert result.total == 1
    assert len(result.unclassified) == 1
    assert result.unclassified[0].ident_kind == "unclassified"
    assert "SomeFutureSubsystem" in result.unclassified[0].message


def test_jobengine_names_the_job_that_could_not_spawn():
    """THE case this exists for — invisible to the parser before today."""
    e = _one(SUBSYSTEM_SAMPLE, "jobengine")
    assert e.entity_kind == "job"
    assert e.entity == "argon_heavyfrigate_patrol_l_sector"


def test_shipgenerator_tag_miss_carries_its_tags_and_faction():
    """No entity id exists in this shape, so the tags ARE the identity. Recording
    them is what makes 'nothing carries tag.heavyfrigate' a measurable claim."""
    e = _one(SUBSYSTEM_SAMPLE, "shipgenerator", entity_kind="tags")
    assert "heavyfrigate" in e.entity
    assert "argon" in e.message


def test_group_reference_misses_name_the_group_AND_its_kind():
    """Two near-identical shapes from different subsystems: a STATION group and a
    SHIP group. Collapsing them would make 'who emptied dockarea_ter_hightech'
    unanswerable, which is the question that exposed the modulegroups gap."""
    station = _one(SUBSYSTEM_SAMPLE, "factorygenerator")
    assert station.entity_kind == "stationgroup"
    assert station.entity == "dockarea_ter_hightech"
    ship = _one(SUBSYSTEM_SAMPLE, "shipgenerator", entity_kind="shipgroup")
    assert ship.entity == "sca_heavyfrigate_plunderer_l"


def test_part_template_miss_names_the_component_not_the_index():
    """The engine names three things here; the actionable one is the component
    template that holds the broken connection."""
    e = _one(SUBSYSTEM_SAMPLE, "parttemplate")
    assert e.entity_kind == "component"
    assert e.entity == "ship_shadow"
    assert "thruster_ship_l_00" in e.message


def test_waredb_and_effectlibrary_name_their_entity():
    ware = _one(SUBSYSTEM_SAMPLE, "waredb")
    assert ware.entity_kind == "ware" and ware.entity == "ship_cpsdo_l_ninghai"
    eff = _one(SUBSYSTEM_SAMPLE, "effectlibrary")
    assert eff.entity_kind == "effect" and eff.entity == "impact_cpsdo_s_laser_01_mk4_inside"


def test_god_engine_names_the_god_entry():
    e = _one(SUBSYSTEM_SAMPLE, "godengine")
    assert e.entity_kind == "godentry" and e.entity == "yaki_shipyard"


def test_subsystem_shapes_do_not_leak_into_the_two_gate_filters():
    """`gates/oracle.py` selects on `.cardinality`, `gates/oracle_index.py` on
    `.lookup`. Both are corpus-wide gates. A new shape that accidentally set
    either field would silently change what those gates measure — so this pins
    the boundary rather than trusting it."""
    result = _debuglog.parse_log_text(SUBSYSTEM_SAMPLE)
    for e in result.entries:
        assert not e.cardinality, f"subsystem shape leaked into the oracle gate: {e.message}"
        assert not e.lookup, f"subsystem shape leaked into the oracle_index gate: {e.message}"


def test_parse_debug_still_returns_a_plain_list_of_the_old_shapes():
    """Backwards compatibility is not optional: 4 call sites (2 gates, _check,
    tests) consume `parse_debug`. One implementation underneath, same surface."""
    old = _debuglog.parse_debug_text(SUBSYSTEM_SAMPLE)
    assert isinstance(old, list)
    assert all(isinstance(e, _debuglog.DebugError) for e in old)


def _one(text: str, subsystem: str, entity_kind: str | None = None):
    hits = [e for e in _debuglog.parse_log_text(text).entries
            if e.subsystem == subsystem
            and (entity_kind is None or e.entity_kind == entity_kind)]
    assert len(hits) == 1, f"expected exactly 1 {subsystem} entry, got {len(hits)}"
    return hits[0]
