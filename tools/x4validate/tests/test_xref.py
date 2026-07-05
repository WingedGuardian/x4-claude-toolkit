"""Tests for _xref.py — MD/aiscript action·event·cue cross-index."""

from __future__ import annotations

from lxml import etree

from x4validate import _xref


def _rows(xml, source="modx", vpath="md/x.xml"):
    root = etree.fromstring(xml)
    out = []
    _xref._walk(root, source, vpath, out)
    return out


ATD_LIKE = b"""
<mdscript name="X">
  <cues>
    <cue name="Init">
      <actions>
        <set_emergency_eject_active active="false"/>
      </actions>
    </cue>
    <cue name="OnPlayerShipHit">
      <conditions>
        <event_object_hull_damaged object="$ship"/>
      </conditions>
      <actions>
        <do_if value="1">
          <set_object_min_hull object="$ship" exact="1"/>
        </do_if>
        <signal_cue cue="PlayerDeath"/>
      </actions>
    </cue>
    <cue name="PlayerDeath">
      <actions><destroy_object object="$ship"/></actions>
    </cue>
  </cues>
</mdscript>
"""


def test_indexes_actions_events_signals_cuedefs():
    rows = _rows(ATD_LIKE)
    kinds = {(r.kind, r.name) for r in rows}
    assert ("action", "set_emergency_eject_active") in kinds
    assert ("action", "set_object_min_hull") in kinds
    assert ("action", "destroy_object") in kinds
    assert ("event", "event_object_hull_damaged") in kinds
    assert ("signal", "signal_cue") in kinds
    assert ("cuedef", "Init") in kinds
    assert ("cuedef", "PlayerDeath") in kinds


def test_skips_control_flow_and_containers():
    rows = _rows(ATD_LIKE)
    tags = {r.name for r in rows if r.kind == "action"}
    for noise in ("do_if", "actions", "conditions", "cues"):
        assert noise not in tags


def test_enclosing_cue_is_recorded():
    rows = _rows(ATD_LIKE)
    eject = next(r for r in rows if r.name == "set_emergency_eject_active")
    assert eject.cue == "Init"
    hull = next(r for r in rows if r.name == "set_object_min_hull")
    assert hull.cue == "OnPlayerShipHit"


def test_event_records_object_target():
    rows = _rows(ATD_LIKE)
    ev = next(r for r in rows if r.name == "event_object_hull_damaged")
    assert ev.target == "$ship"


def test_signal_records_cue_target():
    rows = _rows(ATD_LIKE)
    sig = next(r for r in rows if r.kind == "signal")
    assert sig.target == "PlayerDeath"


def test_query_and_cue_edges():
    rows = _rows(ATD_LIKE)
    assert len(_xref.query(rows, "action", "set_object_min_hull")) == 1
    # case-insensitive
    assert len(_xref.query(rows, "action", "SET_OBJECT_MIN_HULL")) == 1
    edges = _xref.cue_edges(rows, "PlayerDeath")
    assert "defined" in edges  # PlayerDeath cue is defined here
    assert "signal_cue" in edges  # and signalled from OnPlayerShipHit


def test_cue_edges_matches_qualified_ref():
    xml = b"""
    <mdscript name="Y">
      <cues>
        <cue name="Target"><actions/></cue>
        <cue name="Caller">
          <actions><signal_cue cue="md.OtherScript.Target"/></actions>
        </cue>
      </cues>
    </mdscript>
    """
    rows = _rows(xml)
    edges = _xref.cue_edges(rows, "Target")  # short name matches md.OtherScript.Target
    assert "signal_cue" in edges


def test_tsv_round_trip(tmp_path):
    rows = _rows(ATD_LIKE)
    p = tmp_path / "xref.tsv"
    _xref.write_tsv(rows, p)
    back = _xref.read_tsv(p)
    assert len(back) == len(rows)
    assert {(r.kind, r.name) for r in back} == {(r.kind, r.name) for r in rows}


def test_aiscript_uses_script_name_as_context():
    xml = b"""
    <aiscript name="order.fight">
      <actions><create_order object="$x"/></actions>
    </aiscript>
    """
    rows = _rows(xml, vpath="aiscripts/order.fight.xml")
    order = next(r for r in rows if r.name == "create_order")
    assert order.cue == "order.fight"
