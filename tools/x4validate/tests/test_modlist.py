"""Deterministic logic for the modlist registry tool (ingest/merge/classify/dashboard).

The live API paths (fetch/search/steam) are integration-validated by the slice runs;
these cover the pure, mockable logic.
"""

import types
from datetime import date
from pathlib import Path

from x4validate import _modlist, _registry
from x4validate._nexus import ModMeta


def _installed_entry(mod_id, **auto_overrides):
    """A registry entry marked installed=True (the active-set gate) with any
    extra auto: fields set."""
    e = _registry._new_entry(mod_id, True)
    e["auto"]["installed"] = True
    e["auto"].update(auto_overrides)
    return e


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


def test_strip_author_label():
    assert _modlist._strip_author_label("kuertee: Ship scanner") == "Ship scanner"
    assert _modlist._strip_author_label("kuertee UI: Boarding operation notifications") \
        == "Boarding operation notifications"
    assert _modlist._strip_author_label("No colon here") == "No colon here"


def test_manifest_name_variants():
    assert _modlist._manifest_name_variants("Vibrant Engine Plumes - Divinity Edition") == \
        ["Vibrant Engine Plumes - Divinity Edition", "Vibrant Engine Plumes"]
    assert _modlist._manifest_name_variants("Terran Beam Weapons VRO") == \
        ["Terran Beam Weapons VRO", "Terran Beam Weapons"]
    assert _modlist._manifest_name_variants("Plain Title") == ["Plain Title"]


def test_resolve_identity_prefers_installed_name(monkeypatch):
    calls = []

    def fake_search(name, count=5):
        calls.append(name)
        return [(999, "Ship Scanner Mod")] if name == "Ship scanner" else []

    monkeypatch.setattr(_modlist._nexus, "search_mods", fake_search)
    auto = {"installed_name": "kuertee: Ship scanner"}
    nid = _modlist._resolve_identity("kuerteeShipScanner", auto)
    assert nid == 999
    assert calls[0] == "Ship scanner"  # tried the manifest name FIRST, not a humanized guess
    assert auto["resolve"] == "auto (spot-check)"


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


def test_classify_hidden_custom_edited_is_not_dropped():
    # A mod the user is actively maintaining a local fork of should NOT be told
    # to "drop" just because the author temporarily hid the upstream page.
    today = date(2026, 6, 22)
    cls, settled = _modlist._classify(_meta("2026-06-20", "hidden"), today, is_custom=True)
    assert cls == "custom-local"
    cls2, _ = _modlist._classify(_meta("2026-06-20", "removed"), today, is_custom=True)
    assert cls2 == "custom-local"


def test_classify_churning_ready_predates():
    # Use a later 'today' so the post-9.0 settled ("ready") lane is reachable.
    today = date(2026, 8, 1)
    assert _modlist._classify(_meta("2026-07-25"), today)[0] == "churning"   # <14d
    assert _modlist._classify(_meta("2026-06-20"), today)[0] == "ready"      # post-9.0, >14d
    assert _modlist._classify(_meta("2024-02-16"), today)[0] == "predates-9.0"
    assert _modlist._classify(_meta(""), today)[0] == "untriaged"            # unparseable date


def test_needs_review_filters():
    reg = _registry._new_registry()
    e_untri = _installed_entry("u")                                  # untriaged -> review
    e_auto = _installed_entry("a", classification="churning", resolve="auto (spot-check)")  # -> review
    e_clean = _installed_entry("m", classification="ready", resolve="manual")  # resolved clean -> NOT
    e_ign = _installed_entry("ig")
    e_ign["human"]["ignored"] = True                                 # ignored -> NOT
    e_not_installed = _registry._new_entry("ni", True)                # installed=False -> NOT
    e_not_installed["auto"]["classification"] = "untriaged"
    reg["mods"].extend([e_untri, e_auto, e_clean, e_ign, e_not_installed])
    assert {m["id"] for m in _registry.needs_review(reg)} == {"u", "a"}


def test_not_installed_diff_view():
    reg = _registry._new_registry()
    reg["mods"].append(_installed_entry("live"))
    old = _registry._new_entry("gone", True)  # tracked historically, not on disk -> installed=False
    old["auto"]["classification"] = "predates-9.0"
    reg["mods"].append(old)
    ids = {m["id"] for m in _registry.not_installed(reg)}
    assert ids == {"gone"}


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
    reg["mods"].append(_installed_entry(
        "m1", name="VRO", classification="churning", version="5.0", status="published"))
    out = _registry.generate_dashboard(reg)
    assert "CHURNING" in out and "VRO" in out and "1/1" not in out  # 0 done of 1


def test_merge_installed_matches_by_id_and_flags_missing():
    reg = _registry._new_registry()
    # Pre-existing research on a mod (e.g. from an old content.xml ingest).
    old = _registry._new_entry("ws_1696862840", True)
    old["auto"].update(nexus_id=305, classification="churning")
    old["human"]["notes"] = "keep me"
    reg["mods"].append(old)

    installed = [{"id": "ws_1696862840", "folder": "vro", "path": "C:/x/vro",
                  "name": "Variety and Rebalance Overhaul", "version": "501",
                  "date": "2026-06-25", "author": "Shuul", "enabled": True}]
    new, matched, gone = _registry.merge_installed(reg, installed)
    assert (new, matched) == (0, 1)
    m = reg["mods"][0]
    assert m["auto"]["installed"] is True
    assert m["auto"]["installed_version"] == "501"
    assert m["auto"]["nexus_id"] == 305          # prior research preserved
    assert m["human"]["notes"] == "keep me"      # human: untouched

    # A second merge with an EMPTY installed list -> the mod flips to installed=False
    # (uninstalled) rather than being deleted.
    new2, matched2, gone2 = _registry.merge_installed(reg, [])
    assert gone2 == 1
    assert reg["mods"][0]["auto"]["installed"] is False
    assert reg["mods"][0]["auto"]["nexus_id"] == 305  # still preserved
