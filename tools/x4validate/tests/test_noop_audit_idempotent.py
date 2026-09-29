"""noop_audit: a replace whose payload EQUALS its target is applied and changes nothing -- by
design, not a FALSE OK.

MEASURED 2026-09-28, the v3.3.0 release gate run: noop_audit went red on 8 "FALSE OK" rows,
6 of them the Boron/Terran DLC replacing `<loadout/>` with an identical `<loadout/>`
(`md/scenario_combat.xml`). The op applies and the tree is unchanged, correctly. The gate's
`is_structural` rule ("a replace with element children MUST alter the tree") is false for an
identical payload. A FALSE OK must still fire when the payload DIFFERS and nothing changed.
"""
from __future__ import annotations

from lxml import etree

from conftest import hermetic_gate

# Pure functions: the fake install only lets the gate IMPORT on a machine with no X4.
noop_audit = hermetic_gate("noop_audit")


def _op(xml: str) -> etree._Element:
    return etree.fromstring(xml)


BASE = etree.fromstring(
    "<mdscript><cues><create_ship name='$A'>\n    <loadout/>\n    <owner x='1'/>"
    "</create_ship><create_ship name='$B'><loadout ref='x'/></create_ship></cues></mdscript>")


def test_a_replace_with_an_IDENTICAL_payload_is_idempotent():
    op = _op("<replace sel=\"//create_ship[@name='$A']/loadout\">\n  <loadout/> \n</replace>")
    assert noop_audit.is_idempotent_replace(op, BASE) is True


def test_TWIN_a_replace_with_a_DIFFERENT_payload_is_not():
    op = _op("<replace sel=\"//create_ship[@name='$B']/loadout\"><loadout/></replace>")
    assert noop_audit.is_idempotent_replace(op, BASE) is False


def test_TWIN_an_add_is_never_idempotent():
    op = _op("<add sel=\"//create_ship[@name='$A']\"><loadout/></add>")
    assert noop_audit.is_idempotent_replace(op, BASE) is False


def test_TWIN_a_selector_that_cannot_be_evaluated_is_not_excused():
    op = _op("<replace sel=\"//create_ship[@name='$A'\"><loadout/></replace>")   # malformed
    assert noop_audit.is_idempotent_replace(op, BASE) is False


def test_TWIN_a_selector_matching_nothing_is_not_excused():
    op = _op("<replace sel=\"//create_ship[@name='$Z']/loadout\"><loadout/></replace>")
    assert noop_audit.is_idempotent_replace(op, BASE) is False
