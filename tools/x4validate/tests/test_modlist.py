"""Deterministic logic for the modlist registry tool (ingest/merge/classify/dashboard).

The live API paths (fetch/search/steam) are integration-validated by the slice runs;
these cover the pure, mockable logic.
"""

import types
from datetime import date
from pathlib import Path

from x4validate import _modlist, _registry
from x4validate._nexus import ModMeta


def _args(**kw):
    return types.SimpleNamespace(**kw)


def test_ingest_parses_enabled_flag(tmp_path):
    c = tmp_path / "content.xml"
    c.write_text('<content><extension id="a" enabled="true"/>'
                 '<extension id="ws_1" enabled="false"/></content>', encoding="utf-8")
    ids = _registry.ingest_content_xml(c)
    assert ("a", True) in ids and ("ws_1", False) in ids


def test_merge_adds_new_and_preserves_human():
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("existing", True))
    reg["mods"][0]["human"]["notes"] = "MINE"
    reg["mods"][0]["human"]["done"] = True
    added, existing = _registry.merge(reg, [("existing", True), ("new", True), ("off", False)])
    assert added == 1 and existing == 1
    by_id = {m["id"]: m for m in reg["mods"]}
    assert by_id["existing"]["human"]["notes"] == "MINE"  # preserved
    assert by_id["existing"]["human"]["done"] is True
    assert "new" in by_id and "off" not in by_id  # disabled skipped by default


def test_humanize_splits_camel_and_underscore():
    assert _modlist._humanize("kuerteeSocialStandingsAndCitizenships") == \
        "kuertee Social Standings And Citizenships"
    assert _modlist._humanize("station_combat_rebalance_vro") == "station combat rebalance vro"


def _meta(updated, status="published"):
    return ModMeta(1, "n", "1.0", updated, status, "auth")


def test_classify_removed_and_hidden_drop():
    today = date(2026, 6, 22)
    assert _modlist._classify(_meta("2026-06-20", "removed"), today)[0] == "drop"
    assert _modlist._classify(_meta("2026-06-20", "hidden"), today)[0] == "drop"


def test_classify_churning_ready_predates():
    # Use a later 'today' so the post-9.0 settled ("ready") lane is reachable.
    today = date(2026, 8, 1)
    assert _modlist._classify(_meta("2026-07-25"), today)[0] == "churning"   # <14d
    assert _modlist._classify(_meta("2026-06-20"), today)[0] == "ready"      # post-9.0, >14d
    assert _modlist._classify(_meta("2024-02-16"), today)[0] == "predates-9.0"
    assert _modlist._classify(_meta(""), today)[0] == "untriaged"            # unparseable date


def test_needs_review_filters():
    reg = _registry._new_registry()
    e_untri = _registry._new_entry("u", True)                       # untriaged -> review
    e_auto = _registry._new_entry("a", True)
    e_auto["auto"].update(classification="churning", resolve="auto (spot-check)")  # -> review
    e_clean = _registry._new_entry("m", True)
    e_clean["auto"].update(classification="ready", resolve="manual")  # resolved clean -> NOT
    e_ign = _registry._new_entry("ig", True)
    e_ign["human"]["ignored"] = True                                # ignored -> NOT
    reg["mods"].extend([e_untri, e_auto, e_clean, e_ign])
    assert {m["id"] for m in _registry.needs_review(reg)} == {"u", "a"}


def test_ignore_and_mark_persist(tmp_path):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("x", True))
    _registry.save_registry(reg, regp)
    _modlist.cmd_ignore(_args(registry=str(regp), id="x", reason="junk"))
    _modlist.cmd_mark(_args(registry=str(regp), id="x", custom=True, notes="edited"))
    h = _registry.load_registry(regp)["mods"][0]["human"]
    assert h["ignored"] is True and h["custom_edited"] is True and h["notes"] == "edited"


def test_resolve_sets_manual_and_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr(_modlist._nexus, "fetch_mod",
                        lambda nid: ModMeta(nid, "Cool Mod", "2.0", "2026-06-21", "published", "a"))
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("x", True))
    _registry.save_registry(reg, regp)
    assert _modlist.cmd_resolve(_args(registry=str(regp), id="x", nexus_id=999)) == 0
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["nexus_id"] == 999 and a["resolve"] == "manual" and a["name"] == "Cool Mod"
    assert a["classification"] in ("churning", "ready", "predates-9.0")


def test_dashboard_groups_by_lane():
    reg = _registry._new_registry()
    e = _registry._new_entry("m1", True)
    e["auto"].update(name="VRO", classification="churning", version="5.0", status="published")
    reg["mods"].append(e)
    out = _registry.generate_dashboard(reg)
    assert "CHURNING" in out and "VRO" in out and "1/1" not in out  # 0 done of 1
